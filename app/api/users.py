"""
Kullanıcı oluşturma endpoint'i.

İstemciden rol kabul etmez.
Parolayı özetleyerek yeni hesabı requester rolünde kaydeder.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import (
    CurrentUserDependency,
    get_session,
    require_manager,
)
from app.models import User, UserRole
from app.schemas.user import UserCreate, UserRead
from app.security import hash_password


# ============================================================================
# 2. ROUTER VE VERİTABANI BAĞIMLILIĞI
# ============================================================================

router = APIRouter(
    prefix="/users",
    tags=["Kullanıcılar"],
)

SessionDependency = Annotated[Session, Depends(get_session)]


# ============================================================================
# 3. KULLANICI OLUŞTURMA
# ============================================================================

@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni talep sahibi hesabı oluştur",
    responses={
        409: {"description": "Bu e-posta adresi zaten kullanılıyor."},
    },
)
def create_user(
    payload: UserCreate,
    session: SessionDependency,
) -> User:
    """Doğrulanmış bilgileri kullanarak yeni bir requester hesabı oluşturur."""

    # SecretStr içindeki gerçek parolayı yalnızca özetleme işlemine veriyoruz.
    # Düz parolayı veritabanı modeline atamıyoruz.
    password_hash = hash_password(
        payload.password.get_secret_value()
    )

    user = User(
        full_name=payload.full_name,
        email=str(payload.email),
        password_hash=password_hash,

        # Rolü istemci değil, bu işlem için sunucudaki kural belirler.
        role=UserRole.REQUESTER,
    )

    session.add(user)

    try:
        session.commit()

    except IntegrityError as exc:
        session.rollback()

        if (
            isinstance(exc.orig, UniqueViolation)
            and exc.orig.diag.constraint_name == "uq_users_email"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu e-posta adresi zaten kullanılıyor.",
            ) from exc

        # Diğer bütünlük hatalarını yanlış bir mesajla gizleme.
        raise

    session.refresh(user)

    return user

# ============================================================
# GİRİŞ YAPAN KULLANICININ BİLGİLERİ
# ============================================================

@router.get(
    "/me",
    response_model=UserRead,
    summary="Giriş yapan kullanıcının bilgilerini getir",
    responses={
        401: {
            "description": "Oturum doğrulanamadı veya hesap kullanılamıyor.",
        },
    },
)
def read_current_user(
    current_user: CurrentUserDependency,
) -> User:
    """
    İsteği yapan doğrulanmış kullanıcının bilgilerini döndürür.

    Kimlik doğrulama, CurrentUserDependency tarafından yapılır.
    Yanıta hangi alanların yazılacağını UserRead belirler.
    """

    return current_user

# ============================================================
# YÖNETİCİ TARAFINDAN SERVİS GÖREVLİSİ OLUŞTURMA
# ============================================================

@router.post(
    "/agents",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_manager)],
    summary="Servis görevlisi hesabı oluştur",
)
def create_agent(
    payload: UserCreate,
    session: SessionDependency,
) -> User:
    """
    Yönetici tarafından yeni bir agent hesabı oluşturur.

    Rol istek gövdesinden alınmaz; endpoint'in iş kuralı gereği
    sunucu tarafından AGENT olarak belirlenir.
    """

    user = User(
        full_name=payload.full_name,
        email=str(payload.email),
        password_hash=hash_password(
            payload.password.get_secret_value()
        ),
        role=UserRole.AGENT,
    )

    session.add(user)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()

        if (
            isinstance(exc.orig, UniqueViolation)
            and exc.orig.diag.constraint_name == "uq_users_email"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu e-posta adresi zaten kullanılıyor.",
            ) from exc

        raise

    session.refresh(user)
    return user