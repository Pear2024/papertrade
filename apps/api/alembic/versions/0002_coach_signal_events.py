"""Add coach_signal_events for ENTRY/TREND history analysis.

Revision ID: 0002_coach_signal_events
Revises: 0001_initial_schema
Create Date: 2026-08-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_coach_signal_events"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_signal_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("brain", sa.String(length=80), nullable=False),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("entry", sa.String(length=16), nullable=False),
        sa.Column("trend", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("short_reason", sa.String(length=500), nullable=True),
        sa.Column("cofr", sa.String(length=255), nullable=True),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("ema9", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema21", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("take_profit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("risk_reward", sa.String(length=32), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("bar_closed", sa.Boolean(), nullable=False),
        sa.Column("evaluated_bar_time", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "interval",
            "evaluated_bar_time",
            "brain",
            name="uq_coach_signal_bar",
        ),
    )
    op.create_index("ix_coach_signal_events_symbol", "coach_signal_events", ["symbol"])
    op.create_index("ix_coach_signal_events_interval", "coach_signal_events", ["interval"])
    op.create_index("ix_coach_signal_events_signal", "coach_signal_events", ["signal"])
    op.create_index("ix_coach_signal_events_entry", "coach_signal_events", ["entry"])
    op.create_index("ix_coach_signal_events_trend", "coach_signal_events", ["trend"])
    op.create_index(
        "ix_coach_signal_events_evaluated_bar_time",
        "coach_signal_events",
        ["evaluated_bar_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_coach_signal_events_evaluated_bar_time", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_trend", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_entry", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_signal", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_interval", table_name="coach_signal_events")
    op.drop_index("ix_coach_signal_events_symbol", table_name="coach_signal_events")
    op.drop_table("coach_signal_events")
