"""Talep, yorum ve işlem geçmişi için API veri şemaları."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.ticket import TicketPriority, TicketStatus
from app.models.ticket_event import TicketEventType


# ============================================================
# 2. TALEP OLUŞTURMA İSTEĞİ
# ============================================================

class TicketCreate(BaseModel):
    """Kullanıcının yeni talep oluştururken gönderebileceği alanlar."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    title: str = Field(
        min_length=5,
        max_length=150,
    )

    description: str = Field(
        min_length=10,
        max_length=5000,
    )

    priority: TicketPriority = TicketPriority.NORMAL

    team_id: int = Field(
        strict=True,
        gt=0,
        le=2_147_483_647,
    )


# ============================================================
# 3. TALEP YANITI VE SAYFALAMA
# ============================================================

class TicketRead(BaseModel):
    """Kaydedilmiş talebin API üzerinden gösterilen alanları."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    priority: TicketPriority
    status: TicketStatus
    requester_id: int
    team_id: int
    assignee_id: int | None
    claimed_at: datetime | None
    created_at: datetime
    resolved_at: datetime | None


class TicketPage(BaseModel):
    """Talep listesinin bir sayfasını ve toplam kayıt sayısını taşır."""

    items: list[TicketRead]
    total: int
    limit: int
    offset: int


# ============================================================
# 4. YORUM OLUŞTURMA İSTEĞİ
# ============================================================

class TicketCommentCreate(BaseModel):
    """Yorum metnini doğrular; yazar kimliğini istemciden almaz."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    body: str = Field(
        min_length=2,
        max_length=5000,
        description="Talebe eklenecek yorum metni.",
    )


# ============================================================
# 5. YORUM YANITI VE SAYFALAMA
# ============================================================

class TicketCommentRead(BaseModel):
    """Kaydedilmiş yorumun dışarıya açılan alanları."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    author_id: int
    body: str
    created_at: datetime


class TicketCommentPage(BaseModel):
    """Bir talebin yorumlarının sayfalanmış yanıtı."""

    items: list[TicketCommentRead]
    total: int
    limit: int
    offset: int


# ============================================================
# 6. İŞLEM GEÇMİŞİ YANITI VE SAYFALAMA
# ============================================================

class TicketEventRead(BaseModel):
    """Talepte gerçekleşmiş bir işlemin API yanıtı."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    actor_id: int
    event_type: TicketEventType
    details: dict[str, Any]
    created_at: datetime


class TicketEventPage(BaseModel):
    """Bir talebin işlem geçmişinin sayfalanmış yanıtı."""

    items: list[TicketEventRead]
    total: int
    limit: int
    offset: int