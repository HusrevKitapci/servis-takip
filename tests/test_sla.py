"""İlk yanıt süresi kuralları ve API entegrasyon testleri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models import Team, TeamMember, User, UserRole
from app.sla import (
    SlaStatus,
    evaluate_first_response,
    make_policy_snapshot,
)


# ============================================================
# 2. HEDEF SÜRE TESTLERİ
# ============================================================

@pytest.mark.parametrize(
    ("priority", "expected_seconds"),
    [
        ("HIGH", 3600),
        ("NORMAL", 28800),
        ("LOW", 86400),
    ],
)
def test_priority_target(priority, expected_seconds):
    snapshot = make_policy_snapshot(priority)

    assert snapshot["target_seconds"] == expected_seconds
    assert snapshot["policy_version"] == "first-response-v1"


# ============================================================
# 3. ZAMAN SINIRI TESTLERİ
# ============================================================

@pytest.mark.parametrize(
    ("reply_after", "now_after", "expected_status"),
    [
        (None, 0, SlaStatus.WAITING),
        (None, 3600, SlaStatus.WAITING),
        (None, 3601, SlaStatus.BREACHED),
        (3599, 7200, SlaStatus.MET),
        (3600, 7200, SlaStatus.MET),
        (3601, 7200, SlaStatus.MISSED),
    ],
)
def test_first_response_boundaries(
    reply_after,
    now_after,
    expected_status,
):
    started_at = datetime(
        2026, 10, 5, 9, 0, 0,
        tzinfo=timezone.utc,
    )

    first_response_at = (
        None
        if reply_after is None
        else started_at + timedelta(seconds=reply_after)
    )

    result = evaluate_first_response(
        created_at=started_at,
        target_seconds=3600,
        policy_version="first-response-v1",
        first_response_at=first_response_at,
        now=started_at + timedelta(seconds=now_after),
    )

    assert result["status"] == expected_status
    assert result["due_at"] == started_at + timedelta(hours=1)


def test_missing_policy_is_not_tracked():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)

    result = evaluate_first_response(
        created_at=now - timedelta(days=10),
        target_seconds=None,
        policy_version=None,
        first_response_at=None,
        now=now,
    )

    assert result["status"] == SlaStatus.NOT_TRACKED
    assert result["due_at"] is None


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        evaluate_first_response(
            created_at=datetime(2026, 10, 5, 9),
            target_seconds=3600,
            policy_version="first-response-v1",
            first_response_at=None,
            now=datetime(2026, 10, 5, 10, tzinfo=timezone.utc),
        )


def test_same_instant_in_different_timezones():
    utc_start = datetime(
        2026, 10, 5, 9,
        tzinfo=timezone.utc,
    )

    turkey_response = datetime(
        2026, 10, 5, 13,
        tzinfo=timezone(timedelta(hours=3)),
    )

    result = evaluate_first_response(
        created_at=utc_start,
        target_seconds=3600,
        policy_version="first-response-v1",
        first_response_at=turkey_response,
        now=utc_start + timedelta(hours=2),
    )

    # Türkiye'de 13.00, UTC'de 10.00'dır.
    # Başlangıçtan tam bir saat sonra verilen yanıt zamanındadır.
    assert result["status"] == SlaStatus.MET


# ============================================================
# 4. GERÇEK ENDPOINT TESTLERİ İÇİN HAZIRLIK
# ============================================================

@pytest.fixture
def sla_case(authenticated_client, db_session):
    """Talep sahibi, aktif ekip ve HIGH öncelikli talep hazırlar."""

    owner_client = authenticated_client(UserRole.REQUESTER)

    profile = owner_client.get("/users/me")
    assert profile.status_code == 200

    # Aynı istemci başka bir hesapla kullanılsa bile bu oturumu koru.
    owner_headers = {
        "Authorization": profile.request.headers["Authorization"],
    }

    team = Team(
        name=f"SLA-{uuid4().hex[:12]}",
        is_active=True,
    )

    db_session.add(team)
    db_session.flush()

    response = owner_client.post(
        "/tickets",
        headers=owner_headers,
        json={
            "title": "SLA kontrol talebi",
            "description": "İlk görevli yanıt süresi kontrol edilecek.",
            "priority": "HIGH",
            "team_id": team.id,
        },
    )

    assert response.status_code == 201

    return {
        "client": owner_client,
        "headers": owner_headers,
        "ticket_id": response.json()["id"],
        "team_id": team.id,
    }


# ============================================================
# 5. OLUŞTURMA VE TALEP SAHİBİ YORUMU
# ============================================================

def test_new_ticket_has_frozen_target(sla_case):
    response = sla_case["client"].get(
        f"/tickets/{sla_case['ticket_id']}/sla",
        headers=sla_case["headers"],
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "WAITING"
    assert body["target_seconds"] == 3600
    assert body["policy_version"] == "first-response-v1"
    assert body["first_response_at"] is None

    started_at = datetime.fromisoformat(body["started_at"])
    due_at = datetime.fromisoformat(body["due_at"])

    assert due_at - started_at == timedelta(hours=1)


def test_requester_comment_is_not_first_response(sla_case):
    client = sla_case["client"]
    ticket_id = sla_case["ticket_id"]
    headers = sla_case["headers"]

    response = client.post(
        f"/tickets/{ticket_id}/comments",
        headers=headers,
        json={"body": "Sorunla ilgili ek bilgi gönderiyorum."},
    )
    assert response.status_code == 201

    report = client.get(
        f"/tickets/{ticket_id}/sla",
        headers=headers,
    )

    assert report.status_code == 200
    assert report.json()["status"] == "WAITING"
    assert report.json()["first_response_at"] is None


# ============================================================
# 6. GÖREVLİ YANITI VE YENİDEN AÇMA
# ============================================================

def test_first_reply_survives_reopen_and_role_change(
    sla_case,
    authenticated_client,
    db_session,
):
    ticket_id = sla_case["ticket_id"]

    agent_client = authenticated_client(UserRole.AGENT)
    profile = agent_client.get("/users/me")
    assert profile.status_code == 200

    agent_id = profile.json()["id"]
    agent_headers = {
        "Authorization": profile.request.headers["Authorization"],
    }

    db_session.add(
        TeamMember(
            team_id=sla_case["team_id"],
            user_id=agent_id,
        )
    )
    db_session.flush()

    # Üstlenmek, kullanıcıya yanıt vermek anlamına gelmez.
    claim = agent_client.post(
        f"/tickets/{ticket_id}/claim",
        headers=agent_headers,
    )
    assert claim.status_code == 200

    waiting = agent_client.get(
        f"/tickets/{ticket_id}/sla",
        headers=agent_headers,
    )
    assert waiting.json()["status"] == "WAITING"

    first_comment = agent_client.post(
        f"/tickets/{ticket_id}/comments",
        headers=agent_headers,
        json={"body": "Talebinizi inceliyorum, size bilgi vereceğim."},
    )
    assert first_comment.status_code == 201

    first_report = agent_client.get(
        f"/tickets/{ticket_id}/sla",
        headers=agent_headers,
    )
    assert first_report.status_code == 200
    assert first_report.json()["status"] == "MET"

    first_response_at = first_report.json()["first_response_at"]
    original_due_at = first_report.json()["due_at"]

    # İkinci yorum, ilk yanıt zamanının yerini almamalı.
    second_comment = agent_client.post(
        f"/tickets/{ticket_id}/comments",
        headers=agent_headers,
        json={"body": "İkinci kontrolü de tamamladım."},
    )
    assert second_comment.status_code == 201

    resolved = agent_client.post(
        f"/tickets/{ticket_id}/resolve",
        headers=agent_headers,
    )
    assert resolved.status_code == 200

    reopened = sla_case["client"].post(
        f"/tickets/{ticket_id}/reopen",
        headers=sla_case["headers"],
    )
    assert reopened.status_code == 200

    # Eski yanıtın geçerliliği bugünkü role bağlı olmamalı.
    agent = db_session.get(User, agent_id)
    assert agent is not None

    agent.role = UserRole.REQUESTER
    db_session.flush()

    final_report = sla_case["client"].get(
        f"/tickets/{ticket_id}/sla",
        headers=sla_case["headers"],
    )

    assert final_report.status_code == 200
    assert final_report.json()["status"] == "MET"
    assert final_report.json()["first_response_at"] == first_response_at
    assert final_report.json()["due_at"] == original_due_at


# ============================================================
# 7. ERİŞİM KONTROLÜ
# ============================================================

def test_unrelated_agent_cannot_read_sla(
    sla_case,
    authenticated_client,
):
    agent_client = authenticated_client(UserRole.AGENT)

    response = agent_client.get(
        f"/tickets/{sla_case['ticket_id']}/sla"
    )

    # Bu görevli talebin sahibi veya ilgili ekibin üyesi değil.
    assert response.status_code == 404