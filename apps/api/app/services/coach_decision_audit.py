"""Persist per-closed-bar model decisions for debugging (survives restart)."""

from __future__ import annotations

import json
import logging
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import money, to_decimal
from app.models import CoachDecisionAudit
from app.services.coach import CoachVerdict
from app.services.coach_observability import map_final_action, regime_label

logger = logging.getLogger(__name__)


def persist_decision_audit(
    db: Session,
    verdict: CoachVerdict,
    *,
    final_action: str | None = None,
    auto_action: str | None = None,
    rejection_reason: str | None = None,
    rf_proba: float | None = None,
    regime: int | None = None,
    reasons: Sequence[str] | None = None,
    signal_candidate: str | None = None,
    order_id: int | None = None,
    strategy: str | None = None,
    account_id: int | None = None,
) -> CoachDecisionAudit | None:
    """Upsert one audit row per (symbol, interval, bar, brain, strategy)."""
    if not verdict.bar_closed or verdict.evaluated_bar_time is None:
        return None

    bar_time = int(verdict.evaluated_bar_time)
    brain = getattr(verdict, "brain", None) or "DayTradeCryptoCoach"
    strategy_key = (strategy or "A").upper()
    phase = getattr(verdict, "phase", None) or "NONE"
    action = final_action or map_final_action(
        phase=phase, auto_action=auto_action, signal=verdict.signal
    )

    rf = rf_proba if rf_proba is not None else getattr(verdict, "rf_proba", None)
    reg = regime if regime is not None else getattr(verdict, "regime", None)
    reason_list = list(reasons) if reasons is not None else list(
        getattr(verdict, "reasons", None) or []
    )
    candidate = signal_candidate or getattr(verdict, "signal_candidate", None) or verdict.signal

    ema_gap = getattr(verdict, "ema_gap_pct", None)
    if ema_gap is None and verdict.ema9 is not None and verdict.ema21 is not None:
        close = float(to_decimal(verdict.price))
        if close > 0:
            ema_gap = abs(float(to_decimal(verdict.ema9)) - float(to_decimal(verdict.ema21))) / close * 100.0

    reject = rejection_reason
    if reject is None and action == "SKIP":
        reject = getattr(verdict, "short_reason", None) or verdict.reason

    existing = db.scalar(
        select(CoachDecisionAudit).where(
            CoachDecisionAudit.symbol == verdict.symbol,
            CoachDecisionAudit.interval == verdict.interval,
            CoachDecisionAudit.evaluated_bar_time == bar_time,
            CoachDecisionAudit.brain == brain,
            CoachDecisionAudit.strategy == strategy_key,
        )
    )

    payload = {
        "signal": verdict.signal,
        "signal_candidate": candidate,
        "phase": phase,
        "position_state": getattr(verdict, "position", None) or "NEUTRAL",
        "final_action": action,
        "rejection_reason": reject,
        "confidence": int(getattr(verdict, "confidence", 0) or 0),
        "rf_proba": float(rf) if rf is not None else None,
        "regime": int(reg) if reg is not None else None,
        "regime_label": regime_label(int(reg) if reg is not None else None),
        "reasons_json": json.dumps(reason_list, ensure_ascii=False),
        "price": money(verdict.price),
        "ema9": money(verdict.ema9) if verdict.ema9 is not None else None,
        "ema21": money(verdict.ema21) if verdict.ema21 is not None else None,
        "ema_gap_pct": money(ema_gap) if ema_gap is not None else None,
        "stop_loss": money(verdict.stop_loss) if verdict.stop_loss is not None else None,
        "take_profit": money(verdict.take_profit) if verdict.take_profit is not None else None,
        "risk_reward": verdict.risk_reward,
        "auto_action": auto_action,
        "order_id": order_id,
        "account_id": account_id,
        "bar_closed": True,
    }

    if existing is None:
        row = CoachDecisionAudit(
            symbol=verdict.symbol,
            interval=verdict.interval,
            brain=brain,
            strategy=strategy_key,
            evaluated_bar_time=bar_time,
            **payload,
        )
        db.add(row)
    else:
        row = existing
        for k, v in payload.items():
            setattr(row, k, v)

    try:
        db.commit()
        db.refresh(row)
        return row
    except Exception:  # noqa: BLE001 — audit must not break trading
        logger.exception("persist_decision_audit failed")
        db.rollback()
        return None


def list_decision_audits(
    db: Session,
    *,
    symbol: str | None = None,
    interval: str | None = None,
    strategy: str | None = None,
    limit: int = 100,
) -> list[CoachDecisionAudit]:
    q = select(CoachDecisionAudit).order_by(
        CoachDecisionAudit.evaluated_bar_time.desc(),
        CoachDecisionAudit.id.desc(),
    )
    if symbol:
        q = q.where(CoachDecisionAudit.symbol == symbol.upper())
    if interval:
        q = q.where(CoachDecisionAudit.interval == interval.strip().lower())
    if strategy:
        q = q.where(CoachDecisionAudit.strategy == strategy.upper())
    q = q.limit(limit)
    return list(db.scalars(q).all())


def audit_to_dict(row: CoachDecisionAudit) -> dict[str, Any]:
    reasons: list[str] = []
    if row.reasons_json:
        try:
            parsed = json.loads(row.reasons_json)
            if isinstance(parsed, list):
                reasons = [str(x) for x in parsed]
        except json.JSONDecodeError:
            reasons = []
    return {
        "id": row.id,
        "symbol": row.symbol,
        "interval": row.interval,
        "brain": row.brain,
        "strategy": row.strategy,
        "evaluated_bar_time": row.evaluated_bar_time,
        "signal": row.signal,
        "signal_candidate": row.signal_candidate,
        "phase": row.phase,
        "position_state": row.position_state,
        "final_action": row.final_action,
        "rejection_reason": row.rejection_reason,
        "confidence": row.confidence,
        "rf_proba": float(row.rf_proba) if row.rf_proba is not None else None,
        "regime": row.regime,
        "regime_label": row.regime_label,
        "reasons": reasons,
        "price": str(row.price) if row.price is not None else None,
        "ema9": str(row.ema9) if row.ema9 is not None else None,
        "ema21": str(row.ema21) if row.ema21 is not None else None,
        "ema_gap_pct": str(row.ema_gap_pct) if row.ema_gap_pct is not None else None,
        "stop_loss": str(row.stop_loss) if row.stop_loss is not None else None,
        "take_profit": str(row.take_profit) if row.take_profit is not None else None,
        "risk_reward": row.risk_reward,
        "auto_action": row.auto_action,
        "order_id": row.order_id,
        "account_id": row.account_id,
        "bar_closed": row.bar_closed,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
