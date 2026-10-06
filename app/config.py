"""
Uygulamanın yapılandırma ayarları.

Veritabanı bağlantı bilgilerini ortam değişkenlerinden ve .env dosyasından okur.
Gerekli ayarlar eksikse veya geçersizse uygulamanın erken hata vermesini sağlar.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ============================================================================
# 2. DOSYA KONUMLARI
# ============================================================================

# Bu dosya app/config.py konumunda olduğu için iki üst dizin proje köküdür.
# Böylece .env dosyasını terminalin bulunduğu klasörden bağımsız bulabiliriz.

PROJECT_DIR = Path(__file__).resolve().parent.parent

# ============================================================================
# 3. AYAR MODELİ
# ============================================================================

class Settings(BaseSettings):
    """Veritabanına bağlamak için gereken ayarı okur ve doğrular"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",

        # Python'daki postgres_host alanını POSTGRES_HOST ile eşleştirir.
        case_sensitive=False,

        #Ortak .env dosyasındaki başka araçlara ait ayarları yok sayar.
        extra="ignore",
    )

    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(ge=1, le=65535)
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)

    # ------------------------------------------------------------------------
    # Token ayarları
    # ------------------------------------------------------------------------

    jwt_secret_key: SecretStr = Field(
        min_length=64,
    )

    access_token_expire_minutes: int = Field(
        default=15,
        ge=1,
        le=60,
    )

# ============================================================================
# 4. AYARLARA ERİŞİM
# ============================================================================

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Ayarları ilk çağrıda okur; sonraki çağrılarda aynı nesneyi döndürür.

    .env değiştirildiğinde çalışan Python sürecini yeniden başlatmak gerekir.
    """

    return Settings()




