"""DayTradeCrypto coach endpoints (rule-based AI brain, paper only).

Default auto-tick uses locked Version A.
Parallel A/B paper uses /coach/ab-tick and /coach/ab-compare.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.money import position_side_from_qty, to_decimal
from app.models import Asset, Position, User
from app.schemas.coach import (
    CoachAbCompareResponse,
    CoachAbTickResponse,
    CoachAutoTickResponse,
    CoachDecisionAuditItem,
    CoachDecisionAuditResponse,
    CoachPromptResponse,
    CoachSignalHistoryItem,
    CoachSignalHistoryResponse,
    CoachSignalResponse,
    CoachStatsResponse,
    CoachTradeJournalItem,
    CoachTradeJournalResponse,
    HoldPanelResponse,
    MetaAlphaGateResponse,
)
from app.services import coach as coach_service
from app.services import coach_auto
from app.services.coach_brain import DEFAULT_AUTO_USD
from app.services.coach_decision_audit import (
    audit_to_dict,
    list_decision_audits,
    persist_decision_audit,
)
from app.services.coach_meta_enrich import enrich_verdict_meta_alpha
from app.services.coach_observability import (
    gate_to_public,
    hold_pnl,
    map_final_action,
    tp_progress_pct,
)
from app.services.coach_signal_store import list_coach_signals, persist_coach_signal
from app.services.coach_trade_journal import build_trade_journal
from app.services.trading import (
    get_paper_account_for_user,
    latest_entry_order,
    latest_filled_buy_order,
)

router = APIRouter(prefix="/coach", tags=["coach"])


def _hold_panel_from_position(
    *,
    position: Position | None,
    entry_order,
    mark: Decimal | None,
    risk_reward: str | None,
) -> HoldPanelResponse | None:
    if position is None or mark is None:
        return None
    side = position_side_from_qty(position.quantity)
    if side not in {"long", "short"}:
        return None
    entry = to_decimal(position.average_entry_price)
    current = to_decimal(mark)
    pnl_pct, pnl_usd = hold_pnl(
        side=side.upper(),
        entry=entry,
        current=current,
        quantity=position.quantity,
    )
    sl = None
    tp = None
    entry_time = None
    if entry_order is not None:
        if entry_order.stop_loss_price is not None:
            sl = str(entry_order.stop_loss_price)
        if entry_order.take_profit_price is not None:
            tp = str(entry_order.take_profit_price)
        entry_time = entry_order.filled_at
    progress = tp_progress_pct(
        side=side.upper(),
        entry=entry,
        current=current,
        take_profit=entry_order.take_profit_price if entry_order else None,
    )
    time_sec = None
    if entry_time is not None:
        et = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
        time_sec = max(0, int((datetime.now(timezone.utc) - et).total_seconds()))
    return HoldPanelResponse(
        side=side.upper(),
        entry_price=str(entry),
        current_price=str(current),
        pnl_pct=round(pnl_pct, 4),
        pnl_usd=round(pnl_usd, 4) if pnl_usd is not None else None,
        time_in_trade_sec=time_sec,
        stop_loss=sl,
        take_profit=tp,
        risk_reward=risk_reward,
        tp_progress=round(progress, 2) if progress is not None else None,
    )


def _to_response(
    v: coach_service.CoachVerdict,
    *,
    meta_gate: dict | None = None,
    hold: HoldPanelResponse | None = None,
) -> CoachSignalResponse:
    public_gate = gate_to_public(meta_gate) if meta_gate else None
    if public_gate is None and (
        v.rf_proba is not None or v.regime is not None or v.meta_alpha_reason
    ):
        public_gate = {
            "take": 1 if v.meta_alpha_take else 0,
            "proba": v.rf_proba,
            "regime": v.regime,
            "regime_label": v.regime_label,
            "reason": v.meta_alpha_reason or "",
            "warm": True,
        }
    pos = getattr(v, "position", None) or "NEUTRAL"
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
        position=pos,
        trend=getattr(v, "trend", None) or "NONE",
        entry=getattr(v, "entry", None) or "NONE",
        exit=getattr(v, "exit", None) or "NONE",
        exit_reason=getattr(v, "exit_reason", None),
        reasons=list(getattr(v, "reasons", None) or []),
        rf_proba=getattr(v, "rf_proba", None),
        regime=getattr(v, "regime", None),
        regime_label=getattr(v, "regime_label", None),
        signal_candidate=getattr(v, "signal_candidate", None),
        ema_gap_pct=getattr(v, "ema_gap_pct", None),
        entry_price=str(v.entry_price) if getattr(v, "entry_price", None) is not None else (
            str(v.price)
            if (getattr(v, "phase", None) or "").startswith("ENTRY")
            else None
        ),
        confidence_source=getattr(v, "confidence_source", None) or "primary",
        primary_confidence=getattr(v, "primary_confidence", None),
        meta_alpha=MetaAlphaGateResponse(**public_gate) if public_gate else None,
        tp_progress=hold.tp_progress if hold else getattr(v, "tp_progress", None),
        position_state=getattr(v, "position_state", None) or pos,
        hold=hold,
    )


def _tick_response(raw: dict) -> CoachAutoTickResponse:
    meta = raw.get("meta_alpha")
    public = gate_to_public(meta) if isinstance(meta, dict) else None
    hold_raw = raw.get("hold")
    hold = HoldPanelResponse(**hold_raw) if isinstance(hold_raw, dict) else None
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
        reasons=list(raw.get("reasons") or []),
        rf_proba=raw.get("rf_proba"),
        regime=raw.get("regime"),
        regime_label=raw.get("regime_label"),
        entry_price=raw.get("entry_price"),
        confidence_source=raw.get("confidence_source"),
        primary_confidence=raw.get("primary_confidence"),
        meta_alpha=MetaAlphaGateResponse(**public) if public else None,
        tp_progress=raw.get("tp_progress"),
        hold=hold,
        ema_gap_pct=raw.get("ema_gap_pct"),
        signal_candidate=raw.get("signal_candidate"),
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
    verdict = await coach_service.evaluate_daytrade_signal(
        db,
        symbol,
        interval,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        ema_sep_pct=ema_sep_pct,
    )
    verdict, gate = await enrich_verdict_meta_alpha(db, verdict)
    persist_coach_signal(db, verdict)

    hold: HoldPanelResponse | None = None
    try:
        account = get_paper_account_for_user(db, current_user)
        asset = db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
        if asset is not None:
            position = db.scalar(
                select(Position)
                .options(joinedload(Position.asset))
                .where(
                    Position.trading_account_id == account.id,
                    Position.asset_id == asset.id,
                )
            )
            side = position_side_from_qty(position.quantity) if position else None
            entry_order = None
            if position is not None and side in {"long", "short"}:
                entry_order = latest_entry_order(db, account.id, asset.id, side)
                if entry_order is None and side == "long":
                    entry_order = latest_filled_buy_order(db, account.id, asset.id)
            mark = to_decimal(position.current_price) if position else to_decimal(verdict.price)
            hold = _hold_panel_from_position(
                position=position,
                entry_order=entry_order,
                mark=mark,
                risk_reward=verdict.risk_reward,
            )
    except Exception:  # noqa: BLE001 — hold panel is best-effort
        hold = None

    persist_decision_audit(
        db,
        verdict,
        final_action=map_final_action(phase=verdict.phase or "NONE", signal=verdict.signal),
        rf_proba=verdict.rf_proba,
        regime=verdict.regime,
        reasons=verdict.reasons,
        signal_candidate=verdict.signal_candidate,
        strategy="A",
    )
    return _to_response(verdict, meta_gate=gate, hold=hold)


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


@router.get("/decisions", response_model=CoachDecisionAuditResponse)
def coach_decision_audits(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
    strategy: str = Query(default="A", pattern="^[ABab]$"),
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachDecisionAuditResponse:
    """Per closed-bar model decisions (EMA, RF, regime, final action, rejection)."""
    _ = current_user
    rows = list_decision_audits(
        db,
        symbol=symbol,
        interval=interval,
        strategy=strategy.upper(),
        limit=limit,
    )
    items = [CoachDecisionAuditItem(**audit_to_dict(r)) for r in rows]
    return CoachDecisionAuditResponse(count=len(items), items=items)


@router.get("/trade-journal", response_model=CoachTradeJournalResponse)
def coach_trade_journal(
    symbol: str | None = Query(default=None),
    strategy: str = Query(default="A", pattern="^[ABab]$"),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CoachTradeJournalResponse:
    """Completed paper trades for the Trade Journal panel."""
    items_raw = build_trade_journal(
        db,
        current_user,
        symbol=symbol,
        strategy=strategy.upper(),
        limit=limit,
    )
    items = [CoachTradeJournalItem(**row) for row in items_raw]
    return CoachTradeJournalResponse(count=len(items), items=items)


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
