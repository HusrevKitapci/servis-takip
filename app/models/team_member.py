# ============================================================
# İÇE AKTARMALAR
# ============================================================

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# ============================================================
# EKİP ÜYELİĞİ MODELİ
# ============================================================

class TeamMember(Base):
    """
    Bir kullanıcı ile bir ekip arasındaki üyelik ilişkisini saklar.

    Kullanıcının adı veya ekibin adı burada tekrarlanmaz.
    İlgili kayıtları kimlikleri üzerinden ilişkilendiririz.
    """

    __tablename__ = "team_members"

    __table_args__ = (
        # Aynı ekip-kullanıcı çifti yalnızca bir kez bulunabilir.
        PrimaryKeyConstraint(
            "team_id",
            "user_id",
            name="pk_team_members",
        ),

        # Kullanıcının bağlı olduğu ekipleri ararken kullanılabilir.
        Index("ix_team_members_user_id", "user_id"),
    )

    # --------------------------------------------------------
    # 1. İlişkinin iki tarafı
    # --------------------------------------------------------

    team_id: Mapped[int] = mapped_column(
        ForeignKey(
            "teams.id",
            name="fk_team_members_team_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_team_members_user_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    # --------------------------------------------------------
    # 2. Üyeliğin oluşturulma zamanı
    # --------------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )