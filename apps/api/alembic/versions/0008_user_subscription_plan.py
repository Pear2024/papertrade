"""Add the minimal server-side subscription entitlement.

Revision ID: 0008_user_subscription_plan
Revises: 0007_entry_filter_snapshots
Create Date: 2026-08-09 06:12:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_user_subscription_plan"
down_revision: Union[str, None] = "0007_entry_filter_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("subscription_plan", sa.String(length=20), nullable=False, server_default="free"),
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_plan")
