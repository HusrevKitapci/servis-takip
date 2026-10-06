# ============================================================
# İÇE AKTARMALAR
# ============================================================

from uuid import uuid4

import pytest

from app.models import Team, UserRole


# ============================================================
# 1. ORTAK TEST HAZIRLIĞI
# ============================================================

@pytest.fixture
def existing_team_id(db_session):
    """
    Yetki testlerinin kullanacağı ekibi hazırlar.

    Burada ekip oluşturma API'sini kullanmayız; çünkü ölçmek
    istediğimiz şey kayıt işlemi değil, erişim kurallarıdır.
    """

    team = Team(name=f"Yetki Test Ekibi {uuid4().hex}")

    db_session.add(team)
    db_session.flush()

    team_id = team.id

    db_session.commit()

    return team_id


def send_team_request(client, operation: str, team_id: int):
    """Testte seçilen ekip işlemini gerçekleştirir."""

    if operation == "list":
        return client.get("/teams")

    if operation == "read":
        return client.get(f"/teams/{team_id}")

    if operation == "create":
        return client.post(
            "/teams",
            json={"name": f"Yeni Test Ekibi {uuid4().hex}"},
        )

    if operation == "change_status":
        return client.patch(
            f"/teams/{team_id}/status",
            json={"is_active": False},
        )

    raise ValueError(f"Bilinmeyen test işlemi: {operation}")


# ============================================================
# 2. GİRİŞ YAPMAMIŞ KULLANICI
# ============================================================

@pytest.mark.parametrize(
    "operation",
    ["list", "read", "create", "change_status"],
)
def test_team_operations_require_login(
    client,
    existing_team_id,
    operation,
):
    """Dört ekip işlemi de oturum doğrulaması istemeli."""

    response = send_team_request(
        client,
        operation,
        existing_team_id,
    )

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


# ============================================================
# 3. ROL VE İŞLEM YETKİLERİ
# ============================================================

@pytest.mark.parametrize(
    "role",
    [
        UserRole.REQUESTER,
        UserRole.AGENT,
        UserRole.MANAGER,
    ],
)
@pytest.mark.parametrize(
    "operation",
    ["list", "read", "create", "change_status"],
)
def test_team_permissions_by_role(
    authenticated_client,
    db_session,
    existing_team_id,
    role,
    operation,
):
    """
    Üç rolün dört işlemdeki davranışını kontrol eder.

    İki parametrize birlikte 3 x 4 = 12 senaryo üretir.
    """

    client = authenticated_client(role)

    response = send_team_request(
        client,
        operation,
        existing_team_id,
    )

    # --------------------------------------------------------
    # 3.1. Beklenen HTTP sonucunu kontrol et
    # --------------------------------------------------------

    if operation in {"list", "read"}:
        expected_status = 200

    elif role == UserRole.MANAGER:
        expected_status = 201 if operation == "create" else 200

    else:
        expected_status = 403

    assert response.status_code == expected_status

    if expected_status == 403:
        assert response.json() == {
            "detail": "Bu işlem için yönetici yetkisi gerekiyor.",
        }

    # --------------------------------------------------------
    # 3.2. Durum değişikliği gerçekten yetkiye uygun mu?
    # --------------------------------------------------------

    if operation == "change_status":
        # Oturumun belleğindeki eski değer yerine güncel kaydı oku.
        db_session.expire_all()

        team = db_session.get(Team, existing_team_id)
        assert team is not None

        if role == UserRole.MANAGER:
            assert team.is_active is False
        else:
            # Yetkisiz istek, veritabanındaki durumu değiştirmemeli.
            assert team.is_active is True