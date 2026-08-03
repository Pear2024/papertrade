"""Initial schema for Paper Crypto Coach (Phase 2).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-31 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
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
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("asset_type", sa.Enum("crypto", name="assettype"), nullable=False),
        sa.Column("price_precision", sa.Integer(), nullable=False),
        sa.Column("quantity_precision", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
    )
    op.create_index(op.f("ix_assets_symbol"), "assets", ["symbol"], unique=True)

    op.create_table(
        "trading_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=False),
        sa.Column("account_mode", sa.Enum("paper", name="accountmode"), nullable=False),
        sa.Column("starting_balance", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("cash_balance", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
    )
    op.create_index(
        op.f("ix_trading_accounts_user_id"), "trading_accounts", ["user_id"], unique=False
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column(
            "source",
            sa.Enum("public_api", "trade_fill", "manual", name="pricesource"),
            nullable=False,
        ),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_price_snapshots_asset_id"), "price_snapshots", ["asset_id"], unique=False
    )
    op.create_index(
        op.f("ix_price_snapshots_captured_at"),
        "price_snapshots",
        ["captured_at"],
        unique=False,
    )

    op.create_table(
        "account_resets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("previous_balance", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("reset_balance", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "reset_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_account_resets_trading_account_id"),
        "account_resets",
        ["trading_account_id"],
        unique=False,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.Enum("buy", "sell", name="orderside"), nullable=False),
        sa.Column("order_type", sa.Enum("market", name="ordertype"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "filled", "rejected", "cancelled", name="orderstatus"),
            nullable=False,
        ),
        sa.Column("requested_quantity", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("requested_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("filled_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("take_profit_price", sa.Numeric(precision=20, scale=8), nullable=True),
        sa.Column("fee_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_asset_id"), "orders", ["asset_id"], unique=False)
    op.create_index(
        op.f("ix_orders_trading_account_id"), "orders", ["trading_account_id"], unique=False
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("average_entry_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("current_price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("market_value", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trading_account_id", "asset_id", name="uq_position_account_asset"),
    )
    op.create_index(op.f("ix_positions_asset_id"), "positions", ["asset_id"], unique=False)
    op.create_index(
        op.f("ix_positions_trading_account_id"),
        "positions",
        ["trading_account_id"],
        unique=False,
    )

    op.create_table(
        "risk_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("max_risk_percent_per_trade", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("max_daily_loss_percent", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("max_trades_per_day", sa.Integer(), nullable=False),
        sa.Column("require_stop_loss", sa.Boolean(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trading_account_id"),
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.Enum("buy", "sell", name="orderside"), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("price", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("fee_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("net_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trades_asset_id"), "trades", ["asset_id"], unique=False)
    op.create_index(op.f("ix_trades_executed_at"), "trades", ["executed_at"], unique=False)
    op.create_index(op.f("ix_trades_order_id"), "trades", ["order_id"], unique=False)
    op.create_index(
        op.f("ix_trades_trading_account_id"), "trades", ["trading_account_id"], unique=False
    )

    op.create_table(
        "trading_journals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("trading_account_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("setup_name", sa.String(length=120), nullable=True),
        sa.Column("entry_reason", sa.Text(), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column(
            "emotional_state",
            sa.Enum(
                "calm",
                "confident",
                "fearful",
                "greedy",
                "impatient",
                "unsure",
                name="emotionalstate",
            ),
            nullable=True,
        ),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("followed_plan", sa.Boolean(), nullable=True),
        sa.Column("lesson_learned", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["trading_account_id"], ["trading_accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    op.create_index(
        op.f("ix_trading_journals_asset_id"), "trading_journals", ["asset_id"], unique=False
    )
    op.create_index(
        op.f("ix_trading_journals_trading_account_id"),
        "trading_journals",
        ["trading_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trading_journals_user_id"), "trading_journals", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trading_journals_user_id"), table_name="trading_journals")
    op.drop_index(op.f("ix_trading_journals_trading_account_id"), table_name="trading_journals")
    op.drop_index(op.f("ix_trading_journals_asset_id"), table_name="trading_journals")
    op.drop_table("trading_journals")
    op.drop_index(op.f("ix_trades_trading_account_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_order_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_executed_at"), table_name="trades")
    op.drop_index(op.f("ix_trades_asset_id"), table_name="trades")
    op.drop_table("trades")
    op.drop_table("risk_rules")
    op.drop_index(op.f("ix_positions_trading_account_id"), table_name="positions")
    op.drop_index(op.f("ix_positions_asset_id"), table_name="positions")
    op.drop_table("positions")
    op.drop_index(op.f("ix_orders_trading_account_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_asset_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_account_resets_trading_account_id"), table_name="account_resets")
    op.drop_table("account_resets")
    op.drop_index(op.f("ix_price_snapshots_captured_at"), table_name="price_snapshots")
    op.drop_index(op.f("ix_price_snapshots_asset_id"), table_name="price_snapshots")
    op.drop_table("price_snapshots")
    op.drop_index(op.f("ix_trading_accounts_user_id"), table_name="trading_accounts")
    op.drop_table("trading_accounts")
    op.drop_index(op.f("ix_assets_symbol"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
