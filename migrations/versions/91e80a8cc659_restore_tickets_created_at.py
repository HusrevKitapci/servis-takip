"""restore tickets created_at

Revision ID: 91e80a8cc659
Revises: 4fc9f7a9e50d
Create Date: 2026-10-04 20:55:45.624807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91e80a8cc659'
down_revision: Union[str, Sequence[str], None] = '4fc9f7a9e50d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """
    Talebin oluşturulma zamanı sütununu yeniden ekler.

    Mevcut kayıtlara migration'ın uygulandığı zaman atanır.
    Bu, eski kayıtların özgün oluşturulma zamanını geri getirmez.
    """

    op.add_column(
        "tickets",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    """Bu migration geri alınırsa eklenen sütunu kaldırır."""

    op.drop_column(
        "tickets",
        "created_at",
    )