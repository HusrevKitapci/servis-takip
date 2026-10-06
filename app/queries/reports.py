"""Erişilebilir taleplerin özetini tek SQL sorgusunda hesaplar."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from datetime import timedelta, timezone

from sqlalchemy import (
    DateTime,
    Interval,
    case,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.orm import Session

from app.models import (
    Ticket,
    TicketEvent,
    TicketEventType,
    TicketPriority,
    TicketStatus,
    User,
)
from app.queries.tickets import visible_tickets_query
from app.schemas.report import (
    TicketPriorityCount,
    TicketSlaCount,
    TicketStatusCount,
    TicketSummary,
)
from app.sla import SlaStatus


# ============================================================
# 2. RAPOR SORGUSUNU OLUŞTUR
# ============================================================

def build_ticket_summary_statement(
    current_user: User,
    team_id: int | None = None,
):
    """
    Rapor için tek bir SELECT sorgusu oluşturur.

    Ara sorgular Python'da ayrı ayrı çalıştırılmaz.
    Tamamı son SELECT'in parçalarıdır.
    """

    # --------------------------------------------------------
    # 2.1. Önce kullanıcının erişebildiği talepleri seç
    # --------------------------------------------------------

    visible_statement = visible_tickets_query(current_user)

    if team_id is not None:
        visible_statement = visible_statement.where(
            Ticket.team_id == team_id
        )

    visible = visible_statement.order_by(None).cte(
        "visible_tickets"
    )

    # --------------------------------------------------------
    # 2.2. Her talebin açılış anındaki SLA hedefini getir
    # --------------------------------------------------------

    target_seconds = (
        select(
            TicketEvent.details[
                "sla"
            ]["target_seconds"].as_integer()
        )
        .where(
            TicketEvent.ticket_id == visible.c.id,
            TicketEvent.event_type == TicketEventType.CREATED,
        )
        .order_by(TicketEvent.id.asc())
        .limit(1)
        .correlate(visible)
        .scalar_subquery()
    )

    # --------------------------------------------------------
    # 2.3. İlk uygun görevli yanıtının zamanını getir
    # --------------------------------------------------------

    first_response_at = (
        select(
            cast(
                TicketEvent.details["responded_at"].as_string(),
                DateTime(timezone=True),
            )
        )
        .where(
            TicketEvent.ticket_id == visible.c.id,
            TicketEvent.event_type == TicketEventType.COMMENT_ADDED,
            TicketEvent.details[
                "first_response_candidate"
            ].as_boolean().is_(True),
        )
        .order_by(TicketEvent.id.asc())
        .limit(1)
        .correlate(visible)
        .scalar_subquery()
    )

    facts = select(
        visible.c.status,
        visible.c.priority,
        visible.c.created_at,
        target_seconds.label("target_seconds"),
        first_response_at.label("first_response_at"),
    ).cte("ticket_facts")

    # --------------------------------------------------------
    # 2.4. Hedef tarihi ve SLA sonucunu hesapla
    # --------------------------------------------------------

    one_second = literal(
        timedelta(seconds=1),
        type_=Interval(),
    )

    due_at = (
        facts.c.created_at
        + facts.c.target_seconds * one_second
    )

    # Sorgu boyunca aynı değerlendirme anı kullanılır.
    evaluated_at = func.statement_timestamp()

    sla_status = case(
        # Oluşturulma anında hedef kaydedilmemiş olabilir.
        (
            facts.c.target_seconds.is_(None),
            SlaStatus.NOT_TRACKED.value,
        ),
        # Tam son tarihte verilen yanıt zamanında kabul edilir.
        (
            (
                facts.c.first_response_at.is_not(None)
                & (facts.c.first_response_at <= due_at)
            ),
            SlaStatus.MET.value,
        ),
        # Yanıt var ama zamanında verilmemiş.
        (
            facts.c.first_response_at.is_not(None),
            SlaStatus.MISSED.value,
        ),
        # Henüz yanıt yok ve hedef süre aşılmış.
        (
            evaluated_at > due_at,
            SlaStatus.BREACHED.value,
        ),
        else_=SlaStatus.WAITING.value,
    )

    classified = select(
        facts.c.status,
        facts.c.priority,
        sla_status.label("sla_status"),
    ).cte("classified_tickets")

    # --------------------------------------------------------
    # 2.5. Bütün sayımları aynı SELECT içinde hazırla
    # --------------------------------------------------------

    columns = [
        func.count().label("total"),
        evaluated_at.label("evaluated_at"),
    ]

    for index, ticket_status in enumerate(TicketStatus):
        columns.append(
            func.count()
            .filter(classified.c.status == ticket_status)
            .label(f"status_{index}")
        )

    for index, priority in enumerate(TicketPriority):
        columns.append(
            func.count()
            .filter(classified.c.priority == priority)
            .label(f"priority_{index}")
        )

    for index, sla_state in enumerate(SlaStatus):
        columns.append(
            func.count()
            .filter(classified.c.sla_status == sla_state.value)
            .label(f"sla_{index}")
        )

    return select(*columns).select_from(classified)


# ============================================================
# 3. SORGUYU ÇALIŞTIR VE API YANITINA DÖNÜŞTÜR
# ============================================================

def get_ticket_summary(
    session: Session,
    current_user: User,
    team_id: int | None = None,
) -> TicketSummary:
    """Veritabanından tek satırlık özet alır."""

    statement = build_ticket_summary_statement(
        current_user=current_user,
        team_id=team_id,
    )

    row = session.execute(statement).mappings().one()

    return TicketSummary(
        total=row["total"],
        evaluated_at=row["evaluated_at"].astimezone(timezone.utc),
        by_status=[
            TicketStatusCount(
                status=ticket_status,
                count=row[f"status_{index}"],
            )
            for index, ticket_status in enumerate(TicketStatus)
        ],
        by_priority=[
            TicketPriorityCount(
                priority=priority,
                count=row[f"priority_{index}"],
            )
            for index, priority in enumerate(TicketPriority)
        ],
        by_sla=[
            TicketSlaCount(
                status=sla_state,
                count=row[f"sla_{index}"],
            )
            for index, sla_state in enumerate(SlaStatus)
        ],
    )