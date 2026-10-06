"""
Parola özetleme ve doğrulama testleri.

Bunlar birim testleridir: veritabanı oturumu veya HTTP isteği kullanmazlar.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from app.security import hash_password, verify_password


# ============================================================================
# 2. DOĞRU PAROLAYI DOĞRULAMA
# ============================================================================

def test_correct_password_is_verified() -> None:
    """Üretilen özet, oluşturulduğu parolayı doğrulayabilmeli."""

    password = "Yalnizca-Test-Icin-Guclu-Parola-42!"
    password_hash = hash_password(password)

    assert password_hash != password

    assert verify_password(
        password=password,
        password_hash=password_hash,
    ) is True


# ============================================================================
# 3. YANLIŞ PAROLAYI REDDETME
# ============================================================================

def test_wrong_password_is_rejected() -> None:
    """Farklı bir parola, kayıtlı özetle eşleşmemeli."""

    password_hash = hash_password(
        "Yalnizca-Test-Icin-Guclu-Parola-42!"
    )

    assert verify_password(
        password="Bu-Farkli-Bir-Parola-99!",
        password_hash=password_hash,
    ) is False


# ============================================================================
# 4. AYNI PAROLA İÇİN AYRI ÖZETLER ÜRETME
# ============================================================================

def test_same_password_produces_different_valid_hashes() -> None:
    """Rastgele salt nedeniyle özetler farklı olsa da ikisi doğrulanabilmeli."""

    password = "Yalnizca-Test-Icin-Guclu-Parola-42!"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash

    assert verify_password(
        password=password,
        password_hash=first_hash,
    ) is True

    assert verify_password(
        password=password,
        password_hash=second_hash,
    ) is True