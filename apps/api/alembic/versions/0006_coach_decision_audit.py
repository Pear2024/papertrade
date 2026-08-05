"""Add coach_decision_audits for per-bar model decision persistence.

Revision ID: 0006_coach_decision_audit
Revises: 0005_position_leverage
Create Date: 2026-08-04 17:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_coach_decision_audit"
down_revision: Union[str, None] = "0005_position_leverage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coach_decision_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("brain", sa.String(length=80), nullable=False),
        sa.Column("strategy", sa.String(length=8), nullable=False),
        sa.Column("evaluated_bar_time", sa.Integer(), nullable=False),
        sa.Column("signal", sa.String(length=16), nullable=False),
        sa.Column("signal_candidate", sa.String(length=16), nullable=True),
        sa.Column("phase", sa.String(length=24), nullable=True),
        sa.Column("position_state", sa.String(length=16), nullable=True),
        sa.Column("final_action", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("rf_proba", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("regime", sa.Integer(), nullable=True),
        sa.Column("regime_label", sa.String(length=32), nullable=True),
        sa.Column("reasons_json", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema9", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema21", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("ema_gap_pct", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("take_profit", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("risk_reward", sa.String(length=32), nullable=True),
        sa.Column("auto_action", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("bar_closed", sa.Boolean(), nullable=False),
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
            "strategy",
            name="uq_coach_decision_bar",
        ),
    )
    op.create_index(
        "ix_coach_decision_audits_symbol", "coach_decision_audits", ["symbol"]
    )
    op.create_index(
        "ix_coach_decision_audits_interval", "coach_decision_audits", ["interval"]
    )
    op.create_index(
        "ix_coach_decision_audits_strategy", "coach_decision_audits", ["strategy"]
    )
    op.create_index(
        "ix_coach_decision_audits_evaluated_bar_time",
        "coach_decision_audits",
        ["evaluated_bar_time"],
    )
    op.create_index(
        "ix_coach_decision_audits_final_action",
        "coach_decision_audits",
        ["final_action"],
    )


def downgrade() -> None:
    op.drop_index("ix_coach_decision_audits_final_action", table_name="coach_decision_audits")
    op.drop_index(
        "ix_coach_decision_audits_evaluated_bar_time", table_name="coach_decision_audits"
    )
    op.drop_index("ix_coach_decision_audits_strategy", table_name="coach_decision_audits")
    op.drop_index("ix_coach_decision_audits_interval", table_name="coach_decision_audits")
    op.drop_index("ix_coach_decision_audits_symbol", table_name="coach_decision_audits")
    op.drop_table("coach_decision_audits")
