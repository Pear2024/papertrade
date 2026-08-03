"""Development seed data: assets, demo user, sample trades/journals."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal, check_database_connection, engine
from app.core.assets_catalog import seed_rows
from app.core.security import hash_password
from app.models import (
    Asset,
    AssetType,
    EmotionalState,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PriceSnapshot,
    PriceSource,
    Trade,
    TradingAccount,
    TradingJournal,
    User,
)
from app.services.auth import create_paper_account_for_user

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "Demo1234!"
DEMO_DISPLAY_NAME = "Demo Trader"

ASSETS = seed_rows()


def seed_assets(db: Session) -> dict[str, Asset]:
    by_symbol: dict[str, Asset] = {}
    for item in ASSETS:
        asset = db.scalar(select(Asset).where(Asset.symbol == item["symbol"]))
        if asset is None:
            asset = Asset(
                symbol=item["symbol"],
                name=item["name"],
                asset_type=AssetType.crypto,
                price_precision=item["price_precision"],
                quantity_precision=item["quantity_precision"],
                is_active=True,
            )
            db.add(asset)
            db.flush()
            db.add(
                PriceSnapshot(
                    asset_id=asset.id,
                    price=item["seed_price"],
                    source=PriceSource.manual,
                )
            )
        by_symbol[item["symbol"]] = asset
    return by_symbol


def seed_demo_user(db: Session, assets: dict[str, Asset]) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name=DEMO_DISPLAY_NAME,
        )
        db.add(user)
        db.flush()
        account = create_paper_account_for_user(db, user, account_name="Demo Paper")
        _seed_sample_activity(db, user, account, assets)
    return user


def _seed_sample_activity(
    db: Session,
    user: User,
    account: TradingAccount,
    assets: dict[str, Asset],
) -> None:
    """Small sample history for UI/demo — development only."""
    btc = assets["BTC"]
    eth = assets["ETH"]

    # Sample filled BUY BTC (~$2 notional for a tiny demo fill)
    buy_qty = Decimal("0.00003000")
    buy_price = Decimal("65000.00")
    buy_gross = (buy_qty * buy_price).quantize(Decimal("0.00000001"))
    buy_fee = (buy_gross * Decimal("0.001")).quantize(Decimal("0.00000001"))
    buy_net = buy_gross + buy_fee

    if account.cash_balance < buy_net:
        return

    buy_order = Order(
        trading_account_id=account.id,
        asset_id=btc.id,
        side=OrderSide.buy,
        order_type=OrderType.market,
        status=OrderStatus.filled,
        requested_quantity=buy_qty,
        filled_quantity=buy_qty,
        requested_price=buy_price,
        filled_price=buy_price,
        stop_loss_price=Decimal("60000.00"),
        take_profit_price=Decimal("70000.00"),
        fee_amount=buy_fee,
    )
    db.add(buy_order)
    db.flush()

    db.add(
        Trade(
            order_id=buy_order.id,
            trading_account_id=account.id,
            asset_id=btc.id,
            side=OrderSide.buy,
            quantity=buy_qty,
            price=buy_price,
            gross_amount=buy_gross,
            fee_amount=buy_fee,
            net_amount=buy_net,
            realized_pnl=Decimal("0"),
        )
    )

    account.cash_balance = account.cash_balance - buy_net
    db.add(
        Position(
            trading_account_id=account.id,
            asset_id=btc.id,
            quantity=buy_qty,
            average_entry_price=buy_price,
            current_price=buy_price,
            market_value=buy_gross,
            unrealized_pnl=Decimal("0"),
        )
    )
    db.add(
        TradingJournal(
            user_id=user.id,
            trading_account_id=account.id,
            order_id=buy_order.id,
            asset_id=btc.id,
            setup_name="Breakout",
            entry_reason="Practice entry near support on paper account",
            emotional_state=EmotionalState.calm,
            confidence_score=4,
            followed_plan=True,
            lesson_learned="Wrote plan before clicking Buy",
        )
    )

    # Sample rejected-style journal-only lesson via a second filled micro ETH buy
    eth_qty = Decimal("0.00050000")
    eth_price = Decimal("3500.00")
    eth_gross = (eth_qty * eth_price).quantize(Decimal("0.00000001"))
    eth_fee = (eth_gross * Decimal("0.001")).quantize(Decimal("0.00000001"))
    eth_net = eth_gross + eth_fee
    if account.cash_balance < eth_net:
        return

    eth_order = Order(
        trading_account_id=account.id,
        asset_id=eth.id,
        side=OrderSide.buy,
        order_type=OrderType.market,
        status=OrderStatus.filled,
        requested_quantity=eth_qty,
        filled_quantity=eth_qty,
        filled_price=eth_price,
        stop_loss_price=Decimal("3200.00"),
        fee_amount=eth_fee,
    )
    db.add(eth_order)
    db.flush()
    db.add(
        Trade(
            order_id=eth_order.id,
            trading_account_id=account.id,
            asset_id=eth.id,
            side=OrderSide.buy,
            quantity=eth_qty,
            price=eth_price,
            gross_amount=eth_gross,
            fee_amount=eth_fee,
            net_amount=eth_net,
            realized_pnl=Decimal("0"),
        )
    )
    account.cash_balance = account.cash_balance - eth_net
    db.add(
        Position(
            trading_account_id=account.id,
            asset_id=eth.id,
            quantity=eth_qty,
            average_entry_price=eth_price,
            current_price=eth_price,
            market_value=eth_gross,
            unrealized_pnl=Decimal("0"),
        )
    )
    db.add(
        TradingJournal(
            user_id=user.id,
            trading_account_id=account.id,
            order_id=eth_order.id,
            asset_id=eth.id,
            setup_name="FOMO",
            entry_reason="Entered quickly without waiting for confirmation",
            emotional_state=EmotionalState.impatient,
            confidence_score=2,
            followed_plan=False,
            lesson_learned="Impatience often leads to weaker entries",
        )
    )


def run_seed() -> None:
    settings = get_settings()
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise RuntimeError("Seed is allowed only in development-like environments")

    if not check_database_connection():
        raise RuntimeError("Database is not reachable — start MySQL and check DATABASE_URL")

    db = SessionLocal()
    try:
        assets = seed_assets(db)
        seed_demo_user(db, assets)
        db.commit()
        print("Seed complete.")
        print(f"  Assets: {', '.join(ASSETS[i]['symbol'] for i in range(len(ASSETS)))}")
        print(f"  Demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print(f"  Starting balance: {settings.paper_starting_balance} USD (paper)")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    run_seed()
