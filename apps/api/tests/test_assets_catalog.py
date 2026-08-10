"""Catalog symbol normalization + asset seed helpers."""

from decimal import Decimal

from app.core.assets_catalog import normalize_symbol
from app.db.seed import seed_assets
from app.models import Asset
from app.services import prices as price_service
from sqlalchemy.orm import Session


def test_normalize_symbol_aliases() -> None:
    assert normalize_symbol("btc") == "BTC"
    assert normalize_symbol("BTCUSD") == "BTC"
    assert normalize_symbol("XBTUSD") == "BTC"
    assert normalize_symbol("BTC/USD") == "BTC"
    assert normalize_symbol("BTCUSDT") == "BTC"
    assert normalize_symbol("XBT") == "BTC"
    assert normalize_symbol("ETHUSDT") == "ETH"
    assert normalize_symbol("sol/usd") == "SOL"


def test_require_asset_resolves_alias(db_session: Session, seeded_assets: dict[str, Asset]) -> None:
    _ = seeded_assets
    asset = price_service.require_asset(db_session, "XBTUSD")
    assert asset.symbol == "BTC"
    asset2 = price_service.require_asset(db_session, "BTC/USD")
    assert asset2.symbol == "BTC"


def test_seed_assets_idempotent(db_session: Session) -> None:
    first = seed_assets(db_session)
    db_session.commit()
    assert "BTC" in first
    assert db_session.query(Asset).count() >= 3

    second = seed_assets(db_session)
    db_session.commit()
    assert second["BTC"].id == first["BTC"].id
    assert second["BTC"].is_active is True
    # Seed price snapshot should exist for new inserts only; re-seed must not duplicate assets.
    assert db_session.query(Asset).filter(Asset.symbol == "BTC").count() == 1


def test_seed_assets_activates_existing(db_session: Session) -> None:
    from app.models import AssetType

    orphan = Asset(
        symbol="BTC",
        name="Old",
        asset_type=AssetType.crypto,
        price_precision=2,
        quantity_precision=8,
        is_active=False,
    )
    db_session.add(orphan)
    db_session.commit()

    seeded = seed_assets(db_session)
    db_session.commit()
    assert seeded["BTC"].is_active is True
    assert seeded["BTC"].name == "Bitcoin"
    assert seeded["BTC"].id == orphan.id
