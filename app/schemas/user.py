"""
Kullanıcı oluşturma işleminin API veri modelleri.

UserCreate: İstemcinin gönderebileceği alanlar.
UserRead: Başarılı işlemde istemciye döndürülecek alanlar.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from app.models.user import UserRole


# ============================================================================
# 2. KULLANICI OLUŞTURMA İSTEĞİ
# ============================================================================

class UserCreate(BaseModel):
    """Yeni hesap oluşturulurken alınacak bilgileri doğrular."""

    model_config = ConfigDict(
        # role veya is_active gibi tanımlanmayan alanları kabul etme.
        extra="forbid",
    )

    full_name: str = Field(
        min_length=2,
        max_length=100,
        description="Kullanıcının adı ve soyadı.",
    )

    email: EmailStr = Field(
        max_length=254,
        description="Girişte kullanılacak e-posta adresi.",
    )

    # Bu proje için başlangıç parola uzunluğu politikamız.
    # Parolanın karakterlerini değiştirmiyoruz.
    password: SecretStr = Field(
        min_length=15,
        max_length=128,
        description="15–128 karakter uzunluğunda parola.",
    )

    # ------------------------------------------------------------------------
    # 2.1. Metin alanlarını temizleme
    # ------------------------------------------------------------------------

    @field_validator("full_name", "email", mode="before")
    @classmethod
    def strip_text_fields(cls, value: Any) -> Any:
        """Yalnızca ad ve e-posta alanlarının kenar boşluklarını temizler."""

        if isinstance(value, str):
            return value.strip()

        # Metin olmayan değerlerin reddedilmesini alan doğrulamasına bırak.
        return value

    # ------------------------------------------------------------------------
    # 2.2. E-postayı uygulamanın saklama biçimine dönüştürme
    # ------------------------------------------------------------------------

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Doğrulanmış e-postayı uygulama politikamız gereği küçük harfe çevirir."""

        normalized = value.lower()

        # Dönüşüm sonrası değerin de veritabanı sınırına uyduğunu kontrol et.
        if len(normalized) > 254:
            raise ValueError("E-posta en fazla 254 karakter olabilir.")

        return normalized


# ============================================================================
# 3. KULLANICI YANITI
# ============================================================================

class UserRead(BaseModel):
    """Kullanıcı kaydının API üzerinden gösterilebilecek alanları."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime