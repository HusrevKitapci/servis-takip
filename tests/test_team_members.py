# ============================================================
# İÇE AKTARMALAR
# ============================================================

from uuid import uuid4

import pytest

from app.models import Team, User, UserRole


# ============================================================
# 1. ORTAK HAZIRLIK
# ============================================================

@pytest.fixture
def membership_setup(manager_client):
    """Gerçek API üzerinden bir ekip ve servis görevlisi oluşturur."""

    team_response = manager_client.post(
        "/teams",
        json={"name": f"Üyelik Test Ekibi {uuid4().hex}"},
    )
    assert team_response.status_code == 201

    agent_response = manager_client.post(
        "/users/agents",
        json={
            "full_name": "Test Servis Görevlisi",
            "email": f"agent-{uuid4().hex}@example.com",
            "password": "Sadece-Test-Icin-Guclu-Parola-42!",
        },
    )
    assert agent_response.status_code == 201
    assert agent_response.json()["role"] == "agent"

    return {
        "team_id": team_response.json()["id"],
        "user_id": agent_response.json()["id"],
    }


# ============================================================
# 2. ÜYELİK YAŞAM DÖNGÜSÜ
# ============================================================

def test_membership_create_list_and_remove(
    manager_client,
    membership_setup,
):
    team_id = membership_setup["team_id"]
    user_id = membership_setup["user_id"]
    url = f"/teams/{team_id}/members"

    # Üyeliği oluştur.
    created = manager_client.post(url, json={"user_id": user_id})

    assert created.status_code == 201
    assert created.json()["team_id"] == team_id
    assert created.json()["user"]["id"] == user_id
    assert "password_hash" not in created.json()["user"]

    # Üyeliği listede gör.
    listed = manager_client.get(url)

    assert listed.status_code == 200
    assert [item["user"]["id"] for item in listed.json()] == [user_id]

    # Aynı görevli başka bir ekibe de üye olabilir.
    second_team = manager_client.post(
        "/teams",
        json={"name": f"İkinci Test Ekibi {uuid4().hex}"},
    )
    assert second_team.status_code == 201

    second_url = f"/teams/{second_team.json()['id']}/members"

    second_membership = manager_client.post(
        second_url,
        json={"user_id": user_id},
    )
    assert second_membership.status_code == 201

    # İlk üyeliği kaldır.
    removed = manager_client.delete(f"{url}/{user_id}")

    assert removed.status_code == 204
    assert removed.content == b""

    first_list = manager_client.get(url)
    assert first_list.status_code == 200
    assert first_list.json() == []

    # Diğer ekipteki üyelik etkilenmemeli.
    second_list = manager_client.get(second_url)
    assert second_list.status_code == 200
    assert second_list.json()[0]["user"]["id"] == user_id


def test_duplicate_membership_is_rejected(
    manager_client,
    membership_setup,
):
    url = f"/teams/{membership_setup['team_id']}/members"
    payload = {"user_id": membership_setup["user_id"]}

    first = manager_client.post(url, json=payload)
    second = manager_client.post(url, json=payload)

    assert first.status_code == 201
    assert second.status_code == 409

    listed = manager_client.get(url)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# ============================================================
# 3. İŞ KURALLARI
# ============================================================

@pytest.mark.parametrize(
    "failure_case",
    ["requester", "inactive_user", "inactive_team", "missing_user"],
)
def test_ineligible_membership_is_rejected(
    manager_client,
    db_session,
    membership_setup,
    failure_case,
):
    team_id = membership_setup["team_id"]
    user_id = membership_setup["user_id"]

    user = db_session.get(User, user_id)
    assert user is not None

    if failure_case == "requester":
        user.role = UserRole.REQUESTER

    elif failure_case == "inactive_user":
        user.is_active = False

    elif failure_case == "inactive_team":
        team = db_session.get(Team, team_id)
        assert team is not None
        team.is_active = False

    elif failure_case == "missing_user":
        db_session.delete(user)

    db_session.commit()

    url = f"/teams/{team_id}/members"
    response = manager_client.post(url, json={"user_id": user_id})

    expected_status = 404 if failure_case == "missing_user" else 409
    assert response.status_code == expected_status

    listed = manager_client.get(url)
    assert listed.status_code == 200
    assert listed.json() == []


# ============================================================
# 4. ERİŞİM KURALLARI
# ============================================================

@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_membership_endpoints_require_login(client, method):
    # Kimlik doğrulaması kaynak aranmadan önce isteği durdurmalı.
    url = "/teams/1/members"

    if method == "DELETE":
        url += "/1"

    kwargs = {"json": {"user_id": 1}} if method == "POST" else {}

    response = client.request(method, url, **kwargs)

    assert response.status_code == 401


@pytest.mark.parametrize("role", [UserRole.REQUESTER, UserRole.AGENT])
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_membership_endpoints_require_manager(
    authenticated_client,
    membership_setup,
    role,
    method,
):
    # Hazırlık yöneticiyle yapıldı; şimdi başka rolde giriş yapıyoruz.
    client = authenticated_client(role)

    team_id = membership_setup["team_id"]
    user_id = membership_setup["user_id"]
    url = f"/teams/{team_id}/members"

    if method == "DELETE":
        url += f"/{user_id}"

    kwargs = {"json": {"user_id": user_id}} if method == "POST" else {}

    response = client.request(method, url, **kwargs)

    assert response.status_code == 403


@pytest.mark.parametrize("role", [UserRole.REQUESTER, UserRole.AGENT])
def test_agent_creation_requires_manager(authenticated_client, role):
    client = authenticated_client(role)

    response = client.post(
        "/users/agents",
        json={
            "full_name": "Yetkisiz Oluşturma Denemesi",
            "email": f"forbidden-{uuid4().hex}@example.com",
            "password": "Sadece-Test-Icin-Guclu-Parola-42!",
        },
    )

    assert response.status_code == 403