"""Yorum ve işlem geçmişi davranışlarına ait birim testleri."""

# ============================================================
# 1. İÇE AKTARMALAR
# ============================================================

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import tickets as ticket_api
from app.models import (
    TicketComment,
    TicketEvent,
    TicketEventType,
    TicketStatus,
)
from app.schemas.ticket import TicketCommentCreate


# ============================================================
# 2. YORUM VERİSİNİN DOĞRULANMASI
# ============================================================

def test_comment_body_is_trimmed():
    payload = TicketCommentCreate(body="  Yazıcı hâlâ çalışmıyor.  ")

    assert payload.body == "Yazıcı hâlâ çalışmıyor."


@pytest.mark.parametrize(
    "body",
    [
        "",
        "   ",
        "\n\t",
        "a",
        "a" * 5001,
    ],
)
def test_invalid_comment_body_is_rejected(body):
    with pytest.raises(ValidationError):
        TicketCommentCreate(body=body)


def test_comment_author_cannot_be_supplied_by_client():
    with pytest.raises(ValidationError):
        TicketCommentCreate.model_validate(
            {
                "body": "Bu yorum başka biri adına yazılmamalı.",
                "author_id": 999,
            }
        )


# ============================================================
# 3. YORUM EKLEME KURALLARI
# ============================================================

def test_invisible_ticket_does_not_receive_comment(monkeypatch):
    session = MagicMock(spec=Session)
    current_user = SimpleNamespace(id=7)

    def deny_access(*args, **kwargs):
        raise HTTPException(
            status_code=404,
            detail="Talep bulunamadı.",
        )

    monkeypatch.setattr(
        ticket_api,
        "_get_visible_ticket",
        deny_access,
    )

    with pytest.raises(HTTPException) as error:
        ticket_api.create_ticket_comment(
            ticket_id=10,
            payload=TicketCommentCreate(body="Kontrol eder misiniz?"),
            current_user=current_user,
            session=session,
        )

    assert error.value.status_code == 404
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_resolved_ticket_rejects_comment(monkeypatch):
    session = MagicMock(spec=Session)
    current_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        ticket_api,
        "_get_visible_ticket",
        lambda *args, **kwargs: SimpleNamespace(
            id=10,
            status=TicketStatus.RESOLVED,
        ),
    )

    with pytest.raises(HTTPException) as error:
        ticket_api.create_ticket_comment(
            ticket_id=10,
            payload=TicketCommentCreate(body="Yeni bir yorum."),
            current_user=current_user,
            session=session,
        )

    assert error.value.status_code == 409
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_called_once()


def test_comment_and_event_share_one_commit(monkeypatch):
    session = MagicMock(spec=Session)
    current_user = SimpleNamespace(id=7)
    added_objects = []

    get_ticket = MagicMock(
        return_value=SimpleNamespace(
            id=10,
            status=TicketStatus.OPEN,
        )
    )
    monkeypatch.setattr(
        ticket_api,
        "_get_visible_ticket",
        get_ticket,
    )

    session.add.side_effect = added_objects.append

    def assign_comment_id():
        # Gerçek veritabanının flush sırasında kimlik üretmesini taklit eder.
        added_objects[0].id = 42

    session.flush.side_effect = assign_comment_id

    comment = ticket_api.create_ticket_comment(
        ticket_id=10,
        payload=TicketCommentCreate(body="Sorun devam ediyor."),
        current_user=current_user,
        session=session,
    )

    assert len(added_objects) == 2

    saved_comment, saved_event = added_objects

    assert isinstance(saved_comment, TicketComment)
    assert isinstance(saved_event, TicketEvent)

    assert comment.author_id == 7
    assert comment.ticket_id == 10

    assert saved_event.actor_id == 7
    assert saved_event.ticket_id == 10
    assert saved_event.event_type == TicketEventType.COMMENT_ADDED
    assert saved_event.details == {"comment_id": 42}

    get_ticket.assert_called_once_with(
        session,
        current_user,
        10,
        lock=True,
    )
    session.commit.assert_called_once()
    session.rollback.assert_not_called()


def test_comment_commit_failure_triggers_rollback(monkeypatch):
    session = MagicMock(spec=Session)
    current_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        ticket_api,
        "_get_visible_ticket",
        lambda *args, **kwargs: SimpleNamespace(
            id=10,
            status=TicketStatus.OPEN,
        ),
    )

    session.commit.side_effect = SQLAlchemyError(
        "Test için oluşturulan veritabanı hatası."
    )

    with pytest.raises(SQLAlchemyError):
        ticket_api.create_ticket_comment(
            ticket_id=10,
            payload=TicketCommentCreate(body="Kontrol edilmesini istiyorum."),
            current_user=current_user,
            session=session,
        )

    session.rollback.assert_called_once()
    session.refresh.assert_not_called()


# ============================================================
# 4. DURUM DEĞİŞİKLİĞİ VE GEÇMİŞ KAYDI
# ============================================================

@pytest.mark.parametrize(
    "event_type",
    [
        TicketEventType.CLAIMED,
        TicketEventType.RESOLVED,
        TicketEventType.REOPENED,
    ],
)
def test_successful_transition_records_event(event_type):
    session = MagicMock(spec=Session)
    changed_ticket = SimpleNamespace(id=10)
    session.scalar.return_value = changed_ticket

    result = ticket_api._apply_transition(
        session,
        object(),
        actor_id=7,
        event_type=event_type,
        details={"example": "value"},
        conflict_detail="İşlem yapılamadı.",
    )

    saved_event = session.add.call_args.args[0]

    assert result is changed_ticket
    assert isinstance(saved_event, TicketEvent)
    assert saved_event.ticket_id == 10
    assert saved_event.actor_id == 7
    assert saved_event.event_type == event_type

    session.commit.assert_called_once()


def test_failed_transition_does_not_record_event():
    session = MagicMock(spec=Session)
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as error:
        ticket_api._apply_transition(
            session,
            object(),
            actor_id=7,
            event_type=TicketEventType.CLAIMED,
            details={},
            conflict_detail="Talep üstlenilemedi.",
        )

    assert error.value.status_code == 409
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_called_once()


def test_transition_commit_failure_triggers_rollback():
    session = MagicMock(spec=Session)
    session.scalar.return_value = SimpleNamespace(id=10)
    session.commit.side_effect = SQLAlchemyError(
        "Test için oluşturulan kayıt hatası."
    )

    with pytest.raises(SQLAlchemyError):
        ticket_api._apply_transition(
            session,
            object(),
            actor_id=7,
            event_type=TicketEventType.RESOLVED,
            details={},
            conflict_detail="Talep çözülemedi.",
        )

    session.rollback.assert_called_once()
    session.refresh.assert_not_called()