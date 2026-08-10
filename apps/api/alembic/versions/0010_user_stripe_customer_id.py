"""Store Stripe customer id on users for Customer Portal + webhooks.

Revision ID: 0010_user_stripe_customer_id
Revises: 0009_user_data_isolation
Create Date: 2026-08-10 05:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_user_stripe_customer_id"
down_revision: Union[str, None] = "0009_user_data_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")
