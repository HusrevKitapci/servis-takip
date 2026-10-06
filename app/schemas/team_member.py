
# ============================================================
# İÇE AKTARMALAR
# ============================================================

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserRead


# ============================================================
# 1. ÜYE EKLEME İSTEĞİ
# ============================================================

class TeamMemberCreate(BaseModel):
    """Ekip adresinden, kullanıcı kimliği istek gövdesinden alınır."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(
        strict=True,
        gt=0,
        le=2_147_483_647,
    )


# ============================================================
# 2. ÜYELİK YANITI
# ============================================================

class TeamMemberRead(BaseModel):
    """
    Üyeliği, kullanıcının dışarıya açılabilir bilgileriyle döndürür.

    UserRead kullanıldığı için parola özeti yanıta dahil edilmez.
    """

    team_id: int
    user: UserRead
    created_at: datetime