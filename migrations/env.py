"""
Alembic'in veritabanı bağlantısı ve model yapılandırması.

Bağlantı bilgilerini uygulamanın database modülünden alır.
Tablo tanımlarını uygulamanın ortak metadata nesnesinden okur.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from logging.config import fileConfig

from alembic import context

from app.database import database_url, engine
from app.models import Base


# ============================================================================
# 2. ALEMBIC VE MODEL AYARLARI
# ============================================================================

config = context.config

# Alembic'in oluşturduğu ini dosyasındaki günlükleme ayarlarını kullan.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# app.models yüklendiği için Team tablosunun tanımı da metadata içindedir.
target_metadata = Base.metadata


# ============================================================================
# 3. VERİTABANINA BAĞLANMADAN SQL ÜRETME
# ============================================================================

def run_migrations_offline() -> None:
    """Migration dosyalarından SQL metni üretmek için kullanılan çalışma modu."""

    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ============================================================================
# 4. VERİTABANINA BAĞLANARAK ÇALIŞMA
# ============================================================================

def run_migrations_online() -> None:
    """Canlı veritabanına bağlanarak Alembic işlemlerini yürütür."""

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Alembic komutu tamamlandığında bu sürece ait bağlantıları temizle.
        engine.dispose()


# ============================================================================
# 5. ÇALIŞMA MODUNU SEÇME
# ============================================================================

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()