"""Position endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.money import position_side_from_qty, to_decimal
from app.models import Asset, Position, User
from app.schemas.portfolio import PositionExitsUpdate, PositionResponse
from app.services import trading as trading_service
from app.services.prices import get_price_quote
from app.services.trading import apply_position_mark, get_paper_account_for_user

router = APIRouter(prefix="/positions", tags=["positions"])


def _to_response(db, position: Position, account_id: int) -> PositionResponse:
    side = position_side_from_qty(position.quantity) or "flat"
    order = None
    if side in {"long", "short"}:
        order = trading_service.latest_entry_order(db, account_id, position.asset_id, side)
        if order is None and side == "long":
            order = trading_service.latest_filled_buy_order(db, account_id, position.asset_id)
    qty = to_decimal(position.quantity)
    return PositionResponse(
        id=position.id,
        symbol=position.asset.symbol,
        quantity=position.quantity,
        average_entry_price=position.average_entry_price,
        current_price=position.current_price,
        market_value=position.market_value,
        unrealized_pnl=position.unrealized_pnl,
        updated_at=position.updated_at,
        stop_loss_price=order.stop_loss_price if order else None,
        take_profit_price=order.take_profit_price if order else None,
        exit_plan_order_id=order.id if order else None,
        side=side,
        abs_quantity=abs(qty),
        leverage=getattr(position, "leverage", None) or 1,
    )


@router.get("", response_model=list[PositionResponse])
def list_positions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PositionResponse]:
    account = get_paper_account_for_user(db, current_user)
    positions = db.scalars(
        select(Position)
        .options(joinedload(Position.asset))
        .where(Position.trading_account_id == account.id)
        .order_by(Position.id.asc())
    ).all()
    return [_to_response(db, p, account.id) for p in positions]


@router.get("/{symbol}", response_model=PositionResponse)
async def get_position(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionResponse:
    account = get_paper_account_for_user(db, current_user)
    position = db.scalar(
        select(Position)
        .options(joinedload(Position.asset))
        .join(Asset, Asset.id == Position.asset_id)
        .where(
            Position.trading_account_id == account.id,
            Asset.symbol == symbol.upper(),
        )
    )
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No position for {symbol.upper()}",
        )
    # Keep unrealized P/L live (Desk polls this endpoint).
    quote = await get_price_quote(db, symbol.upper())
    apply_position_mark(position, quote.price)
    db.commit()
    db.refresh(position)
    return _to_response(db, position, account.id)


@router.patch("/{symbol}/exits", response_model=PositionResponse)
def update_position_exits(
    symbol: str,
    body: PositionExitsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PositionResponse:
    position, _order = trading_service.update_position_exits(
        db,
        current_user,
        symbol,
        body.stop_loss_price,
        body.take_profit_price,
    )
    account = get_paper_account_for_user(db, current_user)
    # Reload with asset for response
    position = db.scalar(
        select(Position)
        .options(joinedload(Position.asset))
        .where(Position.id == position.id)
    )
    assert position is not None
    return _to_response(db, position, account.id)
