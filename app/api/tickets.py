"""Talep yönetimi, yorumlar ve işlem geçmişi endpoint'leri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status
from psycopg.errors import ForeignKeyViolation
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.dependencies import (
    AgentDependency,
    CurrentUserDependency,
    SessionDependency,
)
from app.models import (
    Team,
    TeamMember,
    Ticket,
    TicketComment,
    TicketEvent,
    TicketEventType,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
)
from app.queries.tickets import visible_tickets_query
from app.schemas.ticket import (
    TicketCommentCreate,
    TicketCommentPage,
    TicketCommentRead,
    TicketCreate,
    TicketEventPage,
    TicketEventRead,
    TicketPage,
    TicketRead,
)
from app.sla import make_policy_snapshot


# ============================================================
# 2. ROUTER VE PARAMETRE KURALLARI
# ============================================================

router = APIRouter(
    prefix="/tickets",
    tags=["Servis Talepleri"],
)

TicketId = Annotated[int, Path(gt=0, le=2_147_483_647)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


# ============================================================
# 3. ORTAK YARDIMCI FONKSİYONLAR
# ============================================================

def _get_visible_ticket(
    session: Session,
    current_user: User,
    ticket_id: int,
    *,
    lock: bool = False,
) -> Ticket:
    """Talebi kullanıcının görünürlük alanında arar."""

    statement = visible_tickets_query(current_user).where(
        Ticket.id == ticket_id
    )

    if lock:
        statement = statement.with_for_update(of=Ticket)

    statement = statement.execution_options(populate_existing=True)
    ticket = session.scalar(statement)

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Talep bulunamadı.",
        )

    return ticket


def _add_event(
    session: Session,
    *,
    ticket_id: int,
    actor_id: int,
    event_type: TicketEventType,
    details: dict[str, Any],
) -> None:
    """Geçmiş kaydını mevcut transaction'a ekler."""

    session.add(
        TicketEvent(
            ticket_id=ticket_id,
            actor_id=actor_id,
            event_type=event_type,
            details=details,
        )
    )


def _comment_event_details(
    session: Session,
    ticket: Ticket,
    comment: TicketComment,
) -> dict[str, Any]:
    """
    Yorum olayının bilgilerini hazırlar.

    İlk yanıt sayılma kararını yorum yazıldığı anda kaydeder.
    Kullanıcının rolü daha sonra değişse de bu kayıt değişmez.
    """

    details: dict[str, Any] = {"comment_id": comment.id}

    author = session.get(User, comment.author_id)

    if author is None or author.role != UserRole.AGENT:
        return details

    # Görevlinin kendi talebine yazdığı yorum ilk yanıt sayılmaz.
    if author.id == ticket.requester_id:
        return details

    membership = session.get(
        TeamMember,
        (ticket.team_id, author.id),
    )

    if membership is None:
        return details

    # Kilit beklenmiş olsa bile gerçek kayıt anını ölç.
    response_at = session.scalar(select(func.clock_timestamp()))
    assert response_at is not None

    # Yorum zamanı ile SLA yanıt zamanı aynı anı temsil etsin.
    comment.created_at = response_at

    details.update(
        {
            "first_response_candidate": True,
            "responded_at": response_at.isoformat(),
            "author_role": author.role.value,
            "is_public": True,
        }
    )

    return details


def _agent_conditions(agent_id: int) -> tuple:
    """Görevlinin işlem anındaki uygunluğunu denetleyen koşullar."""

    has_membership = (
        select(TeamMember.user_id)
        .where(
            TeamMember.team_id == Ticket.team_id,
            TeamMember.user_id == agent_id,
        )
        .exists()
    )

    team_is_active = (
        select(Team.id)
        .where(
            Team.id == Ticket.team_id,
            Team.is_active.is_(True),
        )
        .exists()
    )

    agent_is_active = (
        select(User.id)
        .where(
            User.id == agent_id,
            User.is_active.is_(True),
            User.role == UserRole.AGENT,
        )
        .exists()
    )

    return has_membership, team_is_active, agent_is_active


def _apply_transition(
    session: Session,
    statement,
    *,
    actor_id: int,
    event_type: TicketEventType,
    details: dict[str, Any],
    conflict_detail: str,
) -> Ticket:
    """Durum değişikliğini ve geçmiş kaydını birlikte kaydeder."""

    try:
        changed_ticket = session.scalar(statement)

        if changed_ticket is None:
            session.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=conflict_detail,
            )

        _add_event(
            session,
            ticket_id=changed_ticket.id,
            actor_id=actor_id,
            event_type=event_type,
            details=details,
        )

        session.commit()

    except SQLAlchemyError as exc:
        session.rollback()

        if (
            isinstance(exc, IntegrityError)
            and isinstance(exc.orig, ForeignKeyViolation)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="İlgili kayıt değişti. İşlemi yenileyin.",
            ) from exc

        raise

    session.refresh(changed_ticket)
    return changed_ticket


# ============================================================
# 4. TALEP OLUŞTURMA
# ============================================================

@router.post(
    "",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
    summary="Servis talebi oluştur",
)
def create_ticket(
    payload: TicketCreate,
    current_user: CurrentUserDependency,
    session: SessionDependency,
) -> Ticket:
    """Yeni talebi, oluşturulma olayını ve SLA hedefini kaydeder."""

    team = session.get(Team, payload.team_id)

    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ekip bulunamadı.",
        )

    if not team.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pasif ekibe servis talebi açılamaz.",
        )

    ticket = Ticket(
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        team_id=team.id,
        requester_id=current_user.id,
        status=TicketStatus.OPEN,
    )

    try:
        session.add(ticket)
        session.flush()

        _add_event(
            session,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            event_type=TicketEventType.CREATED,
            details={
                "status": TicketStatus.OPEN.value,
                "team_id": ticket.team_id,
                "priority": ticket.priority.value,
                # Politika değişse bile bu talebin hedefi korunur.
                "sla": make_policy_snapshot(ticket.priority.value),
            },
        )

        session.commit()

    except SQLAlchemyError as exc:
        session.rollback()

        if (
            isinstance(exc, IntegrityError)
            and isinstance(exc.orig, ForeignKeyViolation)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ekip veya kullanıcı kaydı değişti. İşlemi yenileyin.",
            ) from exc

        raise

    session.refresh(ticket)
    return ticket


# ============================================================
# 5. TALEPLERİ LİSTELEME
# ============================================================

@router.get(
    "",
    response_model=TicketPage,
    summary="Görebildiğin servis taleplerini listele",
)
def list_tickets(
    current_user: CurrentUserDependency,
    session: SessionDependency,
    priority: TicketPriority | None = None,
    ticket_status: Annotated[
        TicketStatus | None,
        Query(alias="status"),
    ] = None,
    team_id: Annotated[
        int | None,
        Query(gt=0, le=2_147_483_647),
    ] = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> TicketPage:
    """Görünürlük kurallarını uygulayıp filtrelenmiş sayfayı getirir."""

    statement = visible_tickets_query(current_user)

    if priority is not None:
        statement = statement.where(Ticket.priority == priority)

    if ticket_status is not None:
        statement = statement.where(Ticket.status == ticket_status)

    if team_id is not None:
        statement = statement.where(Ticket.team_id == team_id)

    total = session.scalar(
        select(func.count()).select_from(statement.subquery())
    )
    assert total is not None

    tickets = session.scalars(
        statement.order_by(Ticket.id.desc()).offset(offset).limit(limit)
    ).all()

    return TicketPage(
        items=[TicketRead.model_validate(ticket) for ticket in tickets],
        total=total,
        limit=limit,
        offset=offset,
    )


# ============================================================
# 6. TEK TALEBİ GÖRÜNTÜLEME
# ============================================================

@router.get(
    "/{ticket_id}",
    response_model=TicketRead,
    summary="Erişebildiğin bir servis talebini getir",
)
def read_ticket(
    ticket_id: TicketId,
    current_user: CurrentUserDependency,
    session: SessionDependency,
) -> Ticket:
    return _get_visible_ticket(session, current_user, ticket_id)


# ============================================================
# 7. TALEBİ ÜSTLENME
# ============================================================

@router.post(
    "/{ticket_id}/claim",
    response_model=TicketRead,
    summary="Servis talebini üstlen",
)
def claim_ticket(
    ticket_id: TicketId,
    agent: AgentDependency,
    session: SessionDependency,
) -> Ticket:
    """Talebi üstlenir; üstlenme işlemi ilk yanıt sayılmaz."""

    ticket = _get_visible_ticket(session, agent, ticket_id)

    membership = session.get(
        TeamMember,
        (ticket.team_id, agent.id),
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Talebi üstlenmek için ilgili ekibin üyesi olmalısın.",
        )

    statement = (
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.status == TicketStatus.OPEN,
            Ticket.assignee_id.is_(None),
            *_agent_conditions(agent.id),
        )
        .values(
            assignee_id=agent.id,
            claimed_at=func.now(),
            status=TicketStatus.IN_PROGRESS,
        )
        .returning(Ticket)
        .execution_options(
            synchronize_session=False,
            populate_existing=True,
        )
    )

    return _apply_transition(
        session,
        statement,
        actor_id=agent.id,
        event_type=TicketEventType.CLAIMED,
        details={
            "from_status": TicketStatus.OPEN.value,
            "to_status": TicketStatus.IN_PROGRESS.value,
            "assignee_id": agent.id,
        },
        conflict_detail=(
            "Talep üstlenilemedi. Talebin durumu veya "
            "ekip ve kullanıcı uygunluğu değişmiş olabilir."
        ),
    )


# ============================================================
# 8. TALEBİ ÇÖZME
# ============================================================

@router.post(
    "/{ticket_id}/resolve",
    response_model=TicketRead,
    summary="Üstlendiğin servis talebini çöz",
)
def resolve_ticket(
    ticket_id: TicketId,
    agent: AgentDependency,
    session: SessionDependency,
) -> Ticket:
    """Talebi yalnızca üstlenen ve uygun olan görevli çözebilir."""

    ticket = _get_visible_ticket(session, agent, ticket_id)

    if ticket.status != TicketStatus.IN_PROGRESS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Yalnızca işlemdeki talepler çözülebilir.",
        )

    if ticket.assignee_id != agent.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Yalnızca üstlendiğin talebi çözebilirsin.",
        )

    statement = (
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.status == TicketStatus.IN_PROGRESS,
            Ticket.assignee_id == agent.id,
            *_agent_conditions(agent.id),
        )
        .values(
            status=TicketStatus.RESOLVED,
            resolved_at=func.now(),
        )
        .returning(Ticket)
        .execution_options(
            synchronize_session=False,
            populate_existing=True,
        )
    )

    return _apply_transition(
        session,
        statement,
        actor_id=agent.id,
        event_type=TicketEventType.RESOLVED,
        details={
            "from_status": TicketStatus.IN_PROGRESS.value,
            "to_status": TicketStatus.RESOLVED.value,
        },
        conflict_detail=(
            "Talep çözülemedi. Durum veya işlem uygunluğu değişti."
        ),
    )


# ============================================================
# 9. TALEBİ YENİDEN AÇMA
# ============================================================

@router.post(
    "/{ticket_id}/reopen",
    response_model=TicketRead,
    summary="Çözülmüş servis talebini yeniden aç",
)
def reopen_ticket(
    ticket_id: TicketId,
    current_user: CurrentUserDependency,
    session: SessionDependency,
) -> Ticket:
    """Talebi açar; ilk yanıt geçmişi ve SLA hedefi korunur."""

    ticket = _get_visible_ticket(session, current_user, ticket_id)

    is_owner = ticket.requester_id == current_user.id
    is_manager = current_user.role == UserRole.MANAGER

    if not is_owner and not is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Talebi yalnızca sahibi veya yönetici yeniden açabilir.",
        )

    team_is_active = (
        select(Team.id)
        .where(
            Team.id == Ticket.team_id,
            Team.is_active.is_(True),
        )
        .exists()
    )

    statement = (
        update(Ticket)
        .where(
            Ticket.id == ticket_id,
            Ticket.status == TicketStatus.RESOLVED,
            team_is_active,
        )
        .values(
            status=TicketStatus.OPEN,
            assignee_id=None,
            claimed_at=None,
            resolved_at=None,
        )
        .returning(Ticket)
        .execution_options(
            synchronize_session=False,
            populate_existing=True,
        )
    )

    return _apply_transition(
        session,
        statement,
        actor_id=current_user.id,
        event_type=TicketEventType.REOPENED,
        details={
            "from_status": TicketStatus.RESOLVED.value,
            "to_status": TicketStatus.OPEN.value,
        },
        conflict_detail=(
            "Yalnızca aktif ekibe ait çözülmüş talepler yeniden açılabilir."
        ),
    )


# ============================================================
# 10. YORUM EKLEME
# ============================================================

@router.post(
    "/{ticket_id}/comments",
    response_model=TicketCommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Servis talebine yorum ekle",
)
def create_ticket_comment(
    ticket_id: TicketId,
    payload: TicketCommentCreate,
    current_user: CurrentUserDependency,
    session: SessionDependency,
) -> TicketComment:
    """Yorumu ve varsa ilk yanıt adayına ait bilgileri birlikte kaydeder."""

    try:
        ticket = _get_visible_ticket(
            session,
            current_user,
            ticket_id,
            lock=True,
        )

        if ticket.status == TicketStatus.RESOLVED:
            session.rollback()

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Çözülmüş talebe yorum eklenemez. "
                    "Önce talebi yeniden açın."
                ),
            )

        comment = TicketComment(
            ticket_id=ticket.id,
            author_id=current_user.id,
            body=payload.body,
        )

        session.add(comment)
        session.flush()

        event_details = _comment_event_details(
            session,
            ticket,
            comment,
        )

        _add_event(
            session,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            event_type=TicketEventType.COMMENT_ADDED,
            details=event_details,
        )

        session.commit()

    except SQLAlchemyError:
        session.rollback()
        raise

    session.refresh(comment)
    return comment


# ============================================================
# 11. YORUMLARI LİSTELEME
# ============================================================

@router.get(
    "/{ticket_id}/comments",
    response_model=TicketCommentPage,
    summary="Talebin yorumlarını listele",
)
def list_ticket_comments(
    ticket_id: TicketId,
    current_user: CurrentUserDependency,
    session: SessionDependency,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> TicketCommentPage:
    _get_visible_ticket(session, current_user, ticket_id)

    total = session.scalar(
        select(func.count())
        .select_from(TicketComment)
        .where(TicketComment.ticket_id == ticket_id)
    )
    assert total is not None

    comments = session.scalars(
        select(TicketComment)
        .where(TicketComment.ticket_id == ticket_id)
        .order_by(TicketComment.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()

    return TicketCommentPage(
        items=[
            TicketCommentRead.model_validate(comment)
            for comment in comments
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ============================================================
# 12. İŞLEM GEÇMİŞİNİ LİSTELEME
# ============================================================

@router.get(
    "/{ticket_id}/events",
    response_model=TicketEventPage,
    summary="Talebin işlem geçmişini listele",
)
def list_ticket_events(
    ticket_id: TicketId,
    current_user: CurrentUserDependency,
    session: SessionDependency,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> TicketEventPage:
    _get_visible_ticket(session, current_user, ticket_id)

    total = session.scalar(
        select(func.count())
        .select_from(TicketEvent)
        .where(TicketEvent.ticket_id == ticket_id)
    )
    assert total is not None

    events = session.scalars(
        select(TicketEvent)
        .where(TicketEvent.ticket_id == ticket_id)
        .order_by(TicketEvent.id.asc())
        .offset(offset)
        .limit(limit)
    ).all()

    return TicketEventPage(
        items=[
            TicketEventRead.model_validate(event)
            for event in events
        ],
        total=total,
        limit=limit,
        offset=offset,
    )