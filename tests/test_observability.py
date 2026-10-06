"""İstek takibi, günlük biçimi ve güvenli hata yanıtı testleri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

import json
import logging
import sys

from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app import observability


# ============================================================
# 2. BAĞIMSIZ TEST UYGULAMASI
# ============================================================

@pytest.fixture
def observed_client(monkeypatch):
    """
    Middleware'i gerçek HTTP istekleriyle test eden küçük uygulama.

    Günlükleri terminal yerine bir listeye alır.
    """

    entries = []

    def capture(level, message, *, extra):
        entries.append(
            {
                "level": level,
                "event": message,
                **extra,
            }
        )

    monkeypatch.setattr(
        observability.logger,
        "log",
        capture,
    )

    test_app = FastAPI()

    test_app.add_middleware(
        observability.RequestLoggingMiddleware
    )

    test_app.add_exception_handler(
        Exception,
        observability.unexpected_error_handler,
    )

    # --------------------------------------------------------
    # 2.1. Normal yanıt
    # --------------------------------------------------------

    @test_app.get("/items/{item_id}")
    def read_item(item_id: int):
        return {
            "id": item_id,
            "request_id": observability.request_id_context.get(),
        }

    # --------------------------------------------------------
    # 2.2. Gövde içeren istek
    # --------------------------------------------------------

    @test_app.post("/submit")
    def submit(payload: dict):
        return {"received": True}

    # --------------------------------------------------------
    # 2.3. Yalnızca test uygulamasında bulunan hatalı endpoint
    # --------------------------------------------------------

    @test_app.get("/crash")
    def crash():
        raise RuntimeError(
            "fake_database_password=do-not-expose"
        )

    # --------------------------------------------------------
    # 2.4. Akış yanıtı
    # --------------------------------------------------------

    @test_app.get("/stream")
    def stream():
        return StreamingResponse(
            iter(["one", "two"]),
            media_type="text/plain",
        )

    # Beklenmeyen hatada oluşan HTTP yanıtını incelemek istiyoruz.
    with TestClient(
        test_app,
        raise_server_exceptions=False,
    ) as client:
        yield client, entries


# ============================================================
# 3. İSTEK KİMLİĞİ TESTLERİ
# ============================================================

def test_request_id_matches_response_and_log(observed_client):
    client, entries = observed_client

    response = client.get("/items/15")

    assert response.status_code == 200

    request_id = response.headers["x-request-id"]

    assert str(UUID(request_id)) == request_id
    assert response.json()["request_id"] == request_id
    assert entries[-1]["request_id"] == request_id

    assert entries[-1]["route"] == "/items/{item_id}"
    assert entries[-1]["duration_ms"] >= 0
    assert entries[-1]["outcome"] == "completed"

    # İstek bittiğinde bağlam dışarıya taşmamalı.
    assert observability.request_id_context.get() is None


def test_each_request_has_its_own_id(observed_client):
    client, entries = observed_client

    first = client.get("/items/1")
    second = client.get("/items/2")

    assert (
        first.headers["x-request-id"]
        != second.headers["x-request-id"]
    )
    assert len(entries) == 2


def test_client_supplied_id_is_not_used(observed_client):
    client, entries = observed_client

    response = client.get(
        "/items/1",
        headers={
            "X-Request-ID": "client-chosen-value",
        },
    )

    assert response.headers["x-request-id"] != "client-chosen-value"


# ============================================================
# 4. GÜNLÜKLERE YAZILMAMASI GEREKEN VERİLER
# ============================================================

def test_request_secrets_are_not_logged(observed_client):
    client, entries = observed_client

    response = client.post(
        "/submit?api_key=secret-query-value",
        headers={
            "Authorization": "Bearer secret-header-value",
        },
        json={
            "password": "secret-body-value",
        },
    )

    assert response.status_code == 200

    serialized = json.dumps(entries)

    for value in (
        "secret-query-value",
        "secret-header-value",
        "secret-body-value",
    ):
        assert value not in serialized


def test_unknown_path_is_not_logged_verbatim(observed_client):
    client, entries = observed_client

    response = client.get("/unknown-private-value")

    assert response.status_code == 404
    assert response.headers["x-request-id"]

    assert entries[-1]["route"] == "<unmatched>"
    assert "unknown-private-value" not in json.dumps(entries)


# ============================================================
# 5. HATA YANITLARI
# ============================================================

def test_validation_error_has_request_id(observed_client):
    client, entries = observed_client

    response = client.get("/items/not-an-integer")

    assert response.status_code == 422

    assert (
        response.headers["x-request-id"]
        == entries[-1]["request_id"]
    )
    assert entries[-1]["status_code"] == 422


def test_unexpected_error_is_safe_and_correlated(observed_client):
    client, entries = observed_client

    response = client.get("/crash")

    assert response.status_code == 500

    assert response.json()["detail"] == (
        "Beklenmeyen bir sunucu hatası oluştu."
    )

    assert (
        response.json()["request_id"]
        == response.headers["x-request-id"]
    )

    assert (
        entries[-1]["request_id"]
        == response.headers["x-request-id"]
    )

    assert entries[-1]["error_type"] == "RuntimeError"
    assert entries[-1]["error_location"].startswith(
        "test_observability.py:"
    )

    assert entries[-1]["outcome"] == "failed"
    assert entries[-1]["status_code"] == 500

    assert "do-not-expose" not in response.text
    assert "do-not-expose" not in json.dumps(entries)


# ============================================================
# 6. AKIŞ YANITININ KORUNMASI
# ============================================================

def test_streaming_response_is_preserved(observed_client):
    client, entries = observed_client

    response = client.get("/stream")

    assert response.status_code == 200
    assert response.text == "onetwo"
    assert response.headers["x-request-id"]
    assert entries[-1]["outcome"] == "completed"


# ============================================================
# 7. JSON GÜNLÜK BİÇİMİ
# ============================================================

def test_formatter_outputs_json():
    record = logging.LogRecord(
        "servis_takip.http",
        logging.INFO,
        __file__,
        1,
        "http_request",
        (),
        None,
    )

    record.request_id = "example-request-id"
    record.status_code = 200
    record.duration_ms = 12.5

    parsed = json.loads(
        observability.JsonLogFormatter().format(record)
    )

    assert parsed["event"] == "http_request"
    assert parsed["request_id"] == "example-request-id"
    assert parsed["status_code"] == 200
    assert parsed["duration_ms"] == 12.5
    assert parsed["level"] == "INFO"


def test_formatter_does_not_serialize_raw_exception():
    try:
        raise RuntimeError("private-exception-value")

    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            (),
            sys.exc_info(),
        )

    output = observability.JsonLogFormatter().format(record)

    assert "private-exception-value" not in output
    assert json.loads(output)["level"] == "ERROR"