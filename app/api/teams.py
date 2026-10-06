"""
Ekip oluşturma ve listeleme endpoint'leri.

Bu modül ekip işlemlerinin HTTP arayüzünü tanımlar.
Veri doğrulaması Pydantic modelleriyle, kalıcılık SQLAlchemy ile sağlanır.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import (
    get_current_user,
    get_session,
    require_manager,
)
from app.models import Team
from app.schemas.team import TeamCreate, TeamRead, TeamStatusUpdate


# ============================================================================
# 2. ROUTER VE ORTAK BAĞIMLILIK
# ============================================================================

# Bu router içindeki yollar /teams adresiyle başlayacak.
router = APIRouter(
    prefix="/teams",
    tags=["Ekipler"],
    dependencies=[Depends(get_current_user)],
)

# FastAPI, bu türdeki parametreye get_session üzerinden oturum sağlayacak.
SessionDependency = Annotated[Session, Depends(get_session)]


# ============================================================================
# 3. EKİP OLUŞTURMA
# ============================================================================

@router.post(
    "",
    response_model=TeamRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_manager)],
    summary="Yeni ekip oluştur",
    responses={
        409: {"description": "Bu ekip adı zaten kullanılıyor."},
    },
)
def create_team(
    payload: TeamCreate,
    session: SessionDependency,
) -> Team:
    """Ekip oluşturur; aynı ad zaten varsa anlaşılır bir çakışma hatası döndürür."""

    # Doğrulanmış istek verisinden bir veritabanı modeli oluştur.
    team = Team(name=payload.name)

    # Nesneyi oturumun takip ettiği yeni kayıtlar arasına al.
    # Bu satır tek başına kaydı kalıcı hâle getirmez.
    session.add(team)

    try:
        # Bekleyen değişiklikleri gönder ve veritabanı işlemini tamamla.
        session.commit()

    except IntegrityError as exc:
        # Başarısız işlemden sonra oturumu yeniden kullanılabilir duruma getir.
        session.rollback()

        # Yalnızca ekip adının benzersizlik kuralına ait hatayı 409'a dönüştür.
        # Diğer bütünlük hatalarını yanlışlıkla "aynı isim var" diye gizleme.
        if (
            isinstance(exc.orig, UniqueViolation)
            and exc.orig.diag.constraint_name == "uq_teams_name"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu isimde bir ekip zaten var.",
            ) from exc

        raise

    # PostgreSQL'in ürettiği kimlik ve varsayılan değerleri nesneye yeniden oku.
    session.refresh(team)

    return team


# ============================================================================
# 4. EKİPLERİ LİSTELEME
# ============================================================================

@router.get(
    "",
    response_model=list[TeamRead],
    summary="Ekipleri listele",
)
def list_teams(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Team]:
    """Ekipleri kimlik sırasıyla, sınırlı sayıda kayıt döndürerek listeler."""

    statement = (
        select(Team)
        .order_by(Team.id)
        .offset(offset)
        .limit(limit)
    )

    # scalars(), sonuç satırlarından doğrudan Team nesnelerini almamızı sağlar.
    teams = session.scalars(statement).all()

    return list(teams)


# ============================================================================
# 5. EKİP AYRINTISINI GETİRME
# ============================================================================

@router.get(
    "/{team_id}",
    response_model=TeamRead,
    summary="Bir ekibin ayrıntısını getir",
    responses={
        404: {"description": "Belirtilen ekip bulunamadı."},
    },
)
def get_team(
    team_id: Annotated[int, Path(gt=0)],
    session: SessionDependency,
) -> Team:
    """Bir ekibi birincil anahtarıyla bulur; yoksa 404 döndürür."""

    team = session.get(Team, team_id)

    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ekip bulunamadı.",
        )

    return team


# ============================================================================
# 6. EKİBİN AKTİFLİK DURUMUNU DEĞİŞTİRME
# ============================================================================

@router.patch(
    "/{team_id}/status",
    response_model=TeamRead,
    dependencies=[Depends(require_manager)],
    summary="Ekibi aktif veya pasif yap",
    responses={
        404: {"description": "Belirtilen ekip bulunamadı."},
    },
)
def update_team_status(
    team_id: Annotated[int, Path(gt=0)],
    payload: TeamStatusUpdate,
    session: SessionDependency,
) -> Team:
    """Mevcut ekibin aktiflik bilgisini değiştirir ve güncel kaydı döndürür."""

    # Güncellenecek kayıt gerçekten var mı?
    team = session.get(Team, team_id)

    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ekip bulunamadı.",
        )

    # false geçerli bir değerdir; doğrudan atama yaparak onu da uygularız.
    team.is_active = payload.is_active

    # Oturumun takip ettiği nesnedeki değişikliği veritabanına kaydet.
    session.commit()

    # Veritabanındaki güncel değerleri yeniden oku.
    session.refresh(team)

    return team