# ============================================================
# İÇE AKTARMALAR
# ============================================================

from uuid import uuid4

import pytest

from app.models import (
    Team,
    TeamMember,
    Ticket,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
)
from app.security import hash_password


# ============================================================
# 1. ERİŞİM SENARYOSU İÇİN VERİ HAZIRLIĞI
# ============================================================

@pytest.fixture
def ticket_world(db_session):
    """
    İki ekip, dört kullanıcı ve dört talep oluşturur.

    Bu testlerin konusu kayıt endpoint'i değil, görünürlüktür.
    Bu yüzden senaryo verilerini doğrudan veritabanında hazırlarız.
    """

    password = "Sadece-Test-Icin-Guclu-Parola-42!"
    password_hash = hash_password(password)
    unique_part = uuid4().hex

    users = {
        "requester": User(
            full_name="Birinci Talep Sahibi",
            email=f"requester-{unique_part}@example.com",
            password_hash=password_hash,
            role=UserRole.REQUESTER,
        ),
        "other": User(
            full_name="İkinci Talep Sahibi",
            email=f"other-{unique_part}@example.com",
            password_hash=password_hash,
            role=UserRole.REQUESTER,
        ),
        "agent": User(
            full_name="Test Servis Görevlisi",
            email=f"agent-{unique_part}@example.com",
            password_hash=password_hash,
            role=UserRole.AGENT,
        ),
        "manager": User(
            full_name="Test Yöneticisi",
            email=f"manager-{unique_part}@example.com",
            password_hash=password_hash,
            role=UserRole.MANAGER,
        ),
    }

    team_a = Team(name=f"Ekip A {unique_part}")
    team_b = Team(name=f"Ekip B {unique_part}")

    db_session.add_all([*users.values(), team_a, team_b])
    db_session.flush()

    # Görevli yalnızca A ekibinin üyesidir.
    db_session.add(
        TeamMember(
            team_id=team_a.id,
            user_id=users["agent"].id,
        )
    )

    common_description = "Erişim kurallarını kontrol eden test talebi."

    tickets = {
        "requester_own": Ticket(
            title="Talep sahibinin kendi kaydı",
            description=common_description,
            requester_id=users["requester"].id,
            team_id=team_b.id,
            priority=TicketPriority.NORMAL,
            status=TicketStatus.OPEN,
        ),
        "other_private": Ticket(
            title="Başkasının B ekibindeki kaydı",
            description=common_description,
            requester_id=users["other"].id,
            team_id=team_b.id,
            priority=TicketPriority.HIGH,
            status=TicketStatus.OPEN,
        ),
        "agent_team": Ticket(
            title="Görevlinin A ekibindeki kayıt",
            description=common_description,
            requester_id=users["other"].id,
            team_id=team_a.id,
            priority=TicketPriority.HIGH,
            status=TicketStatus.OPEN,
        ),
        "agent_own": Ticket(
            title="Görevlinin kendi açtığı kayıt",
            description=common_description,
            requester_id=users["agent"].id,
            team_id=team_b.id,
            priority=TicketPriority.LOW,
            status=TicketStatus.OPEN,
        ),
    }

    db_session.add_all(tickets.values())
    db_session.flush()

    # Commit sonrasında ORM nesnelerine bağlı kalmamak için
    # gerekli kimlikleri ve giriş bilgilerini sade verilere çevir.
    world = {
        "password": password,
        "users": {
            name: {"id": user.id, "email": user.email}
            for name, user in users.items()
        },
        "teams": {"a": team_a.id, "b": team_b.id},
        "tickets": {
            name: ticket.id
            for name, ticket in tickets.items()
        },
    }

    db_session.commit()

    return world


def login_actor(client, world, actor: str):
    """Senaryodaki kullanıcıyla gerçek giriş endpoint'inden giriş yapar."""

    response = client.post(
        "/auth/token",
        data={
            "username": world["users"][actor]["email"],
            "password": world["password"],
        },
    )

    assert response.status_code == 200

    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    return client


# ============================================================
# 2. LİSTE GÖRÜNÜRLÜĞÜ
# ============================================================

@pytest.mark.parametrize(
    ("actor", "visible_names"),
    [
        ("requester", ["requester_own"]),
        ("agent", ["agent_team", "agent_own"]),
        (
            "manager",
            [
                "requester_own",
                "other_private",
                "agent_team",
                "agent_own",
            ],
        ),
    ],
)
def test_ticket_list_respects_visibility(
    client,
    ticket_world,
    actor,
    visible_names,
):
    client = login_actor(client, ticket_world, actor)

    response = client.get("/tickets")
    assert response.status_code == 200

    data = response.json()

    expected_ids = {
        ticket_world["tickets"][name]
        for name in visible_names
    }
    actual_ids = {item["id"] for item in data["items"]}

    assert actual_ids == expected_ids
    assert data["total"] == len(expected_ids)


# ============================================================
# 3. TEK KAYIT GÖRÜNÜRLÜĞÜ
# ============================================================

@pytest.mark.parametrize(
    ("actor", "ticket_name", "expected_status"),
    [
        ("requester", "requester_own", 200),
        ("requester", "other_private", 404),
        ("agent", "agent_team", 200),
        ("agent", "agent_own", 200),
        ("agent", "other_private", 404),
        ("manager", "other_private", 200),
    ],
)
def test_ticket_detail_respects_visibility(
    client,
    ticket_world,
    actor,
    ticket_name,
    expected_status,
):
    client = login_actor(client, ticket_world, actor)
    ticket_id = ticket_world["tickets"][ticket_name]

    response = client.get(f"/tickets/{ticket_id}")

    assert response.status_code == expected_status

    if expected_status == 200:
        assert response.json()["id"] == ticket_id
    else:
        assert response.json() == {"detail": "Talep bulunamadı."}


def test_missing_ticket_returns_not_found(client, ticket_world, db_session):
    client = login_actor(client, ticket_world, "requester")

    ticket_id = ticket_world["tickets"]["requester_own"]
    ticket = db_session.get(Ticket, ticket_id)

    assert ticket is not None

    db_session.delete(ticket)
    db_session.commit()

    response = client.get(f"/tickets/{ticket_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Talep bulunamadı."}


# ============================================================
# 4. FİLTRELER ERİŞİMİ GENİŞLETMEMELİ
# ============================================================

def test_filters_do_not_expand_visibility(client, ticket_world):
    client = login_actor(client, ticket_world, "agent")

    # Görevlinin görebildiği tek HIGH kayıt, A ekibindeki kayıttır.
    response = client.get(
        "/tickets",
        params={"priority": "HIGH", "status": "OPEN"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == (
        ticket_world["tickets"]["agent_team"]
    )

    # B ekibinde başka birinin HIGH talebi var.
    # Filtre kullanmak bu gizli kaydı görünür yapmamalı.
    response = client.get(
        "/tickets",
        params={
            "team_id": ticket_world["teams"]["b"],
            "priority": "HIGH",
        },
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


# ============================================================
# 5. SAYFALAMA
# ============================================================

def test_ticket_pagination(client, ticket_world):
    client = login_actor(client, ticket_world, "manager")

    expected_ids = sorted(
        ticket_world["tickets"].values(),
        reverse=True,
    )

    first = client.get("/tickets", params={"limit": 2, "offset": 0})
    second = client.get("/tickets", params={"limit": 2, "offset": 2})

    assert first.status_code == 200
    assert second.status_code == 200

    assert [item["id"] for item in first.json()["items"]] == expected_ids[:2]
    assert [item["id"] for item in second.json()["items"]] == expected_ids[2:]

    assert first.json()["total"] == 4
    assert second.json()["total"] == 4

    assert first.json()["limit"] == 2
    assert second.json()["offset"] == 2


# ============================================================
# 6. ÜYELİK VE ROL DEĞİŞİKLİKLERİ
# ============================================================

def test_removed_membership_revokes_team_visibility(
    client,
    ticket_world,
    db_session,
):
    client = login_actor(client, ticket_world, "agent")

    team_ticket_id = ticket_world["tickets"]["agent_team"]

    before = client.get(f"/tickets/{team_ticket_id}")
    assert before.status_code == 200

    membership = db_session.get(
        TeamMember,
        (
            ticket_world["teams"]["a"],
            ticket_world["users"]["agent"]["id"],
        ),
    )
    assert membership is not None

    db_session.delete(membership)
    db_session.commit()

    # Aynı token ile tekrar istek gönderiyoruz.
    after = client.get(f"/tickets/{team_ticket_id}")
    assert after.status_code == 404

    # Kendi açtığı talebi görme hakkı devam eder.
    own_id = ticket_world["tickets"]["agent_own"]
    assert client.get(f"/tickets/{own_id}").status_code == 200

    listed = client.get("/tickets")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [own_id]


def test_role_change_uses_current_database_role(
    client,
    ticket_world,
    db_session,
):
    client = login_actor(client, ticket_world, "agent")

    user = db_session.get(
        User,
        ticket_world["users"]["agent"]["id"],
    )
    assert user is not None

    # Üyelik duruyor; ancak kullanıcı artık agent değil.
    user.role = UserRole.REQUESTER
    db_session.commit()

    response = client.get("/tickets")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [
        ticket_world["tickets"]["agent_own"]
    ]


# ============================================================
# 7. OTURUM VE PARAMETRE DOĞRULAMA
# ============================================================

@pytest.mark.parametrize("url", ["/tickets", "/tickets/1"])
def test_ticket_reading_requires_login(client, url):
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"offset": -1},
        {"status": "UNKNOWN"},
        {"priority": "URGENT"},
    ],
)
def test_invalid_ticket_filters_are_rejected(
    client,
    ticket_world,
    params,
):
    client = login_actor(client, ticket_world, "requester")

    response = client.get("/tickets", params=params)

    assert response.status_code == 422