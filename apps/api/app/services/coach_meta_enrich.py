"""Attach MetaAlpha RF / regime snapshot onto a CoachVerdict (read-only).

Does not gate trades — AUTO still uses ``_meta_alpha_entry_gate`` for opens.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.coach import CoachVerdict
from app.services.coach_observability import (
    display_confidence,
    regime_label,
)
from app.services.prices import get_candles

logger = logging.getLogger(__name__)


async def enrich_verdict_meta_alpha(
    db: Session,
    verdict: CoachVerdict,
    *,
    for_entry_gate: bool = False,
) -> tuple[CoachVerdict, dict]:
    """Fetch RF proba + causal regime for display/audit.

    Returns (updated_verdict, gate_dict).
    When MetaAlpha is disabled, regime/proba stay None and confidence stays primary.
    """
    settings = get_settings()
    meta_enabled = bool(settings.meta_alpha_enabled)

    gate: dict = {
        "take": 1,
        "proba": None,
        "regime": None,
        "reason": "meta_alpha_disabled",
        "warm": True,
    }

    if not meta_enabled:
        reasons = _rebuild_reasons(verdict, gate)
        conf, src = display_confidence(
            primary_confidence=verdict.primary_confidence or verdict.confidence,
            rf_proba=None,
            meta_enabled=False,
        )
        updated = replace(
            verdict,
            reasons=reasons,
            rf_proba=None,
            regime=None,
            regime_label=None,
            confidence=conf,
            confidence_source=src,
            meta_alpha_reason="meta_alpha_disabled",
            meta_alpha_take=True,
            primary_confidence=verdict.primary_confidence or verdict.confidence,
        )
        return updated, gate

    primary_side = 0
    if verdict.signal == "BUY" or verdict.phase in {
        "ENTRY_BUY",
        "HOLD_LONG",
        "FLIP_TO_LONG",
    }:
        primary_side = 1
    elif verdict.signal == "SELL" or verdict.phase in {
        "ENTRY_SELL",
        "HOLD_SHORT",
        "FLIP_TO_SHORT",
    }:
        primary_side = -1
    else:
        # Still compute regime for WAIT bars using long bias as placeholder side.
        primary_side = 1

    fail_closed = bool(settings.meta_alpha_fail_closed)
    try:
        from app.services.meta_alpha.live_gate import decide_take_trade
    except ImportError as exc:
        logger.warning("meta_alpha import failed during enrich: %s", exc)
        gate = {
            "take": 0 if fail_closed else 1,
            "proba": None,
            "regime": None,
            "reason": f"import_error:{exc}",
            "warm": False,
        }
        return _apply_gate(verdict, gate, meta_enabled=True), gate

    min_bars = max(int(settings.meta_alpha_min_bars), 120)
    try:
        _sym, _iv, _src, candles = await get_candles(
            db, verdict.symbol, verdict.interval, min_bars + 5
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta_alpha candle fetch failed during enrich: %s", exc)
        gate = {
            "take": 0 if fail_closed else 1,
            "proba": None,
            "regime": None,
            "reason": f"candles_error:{type(exc).__name__}",
            "warm": False,
        }
        return _apply_gate(verdict, gate, meta_enabled=True), gate

    if verdict.evaluated_bar_time is not None:
        candles = [c for c in candles if int(c.time) <= int(verdict.evaluated_bar_time)]

    gate = decide_take_trade(
        candles=candles,
        primary_side=primary_side,
        enabled=True,
        threshold=float(settings.meta_alpha_threshold),
        model_path=settings.meta_alpha_model_path,
        mode=str(settings.meta_alpha_mode or "feature"),
        fail_closed=fail_closed,
        min_bars=int(settings.meta_alpha_min_bars),
    )
    # Observability path: do not change signal/phase; only annotate.
    _ = for_entry_gate
    return _apply_gate(verdict, gate, meta_enabled=True), gate


def _rebuild_reasons(verdict: CoachVerdict, gate: dict) -> list[str]:
    base = list(verdict.reasons or [])
    # Strip prior MetaAlpha / regime lines then rebuild.
    filtered = [
        r
        for r in base
        if not r.startswith("MetaAlpha") and not r.startswith("Market regime:")
    ]
    # Reconstruct A4-ish reasons from checklist when empty.
    if not filtered and verdict.checklist:
        for item in verdict.checklist:
            if item.id in {
                "uptrend",
                "downtrend",
                "close_above_ema9",
                "close_below_ema9",
                "separation",
            }:
                filtered.append(item.label)

    take = gate.get("take")
    meta_take = bool(take) if take is not None else None
    reason = str(gate.get("reason") or "")
    if reason == "meta_alpha_disabled":
        filtered.append("MetaAlpha off — primary-only")
    elif reason in {"take", "below_threshold"} or meta_take is not None:
        if meta_take and reason != "below_threshold":
            filtered.append("MetaAlpha filter passed")
        elif not meta_take:
            filtered.append(
                f"MetaAlpha filter rejected ({reason})" if reason else "MetaAlpha filter rejected"
            )
        else:
            filtered.append("MetaAlpha filter passed")
    elif reason:
        filtered.append(f"MetaAlpha: {reason}")

    label = regime_label(gate.get("regime"))
    if label:
        pretty = {
            "RANGE": "Range",
            "TREND": "Trend",
            "HIGH VOLATILITY": "High Volatility",
        }.get(label, label)
        filtered.append(f"Market regime: {pretty}")
    return filtered


def _apply_gate(verdict: CoachVerdict, gate: dict, *, meta_enabled: bool) -> CoachVerdict:
    proba = gate.get("proba")
    regime = gate.get("regime")
    primary = verdict.primary_confidence if verdict.primary_confidence is not None else verdict.confidence
    conf, src = display_confidence(
        primary_confidence=primary,
        rf_proba=float(proba) if proba is not None else None,
        meta_enabled=meta_enabled,
    )
    # Only remap displayed confidence from RF on ENTRY phases.
    is_entry = verdict.phase in {
        "ENTRY_BUY",
        "ENTRY_SELL",
        "FLIP_TO_LONG",
        "FLIP_TO_SHORT",
    } or verdict.signal in {"BUY", "SELL"}
    if not is_entry:
        conf = primary
        src = "primary"

    reasons = _rebuild_reasons(verdict, gate)
    return replace(
        verdict,
        confidence=int(conf),
        confidence_source=src,
        primary_confidence=primary,
        rf_proba=float(proba) if proba is not None else None,
        regime=int(regime) if regime is not None else None,
        regime_label=regime_label(int(regime) if regime is not None else None),
        reasons=reasons,
        meta_alpha_reason=str(gate.get("reason") or "") or None,
        meta_alpha_take=bool(gate.get("take")) if gate.get("take") is not None else None,
        cofr=(
            f"C:{conf} | O:{verdict.cofr.split('| O:')[-1]}"
            if "| O:" in (verdict.cofr or "")
            else verdict.cofr
        ),
    )
