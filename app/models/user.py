"""
Kullanıcı tablosu ve kullanıcı rolleri.

Bu modül kullanıcıların veritabanında nasıl saklanacağını tanımlar.
Parola özetleme, giriş yapma ve yetki kontrolü işlemlerini gerçekleştirmez.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    Identity,
    String,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================================
# 2. KULLANICI ROLLERİ
# ============================================================================

class UserRole(StrEnum):
    """Uygulamada kabul edilen kullanıcı rolleri."""

    REQUESTER = "requester"
    AGENT = "agent"
    MANAGER = "manager"


# ============================================================================
# 3. KULLANICI TABLOSU
# ============================================================================

class User(Base):
    """PostgreSQL'deki users tablosunu temsil eder."""

    __tablename__ = "users"

    # ------------------------------------------------------------------------
    # 3.1. Veritabanı kısıtları
    # ------------------------------------------------------------------------

    __table_args__ = (
        UniqueConstraint(
            "email",
            name="uq_users_email",
        ),

        CheckConstraint(
            "char_length(btrim(full_name)) >= 2",
            name="ck_users_full_name_min_length",
        ),

        # Bu projede e-postaları küçük harfli ve kenar boşluksuz saklayacağız.
        # Kısıt veriyi dönüştürmez; bu kurala uymayan kaydı reddeder.
        CheckConstraint(
            "email = lower(btrim(email))",
            name="ck_users_email_normalized",
        ),

        CheckConstraint(
            "char_length(email) >= 3",
            name="ck_users_email_min_length",
        ),
    )

    # ------------------------------------------------------------------------
    # 3.2. Kimlik ve iletişim bilgileri
    # ------------------------------------------------------------------------

    id: Mapped[int] = mapped_column(
        Identity(),
        primary_key=True,
    )

    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
    )

    # ------------------------------------------------------------------------
    # 3.3. Parola doğrulama bilgisi
    # ------------------------------------------------------------------------

    # Bu sütuna yalnızca parola özetleme işleminin sonucu yazılacak.
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # ------------------------------------------------------------------------
    # 3.4. Rol ve hesap durumu
    # ------------------------------------------------------------------------

    role: Mapped[UserRole] = mapped_column(
        SqlEnum(
            UserRole,

            # Python üye adları yerine "requester" gibi değerleri sakla.
            values_callable=lambda enum_class: [
                member.value for member in enum_class
            ],

            # Rolü metin sütunu ve CHECK kısıtıyla sakla.
            native_enum=False,
            create_constraint=True,
            name="ck_users_role",

            # SQLAlchemy üzerinden verilen geçersiz metin değerlerini de reddet.
            validate_strings=True,
        ),
        nullable=False,
        server_default=text("'requester'"),
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )

    # ------------------------------------------------------------------------
    # 3.5. Oluşturulma zamanı
    # ------------------------------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )