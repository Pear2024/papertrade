"""Asset endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.market import AssetResponse
from app.services import prices as price_service

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetResponse])
def list_assets(db: Session = Depends(get_db)) -> list[AssetResponse]:
    assets = price_service.get_active_assets(db)
    return [
        AssetResponse(
            id=a.id,
            symbol=a.symbol,
            name=a.name,
            asset_type=a.asset_type.value,
            price_precision=a.price_precision,
            quantity_precision=a.quantity_precision,
            is_active=a.is_active,
        )
        for a in assets
    ]


@router.get("/{symbol}", response_model=AssetResponse)
def get_asset(symbol: str, db: Session = Depends(get_db)) -> AssetResponse:
    asset = price_service.require_asset(db, symbol)
    return AssetResponse(
        id=asset.id,
        symbol=asset.symbol,
        name=asset.name,
        asset_type=asset.asset_type.value,
        price_precision=asset.price_precision,
        quantity_precision=asset.quantity_precision,
        is_active=asset.is_active,
    )
