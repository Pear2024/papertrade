"""Add phase / position / exit_reason for ENTRY→HOLD→EXIT story.

Revision ID: 0004_phase_exit_position
Revises: 0003_signal_seq_pnl
Create Date: 2026-08-02 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_phase_exit_position"
down_revision: Union[str, None] = "0003_signal_seq_pnl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coach_signal_events",
        sa.Column("phase", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("position_state", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("exit_kind", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_coach_signal_events_phase", "coach_signal_events", ["phase"])
    op.create_index(
        "ix_coach_signal_events_position_state",
        "coach_signal_events",
        ["position_state"],
    )


def downgrade() -> None:
    op.drop_index("ix_coach_signal_events_position_state", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_phase", table_name="coach_signal_events")
    op.drop_column("coach_signal_events", "exit_reason")
    op.drop_column("coach_signal_events", "exit_kind")
    op.drop_column("coach_signal_events", "position_state")
    op.drop_column("coach_signal_events", "phase")
