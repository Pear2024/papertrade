"""Per-user Hypothesis Lab, coach prefs, and signal ownership.

Revision ID: 0009_user_data_isolation
Revises: 0008_user_subscription_plan
Create Date: 2026-08-10 04:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_user_data_isolation"
down_revision: Union[str, None] = "0008_user_subscription_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lab_hypotheses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("natural_language_prompt", sa.Text(), nullable=False),
        sa.Column("structured_rules_json", sa.Text(), nullable=False),
        sa.Column("parser", sa.String(length=32), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paper_profile_json", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_lab_hypotheses_public_id", "lab_hypotheses", ["public_id"])
    op.create_index("ix_lab_hypotheses_user_id", "lab_hypotheses", ["user_id"])

    op.create_table(
        "lab_backtests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=40), nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hypothesis_id"], ["lab_hypotheses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
    )
    op.create_index("ix_lab_backtests_public_id", "lab_backtests", ["public_id"])
    op.create_index("ix_lab_backtests_hypothesis_id", "lab_backtests", ["hypothesis_id"])
    op.create_index("ix_lab_backtests_ran_at", "lab_backtests", ["ran_at"])

    op.create_table(
        "user_coach_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=False),
        sa.Column("auto_session_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.add_column(
        "coach_signal_events",
        sa.Column("user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_coach_signal_events_user_id", "coach_signal_events", ["user_id"])
    op.create_foreign_key(
        "fk_coach_signal_events_user_id",
        "coach_signal_events",
        "users",
        ["user_id"],
        ["id"],
    )
    op.drop_constraint("uq_coach_signal_bar", "coach_signal_events", type_="unique")
    op.create_unique_constraint(
        "uq_coach_signal_bar_user",
        "coach_signal_events",
        ["user_id", "symbol", "interval", "evaluated_bar_time", "brain"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_coach_signal_bar_user", "coach_signal_events", type_="unique")
    op.create_unique_constraint(
        "uq_coach_signal_bar",
        "coach_signal_events",
        ["symbol", "interval", "evaluated_bar_time", "brain"],
    )
    op.drop_constraint("fk_coach_signal_events_user_id", "coach_signal_events", type_="foreignkey")
    op.drop_index("ix_coach_signal_events_user_id", table_name="coach_signal_events")
    op.drop_column("coach_signal_events", "user_id")

    op.drop_table("user_coach_settings")
    op.drop_index("ix_lab_backtests_ran_at", table_name="lab_backtests")
    op.drop_index("ix_lab_backtests_hypothesis_id", table_name="lab_backtests")
    op.drop_index("ix_lab_backtests_public_id", table_name="lab_backtests")
    op.drop_table("lab_backtests")
    op.drop_index("ix_lab_hypotheses_user_id", table_name="lab_hypotheses")
    op.drop_index("ix_lab_hypotheses_public_id", table_name="lab_hypotheses")
    op.drop_table("lab_hypotheses")
