# ============================================================
# İÇE AKTARMALAR
# ============================================================

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Response,
    status,
)
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.dependencies import SessionDependency, require_manager
from app.models import Team, TeamMember, User, UserRole
from app.schemas.team_member import TeamMemberCreate, TeamMemberRead
from app.schemas.user import UserRead


# ============================================================
# 1. ROUTER VE ORTAK TİPLER
# ============================================================

router = APIRouter(
    prefix="/teams/{team_id}/members",
    tags=["Ekip Üyelikleri"],
    dependencies=[Depends(require_manager)],
)

# URL içindeki kimlikler pozitif PostgreSQL INTEGER sınırında olmalı.
IdPath = Annotated[int, Path(gt=0, le=2_147_483_647)]


# ============================================================
# 2. DOSYA İÇİ YARDIMCI FONKSİYONLAR
# ============================================================

def _get_team(session, team_id: int) -> Team:
    """Ekip yoksa ortak 404 yanıtını üretir."""

    team = session.get(Team, team_id)

    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ekip bulunamadı.",
        )

    return team


def _membership_response(
    membership: TeamMember,
    user: User,
) -> TeamMemberRead:
    """Üyelik kaydını güvenli kullanıcı şemasıyla birleştirir."""

    return TeamMemberRead(
        team_id=membership.team_id,
        user=UserRead.model_validate(user),
        created_at=membership.created_at,
    )


# ============================================================
# 3. EKİBE ÜYE EKLEME
# ============================================================

@router.post(
    "",
    response_model=TeamMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ekibe servis görevlisi ekle",
)
def add_team_member(
    team_id: IdPath,
    payload: TeamMemberCreate,
    session: SessionDependency,
) -> TeamMemberRead:

    # --------------------------------------------------------
    # 3.1. Ekibi ve kullanıcıyı kontrol et
    # --------------------------------------------------------

    team = _get_team(session, team_id)

    if not team.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pasif ekibe üye eklenemez.",
        )

    user = session.get(User, payload.user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kullanıcı bulunamadı.",
        )

    if not user.is_active or user.role != UserRole.AGENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ekibe yalnızca aktif servis görevlisi eklenebilir.",
        )

    # --------------------------------------------------------
    # 3.2. Üyeliği kaydet
    # --------------------------------------------------------

    membership = TeamMember(
        team_id=team_id,
        user_id=payload.user_id,
    )

    session.add(membership)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()

        # Aynı ikilinin tekrarını veritabanı engeller.
        if (
            isinstance(exc.orig, UniqueViolation)
            and exc.orig.diag.constraint_name == "pk_team_members"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Kullanıcı zaten bu ekibin üyesi.",
            ) from exc

        # Ön kontrolden sonra ekip veya kullanıcı başka bir
        # işlemde silinmişse veritabanı ilişkiyi reddeder.
        if isinstance(exc.orig, ForeignKeyViolation):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ekip veya kullanıcı kaydı değişti. İşlemi yenileyin.",
            ) from exc

        raise

    session.refresh(membership)

    return _membership_response(membership, user)


# ============================================================
# 4. EKİP ÜYELERİNİ LİSTELEME
# ============================================================

@router.get(
    "",
    response_model=list[TeamMemberRead],
    summary="Ekip üyelerini listele",
)
def list_team_members(
    team_id: IdPath,
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamMemberRead]:

    _get_team(session, team_id)

    # Üyelik ile kullanıcı bilgisini tek sorguda alırız.
    # Her üye için ayrı kullanıcı sorgusu çalıştırmayız.
    statement = (
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.user_id)
        .offset(offset)
        .limit(limit)
    )

    rows = session.execute(statement).all()

    return [
        _membership_response(membership, user)
        for membership, user in rows
    ]


# ============================================================
# 5. EKİPTEN ÜYE ÇIKARMA
# ============================================================

@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Servis görevlisini ekipten çıkar",
)
def remove_team_member(
    team_id: IdPath,
    user_id: IdPath,
    session: SessionDependency,
) -> Response:

    _get_team(session, team_id)

    # Yalnızca belirtilen ekip-kullanıcı ilişkisini sileriz.
    # Kullanıcı ve ekip kayıtları korunur.
    statement = (
        delete(TeamMember)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
        )
        .returning(TeamMember.user_id)
    )

    deleted_user_id = session.execute(statement).scalar_one_or_none()

    if deleted_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ekip üyeliği bulunamadı.",
        )

    session.commit()

    # 204 yanıtında gövde bulunmaz.
    return Response(status_code=status.HTTP_204_NO_CONTENT)