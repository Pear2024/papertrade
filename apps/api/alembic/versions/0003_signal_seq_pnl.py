"""Add seq/pnl analysis columns to coach_signal_events.

Revision ID: 0003_signal_seq_pnl
Revises: 0002_coach_signal_events
Create Date: 2026-08-02 12:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_signal_seq_pnl"
down_revision: Union[str, None] = "0002_coach_signal_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coach_signal_events",
        sa.Column("alert_side", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("seq_from_entry", sa.Integer(), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("entry_price", sa.Numeric(precision=20, scale=8), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("pnl_pct_vs_entry", sa.Numeric(precision=12, scale=6), nullable=True),
    )
    op.add_column(
        "coach_signal_events",
        sa.Column("still_profit", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "ix_coach_signal_events_alert_side", "coach_signal_events", ["alert_side"]
    )
    op.create_index(
        "ix_coach_signal_events_seq_from_entry",
        "coach_signal_events",
        ["seq_from_entry"],
    )


def downgrade() -> None:
    op.drop_index("ix_coach_signal_events_seq_from_entry", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_alert_side", table_name="coach_signal_events")
    op.drop_column("coach_signal_events", "still_profit")
    op.drop_column("coach_signal_events", "pnl_pct_vs_entry")
    op.drop_column("coach_signal_events", "entry_price")
    op.drop_column("coach_signal_events", "seq_from_entry")
    op.drop_column("coach_signal_events", "alert_side")
