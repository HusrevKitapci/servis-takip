"""
Ekip işlemlerinde kullanılan API veri modelleri.

TeamCreate: Kullanıcının gönderebileceği alanlar.
TeamRead: API'nin kullanıcıya döndüreceği alanlar.
"""

# ============================================================================
# 1. KÜTÜPHANELER
# ============================================================================

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# 2. İSTEK MODELİ
# ============================================================================

class TeamCreate(BaseModel):
    """Yeni ekip oluşturulurken alınacak veriyi doğrular."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    name: str = Field(
        min_length=2,
        max_length=100,
        description="Ekibin adı.",
    )


# ============================================================================
# 3. YANIT MODELİ
# ============================================================================

class TeamRead(BaseModel):
    """Kaydedilmiş bir ekibin API yanıtındaki görünümünü tanımlar."""

    # Alanları yalnızca sözlüklerden değil, Team gibi nesnelerden de okuyabilir.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    created_at: datetime


# ============================================================================
# 4. AKTİFLİK DEĞİŞTİRME İSTEK MODELİ
# ============================================================================

class TeamStatusUpdate(BaseModel):
    """Bir ekibin aktiflik durumunu değiştirmek için alınacak veriyi tanımlar."""

    model_config = ConfigDict(
        extra="forbid",
    )

    # Varsayılan değer vermiyoruz: kullanıcı istediği durumu açıkça göndermeli.
    # strict=True sayesinde yalnızca gerçek boolean değerler kabul edilir.
    is_active: bool = Field(
        strict=True,
        description="Ekibi aktifleştirmek için true, pasifleştirmek için false.",
    )

