"""Servis taleplerine yazılan kullanıcı yorumlarını saklar."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================
# 2. YORUM TABLOSU
# ============================================================

class TicketComment(Base):
    """Bir kullanıcının bir talebe yazdığı yorumu temsil eder."""

    __tablename__ = "ticket_comments"

    __table_args__ = (
        # API dışında yapılan eklemelerde de temel uzunluk kuralını korur.
        CheckConstraint(
            "char_length(body) <= 5000 "
            "AND char_length(btrim(body)) >= 2",
            name="ck_ticket_comments_body_length",
        ),
        # Bir talebin yorumlarını kayıt sırasına göre okumayı destekler.
        Index(
            "ix_ticket_comments_ticket_id_id",
            "ticket_id",
            "id",
        ),
    )

    # --------------------------------------------------------
    # 2.1. Yorum kimliği
    # --------------------------------------------------------

    id: Mapped[int] = mapped_column(
        Identity(),
        primary_key=True,
    )

    # --------------------------------------------------------
    # 2.2. Yorumun ait olduğu talep
    # --------------------------------------------------------

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # --------------------------------------------------------
    # 2.3. Yorumu yazan kullanıcı
    # --------------------------------------------------------

    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # --------------------------------------------------------
    # 2.4. Yorumun içeriği
    # --------------------------------------------------------

    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # --------------------------------------------------------
    # 2.5. Oluşturulma zamanı
    # --------------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )