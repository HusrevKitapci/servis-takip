"""
Kullanıcı oluşturma işleminin davranış ve veri saklama testleri.

API yanıtını ve veritabanındaki gerçek kaydı birlikte kontrol eder.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User, UserRole
from app.security import verify_password


# ============================================================================
# 2. ÖRNEK İSTEK VERİSİ
# ============================================================================

@pytest.fixture
def user_payload() -> dict[str, str]:
    """Her test için benzersiz e-posta içeren yeni bir istek gövdesi oluşturur."""

    return {
        "full_name": "   Test Kullanıcısı   ",
        "email": f"USER-{uuid4().hex}@EXAMPLE.COM",

        # Kenar boşluklarını bilerek ekliyoruz.
        # Parolanın sessizce kırpılmadığını da kontrol edeceğiz.
        "password": "  Sadece-Test-Icin-Guclu-Parola-42!  ",
    }


# ============================================================================
# 3. BAŞARILI KAYIT VE PAROLANIN SAKLANMA BİÇİMİ
# ============================================================================

def test_create_user_stores_hash_and_returns_safe_response(
    client: TestClient,
    db_session: Session,
    user_payload: dict[str, str],
) -> None:
    """Yanıt güvenli olmalı; veritabanında doğrulanabilir parola özeti bulunmalı."""

    response = client.post("/users", json=user_payload)

    assert response.status_code == 201, response.text

    data = response.json()

    # Başarılı yanıtta yalnızca izin verdiğimiz alanlar bulunmalı.
    assert set(data) == {
        "id",
        "full_name",
        "email",
        "role",
        "is_active",
        "created_at",
    }

    assert data["full_name"] == "Test Kullanıcısı"
    assert data["email"] == user_payload["email"].lower()
    assert data["role"] == "requester"
    assert data["is_active"] is True

    # API yanıtıyla yetinmeyip veritabanındaki kaydı incele.
    stored_user = db_session.get(User, data["id"])

    assert stored_user is not None
    assert stored_user.email == user_payload["email"].lower()
    assert stored_user.role == UserRole.REQUESTER

    original_password = user_payload["password"]

    assert stored_user.password_hash != original_password
    assert verify_password(
        original_password,
        stored_user.password_hash,
    ) is True

    # Ad ve e-posta temizlenebilir; parolanın kenar boşlukları korunmalı.
    assert verify_password(
        original_password.strip(),
        stored_user.password_hash,
    ) is False


# ============================================================================
# 4. E-POSTA NORMALLEŞTİRME VE BENZERSİZLİK
# ============================================================================

def test_email_is_unique_after_normalization(
    client: TestClient,
    db_session: Session,
    user_payload: dict[str, str],
) -> None:
    """Büyük/küçük harf değişikliğiyle aynı e-postadan ikinci hesap açılamamalı."""

    first_response = client.post("/users", json=user_payload)

    assert first_response.status_code == 201, first_response.text

    second_payload = {
        **user_payload,
        "email": user_payload["email"].lower(),
    }

    second_response = client.post("/users", json=second_payload)

    assert second_response.status_code == 409, second_response.text

    statement = (
        select(func.count())
        .select_from(User)
        .where(User.email == user_payload["email"].lower())
    )

    assert db_session.scalar(statement) == 1


# ============================================================================
# 5. SUNUCUNUN YÖNETTİĞİ ALANLARI İSTEMCİDEN KABUL ETMEME
# ============================================================================

@pytest.mark.parametrize(
    "extra_fields",
    [
        {"role": "manager"},
        {"is_active": False},
        {"password_hash": "istemcinin-gonderdigi-deger"},
    ],
    ids=[
        "role_cannot_be_selected",
        "active_status_cannot_be_selected",
        "password_hash_cannot_be_supplied",
    ],
)
def test_client_cannot_supply_server_managed_fields(
    client: TestClient,
    db_session: Session,
    user_payload: dict[str, str],
    extra_fields: dict[str, object],
) -> None:
    """İzin verilmeyen alanları içeren istek reddedilmeli ve kayıt oluşmamalı."""

    payload = {
        **user_payload,
        **extra_fields,
    }

    response = client.post("/users", json=payload)

    assert response.status_code == 422, response.text

    statement = select(User.id).where(
        User.email == user_payload["email"].lower()
    )

    assert db_session.scalar(statement) is None


# ============================================================================
# 6. PAROLAYI DOĞRULAMA HATASINDA GERİ DÖNDÜRMEME
# ============================================================================

def test_short_password_is_not_echoed_in_validation_error(
    client: TestClient,
    db_session: Session,
    user_payload: dict[str, str],
) -> None:
    """Kısa parola reddedilmeli; hata yanıtı gönderilen parolayı içermemeli."""

    payload = {
        **user_payload,
        "password": "kisa",
    }

    response = client.post("/users", json=payload)

    assert response.status_code == 422, response.text

    errors = response.json()["detail"]

    assert any(
        error["loc"] == ["body", "password"]
        for error in errors
    )

    assert all("input" not in error for error in errors)
    assert "kisa" not in response.text

    statement = select(User.id).where(
        User.email == user_payload["email"].lower()
    )

    assert db_session.scalar(statement) is None