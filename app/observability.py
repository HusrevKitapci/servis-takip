"""İstek kimliği, yapılandırılmış günlükler ve güvenli hata yanıtları."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

import json
import logging

from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from traceback import extract_tb
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# ============================================================
# 2. İSTEĞE AİT KİMLİK VE LOGGER
# ============================================================

# Her isteğin kendi kimliğini taşımasını sağlar.
# Eşzamanlı istekler aynı global değişkeni paylaşmaz.
request_id_context: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

logger = logging.getLogger("servis_takip.http")


# ============================================================
# 3. GÜNLÜK KAYDINI JSON'A DÖNÜŞTÜR
# ============================================================

class JsonLogFormatter(logging.Formatter):
    """Günlük kaydından belirlediğimiz alanları JSON olarak üretir."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                timezone.utc,
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Açıkça gönderilmiş kimlik varsa onu kullan.
        # Yoksa mevcut isteğin bağlamındaki kimliği al.
        request_id = (
            getattr(record, "request_id", None)
            or request_id_context.get()
        )

        if request_id is not None:
            data["request_id"] = request_id

        # Tüm LogRecord içeriğini dışarı vermek yerine alanları seçiyoruz.
        allowed_fields = (
            "method",
            "route",
            "status_code",
            "duration_ms",
            "outcome",
            "error_type",
            "error_location",
        )

        for field in allowed_fields:
            if hasattr(record, field):
                data[field] = getattr(record, field)

        # Ham exception metnini veya traceback içeriğini eklemiyoruz.
        return json.dumps(data, ensure_ascii=False)


# ============================================================
# 4. UYGULAMA GÜNLÜKLEMESİNİ HAZIRLA
# ============================================================

def configure_logging() -> None:
    """Uygulama logger'ına JSON çıktısı veren handler ekler."""

    application_logger = logging.getLogger("servis_takip")
    application_logger.setLevel(logging.INFO)
    application_logger.propagate = False

    # Uvicorn logging.json üzerinden zaten ayarladıysa tekrar ekleme.
    already_configured = any(
        isinstance(handler.formatter, JsonLogFormatter)
        for handler in application_logger.handlers
    )

    if not already_configured:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        application_logger.addHandler(handler)


# ============================================================
# 5. HTTP İSTEKLERİNİ TAKİP EDEN MIDDLEWARE
# ============================================================

class RequestLoggingMiddleware:
    """
    Her HTTP isteğine kimlik verir ve sonucunu kaydeder.

    Yanıt gövdesini bellekte toplamaz.
    Bu sayede akış halinde gönderilen yanıtlar da çalışabilir.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        # Bu middleware yalnızca HTTP isteklerini takip eder.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ----------------------------------------------------
        # 5.1. Sunucu tarafından yeni bir istek kimliği üret
        # ----------------------------------------------------

        request_id = str(uuid4())

        # Hata işleyicisi kimliği request.state üzerinden okuyabilir.
        scope.setdefault("state", {})["request_id"] = request_id

        # İstek içindeki diğer günlükler de bu kimliğe erişebilir.
        token = request_id_context.set(request_id)

        started_at = perf_counter()

        status_code = None
        response_started = False
        response_finished = False

        error_type = None
        error_location = None

        # ----------------------------------------------------
        # 5.2. Yanıta istek kimliğini ekle ve durumunu izle
        # ----------------------------------------------------

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            nonlocal response_started
            nonlocal response_finished

            if message["type"] == "http.response.start":
                status_code = message["status"]

                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id

                await send(message)
                response_started = True
                return

            await send(message)

            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                response_finished = True

        # ----------------------------------------------------
        # 5.3. İsteği uygulamaya ilet
        # ----------------------------------------------------

        try:
            await self.app(
                scope,
                receive,
                send_with_request_id,
            )

        except Exception as exc:
            error_type = type(exc).__name__

            frames = extract_tb(exc.__traceback__)

            if frames:
                last_frame = frames[-1]

                # Tam dosya yolunu ve ham hata metnini kaydetmiyoruz.
                error_location = (
                    f"{Path(last_frame.filename).name}:"
                    f"{last_frame.lineno}"
                )

            if not response_started:
                status_code = 500

            # Hatanın FastAPI/Starlette hata işleyicisine ulaşmasını sağla.
            raise

        finally:
            # -----------------------------------------------
            # 5.4. Tek bir HTTP günlük kaydı oluştur
            # -----------------------------------------------

            # Gerçek URL yerine endpoint şablonunu kullan.
            # Örnek: /tickets/123 yerine /tickets/{ticket_id}
            route = getattr(
                scope.get("route"),
                "path",
                "<unmatched>",
            )

            if error_type:
                outcome = "failed"
            elif response_finished:
                outcome = "completed"
            else:
                outcome = "incomplete"

            try:
                logger.log(
                    logging.ERROR if error_type else logging.INFO,
                    "http_request",
                    extra={
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": round(
                            (perf_counter() - started_at) * 1000,
                            3,
                        ),
                        "outcome": outcome,
                        "error_type": error_type,
                        "error_location": error_location,
                    },
                )

            finally:
                # Bu isteğin kimliğini bağlamdan temizle.
                request_id_context.reset(token)


# ============================================================
# 6. BEKLENMEYEN HATALAR İÇİN KULLANICI YANITI
# ============================================================

async def unexpected_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Teknik hata ayrıntısını göstermeden ilişkilendirilebilir yanıt verir."""

    request_id = (
        getattr(request.state, "request_id", None)
        or str(uuid4())
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Beklenmeyen bir sunucu hatası oluştu.",
            "request_id": request_id,
        },
        headers={
            "X-Request-ID": request_id,
        },
    )