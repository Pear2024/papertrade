"""Order endpoints — paper market buy/sell."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Order, User
from app.schemas.orders import OrderRequest, OrderResponse, TradePreview
from app.services import trading as trading_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/buy", response_model=OrderResponse, status_code=201)
async def buy(
    payload: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderResponse:
    return await trading_service.execute_buy(db, current_user, payload)


@router.post("/sell", response_model=OrderResponse, status_code=201)
async def sell(
    payload: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderResponse:
    return await trading_service.execute_sell(db, current_user, payload)


@router.post("/buy/preview", response_model=TradePreview)
async def buy_preview(
    payload: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TradePreview:
    return await trading_service.preview_buy(db, current_user, payload)


@router.post("/sell/preview", response_model=TradePreview)
async def sell_preview(
    payload: OrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TradePreview:
    return await trading_service.preview_sell(db, current_user, payload)


@router.get("", response_model=list[OrderResponse])
def list_orders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[OrderResponse]:
    account = trading_service.get_paper_account_for_user(db, current_user)
    orders = db.scalars(
        select(Order)
        .options(joinedload(Order.asset))
        .where(Order.trading_account_id == account.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    return [trading_service.order_to_response(o, o.asset.symbol) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderResponse:
    account = trading_service.get_paper_account_for_user(db, current_user)
    order = db.scalar(
        select(Order)
        .options(joinedload(Order.asset))
        .where(Order.id == order_id, Order.trading_account_id == account.id)
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return trading_service.order_to_response(order, order.asset.symbol)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrderResponse:
    return trading_service.cancel_order(db, current_user, order_id)
