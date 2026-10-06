# ============================================================
# İÇE AKTARMALAR
# ============================================================

from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.models import (
    Team,
    TeamMember,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from app.security import create_access_token, hash_password


# ============================================================
# 1. TEST SENARYOSU HAZIRLIĞI
# ============================================================

@pytest.fixture
def workflow_case(db_session):
    """Bir talep ve farklı yetkilere sahip kullanıcılar hazırlar."""

    unique_part = uuid4().hex
    password_hash = hash_password("Sadece-Test-Icin-Guclu-Parola-42!")

    roles = {
        "owner": UserRole.REQUESTER,
        "agent_a": UserRole.AGENT,
        "agent_b": UserRole.AGENT,
        "manager": UserRole.MANAGER,
        "outsider": UserRole.REQUESTER,
    }

    users = {
        name: User(
            full_name=f"Akış Test Kullanıcısı {name}",
            email=f"{name}-{unique_part}@example.com",
            password_hash=password_hash,
            role=role,
        )
        for name, role in roles.items()
    }

    team = Team(name=f"Akış Test Ekibi {unique_part}")

    db_session.add_all([*users.values(), team])
    db_session.flush()

    db_session.add_all(
        [
            TeamMember(team_id=team.id, user_id=users["agent_a"].id),
            TeamMember(team_id=team.id, user_id=users["agent_b"].id),
        ]
    )

    ticket = Ticket(
        title="Durum geçişi test talebi",
        description="Çözme ve yeniden açma kurallarını kontrol eden talep.",
        requester_id=users["owner"].id,
        team_id=team.id,
        status=TicketStatus.OPEN,
    )

    db_session.add(ticket)
    db_session.flush()

    case = {
        "ticket_id": ticket.id,
        "team_id": team.id,
        "users": {
            name: user.id
            for name, user in users.items()
        },
    }

    db_session.commit()

    return case


def perform_action(client, case, actor: str, action: str):
    """Seçilen kullanıcı adına gerçek endpoint'e istek gönderir."""

    token = create_access_token(case["users"][actor])

    return client.post(
        f"/tickets/{case['ticket_id']}/{action}",
        headers={"Authorization": f"Bearer {token}"},
    )


def claim_as_agent_a(client, case):
    response = perform_action(client, case, "agent_a", "claim")
    assert response.status_code == 200
    return response.json()


def prepare_resolved_ticket(client, case):
    claim_as_agent_a(client, case)

    response = perform_action(client, case, "agent_a", "resolve")
    assert response.status_code == 200

    return response.json()


# ============================================================
# 2. TAM İŞ AKIŞI
# ============================================================

def test_claim_resolve_reopen_and_claim_again(
    client,
    workflow_case,
    db_session,
):
    claimed = claim_as_agent_a(client, workflow_case)

    resolved_response = perform_action(
        client, workflow_case, "agent_a", "resolve"
    )
    assert resolved_response.status_code == 200

    resolved = resolved_response.json()

    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_at"] is not None
    assert resolved["assignee_id"] == workflow_case["users"]["agent_a"]
    assert resolved["claimed_at"] == claimed["claimed_at"]

    reopened_response = perform_action(
        client, workflow_case, "owner", "reopen"
    )
    assert reopened_response.status_code == 200

    reopened = reopened_response.json()

    assert reopened["status"] == "OPEN"
    assert reopened["assignee_id"] is None
    assert reopened["claimed_at"] is None
    assert reopened["resolved_at"] is None

    # Aynı talep devam ediyor; oluşturulma zamanı değişmemeli.
    assert reopened["id"] == claimed["id"]
    assert reopened["created_at"] == claimed["created_at"]

    # Başka bir uygun görevli yeniden üstlenebilir.
    second_claim = perform_action(
        client, workflow_case, "agent_b", "claim"
    )
    assert second_claim.status_code == 200

    db_session.expire_all()
    ticket = db_session.get(Ticket, workflow_case["ticket_id"])

    assert ticket is not None
    assert ticket.status == TicketStatus.IN_PROGRESS
    assert ticket.assignee_id == workflow_case["users"]["agent_b"]
    assert ticket.resolved_at is None


# ============================================================
# 3. ÇÖZME YETKİLERİ VE DURUM KURALLARI
# ============================================================

@pytest.mark.parametrize("actor", ["owner", "manager"])
def test_non_agents_cannot_resolve(client, workflow_case, actor):
    claim_as_agent_a(client, workflow_case)

    response = perform_action(client, workflow_case, actor, "resolve")

    assert response.status_code == 403


def test_other_agent_cannot_resolve(client, workflow_case):
    claim_as_agent_a(client, workflow_case)

    response = perform_action(
        client, workflow_case, "agent_b", "resolve"
    )

    assert response.status_code == 403


def test_open_ticket_cannot_be_resolved(client, workflow_case):
    response = perform_action(
        client, workflow_case, "agent_a", "resolve"
    )

    assert response.status_code == 409


def test_resolved_ticket_cannot_be_resolved_again(client, workflow_case):
    prepare_resolved_ticket(client, workflow_case)

    response = perform_action(
        client, workflow_case, "agent_a", "resolve"
    )

    assert response.status_code == 409


# ============================================================
# 4. YENİDEN AÇMA KURALLARI
# ============================================================

def test_in_progress_ticket_cannot_be_reopened(client, workflow_case):
    claim_as_agent_a(client, workflow_case)

    response = perform_action(
        client, workflow_case, "owner", "reopen"
    )

    assert response.status_code == 409


@pytest.mark.parametrize("actor", ["owner", "manager"])
def test_owner_or_manager_can_reopen(client, workflow_case, actor):
    prepare_resolved_ticket(client, workflow_case)

    response = perform_action(client, workflow_case, actor, "reopen")

    assert response.status_code == 200
    assert response.json()["status"] == "OPEN"


@pytest.mark.parametrize(
    ("actor", "expected_status"),
    [
        ("agent_b", 403),
        ("outsider", 404),
    ],
)
def test_other_users_cannot_reopen(
    client,
    workflow_case,
    actor,
    expected_status,
):
    prepare_resolved_ticket(client, workflow_case)

    response = perform_action(client, workflow_case, actor, "reopen")

    assert response.status_code == expected_status


# ============================================================
# 5. EKİP VE ÜYELİK DEĞİŞİKLİKLERİ
# ============================================================

@pytest.mark.parametrize("action", ["resolve", "reopen"])
def test_inactive_team_prevents_transition(
    client,
    workflow_case,
    db_session,
    action,
):
    claim_as_agent_a(client, workflow_case)

    if action == "reopen":
        resolved = perform_action(
            client, workflow_case, "agent_a", "resolve"
        )
        assert resolved.status_code == 200

    team = db_session.get(Team, workflow_case["team_id"])
    assert team is not None

    team.is_active = False
    db_session.commit()

    actor = "agent_a" if action == "resolve" else "owner"
    response = perform_action(client, workflow_case, actor, action)

    assert response.status_code == 409

    db_session.expire_all()
    ticket = db_session.get(Ticket, workflow_case["ticket_id"])
    assert ticket is not None

    expected_status = (
        TicketStatus.IN_PROGRESS
        if action == "resolve"
        else TicketStatus.RESOLVED
    )
    assert ticket.status == expected_status


def test_removed_member_cannot_resolve(
    client,
    workflow_case,
    db_session,
):
    claim_as_agent_a(client, workflow_case)

    membership = db_session.get(
        TeamMember,
        (
            workflow_case["team_id"],
            workflow_case["users"]["agent_a"],
        ),
    )
    assert membership is not None

    db_session.delete(membership)
    db_session.commit()

    response = perform_action(
        client, workflow_case, "agent_a", "resolve"
    )

    # Talep başkasına ait; üyelik kalkınca artık görünür değil.
    assert response.status_code == 404


# ============================================================
# 6. OTURUM VE VERİTABANI KISITI
# ============================================================

@pytest.mark.parametrize("action", ["resolve", "reopen"])
def test_workflow_requires_login(client, action):
    response = client.post(f"/tickets/1/{action}")
    assert response.status_code == 401


def test_database_rejects_resolution_without_timestamp(
    client,
    workflow_case,
    db_session,
):
    claim_as_agent_a(client, workflow_case)

    # API'yi atlayarak hatalı veri yazmayı deniyoruz.
    # İç savepoint yalnızca bu başarısız denemeyi geri alır.
    with pytest.raises(IntegrityError) as captured:
        with db_session.begin_nested():
            db_session.execute(
                update(Ticket)
                .where(Ticket.id == workflow_case["ticket_id"])
                .values(
                    status=TicketStatus.RESOLVED,
                    resolved_at=None,
                )
            )

    assert captured.value.orig.diag.constraint_name == (
        "ck_tickets_resolution_time"
    )