"""Talep raporlama endpoint'leri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import (
    CurrentUserDependency,
    SessionDependency,
)
from app.queries.reports import get_ticket_summary
from app.schemas.report import TicketSummary


# ============================================================
# 2. ROUTER
# ============================================================

router = APIRouter(
    prefix="/reports",
    tags=["Raporlar"],
)


# ============================================================
# 3. TALEP ÖZET RAPORU
# ============================================================

@router.get(
    "/tickets/summary",
    response_model=TicketSummary,
    summary="Erişebildiğin taleplerin özetini getir",
)
def read_ticket_summary(
    current_user: CurrentUserDependency,
    session: SessionDependency,
    team_id: Annotated[
        int | None,
        Query(gt=0, le=2_147_483_647),
    ] = None,
) -> TicketSummary:
    """
    Kullanıcının görebildiği talepleri özetler.

    Ekip filtresi, görünürlük kurallarından sonra uygulanır.
    Erişilebilen kayıt yoksa sayılar sıfır döner.
    """

    return get_ticket_summary(
        session=session,
        current_user=current_user,
        team_id=team_id,
    )