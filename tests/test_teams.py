"""
Ekip API'sinin temel davranış testleri.

Testler yalnızca durum kodlarını değil, kaydın sonraki isteklerdeki
durumunu da kontrol eder.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from uuid import uuid4

from fastapi.testclient import TestClient


# ============================================================================
# 2. EKİP OLUŞTURMA VE YENİDEN OKUMA
# ============================================================================

def test_create_team_and_read_it(client, manager_client) -> None:
    """Oluşturulan ekip, ayrı bir GET isteğiyle aynı bilgilerle okunabilmeli."""

    team_name = f"Test Ekibi {uuid4().hex}"

    create_response = client.post(
        "/teams",
        json={"name": team_name},
    )

    assert create_response.status_code == 201, create_response.text

    created_team = create_response.json()

    assert created_team["name"] == team_name
    assert created_team["is_active"] is True
    assert created_team["id"] > 0
    assert created_team["created_at"]

    read_response = client.get(f"/teams/{created_team['id']}")

    assert read_response.status_code == 200, read_response.text
    assert read_response.json() == created_team


# ============================================================================
# 3. AYNI İSİMLE İKİNCİ KAYDI ENGELLEME
# ============================================================================

def test_duplicate_team_name_preserves_original(client, manager_client) -> None:
    """İkinci kayıt reddedilirken ilk ekip korunmalı ve API çalışmaya devam etmeli."""

    team_name = f"Test Ekibi {uuid4().hex}"

    first_response = client.post(
        "/teams",
        json={"name": team_name},
    )

    assert first_response.status_code == 201, first_response.text
    original_team = first_response.json()

    duplicate_response = client.post(
        "/teams",
        json={"name": team_name},
    )

    assert duplicate_response.status_code == 409, duplicate_response.text

    # Başarısız ikinci işlem, ilk kaydı ortadan kaldırmamalı.
    read_response = client.get(f"/teams/{original_team['id']}")

    assert read_response.status_code == 200, read_response.text
    assert read_response.json() == original_team

    # Hata sonrasında farklı bir ekibin oluşturulabildiğini de kontrol et.
    another_response = client.post(
        "/teams",
        json={"name": f"Test Ekibi {uuid4().hex}"},
    )

    assert another_response.status_code == 201, another_response.text


# ============================================================================
# 4. PASİFE ALMA VE YENİDEN AKTİFLEŞTİRME
# ============================================================================

def test_team_can_be_deactivated_and_reactivated(client, manager_client) -> None:
    """Aktiflik değişikliği sonraki GET isteğinde de görülebilmeli."""

    create_response = client.post(
        "/teams",
        json={"name": f"Test Ekibi {uuid4().hex}"},
    )

    assert create_response.status_code == 201, create_response.text
    original_team = create_response.json()
    team_id = original_team["id"]

    # Önce pasife al, sonra yeniden aktifleştir.
    for desired_status in (False, True):
        update_response = client.patch(
            f"/teams/{team_id}/status",
            json={"is_active": desired_status},
        )

        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["is_active"] is desired_status

        read_response = client.get(f"/teams/{team_id}")

        assert read_response.status_code == 200, read_response.text

        current_team = read_response.json()

        assert current_team["is_active"] is desired_status

        # Aktiflik değişirken diğer bilgiler korunmalı.
        assert current_team["id"] == original_team["id"]
        assert current_team["name"] == original_team["name"]
        assert current_team["created_at"] == original_team["created_at"]