"""Trade history endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Trade, User
from app.schemas.portfolio import TradeResponse
from app.services.trading import get_paper_account_for_user

router = APIRouter(prefix="/trades", tags=["trades"])


def _to_response(trade: Trade) -> TradeResponse:
    return TradeResponse(
        id=trade.id,
        order_id=trade.order_id,
        symbol=trade.asset.symbol,
        side=trade.side.value,
        quantity=trade.quantity,
        price=trade.price,
        gross_amount=trade.gross_amount,
        fee_amount=trade.fee_amount,
        net_amount=trade.net_amount,
        realized_pnl=trade.realized_pnl,
        executed_at=trade.executed_at,
    )


@router.get("", response_model=list[TradeResponse])
def list_trades(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TradeResponse]:
    account = get_paper_account_for_user(db, current_user)
    trades = db.scalars(
        select(Trade)
        .options(joinedload(Trade.asset))
        .where(Trade.trading_account_id == account.id)
        .order_by(Trade.executed_at.desc(), Trade.id.desc())
    ).all()
    return [_to_response(t) for t in trades]


@router.get("/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TradeResponse:
    account = get_paper_account_for_user(db, current_user)
    trade = db.scalar(
        select(Trade)
        .options(joinedload(Trade.asset))
        .where(Trade.id == trade_id, Trade.trading_account_id == account.id)
    )
    if trade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return _to_response(trade)
