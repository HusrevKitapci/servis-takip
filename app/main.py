"""ServisTakip API uygulamasının başlangıç noktası."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.reports import router as reports_router
from app.api.sla import router as sla_router
from app.api.team_members import router as team_members_router
from app.api.teams import router as teams_router
from app.api.tickets import router as tickets_router
from app.api.users import router as users_router
from app.database import engine
from app.observability import (
    RequestLoggingMiddleware,
    configure_logging,
    unexpected_error_handler,
)


# ============================================================
# 2. GÜNLÜKLEME VE UYGULAMA
# ============================================================

configure_logging()

logger = logging.getLogger("servis_takip.database")

app = FastAPI(
    title="ServisTakip API",
    description="Destek taleplerini, ekipleri ve yanıt sürelerini yöneten API.",
    version="0.1.0",
)


# ============================================================
# 3. İSTEK TAKİBİ VE HATA İŞLEYİCİSİ
# ============================================================

app.add_middleware(RequestLoggingMiddleware)

app.add_exception_handler(
    Exception,
    unexpected_error_handler,
)


# ============================================================
# 4. ROUTER KAYITLARI
# ============================================================

app.include_router(teams_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(team_members_router)
app.include_router(tickets_router)
app.include_router(sla_router)
app.include_router(reports_router)


# ============================================================
# 5. UYGULAMANIN ÇALIŞMA KONTROLÜ
# ============================================================

@app.get(
    "/health",
    tags=["Sistem"],
    summary="Uygulamanın çalıştığını kontrol et",
)
def health_check() -> dict[str, str]:
    """Veritabanına bağlanmadan uygulamanın yanıt verdiğini bildirir."""

    return {
        "status": "ok",
        "service": "servis-takip",
    }


# ============================================================
# 6. VERİTABANI HAZIRLIK KONTROLÜ
# ============================================================

@app.get(
    "/ready",
    tags=["Sistem"],
    summary="Veritabanı bağlantısını kontrol et",
    responses={
        503: {"description": "Veritabanı kontrolü başarısız."},
    },
)
def readiness_check() -> dict[str, str]:
    """Veritabanında basit bir sorgu çalıştırır."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

    except SQLAlchemyError as exc:
        logger.warning(
            "Veritabanı hazırlık kontrolü başarısız. Hata türü: %s",
            type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Veritabanı şu anda kullanılamıyor.",
        ) from exc

    return {
        "status": "ready",
        "database": "ok",
    }


# ============================================================
# 7. DOĞRULAMA HATALARININ YANIT BİÇİMİ
# ============================================================

@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Gönderilen ham değerleri doğrulama hatasına eklemez."""

    errors = [
        {
            "type": error["type"],
            "loc": error["loc"],
            "msg": error["msg"],
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={"detail": errors},
    )