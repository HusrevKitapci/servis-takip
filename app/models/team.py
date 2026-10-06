"""
Ekip tablosunun SQLAlchemy modeli.

Bir ekip, destek taleplerinin yönlendirileceği çalışma grubudur.
Örnek: Bilgi Teknolojileri veya İnsan Kaynakları.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================================
# 2. EKİP TABLOSU
# ============================================================================

class Team(Base):
    """PostgreSQL'deki teams tablosunu temsil eder."""

    __tablename__ = "teams"

    # ------------------------------------------------------------------------
    # 2.1. Veritabanı kısıtları
    # ------------------------------------------------------------------------

    __table_args__ = (
        # Aynı ekip adının ikinci kez kaydedilmesini engeller.
        UniqueConstraint(
            "name",
            name="uq_teams_name",
        ),

        # Kenarlardaki normal boşluklar çıkarıldığında en az iki karakter ister.
        # Bu kontrol veriyi temizlemez; kurala uymayan kaydı reddeder.
        CheckConstraint(
            "char_length(btrim(name)) >= 2",
            name="ck_teams_name_min_length",
        ),
    )

    # ------------------------------------------------------------------------
    # 2.2. Kimlik ve ekip bilgileri
    # ------------------------------------------------------------------------

    id: Mapped[int] = mapped_column(
        Identity(),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # ------------------------------------------------------------------------
    # 2.3. Kullanılabilirlik ve oluşturulma zamanı
    # ------------------------------------------------------------------------

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )