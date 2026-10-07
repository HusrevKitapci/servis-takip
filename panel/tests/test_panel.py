"""Panel akışlarını gerçek API'ye veri yazmadan AppTest ile kontrol eder."""
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
NOW = "2026-10-06T12:00:00+00:00"


def button(app, label):
    return next(item for item in app.button if item.label == label)


@pytest.fixture
def ui(monkeypatch):
    monkeypatch.delenv("SERVIS_API_URL", raising=False)
    state = {"role": "manager", "expired": False, "calls": [], "status": "OPEN"}

    def request(method, url, **kwargs):
        path = url.removeprefix("http://127.0.0.1:8000")
        state["calls"].append((method, path, kwargs))
        status = 200
        if path == "/auth/token":
            data = {"access_token": "test-token"}
        elif state["expired"]:
            status, data = 401, {"detail": "expired"}
        elif path == "/users/me":
            data = {"id": 2, "full_name": "Deneme", "role": state["role"]}
        elif path == "/reports/tickets/summary":
            data = {"total": 1, "by_status": [{"status": "OPEN", "count": 1}],
                    "by_priority": [{"priority": "NORMAL", "count": 1}],
                    "by_sla": [{"status": "WAITING", "count": 1}], "evaluated_at": NOW}
        elif path == "/teams":
            data = [{"id": 9, "name": "Destek", "is_active": True}]
        elif path == "/teams/9/members":
            data = []
        elif path == "/tickets" and method == "POST":
            status, data = 201, {"id": 42}
        elif path.endswith("/comments") and method == "POST":
            status, data = 201, {"id": 8}
        elif path.endswith("/comments") or path.endswith("/events"):
            data = {"total": 0, "items": []}
        elif path.endswith("/sla"):
            data = {"status": "WAITING", "due_at": NOW, "first_response_at": None}
        elif path.endswith("/claim"):
            state["status"] = "IN_PROGRESS"
            data = {}
        elif path.startswith("/tickets"):
            ticket = {"id": 42, "title": "Yazıcı çalışmıyor", "description": "Bağlantı yok",
                      "status": state["status"], "priority": "NORMAL", "team_id": 9,
                      "requester_id": 5, "assignee_id": 2 if state["status"] == "IN_PROGRESS" else None,
                      "created_at": NOW}
            data = {"total": 1, "items": [ticket]} if path == "/tickets" else ticket
        else:
            raise AssertionError(f"Testte beklenmeyen istek: {method} {path}")
        return httpx.Response(status, json=data, headers={"X-Request-ID": "test-request"})

    with patch("httpx.request", side_effect=request):
        app = AppTest.from_file(APP, default_timeout=15).run()
        yield app, state


def login(app):
    app.text_input(key="login_email").set_value("manager@example.com")
    app.text_input(key="login_password").set_value("long-password-value")
    button(app, "Giriş yap").click().run()
    assert not app.exception


def test_login_and_logout_clear_session(ui):
    app, _ = ui
    login(app)
    assert app.metric[0].value == "1"
    assert "Ekip yönetimi" in app.radio[0].options
    button(app, "Çıkış yap").click().run()
    assert not app.exception
    assert "token" not in app.session_state
    assert len(app.radio) == 0


def test_requester_has_no_manager_pages(ui):
    app, state = ui
    state["role"] = "requester"
    login(app)
    assert "Ekip yönetimi" not in app.radio[0].options
    assert "Görevli oluştur" not in app.radio[0].options


def test_expired_token_returns_login(ui):
    app, state = ui
    login(app)
    state["expired"] = True
    button(app, "Verileri yenile").click().run()
    assert not app.exception
    assert "token" not in app.session_state
    assert app.text_input(key="login_email")


def test_list_opens_ticket_and_posts_comment_once(ui):
    app, state = ui
    state["role"] = "agent"
    login(app)
    app.radio[0].set_value("Talepler").run()
    assert not app.exception
    button(app, "Talebi aç").click().run()
    assert not app.exception
    assert app.number_input(key="detail_id").value == 42
    app.text_area[0].set_value("Talebinizi incelemeye başladım.")
    button(app, "Yorumu gönder").click().run()
    assert not app.exception
    posts = [c for c in state["calls"] if c[0] == "POST" and c[1].endswith("/comments")]
    assert len(posts) == 1
    assert posts[0][2]["json"] == {"body": "Talebinizi incelemeye başladım."}
    assert posts[0][2]["headers"]["Authorization"] == "Bearer test-token"


def test_claim_button_tracks_updated_status(ui):
    app, state = ui
    state["role"] = "agent"
    login(app)
    app.session_state["detail_id"] = 42
    app.radio[0].set_value("Talep ayrıntısı").run()
    button(app, "Talebi üstlen").click().run()
    assert not app.exception
    assert button(app, "Çözüldü olarak işaretle")
    assert not any(b.label == "Talebi üstlen" for b in app.button)


def test_creation_navigates_without_reposting(ui):
    app, state = ui
    login(app)
    app.radio[0].set_value("Yeni talep").run()
    app.text_input[0].set_value("Yazıcı çalışmıyor")
    app.text_area[0].set_value("Belgeleri yazıcıdan alamıyorum.")
    button(app, "Talep oluştur").click().run()
    assert not app.exception
    assert app.radio[0].value == "Talep ayrıntısı"
    assert len([c for c in state["calls"] if c[:2] == ("POST", "/tickets")]) == 1


def test_manager_team_page(ui):
    app, _ = ui
    login(app)
    app.radio[0].set_value("Ekip yönetimi").run()
    assert not app.exception
    assert button(app, "Ekibe ekle")


def test_login_error_does_not_show_password():
    def fail(method, url, **kwargs):
        return httpx.Response(401, json={"detail": "Giriş bilgileri geçersiz."})
    with patch("httpx.request", side_effect=fail):
        app = AppTest.from_file(APP).run()
        app.text_input(key="login_email").set_value("manager@example.com")
        app.text_input(key="login_password").set_value("secret-not-for-display")
        button(app, "Giriş yap").click().run()
        assert not app.exception
        assert "Giriş bilgileri geçersiz." in app.error[0].value
        assert "secret-not-for-display" not in app.error[0].value
