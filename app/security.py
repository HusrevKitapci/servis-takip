"""
Parola işlemleri ve erişim tokenı üretimi.

Bu modül:
- Parolaları özetler.
- Parolaları kayıtlı özetlerle doğrular.
- Kullanıcı kimliği için süreli, imzalı erişim tokenı üretir.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.config import get_settings


# ============================================================================
# 2. GÜVENLİK ARAÇLARI
# ============================================================================

password_hasher = PasswordHash.recommended()

# İmzalama algoritmasını uygulama belirler.
# İstemcinin gönderdiği bir değerden seçmiyoruz.
JWT_ALGORITHM = "HS256"


# ============================================================================
# 3. PAROLA İŞLEMLERİ
# ============================================================================

def hash_password(password: str) -> str:
    """Parolayı değiştirmeden, saklanabilir bir parola özeti üretir."""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Geçerli bir parola özeti için eşleşme varsa True, yoksa False döndürür."""

    return password_hasher.verify(password, password_hash)


# ============================================================================
# 4. ERİŞİM TOKENI ÜRETME
# ============================================================================

def create_access_token(user_id: int) -> str:
    """Kullanıcı kimliği ve zaman bilgilerini içeren imzalı token üretir."""

    settings = get_settings()

    issued_at = datetime.now(timezone.utc)

    expires_at = issued_at + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        # sub: Tokenın hangi kullanıcıya ait olduğunu belirtir.
        # JWT içinde kullanıcı kimliğini metin olarak saklıyoruz.
        "sub": str(user_id),

        # iat: Tokenın oluşturulduğu zaman.
        "iat": issued_at,

        # exp: Tokenın kabul edilebileceği son zaman.
        "exp": expires_at,
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

# ============================================================
# TOKEN DOĞRULAMA
# ============================================================

def get_user_id_from_token(token: str) -> int:
    """
    Token'ı doğrular ve token'ın ait olduğu kullanıcı kimliğini döndürür.

    Geçersiz imza, süresi dolmuş token, eksik zorunlu alan veya
    uygun olmayan kullanıcı kimliği için InvalidTokenError oluşur.

    Bu fonksiyon veritabanına erişmez. Kullanıcının hâlâ var olup
    olmadığı ve aktifliği, isteğe ait veritabanı oturumunda kontrol edilir.
    """

    # --------------------------------------------------------
    # 1. İmzayı, süreyi ve zorunlu alanları doğrula
    # --------------------------------------------------------

    settings = get_settings()

    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        options={
            "require": ["sub", "iat", "exp"],
        },
    )

    # --------------------------------------------------------
    # 2. Token'daki kullanıcı kimliğinin biçimini kontrol et
    # --------------------------------------------------------

    # Token üretirken kullanıcı kimliğini "sub" alanına metin
    # olarak yazmıştık. Örneğin: {"sub": "12"}.
    subject = payload["sub"]

    # Kabul ettiğimiz biçim: başında sıfır bulunmayan,
    # yalnızca ASCII rakamlarından oluşan pozitif bir kimlik.
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 10
        or not subject.isascii()
        or not subject.isdigit()
        or subject.startswith("0")
    ):
        raise InvalidTokenError("Token kullanıcı kimliği geçersiz.")

    user_id = int(subject)

    # User.id sütunumuz PostgreSQL INTEGER türündedir.
    # Bu sınırın dışındaki değerleri sorguya göndermeden reddederiz.
    if user_id > 2_147_483_647:
        raise InvalidTokenError("Token kullanıcı kimliği sınır dışında.")

    return user_id