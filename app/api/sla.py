"""Talebin ilk yanıt hedefini görüntüleyen endpoint."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from sqlalchemy import func, select

from app.dependencies import CurrentUserDependency, SessionDependency
from app.models import Ticket, TicketEvent, TicketEventType
from app.queries.tickets import visible_tickets_query
from app.schemas.sla import TicketSlaRead
from app.sla import evaluate_first_response


# ============================================================
# 2. ROUTER
# ============================================================

router = APIRouter(
    prefix="/tickets",
    tags=["İlk Yanıt Süresi"],
)


# ============================================================
# 3. İLK YANIT HEDEFİNİ GÖRÜNTÜLE
# ============================================================

@router.get(
    "/{ticket_id}/sla",
    response_model=TicketSlaRead,
    summary="Talebin ilk yanıt hedefini görüntüle",
)
def read_ticket_sla(
    ticket_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    current_user: CurrentUserDependency,
    session: SessionDependency,
) -> TicketSlaRead:
    """Yalnızca erişilebilen talebin SLA bilgisini getirir."""

    # --------------------------------------------------------
    # 3.1. Talebe erişimi doğrula
    # --------------------------------------------------------

    ticket = session.scalar(
        visible_tickets_query(current_user).where(
            Ticket.id == ticket_id
        )
    )

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Talep bulunamadı.",
        )

    # --------------------------------------------------------
    # 3.2. Oluşturulma anında kaydedilen hedefi getir
    # --------------------------------------------------------

    creation_event = session.scalar(
        select(TicketEvent)
        .where(
            TicketEvent.ticket_id == ticket_id,
            TicketEvent.event_type == TicketEventType.CREATED,
        )
        .order_by(TicketEvent.id.asc())
        .limit(1)
    )

    policy = (
        creation_event.details.get("sla")
        if creation_event is not None
        else None
    )

    target_seconds = None
    policy_version = None
    first_response_at = None

    if isinstance(policy, dict):
        target_seconds = policy["target_seconds"]
        policy_version = policy["policy_version"]

        # ----------------------------------------------------
        # 3.3. İlk uygun görevli yorumunu getir
        # ----------------------------------------------------

        first_response_event = session.scalar(
            select(TicketEvent)
            .where(
                TicketEvent.ticket_id == ticket_id,
                TicketEvent.event_type == TicketEventType.COMMENT_ADDED,
                TicketEvent.details[
                    "first_response_candidate"
                ].as_boolean().is_(True),
            )
            .order_by(TicketEvent.id.asc())
            .limit(1)
        )

        if first_response_event is not None:
            first_response_at = datetime.fromisoformat(
                first_response_event.details["responded_at"]
            )

    # --------------------------------------------------------
    # 3.4. Aynı veritabanının saatini kullanarak değerlendir
    # --------------------------------------------------------

    now = session.scalar(select(func.clock_timestamp()))
    assert now is not None

    result = evaluate_first_response(
        created_at=ticket.created_at,
        target_seconds=target_seconds,
        policy_version=policy_version,
        first_response_at=first_response_at,
        now=now,
    )

    return TicketSlaRead(
        ticket_id=ticket.id,
        **result,
    )