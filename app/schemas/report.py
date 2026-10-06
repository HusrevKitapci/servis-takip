"""Talep özet raporunun API yanıt şemaları."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime

from pydantic import BaseModel, Field

from app.models import TicketPriority, TicketStatus
from app.sla import SlaStatus


# ============================================================
# 2. RAPORDAKİ SAYIM SATIRLARI
# ============================================================

class TicketStatusCount(BaseModel):
    """Bir talep durumuna ait kayıt sayısı."""

    status: TicketStatus
    count: int = Field(ge=0)


class TicketPriorityCount(BaseModel):
    """Bir öncelik seviyesine ait kayıt sayısı."""

    priority: TicketPriority
    count: int = Field(ge=0)


class TicketSlaCount(BaseModel):
    """Bir SLA sonucuna ait kayıt sayısı."""

    status: SlaStatus
    count: int = Field(ge=0)


# ============================================================
# 3. RAPORUN TAMAMI
# ============================================================

class TicketSummary(BaseModel):
    """Kullanıcının erişebildiği taleplerin sayısal özeti."""

    total: int = Field(ge=0)
    evaluated_at: datetime

    by_status: list[TicketStatusCount]
    by_priority: list[TicketPriorityCount]
    by_sla: list[TicketSlaCount]