"""Store immutable BUY entry experiment snapshots.

Revision ID: 0007_entry_filter_snapshots
Revises: 0006_coach_decision_audit
Create Date: 2026-08-08 11:45:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_entry_filter_snapshots"
down_revision: Union[str, None] = "0006_coach_decision_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("coach_signal_events", sa.Column("filter_set_id", sa.String(length=255), nullable=True))
    op.add_column("coach_signal_events", sa.Column("filter_snapshot", sa.Text(), nullable=True))
    op.create_index("ix_coach_signal_events_filter_set_id", "coach_signal_events", ["filter_set_id"])


def downgrade() -> None:
    op.drop_index("ix_coach_signal_events_filter_set_id", table_name="coach_signal_events")
    op.drop_column("coach_signal_events", "filter_snapshot")
    op.drop_column("coach_signal_events", "filter_set_id")
