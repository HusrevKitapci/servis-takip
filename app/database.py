"""
Veritabanı bağlantısının yapılandırılması.

Bu modül, uygulamanın kullanacağı SQLAlchemy engine nesnesini oluşturur.
Modül doğrudan çalıştırıldığında küçük bir bağlantı kontrolü gerçekleştirir.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from sqlalchemy import URL, create_engine, text

from app.config import get_settings


# ============================================================================
# 2. BAĞLANTI AYARLARI
# ============================================================================

settings = get_settings()

# Bağlantı bilgisini metin birleştirmek yerine URL nesnesiyle oluşturuyoruz.
# Böylece paroladaki @ veya / gibi karakterler adresin yapısını bozmaz.
database_url = URL.create(
    drivername="postgresql+psycopg",
    username=settings.postgres_user,
    password=settings.postgres_password.get_secret_value(),
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
)


# ============================================================================
# 3. VERİTABANI ENGINE NESNESİ
# ============================================================================

# Engine, bağlantıları ve bağlantı havuzunu yöneten nesnedir.
# Oluşturulması tek başına veritabanına bağlantı kurulduğu anlamına gelmez.
engine = create_engine(
    database_url,

    # Havuzdan alınan bağlantıların kullanılabilirliğini kontrol eder.
    pool_pre_ping=True,

    # İlk bağlantı girişiminde uzun süre beklemeyi sınırlar.
    connect_args={"connect_timeout": 5},
)


# ============================================================================
# 4. BAĞLANTI KONTROLÜ
# ============================================================================

def check_database_connection() -> None:
    """Veritabanına bağlanır ve kullanılan veritabanı ile kullanıcıyı gösterir."""

    # Bağlantıyı yalnızca bu işlem süresince kullanırız.
    # Blok bittiğinde bağlantı havuza geri bırakılır.
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    current_database() AS database_name,
                    current_user AS user_name
                """
            )
        )

        # Tam olarak bir sonuç satırı bekliyoruz.
        # mappings(), sütunlara adları üzerinden erişmemizi sağlar.
        row = result.mappings().one()

        print("Veritabanı bağlantısı başarılı.")
        print(f"Veritabanı: {row['database_name']}")
        print(f"Kullanıcı: {row['user_name']}")
        print(f"Bağlantı adresi: {settings.postgres_host}:{settings.postgres_port}")


# ============================================================================
# 5. MODÜLÜ KOMUT SATIRINDAN ÇALIŞTIRMA
# ============================================================================

if __name__ == "__main__":
    try:
        check_database_connection()
    finally:
        # Bağımsız kontrol tamamlandığında havuzdaki bağlantıları kapatır.
        # Kontrol hata verse bile bu temizlik adımı çalışır.
        engine.dispose()