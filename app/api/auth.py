"""
E-posta ve parolayla giriş işlemi.

Geçerli ve aktif hesaplar için erişim tokenı üretir.
Başarısız girişlerde aynı genel hata mesajını kullanır.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_session
from app.models import User
from app.schemas.auth import TokenRead
from app.security import create_access_token, hash_password, verify_password


# ============================================================================
# 2. ROUTER VE BAĞIMLILIKLAR
# ============================================================================

router = APIRouter(
    prefix="/auth",
    tags=["Kimlik Doğrulama"],
)

SessionDependency = Annotated[Session, Depends(get_session)]

LoginFormDependency = Annotated[
    OAuth2PasswordRequestForm,
    Depends(),
]

# Var olmayan hesaplarda da parola doğrulama işlemi yapabilmek için kullanılır.
# Gerçek bir kullanıcıya ait değildir; her istekte yeniden üretilmez.
DUMMY_PASSWORD_HASH = hash_password(
    "Bu-Gercek-Bir-Hesabin-Parolasi-Degildir"
)


# ============================================================================
# 3. GİRİŞ VE TOKEN ÜRETİMİ
# ============================================================================

@router.post(
    "/token",
    response_model=TokenRead,
    summary="E-posta ve parolayla giriş yap",
    responses={
        401: {"description": "Giriş bilgileri geçersiz veya hesap kullanılamıyor."},
    },
)
def login(
    response: Response,
    form_data: LoginFormDependency,
    session: SessionDependency,
) -> TokenRead:
    """Aktif hesabın parolasını doğrular ve erişim tokenı döndürür."""

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Giriş bilgileri geçersiz veya hesap kullanılamıyor.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Beklediğimiz hesap alanlarının boyutları dışındaki veriyi reddet.
    if len(form_data.username) > 254 or len(form_data.password) > 128:
        raise credentials_error

    # Form alanının adı username olsa da uygulamada e-posta kullanıyoruz.
    email = form_data.username.strip().lower()

    user = session.scalar(
        select(User).where(User.email == email)
    )

    if user is None:
        # Hesap yokken doğrulamayı tamamen atlamamak, yanıt sürelerindeki
        # belirgin farkı azaltmaya yardımcı olur; eşit süre garantisi değildir.
        verify_password(form_data.password, DUMMY_PASSWORD_HASH)
        raise credentials_error

    password_is_valid = verify_password(
        form_data.password,
        user.password_hash,
    )

    if not password_is_valid or not user.is_active:
        raise credentials_error

    access_token = create_access_token(user.id)

    # Token yanıtının önbelleğe alınmamasını istemciye bildir.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    return TokenRead(access_token=access_token)