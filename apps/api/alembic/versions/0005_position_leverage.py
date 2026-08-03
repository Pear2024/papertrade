"""Add leverage column to positions for paper futures-style sizing.

Revision ID: 0005_position_leverage
Revises: 0004_phase_exit_position
Create Date: 2026-08-03 02:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_position_leverage"
down_revision: Union[str, None] = "0004_phase_exit_position"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column(
            "leverage",
            sa.Numeric(precision=8, scale=2),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("positions", "leverage")
