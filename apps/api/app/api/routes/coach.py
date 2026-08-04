"""DayTradeCrypto coach endpoints (rule-based AI brain, paper only).

Default auto-tick uses locked Version A.
Parallel A/B paper uses /coach/ab-tick and /coach/ab-compare.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.coach import (
    CoachAbCompareResponse,
    CoachAbTickResponse,
    CoachAutoTickResponse,
    CoachPromptResponse,
    CoachSignalHistoryItem,
    CoachSignalHistoryResponse,
    CoachSignalResponse,
    CoachStatsResponse,
)
from app.services import coach as coach_service
from app.services import coach_auto
from app.services.coach_brain import DEFAULT_AUTO_USD
from app.services.coach_signal_store import list_coach_signals, persist_coach_signal

router = APIRouter(prefix="/coach", tags=["coach"])


def _to_response(v: coach_service.CoachVerdict) -> CoachSignalResponse:
    return CoachSignalResponse(
        symbol=v.symbol,
        interval=v.interval,
        signal=v.signal,
        confidence=v.confidence,
        reason=v.reason,
        cofr=v.cofr,
        price=str(v.price),
        ema9=str(v.ema9) if v.ema9 is not None else None,
        ema21=str(v.ema21) if v.ema21 is not None else None,
        volume=str(v.volume) if v.volume is not None else None,
        volume_avg20=str(v.volume_avg20) if v.volume_avg20 is not None else None,
        bar_closed=v.bar_closed,
        stop_loss=str(v.stop_loss) if v.stop_loss is not None else None,
        take_profit=str(v.take_profit) if v.take_profit is not None else None,
        risk_reward=v.risk_reward,
        source=v.source,
        evaluated_bar_time=v.evaluated_bar_time,
        paper_only=True,
        brain=v.brain,
        checklist=[
            {"id": c.id, "label": c.label, "passed": c.passed}
            for c in (v.checklist or [])
        ],
        short_reason=v.short_reason or v.reason,
        phase=getattr(v, "phase", None) or "NONE",
        position=getattr(v, "position", None) or "NEUTRAL",
        trend=getattr(v, "trend", None) or "NONE",
        entry=getattr(v, "entry", None) or "NONE",
        exit=getattr(v, "exit", None) or "NONE",
        exit_reason=getattr(v, "exit_reason", None),
    )


def _tick_response(raw: dict) -> CoachAutoTickResponse:
    return CoachAutoTickResponse(
        paper_only=True,
        action=raw["action"],
        signal=raw["signal"],
        confidence=raw["confidence"],
        reason=raw["reason"],
        cofr=raw["cofr"],
        order_id=raw.get("order_id"),
        stats=CoachStatsResponse(**raw["stats"]),
        strategy=raw.get("strategy") or "A",
        brain=raw.get("brain"),
        account_id=raw.get("account_id"),
        stake_usd=raw.get("stake_usd"),
        stop_loss=raw.get("stop_loss"),
        take_profit=raw.get("take_profit"),
        position_side=raw.get("position_side"),
        logs=list(raw.get("logs") or []),
        trend=raw.get("trend"),
        entry=raw.get("entry"),
        phase=raw.get("phase"),
        exit=raw.get("exit"),
        position_state=raw.get("position_state"),
    )


@router.get("/prompt", response_model=CoachPromptResponse)
def coach_prompt(
    current_user: User = Depends(get_current_user),
) -> CoachPromptResponse:
    _ = current_user
    data = coach_service.get_brain_prompt()
    return CoachPromptResponse(**data)


@router.get("/stats", response_model=CoachStatsResponse)
def coach_stats(
    strategy: str = Query(default="A", pattern="^[ABab]$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachStatsResponse:
    return CoachStatsResponse(
        **coach_auto.paper_performance_stats(
            db, current_user, strategy=strategy.upper()
        )
    )


@router.get("/signal", response_model=CoachSignalResponse)
async def coach_signal(
    symbol: str = Query(default="BTC"),
    interval: str = Query(default="15m"),
    sl_pct: float | None = Query(default=None, gt=0, le=0.5),
    tp_pct: float | None = Query(default=None, gt=0, le=1),
    ema_sep_pct: float | None = Query(default=None, gt=0, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachSignalResponse:
    _ = current_user
    verdict = await coach_service.evaluate_daytrade_signal(
        db,
        symbol,
        interval,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        ema_sep_pct=ema_sep_pct,
    )
    persist_coach_signal(db, verdict)
    # Chat alerts only from auto-tick (ENTRY once) — avoid /signal poll spam.
    return _to_response(verdict)


@router.get("/signals/history", response_model=CoachSignalHistoryResponse)
def coach_signal_history(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
    entry_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachSignalHistoryResponse:
    """Stored ENTRY / TREND / signal rows for paper hypothesis analysis."""
    _ = current_user
    rows = list_coach_signals(
        db,
        symbol=symbol,
        interval=interval,
        entry_only=entry_only,
        limit=limit,
    )
    items = [
        CoachSignalHistoryItem(
            id=r.id,
            symbol=r.symbol,
            interval=r.interval,
            brain=r.brain,
            signal=r.signal,
            entry=r.entry,
            trend=r.trend,
            phase=getattr(r, "phase", None),
            position_state=getattr(r, "position_state", None),
            exit_kind=getattr(r, "exit_kind", None),
            exit_reason=getattr(r, "exit_reason", None),
            alert_side=r.alert_side,
            seq_from_entry=r.seq_from_entry,
            entry_price=str(r.entry_price) if r.entry_price is not None else None,
            pnl_pct_vs_entry=str(r.pnl_pct_vs_entry) if r.pnl_pct_vs_entry is not None else None,
            still_profit=r.still_profit,
            confidence=r.confidence,
            reason=r.reason,
            short_reason=r.short_reason,
            cofr=r.cofr,
            price=str(r.price),
            ema9=str(r.ema9) if r.ema9 is not None else None,
            ema21=str(r.ema21) if r.ema21 is not None else None,
            stop_loss=str(r.stop_loss) if r.stop_loss is not None else None,
            take_profit=str(r.take_profit) if r.take_profit is not None else None,
            risk_reward=r.risk_reward,
            source=r.source,
            bar_closed=r.bar_closed,
            evaluated_bar_time=r.evaluated_bar_time,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return CoachSignalHistoryResponse(count=len(items), items=items)


@router.post("/auto-tick", response_model=CoachAutoTickResponse)
async def coach_auto_tick(
    symbol: str = Query(default="BTC"),
    interval: str = Query(default="15m"),
    usd_amount: float = Query(default=float(DEFAULT_AUTO_USD), ge=0.5, le=5000),
    leverage: float = Query(default=5, ge=1, le=50),
    sl_pct: float | None = Query(default=None, gt=0, le=0.5),
    tp_pct: float | None = Query(default=None, gt=0, le=1),
    tp_usd: float | None = Query(
        default=None,
        ge=0,
        le=1_000_000,
        description="Absolute USD take-profit (unrealized). Default 70 when omitted; 0 disables.",
    ),
    ema_sep_pct: float | None = Query(default=None, gt=0, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachAutoTickResponse:
    """Main locked Version A paper tick only."""
    raw = await coach_auto.run_auto_tick(
        db,
        current_user,
        symbol,
        interval,
        usd_amount=Decimal(str(usd_amount)),
        strategy="A",
        notify=True,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        ema_sep_pct=ema_sep_pct,
        leverage=Decimal(str(leverage)),
        tp_usd=tp_usd,
    )
    return _tick_response(raw)


@router.post("/ab-tick", response_model=CoachAbTickResponse)
async def coach_ab_tick(
    symbol: str = Query(default="BTC"),
    interval: str = Query(default="15m"),
    usd_amount: float = Query(default=float(DEFAULT_AUTO_USD), ge=0.5, le=5000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachAbTickResponse:
    """Simultaneous paper tick for locked A and experiment B (same market time)."""
    raw = await coach_auto.run_ab_auto_tick(
        db,
        current_user,
        symbol,
        interval,
        usd_amount=Decimal(str(usd_amount)),
    )
    return CoachAbTickResponse(
        paper_only=True,
        symbol=raw["symbol"],
        interval=raw["interval"],
        market_time_shared=True,
        main_strategy="A",
        note=raw["note"],
        a=_tick_response(raw["a"]),
        b=_tick_response(raw["b"]),
    )


@router.get("/ab-compare", response_model=CoachAbCompareResponse)
def coach_ab_compare(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachAbCompareResponse:
    raw = coach_auto.compare_ab_paper_stats(db, current_user)
    return CoachAbCompareResponse(
        paper_only=True,
        main_strategy="A",
        a=CoachStatsResponse(**raw["a"]),
        b=CoachStatsResponse(**raw["b"]),
        b_better=raw["b_better"],
        score_b_better_metrics=raw["score_b_better_metrics"],
        promotion=raw["promotion"],
        conclusion=raw["conclusion"],
    )
