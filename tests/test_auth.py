# ============================================================
# İÇE AKTARMALAR
# ============================================================

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from app.config import get_settings
from app.models import User
from app.security import JWT_ALGORITHM


# ============================================================
# 1. ORTAK TEST VERİLERİ VE YARDIMCILAR
# ============================================================

# Bu parola yalnızca otomatik testlerde oluşturulan hesaplara aittir.
TEST_PASSWORD = "Sadece-Test-Icin-Guclu-Parola-42!"


@pytest.fixture
def registered_user(client):
    """
    Test için API üzerinden yeni bir kullanıcı oluşturur.

    Her testin e-posta adresi farklıdır. Temizlik işlemini mevcut
    conftest.py içindeki transaction düzeni gerçekleştirir.
    """

    payload = {
        "full_name": "Kimlik Doğrulama Test Kullanıcısı",
        "email": f"auth-{uuid4().hex}@example.com",
        "password": TEST_PASSWORD,
    }

    response = client.post("/users", json=payload)

    # Hazırlık başarısızsa asıl teste yanlış veriyle devam etmeyiz.
    assert response.status_code == 201

    return response.json()


@pytest.fixture
def access_token(client, registered_user):
    """
    Gerçek giriş endpoint'ini kullanarak geçerli token alır.

    Böylece token gereken testler, kayıtlı bir kullanıcıya ve
    başarılı giriş sonucunda üretilmiş bir token'a sahip olur.
    """

    response = client.post(
        "/auth/token",
        data={
            "username": registered_user["email"],
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    return response.json()["access_token"]


def bearer_headers(token: str) -> dict[str, str]:
    """Token'ı HTTP isteğinin Authorization başlığına yerleştirir."""

    return {"Authorization": f"Bearer {token}"}


def assert_unauthorized(response) -> None:
    """Kimlik doğrulama reddinin ortak HTTP özelliklerini kontrol eder."""

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


# ============================================================
# 2. BAŞARILI GİRİŞ VE KULLANICI BİLGİLERİ
# ============================================================

def test_login_and_read_current_user(client, registered_user):
    """
    Kayıt -> giriş -> token ile kullanıcıyı okuma akışını doğrular.
    """

    # --------------------------------------------------------
    # 2.1. E-posta ve parolayla giriş yap
    # --------------------------------------------------------

    login_response = client.post(
        "/auth/token",
        data={
            "username": registered_user["email"],
            "password": TEST_PASSWORD,
        },
    )

    assert login_response.status_code == 200

    token_data = login_response.json()

    assert token_data["token_type"] == "bearer"
    assert isinstance(token_data["access_token"], str)
    assert token_data["access_token"]

    # Giriş yanıtı, token'ın önbelleğe alınmamasını istemeli.
    assert login_response.headers["cache-control"] == "no-store"
    assert login_response.headers["pragma"] == "no-cache"

    # --------------------------------------------------------
    # 2.2. Alınan token ile kendi bilgilerini iste
    # --------------------------------------------------------

    profile_response = client.get(
        "/users/me",
        headers=bearer_headers(token_data["access_token"]),
    )

    assert profile_response.status_code == 200

    profile = profile_response.json()

    # Yalnızca herhangi bir kullanıcı değil, giriş yapan kullanıcı
    # dönmüş olmalı.
    assert profile["id"] == registered_user["id"]
    assert profile["email"] == registered_user["email"]
    assert profile["role"] == "requester"
    assert profile["is_active"] is True

    # Yanıtta yalnızca dışarıya açtığımız alanlar bulunmalı.
    # Bu kontrol password_hash gibi bir alanın sızmasını da yakalar.
    assert set(profile) == {
        "id",
        "full_name",
        "email",
        "role",
        "is_active",
        "created_at",
    }


# ============================================================
# 3. GEÇERSİZ GİRİŞ BİLGİLERİ
# ============================================================

@pytest.mark.parametrize(
    "failure_case",
    ["wrong_password", "unknown_email"],
)
def test_login_rejects_invalid_credentials(
    client,
    registered_user,
    failure_case,
):
    """
    Yanlış parola ve olmayan kullanıcı için aynı hata yanıtını bekler.
    """

    email = registered_user["email"]
    password = TEST_PASSWORD

    if failure_case == "wrong_password":
        password = "Bu-Parola-Kayitli-Parola-Degil-42!"
    else:
        email = f"missing-{uuid4().hex}@example.com"

    response = client.post(
        "/auth/token",
        data={
            "username": email,
            "password": password,
        },
    )

    assert_unauthorized(response)

    assert response.json() == {
        "detail": "Giriş bilgileri geçersiz veya hesap kullanılamıyor.",
    }


# ============================================================
# 4. TOKEN OLMADAN ERİŞİM
# ============================================================

def test_current_user_requires_token(client):
    """Authorization başlığı olmayan istek reddedilmeli."""

    response = client.get("/users/me")

    assert_unauthorized(response)


# ============================================================
# 5. GEÇERSİZ TOKEN SENARYOLARI
# ============================================================

@pytest.mark.parametrize(
    "failure_case",
    [
        "wrong_signature",
        "expired",
        "missing_exp",
        "invalid_subject",
        "wrong_algorithm",
    ],
)
def test_current_user_rejects_invalid_token(
    client,
    registered_user,
    failure_case,
):
    """
    Her çalıştırmada token'ın tek bir özelliğini geçersiz yapar.

    Diğer özellikleri geçerli tutarak hangi kuralın kontrol
    edildiğini belirgin hâle getiririz.
    """

    # --------------------------------------------------------
    # 5.1. Başlangıçta geçerli olacak token verilerini hazırla
    # --------------------------------------------------------

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(registered_user["id"]),
        "iat": now - timedelta(minutes=1),
        "exp": now + timedelta(minutes=5),
    }

    signing_key = get_settings().jwt_secret_key.get_secret_value()
    algorithm = JWT_ALGORITHM

    # --------------------------------------------------------
    # 5.2. Yalnızca seçilen özelliği geçersiz yap
    # --------------------------------------------------------

    if failure_case == "wrong_signature":
        # Gerçek anahtardan farklı olduğu kesin olan bir anahtar.
        signing_key = f"{signing_key}-different-test-key"

    elif failure_case == "expired":
        # Beklemek yerine geçmişte sona ermiş bir token oluştur.
        payload["iat"] = now - timedelta(minutes=10)
        payload["exp"] = now - timedelta(minutes=5)

    elif failure_case == "missing_exp":
        # İmza doğru olsa bile sona erme alanı zorunludur.
        del payload["exp"]

    elif failure_case == "invalid_subject":
        # PostgreSQL INTEGER üst sınırından büyük bir kimlik.
        # Bu değer sorguya ulaşmadan 401 ile reddedilmeli.
        payload["sub"] = "2147483648"

    elif failure_case == "wrong_algorithm":
        # Anahtar doğru olsa bile yalnızca izin verdiğimiz
        # algoritmayı kabul etmeliyiz.
        algorithm = "HS384"

    # --------------------------------------------------------
    # 5.3. Hazırlanan token'ı gerçek endpoint'e gönder
    # --------------------------------------------------------

    token = jwt.encode(
        payload,
        signing_key,
        algorithm=algorithm,
    )

    response = client.get(
        "/users/me",
        headers=bearer_headers(token),
    )

    assert_unauthorized(response)


# ============================================================
# 6. PASİF HESABIN GİRİŞ YAPMASI
# ============================================================

def test_inactive_user_cannot_login(
    client,
    db_session,
    registered_user,
):
    """Doğru parola, pasif hesabın giriş yapmasına yetmemeli."""

    user = db_session.get(User, registered_user["id"])
    assert user is not None

    user.is_active = False
    db_session.commit()

    response = client.post(
        "/auth/token",
        data={
            "username": registered_user["email"],
            "password": TEST_PASSWORD,
        },
    )

    assert_unauthorized(response)


# ============================================================
# 7. TOKEN VERİLDİKTEN SONRA HESABIN PASİFE ALINMASI
# ============================================================

def test_existing_token_is_rejected_after_deactivation(
    client,
    db_session,
    registered_user,
    access_token,
):
    """
    Önceden alınmış geçerli token, pasife alınan hesaba erişim sağlamamalı.
    """

    # Token fixture'ı bu fonksiyondan önce çalışır.
    # Yani kullanıcı aktifken giriş yapmış durumdadır.
    user = db_session.get(User, registered_user["id"])
    assert user is not None

    user.is_active = False
    db_session.commit()

    response = client.get(
        "/users/me",
        headers=bearer_headers(access_token),
    )

    assert_unauthorized(response)


# ============================================================
# 8. TOKEN VERİLDİKTEN SONRA HESABIN SİLİNMESİ
# ============================================================

def test_existing_token_is_rejected_after_user_deletion(
    client,
    db_session,
    registered_user,
    access_token,
):
    """
    İmzası ve süresi geçerli token, silinmiş hesabı geri getirmemeli.

    Silme işlemi yalnızca test veritabanındaki test kullanıcısına
    uygulanır. Bu test bir kullanıcı silme endpoint'i oluşturmaz.
    """

    user = db_session.get(User, registered_user["id"])
    assert user is not None

    db_session.delete(user)
    db_session.commit()

    response = client.get(
        "/users/me",
        headers=bearer_headers(access_token),
    )

    assert_unauthorized(response)