"""
API testlerinin ortak hazırlıkları.

Her test ayrı bir dış transaction içinde çalışır.
API istekleri ve testin veritabanı kontrolleri aynı bağlantıyı kullanır.
Test sonunda kayıt değişiklikleri geri alınır.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from collections.abc import Generator
from uuid import uuid4

from app.models import User, UserRole

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.database import database_url
from app.dependencies import get_session
from app.main import app


# ============================================================================
# 2. TEST VERİTABANI BAĞLANTISI
# ============================================================================

@pytest.fixture(scope="session")
def test_engine() -> Generator[Engine, None, None]:
    """Test çalışması boyunca kullanılacak bağlantı havuzunu oluşturur."""

    test_url = database_url.set(database="servis_takip_test")

    engine = create_engine(
        test_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )

    try:
        yield engine
    finally:
        engine.dispose()


# ============================================================================
# 3. HER TEST İÇİN DIŞ TRANSACTION
# ============================================================================

@pytest.fixture
def db_connection(test_engine: Engine) -> Generator[Connection, None, None]:
    """Testteki API isteklerinin ve doğrudan sorguların ortak bağlantısını sağlar."""

    with test_engine.connect() as connection:
        transaction = connection.begin()

        try:
            yield connection
        finally:
            # Bağımlı fixture'lar kapandıktan sonra testin değişikliklerini kaldır.
            transaction.rollback()


# ============================================================================
# 4. TEST KODUNUN KULLANACAĞI VERİTABANI OTURUMU
# ============================================================================

@pytest.fixture
def db_session(db_connection: Connection) -> Generator[Session, None, None]:
    """API isteği tamamlandıktan sonra veritabanındaki kayıtları incelemeyi sağlar."""

    with Session(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
    ) as session:
        yield session


# ============================================================================
# 5. API TEST İSTEMCİSİ
# ============================================================================

@pytest.fixture
def client(db_connection: Connection) -> Generator[TestClient, None, None]:
    """get_session kullanan endpoint'leri test bağlantısına yönlendirir."""

    def override_get_session() -> Generator[Session, None, None]:
        """Her API isteğine ayrı bir Session sağlar."""

        with Session(
            bind=db_connection,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


# ============================================================
# ROL BAZLI GİRİŞ YAPMIŞ TEST İSTEMCİSİ
# ============================================================

@pytest.fixture
def authenticated_client(client, db_session):
    """
    İstenen rolde bir test kullanıcısıyla giriş yapmayı sağlar.

    Rol ataması yalnızca test hazırlığında veritabanından yapılır.
    Gerçek kullanıcı kayıt endpoint'i rol kabul etmeye devam etmez.
    """

    previous_authorization = client.headers.get("Authorization")

    def login_as(role: UserRole):
        # ----------------------------------------------------
        # 1. Normal kayıt endpoint'i üzerinden kullanıcı oluştur
        # ----------------------------------------------------

        password = "Sadece-Test-Icin-Guclu-Parola-42!"
        email = f"permissions-{uuid4().hex}@example.com"

        registration = client.post(
            "/users",
            json={
                "full_name": "Yetki Test Kullanıcısı",
                "email": email,
                "password": password,
            },
        )

        assert registration.status_code == 201

        user_id = registration.json()["id"]

        # ----------------------------------------------------
        # 2. Test senaryosunun gerektirdiği rolü hazırla
        # ----------------------------------------------------

        user = db_session.get(User, user_id)
        assert user is not None

        user.role = role
        db_session.commit()

        # ----------------------------------------------------
        # 3. Gerçek giriş endpoint'inden token al
        # ----------------------------------------------------

        login_response = client.post(
            "/auth/token",
            data={
                "username": email,
                "password": password,
            },
        )

        assert login_response.status_code == 200

        token = login_response.json()["access_token"]

        # Bundan sonra bu istemcinin istekleri token içerecek.
        client.headers["Authorization"] = f"Bearer {token}"

        return client

    try:
        yield login_as
    finally:
        # Testte eklediğimiz başlığı temizle veya önceki hâline getir.
        if previous_authorization is None:
            client.headers.pop("Authorization", None)
        else:
            client.headers["Authorization"] = previous_authorization


@pytest.fixture
def manager_client(authenticated_client):
    """Yönetici olarak giriş yapmış test istemcisini döndürür."""

    return authenticated_client(UserRole.MANAGER)