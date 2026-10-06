# ============================================================
# İÇE AKTARMALAR
# ============================================================

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Team, Ticket, TicketStatus, UserRole


# ============================================================
# 1. ORTAK HAZIRLIK
# ============================================================

@pytest.fixture
def ticket_team_id(manager_client):
    """Talebin gönderilebileceği aktif bir ekip oluşturur."""

    response = manager_client.post(
        "/teams",
        json={"name": f"Talep Test Ekibi {uuid4().hex}"},
    )

    assert response.status_code == 201

    return response.json()["id"]


@pytest.fixture
def requester_ticket_context(ticket_team_id, authenticated_client):
    """
    Önce ekip hazırlanır, ardından normal kullanıcıyla giriş yapılır.

    Böylece talep oluşturma isteği yönetici yerine requester
    rolündeki kullanıcı tarafından gönderilir.
    """

    client = authenticated_client(UserRole.REQUESTER)

    return client, ticket_team_id


def ticket_payload(team_id: int) -> dict:
    """Her çağrıda bağımsız bir geçerli istek sözlüğü döndürür."""

    return {
        "title": "  Ofis yazıcısı çıktı vermiyor  ",
        "description": (
            "  Yazıcı açık olmasına rağmen gönderilen belgeler "
            "yazdırılmıyor.  "
        ),
        "priority": "NORMAL",
        "team_id": team_id,
    }


def assert_no_ticket_for_team(db_session, team_id: int) -> None:
    """Başarısız isteğin veritabanına kayıt yazmadığını kontrol eder."""

    ticket_id = db_session.scalar(
        select(Ticket.id)
        .where(Ticket.team_id == team_id)
        .limit(1)
    )

    assert ticket_id is None


# ============================================================
# 2. BAŞARILI TALEP OLUŞTURMA
# ============================================================

@pytest.mark.parametrize(
    "role",
    [
        UserRole.REQUESTER,
        UserRole.AGENT,
        UserRole.MANAGER,
    ],
)
def test_active_user_can_create_own_ticket(
    ticket_team_id,
    authenticated_client,
    db_session,
    role,
):
    """Her rol kendi adına talep açabilir."""

    client = authenticated_client(role)

    profile_response = client.get("/users/me")
    assert profile_response.status_code == 200

    current_user_id = profile_response.json()["id"]

    # Öncelik gönderilmezse NORMAL kullanılmasını da doğrularız.
    payload = ticket_payload(ticket_team_id)
    del payload["priority"]

    response = client.post("/tickets", json=payload)

    assert response.status_code == 201

    data = response.json()

    assert data["requester_id"] == current_user_id
    assert data["team_id"] == ticket_team_id
    assert data["status"] == "OPEN"
    assert data["priority"] == "NORMAL"

    # Başta ve sonda kalan boşluklar temizlenmiş olmalı.
    assert data["title"] == payload["title"].strip()
    assert data["description"] == payload["description"].strip()

    # Yanıt vermekle yetinilmemeli; kayıt veritabanında bulunmalı.
    saved_ticket = db_session.get(Ticket, data["id"])

    assert saved_ticket is not None
    assert saved_ticket.requester_id == current_user_id
    assert saved_ticket.team_id == ticket_team_id
    assert saved_ticket.status == TicketStatus.OPEN
    assert saved_ticket.created_at is not None
    assert saved_ticket.created_at.tzinfo is not None


# ============================================================
# 3. SUNUCUYA AİT ALANLARIN İSTEKLE DEĞİŞTİRİLEMEMESİ
# ============================================================

@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("requester_id", 1),
        ("status", "RESOLVED"),
        ("created_at", "2020-01-01T00:00:00Z"),
    ],
)
def test_client_cannot_set_server_managed_fields(
    requester_ticket_context,
    db_session,
    field_name,
    field_value,
):
    client, team_id = requester_ticket_context

    payload = ticket_payload(team_id)
    payload[field_name] = field_value

    response = client.post("/tickets", json=payload)

    assert response.status_code == 422

    errors = response.json()["detail"]

    assert any(
        error["loc"][-1] == field_name
        and error["type"] == "extra_forbidden"
        for error in errors
    )

    assert_no_ticket_for_team(db_session, team_id)


# ============================================================
# 4. GEÇERSİZ İÇERİK
# ============================================================

@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("title", "abc"),
        ("description", "kisa"),
        ("priority", "URGENT"),
        ("team_id", True),
    ],
)
def test_invalid_ticket_payload_is_rejected(
    requester_ticket_context,
    db_session,
    field_name,
    field_value,
):
    client, team_id = requester_ticket_context

    payload = ticket_payload(team_id)
    payload[field_name] = field_value

    response = client.post("/tickets", json=payload)

    assert response.status_code == 422
    assert_no_ticket_for_team(db_session, team_id)


# ============================================================
# 5. EKİBİN İŞLEME UYGUNLUĞU
# ============================================================

def test_ticket_cannot_be_created_for_inactive_team(
    requester_ticket_context,
    db_session,
):
    client, team_id = requester_ticket_context

    team = db_session.get(Team, team_id)
    assert team is not None

    team.is_active = False
    db_session.commit()

    response = client.post(
        "/tickets",
        json=ticket_payload(team_id),
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Pasif ekibe servis talebi açılamaz.",
    }

    assert_no_ticket_for_team(db_session, team_id)


def test_ticket_cannot_be_created_for_missing_team(
    requester_ticket_context,
    db_session,
):
    client, team_id = requester_ticket_context

    # Rastgele bir kimliğin boş olduğunu varsaymak yerine,
    # kendi hazırladığımız ekibi silerek yokluğunu kesinleştiririz.
    team = db_session.get(Team, team_id)
    assert team is not None

    db_session.delete(team)
    db_session.commit()

    response = client.post(
        "/tickets",
        json=ticket_payload(team_id),
    )

    assert response.status_code == 404
    assert_no_ticket_for_team(db_session, team_id)


# ============================================================
# 6. GİRİŞ YAPMADAN TALEP OLUŞTURMA
# ============================================================

def test_ticket_creation_requires_login(client):
    response = client.post(
        "/tickets",
        json=ticket_payload(team_id=1),
    )

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"