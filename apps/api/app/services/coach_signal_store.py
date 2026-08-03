"""Persist coach ENTRY / HOLD / EXIT snapshots for MySQL analysis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import money, to_decimal
from app.models import CoachSignalEvent
from app.services.coach import CoachVerdict

logger = logging.getLogger(__name__)


def _phase_of(verdict: CoachVerdict) -> str:
    phase = getattr(verdict, "phase", None) or "NONE"
    if phase and phase != "NONE":
        return phase
    entry = getattr(verdict, "entry", None) or "NONE"
    if entry in {"ENTRY_BUY", "ENTRY_SELL"}:
        return entry
    trend = getattr(verdict, "trend", None) or "NONE"
    if trend in {"HOLD_LONG", "BUY_TREND"}:
        return "HOLD_LONG"
    if trend in {"HOLD_SHORT", "SELL_TREND"}:
        return "HOLD_SHORT"
    exit_kind = getattr(verdict, "exit", None) or "NONE"
    if exit_kind in {"EXIT_BUY", "EXIT_SELL"}:
        return exit_kind
    return "NONE"


def _alert_side(phase: str) -> str:
    if phase and phase != "NONE":
        return phase
    return "WAIT"


def _pnl_vs_entry(side: str, entry_price: Decimal, price: Decimal) -> tuple[Decimal, bool]:
    ep = to_decimal(entry_price)
    p = to_decimal(price)
    if ep <= 0:
        return money(0), False
    if side in {"BUY", "LONG", "ENTRY_BUY", "HOLD_LONG", "EXIT_BUY"}:
        pct = (p - ep) / ep * Decimal("100")
    elif side in {"SELL", "SHORT", "ENTRY_SELL", "HOLD_SHORT", "EXIT_SELL"}:
        pct = (ep - p) / ep * Decimal("100")
    else:
        pct = Decimal("0")
    return money(pct), pct > 0


def _trade_side_from_phase(phase: str) -> str | None:
    if phase in {"ENTRY_BUY", "HOLD_LONG", "EXIT_BUY", "FLIP_TO_LONG"}:
        return "LONG"
    if phase in {"ENTRY_SELL", "HOLD_SHORT", "EXIT_SELL", "FLIP_TO_SHORT"}:
        return "SHORT"
    return None


def _seq_and_entry_price(
    db: Session,
    *,
    symbol: str,
    interval: str,
    brain: str,
    bar_time: int,
    phase: str,
    price: Decimal,
) -> tuple[int | None, Decimal | None, Decimal | None, bool | None]:
    """seq_from_entry: 1 = ENTRY bar; HOLD/EXIT continue the run. Count ENTRY trades only in UI."""
    trade_side = _trade_side_from_phase(phase)
    if trade_side is None:
        return None, None, None, None

    alert_long = trade_side == "LONG"
    if phase in {"ENTRY_BUY", "ENTRY_SELL", "FLIP_TO_LONG", "FLIP_TO_SHORT"}:
        pct, _ = _pnl_vs_entry(trade_side, price, price)
        return 1, price, pct, False

    want_entry = "ENTRY_BUY" if alert_long else "ENTRY_SELL"
    prior = db.scalar(
        select(CoachSignalEvent)
        .where(
            CoachSignalEvent.symbol == symbol,
            CoachSignalEvent.interval == interval,
            CoachSignalEvent.brain == brain,
            CoachSignalEvent.entry == want_entry,
            CoachSignalEvent.evaluated_bar_time <= bar_time,
        )
        .order_by(CoachSignalEvent.evaluated_bar_time.desc())
        .limit(1)
    )
    if prior is None or (prior.entry_price is None and prior.price is None):
        pct, _ = _pnl_vs_entry(trade_side, price, price)
        return 1, price, pct, False

    entry_px = prior.entry_price if prior.entry_price is not None else prior.price
    n_prior = db.scalar(
        select(func.count())
        .select_from(CoachSignalEvent)
        .where(
            CoachSignalEvent.symbol == symbol,
            CoachSignalEvent.interval == interval,
            CoachSignalEvent.brain == brain,
            CoachSignalEvent.evaluated_bar_time >= prior.evaluated_bar_time,
            CoachSignalEvent.evaluated_bar_time < bar_time,
            CoachSignalEvent.phase.in_(
                ("ENTRY_BUY", "HOLD_LONG", "EXIT_BUY")
                if alert_long
                else ("ENTRY_SELL", "HOLD_SHORT", "EXIT_SELL")
            ),
        )
    )
    # Fallback when older rows lack phase: count by alert_side / entry streak.
    if n_prior is None:
        n_prior = 0
    seq = int(n_prior or 0) + 1
    pct, still = _pnl_vs_entry(trade_side, entry_px, price)
    return seq, entry_px, pct, still


def persist_coach_signal(db: Session, verdict: CoachVerdict) -> CoachSignalEvent | None:
    """Upsert one row per closed bar; fill phase + seq/pnl vs ENTRY."""
    if not verdict.bar_closed or verdict.evaluated_bar_time is None:
        return None

    brain = verdict.brain or "DayTradeCryptoCoach"
    symbol = verdict.symbol.upper()
    entry = getattr(verdict, "entry", None) or "NONE"
    trend = getattr(verdict, "trend", None) or "NONE"
    phase = _phase_of(verdict)
    position_state = getattr(verdict, "position", None) or "NEUTRAL"
    exit_kind = getattr(verdict, "exit", None) or "NONE"
    exit_reason = getattr(verdict, "exit_reason", None)
    alert_side = _alert_side(phase)
    now = datetime.now(timezone.utc)

    existing = db.scalar(
        select(CoachSignalEvent).where(
            CoachSignalEvent.symbol == symbol,
            CoachSignalEvent.interval == verdict.interval,
            CoachSignalEvent.evaluated_bar_time == verdict.evaluated_bar_time,
            CoachSignalEvent.brain == brain,
        )
    )

    seq, entry_px, pnl_pct, still = _seq_and_entry_price(
        db,
        symbol=symbol,
        interval=verdict.interval,
        brain=brain,
        bar_time=verdict.evaluated_bar_time,
        phase=phase,
        price=verdict.price,
    )

    if existing is None:
        row = CoachSignalEvent(
            symbol=symbol,
            interval=verdict.interval,
            brain=brain,
            signal=verdict.signal,
            entry=entry,
            trend=trend,
            phase=phase if phase != "NONE" else None,
            position_state=position_state,
            exit_kind=exit_kind if exit_kind != "NONE" else None,
            exit_reason=exit_reason,
            alert_side=alert_side,
            seq_from_entry=seq,
            entry_price=entry_px,
            pnl_pct_vs_entry=pnl_pct,
            still_profit=still,
            confidence=int(verdict.confidence),
            reason=verdict.reason,
            short_reason=(verdict.short_reason or "")[:500] or None,
            cofr=verdict.cofr,
            price=verdict.price,
            ema9=verdict.ema9,
            ema21=verdict.ema21,
            stop_loss=verdict.stop_loss,
            take_profit=verdict.take_profit,
            risk_reward=verdict.risk_reward,
            source=verdict.source,
            bar_closed=True,
            evaluated_bar_time=verdict.evaluated_bar_time,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info(
            "coach_signal_stored id=%s %s phase=%s seq=%s pnl=%s",
            row.id,
            row.symbol,
            row.phase,
            row.seq_from_entry,
            row.pnl_pct_vs_entry,
        )
        return row

    existing.signal = verdict.signal
    existing.entry = entry
    existing.trend = trend
    existing.phase = phase if phase != "NONE" else None
    existing.position_state = position_state
    existing.exit_kind = exit_kind if exit_kind != "NONE" else None
    existing.exit_reason = exit_reason
    existing.alert_side = alert_side
    existing.seq_from_entry = seq
    existing.entry_price = entry_px
    existing.pnl_pct_vs_entry = pnl_pct
    existing.still_profit = still
    existing.confidence = int(verdict.confidence)
    existing.reason = verdict.reason
    existing.short_reason = (verdict.short_reason or "")[:500] or None
    existing.cofr = verdict.cofr
    existing.price = verdict.price
    existing.ema9 = verdict.ema9
    existing.ema21 = verdict.ema21
    existing.stop_loss = verdict.stop_loss
    existing.take_profit = verdict.take_profit
    existing.risk_reward = verdict.risk_reward
    existing.source = verdict.source
    existing.updated_at = now
    db.commit()
    db.refresh(existing)
    return existing


def list_coach_signals(
    db: Session,
    *,
    symbol: str | None = None,
    interval: str | None = None,
    entry_only: bool = False,
    limit: int = 100,
) -> list[CoachSignalEvent]:
    q = select(CoachSignalEvent).order_by(
        CoachSignalEvent.evaluated_bar_time.desc(),
        CoachSignalEvent.id.desc(),
    )
    if symbol:
        q = q.where(CoachSignalEvent.symbol == symbol.upper())
    if interval:
        q = q.where(CoachSignalEvent.interval == interval)
    if entry_only:
        q = q.where(
            (CoachSignalEvent.entry.in_(("ENTRY_BUY", "ENTRY_SELL")))
            | (CoachSignalEvent.phase.in_(("ENTRY_BUY", "ENTRY_SELL")))
        )
    q = q.limit(min(max(limit, 1), 1000))
    return list(db.scalars(q).all())
