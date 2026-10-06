# ============================================================
# İÇE AKTARMALAR
# ============================================================

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.database import engine
from app.models import User, UserRole
from app.security import get_user_id_from_token


# ============================================================
# 1. VERİTABANI OTURUMU
# ============================================================

def get_session() -> Generator[Session, None, None]:
    """
    İstek boyunca kullanılacak veritabanı oturumunu sağlar.

    yield sonrasında istek işlenir. İşlem bittiğinde with bloğu
    oturumu kapatır. Kayıt işlemlerinin commit kararı ilgili
    uygulama koduna aittir.
    """

    with Session(engine) as session:
        yield session


# Tekrar tekrar aynı Depends ifadesini yazmamak için bir takma ad.
SessionDependency = Annotated[Session, Depends(get_session)]


# ============================================================
# 2. İSTEKTEN BEARER TOKEN'I ALMA
# ============================================================

# tokenUrl, Swagger'ın giriş yapmak için kullanacağı adresi bildirir.
# Bu tanım /auth/token adresini oluşturmaz; o adres auth.py'de var.
#
# auto_error=False sayesinde token bulunamadığında da aşağıdaki
# fonksiyondan aynı biçimde 401 yanıtı üretebiliriz.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/token",
    auto_error=False,
)

TokenDependency = Annotated[str | None, Depends(oauth2_scheme)]


# ============================================================
# 3. İSTEĞİ YAPAN AKTİF KULLANICIYI BULMA
# ============================================================

def get_current_user(
    token: TokenDependency,
    session: SessionDependency,
) -> User:
    """
    Geçerli token'ın ait olduğu aktif kullanıcıyı döndürür.

    Token yoksa, geçersizse, kullanıcı silinmişse veya hesap
    pasifse istek 401 yanıtıyla durdurulur.
    """

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Oturum doğrulanamadı. Lütfen yeniden giriş yapın.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # --------------------------------------------------------
    # 3.1. İstek token içeriyor mu?
    # --------------------------------------------------------

    if not token:
        raise credentials_error

    # --------------------------------------------------------
    # 3.2. Token geçerli mi ve kimin adına düzenlenmiş?
    # --------------------------------------------------------

    try:
        user_id = get_user_id_from_token(token)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    # --------------------------------------------------------
    # 3.3. Kullanıcı hâlâ var mı ve hesabı aktif mi?
    # --------------------------------------------------------

    user = session.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_error

    return user


# Bir endpoint bu bağımlılığı istediğinde, FastAPI önce yukarıdaki
# kontrolleri çalıştırır. Endpoint'e doğrulanmış User nesnesi gelir.
CurrentUserDependency = Annotated[User, Depends(get_current_user)]


# ============================================================
# 4. YÖNETİCİ YETKİSİ
# ============================================================

def require_manager(current_user: CurrentUserDependency) -> User:
    """
    İsteği yapan kullanıcının yönetici olmasını zorunlu kılar.

    CurrentUserDependency önce token'ı ve hesabın aktifliğini kontrol
    eder. Bu fonksiyona ulaşıldığında kullanıcı doğrulanmış durumdadır.
    """

    # Rolü, veritabanından gelen güncel kullanıcı kaydından okuruz.
    if current_user.role != UserRole.MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetici yetkisi gerekiyor.",
        )

    return current_user

# ============================================================
# 5. SERVİS GÖREVLİSİ YETKİSİ
# ============================================================

def require_agent(current_user: CurrentUserDependency) -> User:
    """Yalnızca doğrulanmış ve aktif servis görevlisini kabul eder."""

    if current_user.role != UserRole.AGENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için servis görevlisi yetkisi gerekiyor.",
        )

    return current_user


AgentDependency = Annotated[User, Depends(require_agent)]