"""Servis taleplerinde gerçekleşen işlemlerin geçmişini saklar."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Identity,
    Index,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================
# 2. GEÇMİŞE KAYDEDİLEBİLEN İŞLEM TÜRLERİ
# ============================================================

class TicketEventType(StrEnum):
    """Talep geçmişinde kullanılabilecek işlem adları."""

    CREATED = "CREATED"
    CLAIMED = "CLAIMED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    COMMENT_ADDED = "COMMENT_ADDED"


# ============================================================
# 3. İŞLEM GEÇMİŞİ TABLOSU
# ============================================================

class TicketEvent(Base):
    """Bir talepte gerçekleşmiş tek bir işlemi temsil eder."""

    __tablename__ = "ticket_events"

    __table_args__ = (
        # Bir talebin geçmişini kayıt sırasına göre okumayı destekler.
        Index(
            "ix_ticket_events_ticket_id_id",
            "ticket_id",
            "id",
        ),
    )

    # --------------------------------------------------------
    # 3.1. Kayıt kimliği
    # --------------------------------------------------------

    id: Mapped[int] = mapped_column(
        Identity(),
        primary_key=True,
    )

    # --------------------------------------------------------
    # 3.2. İşlemin hangi talebe ait olduğu
    # --------------------------------------------------------

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # --------------------------------------------------------
    # 3.3. İşlemi yapan kullanıcı
    # --------------------------------------------------------

    actor_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # --------------------------------------------------------
    # 3.4. İşlemin türü
    # --------------------------------------------------------

    event_type: Mapped[TicketEventType] = mapped_column(
        SqlEnum(
            TicketEventType,
            values_callable=lambda enum_class: [
                item.value for item in enum_class
            ],
            native_enum=False,
            create_constraint=True,
            name="ck_ticket_events_event_type",
        ),
        nullable=False,
    )

    # --------------------------------------------------------
    # 3.5. İşleme ait ek bilgiler
    # --------------------------------------------------------

    # Örnek:
    # {"from_status": "OPEN", "to_status": "IN_PROGRESS"}
    #
    # default=dict, her kayıt için ayrı bir sözlük oluşturur.
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    # --------------------------------------------------------
    # 3.6. Kaydın oluşturulma zamanı
    # --------------------------------------------------------

    # Mapped[datetime], Python tarafındaki veri türünü belirtir.
    # DateTime ise veritabanındaki sütunun türünü belirtir.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )