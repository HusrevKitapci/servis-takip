# ============================================================
# İÇE AKTARMALAR
# ============================================================

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================
# 1. TALEP ÖNCELİKLERİ VE DURUMLARI
# ============================================================

class TicketPriority(StrEnum):
    """Kabul edilen talep öncelikleri."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class TicketStatus(StrEnum):
    """Talebin iş akışındaki durumları."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


# ============================================================
# 2. SERVİS TALEBİ MODELİ
# ============================================================

class Ticket(Base):
    """Servis talebinin içeriğini, sahipliğini ve atamasını saklar."""

    __tablename__ = "tickets"

    # --------------------------------------------------------
    # 2.1. Veritabanı kısıtları ve indeksler
    # --------------------------------------------------------

    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 5 AND 150",
            name="ck_tickets_title_length",
        ),
        CheckConstraint(
            "char_length(btrim(description)) BETWEEN 10 AND 5000",
            name="ck_tickets_description_length",
        ),
        CheckConstraint(
            "(status = 'OPEN' "
            "AND assignee_id IS NULL AND claimed_at IS NULL) "
            "OR "
            "(status IN ('IN_PROGRESS', 'RESOLVED') "
            "AND assignee_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="ck_tickets_assignment_state",
        ),
        CheckConstraint(
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL) "
            "OR "
            "(status <> 'RESOLVED' AND resolved_at IS NULL)",
            name="ck_tickets_resolution_time",
        ),
        Index("ix_tickets_requester_id_id", "requester_id", "id"),
        Index("ix_tickets_team_id_id", "team_id", "id"),
    )

    # --------------------------------------------------------
    # 2.2. Kimlik ve içerik
    # --------------------------------------------------------

    id: Mapped[int] = mapped_column(
        Identity(),
        primary_key=True,
    )

    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    priority: Mapped[TicketPriority] = mapped_column(
        SqlEnum(
            TicketPriority,
            values_callable=lambda enum_class: [
                member.value for member in enum_class
            ],
            native_enum=False,
            create_constraint=True,
            name="ck_tickets_priority",
            validate_strings=True,
        ),
        nullable=False,
        server_default=text("'NORMAL'"),
    )

    # --------------------------------------------------------
    # 2.3. İş akışı durumu
    # --------------------------------------------------------

    status: Mapped[TicketStatus] = mapped_column(
        SqlEnum(
            TicketStatus,
            values_callable=lambda enum_class: [
                member.value for member in enum_class
            ],
            native_enum=False,
            create_constraint=True,
            name="ck_tickets_status",
            validate_strings=True,
        ),
        nullable=False,
        server_default=text("'OPEN'"),
    )

    # --------------------------------------------------------
    # 2.4. Talebi açan kişi ve hedef ekip
    # --------------------------------------------------------

    requester_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_tickets_requester_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    team_id: Mapped[int] = mapped_column(
        ForeignKey(
            "teams.id",
            name="fk_tickets_team_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    # --------------------------------------------------------
    # 2.5. Talebi üstlenen görevli ve üstlenme zamanı
    # --------------------------------------------------------

    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_tickets_assignee_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # 2.6. Talebin oluşturulma zamanı
    # --------------------------------------------------------

    # Bu alan claimed_at'ten farklıdır.
    # Talep açılınca oluşur; üstlenilmeyi beklemez.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # --------------------------------------------------------
    # 2.7. Güncel çözümün zamanı
    # --------------------------------------------------------

    # Talep çözülene kadar boştur.
    # Yeniden açılırsa tekrar boşaltılır.
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )