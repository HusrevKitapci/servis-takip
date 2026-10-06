# ============================================================
# İÇE AKTARMALAR
# ============================================================

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from uuid import uuid4
from app.models import TicketComment, TicketEvent

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session

from app.dependencies import get_session
from app.main import app
from app.models import (
    Team,
    TeamMember,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from app.security import create_access_token, hash_password


# ============================================================
# 1. ORTAK SENARYO HAZIRLIĞI
# ============================================================

def seed_claim_case(session: Session) -> dict:
    """
    Bir ekip, iki üye görevli, bir talep sahibi ve bir yönetici hazırlar.

    Commit kararı çağırana aittir:
    normal testler dış transaction'ı, eşzamanlılık testi gerçek commit'i
    kullanır.
    """

    unique_part = uuid4().hex
    password_hash = hash_password("Sadece-Test-Icin-Guclu-Parola-42!")

    roles = {
        "requester": UserRole.REQUESTER,
        "agent_a": UserRole.AGENT,
        "agent_b": UserRole.AGENT,
        "manager": UserRole.MANAGER,
    }

    users = {
        name: User(
            full_name=f"Üstlenme Testi {name}",
            email=f"{name}-{unique_part}@example.com",
            password_hash=password_hash,
            role=role,
        )
        for name, role in roles.items()
    }

    team = Team(name=f"Üstlenme Ekibi {unique_part}")

    session.add_all([*users.values(), team])
    session.flush()

    session.add_all(
        [
            TeamMember(team_id=team.id, user_id=users["agent_a"].id),
            TeamMember(team_id=team.id, user_id=users["agent_b"].id),
        ]
    )

    ticket = Ticket(
        title="Ortak üstlenme denemesi",
        description="İki görevlinin üstlenmesini test ettiğimiz talep.",
        requester_id=users["requester"].id,
        team_id=team.id,
        status=TicketStatus.OPEN,
    )

    session.add(ticket)
    session.flush()

    return {
        "team_id": team.id,
        "ticket_id": ticket.id,
        "users": {
            name: user.id
            for name, user in users.items()
        },
    }


@pytest.fixture
def claim_case(db_session):
    case = seed_claim_case(db_session)
    db_session.commit()
    return case


def token_headers(case: dict, actor: str) -> dict[str, str]:
    """Giriş akışını yeniden sınamadan gerçek, imzalı token hazırlar."""

    token = create_access_token(case["users"][actor])

    return {"Authorization": f"Bearer {token}"}


# ============================================================
# 2. BAŞARILI ÜSTLENME VE TEKRAR DENEME
# ============================================================

def test_agent_claims_and_second_attempt_conflicts(
    client,
    claim_case,
    db_session,
):
    url = f"/tickets/{claim_case['ticket_id']}/claim"

    first = client.post(
        url,
        headers=token_headers(claim_case, "agent_a"),
    )

    assert first.status_code == 200
    assert first.json()["status"] == "IN_PROGRESS"
    assert first.json()["assignee_id"] == claim_case["users"]["agent_a"]
    assert first.json()["claimed_at"] is not None

    # Farklı görevli tekrar üstlenmeye çalışıyor.
    second = client.post(
        url,
        headers=token_headers(claim_case, "agent_b"),
    )

    assert second.status_code == 409

    db_session.expire_all()
    ticket = db_session.get(Ticket, claim_case["ticket_id"])

    assert ticket is not None
    assert ticket.assignee_id == claim_case["users"]["agent_a"]
    assert ticket.requester_id == claim_case["users"]["requester"]


# ============================================================
# 3. YETKİ VE EKİP KURALLARI
# ============================================================

@pytest.mark.parametrize("actor", ["requester", "manager"])
def test_only_agents_can_claim(client, claim_case, actor):
    response = client.post(
        f"/tickets/{claim_case['ticket_id']}/claim",
        headers=token_headers(claim_case, actor),
    )

    assert response.status_code == 403


def test_nonmember_cannot_claim_other_ticket(
    client,
    claim_case,
    db_session,
):
    membership = db_session.get(
        TeamMember,
        (claim_case["team_id"], claim_case["users"]["agent_b"]),
    )
    assert membership is not None

    db_session.delete(membership)
    db_session.commit()

    response = client.post(
        f"/tickets/{claim_case['ticket_id']}/claim",
        headers=token_headers(claim_case, "agent_b"),
    )

    # Artık talep bu görevlinin görünürlük alanında değil.
    assert response.status_code == 404


def test_own_ticket_does_not_replace_membership(
    client,
    claim_case,
    db_session,
):
    membership = db_session.get(
        TeamMember,
        (claim_case["team_id"], claim_case["users"]["agent_b"]),
    )
    ticket = db_session.get(Ticket, claim_case["ticket_id"])

    assert membership is not None
    assert ticket is not None

    db_session.delete(membership)
    ticket.requester_id = claim_case["users"]["agent_b"]
    db_session.commit()

    response = client.post(
        f"/tickets/{claim_case['ticket_id']}/claim",
        headers=token_headers(claim_case, "agent_b"),
    )

    # Kendi talebini görebiliyor ama ekip üyesi olmadığı için üstlenemiyor.
    assert response.status_code == 403


def test_inactive_team_prevents_claim(
    client,
    claim_case,
    db_session,
):
    team = db_session.get(Team, claim_case["team_id"])
    assert team is not None

    team.is_active = False
    db_session.commit()

    response = client.post(
        f"/tickets/{claim_case['ticket_id']}/claim",
        headers=token_headers(claim_case, "agent_a"),
    )

    assert response.status_code == 409

    db_session.expire_all()
    ticket = db_session.get(Ticket, claim_case["ticket_id"])

    assert ticket is not None
    assert ticket.status == TicketStatus.OPEN
    assert ticket.assignee_id is None
    assert ticket.claimed_at is None


def test_claim_requires_login(client):
    response = client.post("/tickets/1/claim")

    assert response.status_code == 401


# ============================================================
# 4. GERÇEK EŞZAMANLILIK TESTİ
# ============================================================

def test_concurrent_claim_has_exactly_one_winner(test_engine):
    """
    İki ayrı PostgreSQL bağlantısıyla aynı talebi üstlenmeye çalışır.

    Standart client/db_session fixture'larını kullanmaz:
    onlar tek dış transaction üzerinden çalışır.
    """

    # --------------------------------------------------------
    # 4.1. Yalnızca test veritabanında çalıştığımızı doğrula
    # --------------------------------------------------------

    assert test_engine.url.database == "servis_takip_test"

    with Session(test_engine) as setup_session:
        assert setup_session.scalar(
            text("SELECT current_database()")
        ) == "servis_takip_test"

        assert setup_session.scalar(
            text("SHOW transaction_isolation")
        ) == "read committed"

        case = seed_claim_case(setup_session)

        # Diğer bağlantıların kayıtları görebilmesi için gerçek commit.
        setup_session.commit()

    previous_overrides = app.dependency_overrides.copy()

    # İki isteği UPDATE gönderilmeden hemen önce buluşturur.
    update_barrier = Barrier(2)

    # Gerçekten farklı PostgreSQL bağlantıları kullanıldığını ölçer.
    backend_pids = set()
    pids_lock = Lock()

    listener_installed = False

    def independent_session():
        with Session(test_engine) as session:
            # Hatalı testte sınırsız kilit veya sorgu beklenmesini önle.
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '15s'"))

            backend_pid = session.scalar(text("SELECT pg_backend_pid()"))

            with pids_lock:
                backend_pids.add(backend_pid)

            yield session

    def synchronize_ticket_updates(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ):
        compiled_statement = (
            context.compiled.statement
            if context.compiled is not None
            else None
        )

        if (
            getattr(compiled_statement, "is_update", False)
            and compiled_statement.table.name == "tickets"
        ):
            # İki istek de güncelleme noktasına ulaşmadan ilerleme.
            update_barrier.wait(timeout=10)

    def send_claim(actor: str):
        # Her iş parçacığı kendi HTTP test istemcisini kullanır.
        with TestClient(app) as thread_client:
            response = thread_client.post(
                f"/tickets/{case['ticket_id']}/claim",
                headers=token_headers(case, actor),
            )

            return actor, response.status_code, response.json()

    try:
        # ----------------------------------------------------
        # 4.2. İsteklere bağımsız veritabanı oturumları ver
        # ----------------------------------------------------

        app.dependency_overrides[get_session] = independent_session

        event.listen(
            test_engine,
            "before_cursor_execute",
            synchronize_ticket_updates,
        )
        listener_installed = True

        # ----------------------------------------------------
        # 4.3. İki görevliden eşzamanlı istek gönder
        # ----------------------------------------------------

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(send_claim, "agent_a"),
                executor.submit(send_claim, "agent_b"),
            ]

            results = [
                future.result(timeout=30)
                for future in futures
            ]

        assert len(backend_pids) == 2

        # Kimin kazanacağına değil, tam bir kazanan olmasına bakarız.
        assert sorted(result[1] for result in results) == [200, 409]

        winner_actor, _, winner_body = next(
            result for result in results if result[1] == 200
        )
        winner_id = case["users"][winner_actor]

        assert winner_body["assignee_id"] == winner_id

        # ----------------------------------------------------
        # 4.4. Kalıcı sonucu başka bir oturumla doğrula
        # ----------------------------------------------------

        with Session(test_engine) as verify_session:
            ticket = verify_session.get(Ticket, case["ticket_id"])

            assert ticket is not None
            assert ticket.status == TicketStatus.IN_PROGRESS
            assert ticket.assignee_id == winner_id
            assert ticket.claimed_at is not None
            assert ticket.requester_id == case["users"]["requester"]

    finally:
        # ----------------------------------------------------
        # 4.5. Test ayarlarını ve yalnızca kendi kayıtlarımızı temizle
        # ----------------------------------------------------

        if listener_installed:
            event.remove(
                test_engine,
                "before_cursor_execute",
                synchronize_ticket_updates,
            )

        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

        with Session(test_engine) as cleanup_session:
            # ------------------------------------------------
            # Önce bu testin talebine bağlı kayıtları temizle.
            # Yalnızca bu talebin kayıtlarını hedefliyoruz.
            # ------------------------------------------------

            cleanup_session.execute(
                delete(TicketEvent).where(
                    TicketEvent.ticket_id == case["ticket_id"]
                )
            )

            cleanup_session.execute(
                delete(TicketComment).where(
                    TicketComment.ticket_id == case["ticket_id"]
                )
            )

            # Bağlı kayıtlar silindiği için talep artık silinebilir.
            cleanup_session.execute(
                delete(Ticket).where(
                    Ticket.id == case["ticket_id"]
                )

            )

            cleanup_session.commit()