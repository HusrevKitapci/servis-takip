"""İlk yanıt süresi endpoint'inin yanıt şeması."""

from datetime import datetime

from pydantic import BaseModel

from app.sla import SlaStatus


class TicketSlaRead(BaseModel):
    """Bir talebin ilk yanıt hedefini ve değerlendirme sonucunu taşır."""

    ticket_id: int
    status: SlaStatus

    policy_version: str | None
    target_seconds: int | None

    started_at: datetime
    due_at: datetime | None
    first_response_at: datetime | None
    evaluated_at: datetime