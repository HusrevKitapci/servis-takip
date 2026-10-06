"""Talep özet raporunun PostgreSQL entegrasyon testleri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import (
    Team,
    TeamMember,
    Ticket,
    TicketComment,
    TicketEvent,
    TicketEventType,
    TicketPriority,
    TicketStatus,
    UserRole,
)
from app.sla import SlaStatus, make_policy_snapshot


# ============================================================
# 2. ORTAK TEST HAZIRLIĞI
# ============================================================

@pytest.fixture
def report_context(authenticated_client, db_session):
    """Üç rol, iki çalışma ekibi ve bir boş ekip hazırlar."""

    actors = {}

    for role in (
        UserRole.REQUESTER,
        UserRole.AGENT,
        UserRole.MANAGER,
    ):
        client = authenticated_client(role)
        profile = client.get("/users/me")

        assert profile.status_code == 200

        actors[role] = {
            "client": client,
            "id": profile.json()["id"],
            "headers": {
                "Authorization": profile.request.headers["Authorization"],
            },
        }

    suffix = uuid4().hex[:10]

    teams = {
        "a": Team(name=f"Rapor-A-{suffix}", is_active=True),
        "b": Team(name=f"Rapor-B-{suffix}", is_active=True),
        "empty": Team(name=f"Rapor-C-{suffix}", is_active=True),
    }

    db_session.add_all(list(teams.values()))
    db_session.flush()

    # Görevli yalnızca A ekibinin üyesidir.
    db_session.add(
        TeamMember(
            team_id=teams["a"].id,
            user_id=actors[UserRole.AGENT]["id"],
        )
    )
    db_session.flush()

    return {
        "session": db_session,
        "actors": actors,
        "teams": teams,
    }


def _new_ticket(
    context,
    *,
    owner_role,
    team_key,
    ticket_status=TicketStatus.OPEN,
    priority=TicketPriority.NORMAL,
    created_at=None,
):
    """İş kurallarına uygun bir test talebi oluşturur."""

    session = context["session"]

    if created_at is None:
        created_at = datetime.now(timezone.utc) - timedelta(hours=3)

    has_assignee = ticket_status != TicketStatus.OPEN

    ticket = Ticket(
        title="Raporlama test talebi",
        description="Bu kayıt raporlama testleri için oluşturuldu.",
        requester_id=context["actors"][owner_role]["id"],
        team_id=context["teams"][team_key].id,
        priority=priority,
        status=ticket_status,
        created_at=created_at,
        assignee_id=(
            context["actors"][UserRole.AGENT]["id"]
            if has_assignee
            else None
        ),
        claimed_at=(
            created_at + timedelta(minutes=5)
            if has_assignee
            else None
        ),
        resolved_at=(
            created_at + timedelta(minutes=30)
            if ticket_status == TicketStatus.RESOLVED
            else None
        ),
    )

    session.add(ticket)
    session.flush()

    return ticket


def _read_report(context, role, team_key=None):
    """Belirtilen kullanıcının oturumuyla raporu ister."""

    actor = context["actors"][role]

    params = {}

    if team_key is not None:
        params["team_id"] = context["teams"][team_key].id

    return actor["client"].get(
        "/reports/tickets/summary",
        headers=actor["headers"],
        params=params,
    )


def _counts(items, key):
    """Liste biçimindeki sayımları karşılaştırma için sözlüğe çevirir."""

    return {
        item[key]: item["count"]
        for item in items
    }


@pytest.fixture
def report_case(report_context):
    """Erişim testleri için beş talep oluşturur."""

    context = report_context

    _new_ticket(
        context,
        owner_role=UserRole.REQUESTER,
        team_key="a",
        priority=TicketPriority.NORMAL,
    )

    _new_ticket(
        context,
        owner_role=UserRole.MANAGER,
        team_key="a",
        ticket_status=TicketStatus.IN_PROGRESS,
        priority=TicketPriority.HIGH,
    )

    _new_ticket(
        context,
        owner_role=UserRole.MANAGER,
        team_key="a",
        ticket_status=TicketStatus.RESOLVED,
        priority=TicketPriority.LOW,
    )

    _new_ticket(
        context,
        owner_role=UserRole.MANAGER,
        team_key="b",
        priority=TicketPriority.LOW,
    )

    # Görevli B ekibinin üyesi değil; kendi talebini görebilir.
    _new_ticket(
        context,
        owner_role=UserRole.AGENT,
        team_key="b",
        priority=TicketPriority.NORMAL,
    )

    return context


# ============================================================
# 3. GÖRÜNÜRLÜK VE EKİP FİLTRESİ
# ============================================================

@pytest.mark.parametrize(
    ("role", "team_key", "expected_total"),
    [
        (UserRole.REQUESTER, "a", 1),
        (UserRole.REQUESTER, "b", 0),
        (UserRole.AGENT, "a", 3),
        (UserRole.AGENT, "b", 1),
        (UserRole.MANAGER, "b", 2),
    ],
)
def test_report_respects_visibility(
    report_case,
    role,
    team_key,
    expected_total,
):
    response = _read_report(report_case, role, team_key)

    assert response.status_code == 200

    body = response.json()

    assert body["total"] == expected_total
    assert sum(x["count"] for x in body["by_status"]) == expected_total
    assert sum(x["count"] for x in body["by_priority"]) == expected_total
    assert sum(x["count"] for x in body["by_sla"]) == expected_total


def test_manager_sees_correct_distributions(report_case):
    response = _read_report(
        report_case,
        UserRole.MANAGER,
        "a",
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 3

    assert _counts(body["by_status"], "status") == {
        "OPEN": 1,
        "IN_PROGRESS": 1,
        "RESOLVED": 1,
    }

    assert _counts(body["by_priority"], "priority") == {
        "LOW": 1,
        "NORMAL": 1,
        "HIGH": 1,
    }

    # Bu test kayıtları doğrudan modele eklenmiştir.
    # CREATED olayında SLA hedefi bulunmadığı için izlenmiyor sayılır.
    sla_counts = _counts(body["by_sla"], "status")

    assert sla_counts["NOT_TRACKED"] == 3
    assert sum(sla_counts.values()) == 3


def test_empty_team_returns_zero_counts(report_case):
    response = _read_report(
        report_case,
        UserRole.MANAGER,
        "empty",
    )

    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 0

    for field in ("by_status", "by_priority", "by_sla"):
        assert all(item["count"] == 0 for item in body[field])


def test_unfiltered_report_matches_visible_ticket_total(report_case):
    actor = report_case["actors"][UserRole.REQUESTER]

    report = _read_report(
        report_case,
        UserRole.REQUESTER,
    )

    tickets = actor["client"].get(
        "/tickets",
        headers=actor["headers"],
    )

    assert report.status_code == 200
    assert tickets.status_code == 200
    assert report.json()["total"] == tickets.json()["total"]


# ============================================================
# 4. GİRDİ VE OTURUM KONTROLLERİ
# ============================================================

@pytest.mark.parametrize("team_id", [0, -1, 2_147_483_648])
def test_invalid_team_filter_is_rejected(report_context, team_id):
    actor = report_context["actors"][UserRole.MANAGER]

    response = actor["client"].get(
        "/reports/tickets/summary",
        headers=actor["headers"],
        params={"team_id": team_id},
    )

    assert response.status_code == 422


def test_invalid_token_is_rejected(report_context):
    actor = report_context["actors"][UserRole.REQUESTER]

    response = actor["client"].get(
        "/reports/tickets/summary",
        headers={"Authorization": "Bearer invalid-report-token"},
    )

    assert response.status_code == 401


# ============================================================
# 5. BEŞ SLA DURUMU İÇİN TEST VERİLERİ
# ============================================================

@pytest.fixture
def sla_report_case(report_context):
    context = report_context
    session = context["session"]
    now = datetime.now(timezone.utc)

    tickets = {}

    for sla_state in SlaStatus:
        # WAITING kaydının hedefinin dolmasına hâlâ 50 dakika var.
        created_at = now - (
            timedelta(minutes=10)
            if sla_state == SlaStatus.WAITING
            else timedelta(hours=2)
        )

        ticket = _new_ticket(
            context,
            owner_role=UserRole.REQUESTER,
            team_key="a",
            priority=TicketPriority.HIGH,
            created_at=created_at,
        )

        tickets[sla_state] = ticket

        if sla_state == SlaStatus.NOT_TRACKED:
            continue

        session.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=context["actors"][UserRole.REQUESTER]["id"],
                event_type=TicketEventType.CREATED,
                details={
                    "sla": make_policy_snapshot("HIGH"),
                },
            )
        )

        if sla_state == SlaStatus.MET:
            # İkinci yanıt geç olsa da ilk yanıt zamanındadır.
            reply_minutes = [10, 90]
        elif sla_state == SlaStatus.MISSED:
            reply_minutes = [90]
        else:
            reply_minutes = []

        for minute in reply_minutes:
            response_at = created_at + timedelta(minutes=minute)

            comment = TicketComment(
                ticket_id=ticket.id,
                author_id=context["actors"][UserRole.AGENT]["id"],
                body="Talebiniz hakkında görevli yanıtı.",
                created_at=response_at,
            )

            session.add(comment)
            session.flush()

            session.add(
                TicketEvent(
                    ticket_id=ticket.id,
                    actor_id=context["actors"][UserRole.AGENT]["id"],
                    event_type=TicketEventType.COMMENT_ADDED,
                    created_at=response_at,
                    details={
                        "comment_id": comment.id,
                        "first_response_candidate": True,
                        "responded_at": response_at.isoformat(),
                        "author_role": UserRole.AGENT.value,
                        "is_public": True,
                    },
                )
            )

    session.flush()

    return {
        "context": context,
        "tickets": tickets,
    }


# ============================================================
# 6. RAPOR VE TEKİL SLA HESABININ UYUMU
# ============================================================

def test_all_sla_states_match_individual_endpoint(sla_report_case):
    context = sla_report_case["context"]

    report = _read_report(
        context,
        UserRole.REQUESTER,
        "a",
    )

    assert report.status_code == 200

    body = report.json()

    assert body["total"] == 5
    assert _counts(body["by_sla"], "status") == {
        state.value: 1
        for state in SlaStatus
    }

    actor = context["actors"][UserRole.REQUESTER]

    for expected_state, ticket in sla_report_case["tickets"].items():
        response = actor["client"].get(
            f"/tickets/{ticket.id}/sla",
            headers=actor["headers"],
        )

        assert response.status_code == 200
        assert response.json()["status"] == expected_state.value


def test_report_uses_saved_target_after_priority_change(sla_report_case):
    context = sla_report_case["context"]

    ticket = sla_report_case["tickets"][SlaStatus.BREACHED]

    # Talep açılırken hedef 1 saatti.
    # Öncelik sonradan değişse de kaydedilmiş hedef korunmalı.
    ticket.priority = TicketPriority.LOW
    context["session"].flush()

    response = _read_report(
        context,
        UserRole.REQUESTER,
        "a",
    )

    assert response.status_code == 200

    sla_counts = _counts(response.json()["by_sla"], "status")

    assert sla_counts["BREACHED"] == 1
    assert sla_counts["WAITING"] == 1