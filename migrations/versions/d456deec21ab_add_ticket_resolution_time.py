"""add ticket resolution time

Revision ID: d456deec21ab
Revises: 91e80a8cc659
Create Date: 2026-10-04 21:23:35.962928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd456deec21ab'
down_revision: Union[str, Sequence[str], None] = '91e80a8cc659'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Çözüm zamanı alanını ve durumla tutarlılık kuralını ekler."""

    op.add_column(
        "tickets",
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        "ck_tickets_resolution_time",
        "tickets",
        "(status = 'RESOLVED' AND resolved_at IS NOT NULL) "
        "OR "
        "(status <> 'RESOLVED' AND resolved_at IS NULL)",
    )


def downgrade() -> None:
    """Önce kısıtı, ardından kısıtın kullandığı sütunu kaldırır."""

    op.drop_constraint(
        "ck_tickets_resolution_time",
        "tickets",
        type_="check",
    )

    op.drop_column(
        "tickets",
        "resolved_at",
    )