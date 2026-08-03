"""Paper auto-trade helper driven by DayTradeCryptoCoach (no real money).

Version A (locked) remains the default strategy for /coach/auto-tick.
Version B runs only on the isolated Paper B Experiment account via /coach/ab-tick.

LONG/SHORT paper: open only when flat on ENTRY; hold until SL/TP (no signal flip).
Stake is fixed to the requested usd_amount (capped by cash), not equity×risk/SL.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.money import money, position_side_from_qty, to_decimal
from app.models import Asset, Order, OrderSide, Position, Trade, TradingAccount, User
from app.schemas.orders import OrderRequest
from app.services.coach import evaluate_daytrade_signal
from app.services.coach_baseline import promotion_status
from app.services.coach_brain import (
    BRAIN_NAME,
    DEFAULT_AUTO_USD,
    MIN_HOLD_BARS_BEFORE_SIGNAL_SELL,
    MIN_TRADE_USD,
    PRACTICE_TRADES_MIN,
    PRACTICE_TRADES_TARGET,
)
from app.services.coach_experiment_b import (
    VERSION_B_NAME,
    bars_held_since,
    evaluate_daytrade_signal_b,
)
from app.services.google_chat import notify_coach_signal
from app.services.prices import get_price_quote
from app.services.trading import (
    execute_buy,
    execute_sell,
    get_paper_account_for_user,
    get_risk_rules,
    get_strategy_paper_account,
    latest_entry_order,
    latest_filled_buy_order,
)

logger = logging.getLogger(__name__)

# Dedupe: act once per signal change (BUY↔SELL), not every candle with same signal.
# Key = f"{account_id}:{symbol}:{strategy}" → last acted signal.
_last_acted_signal: dict[str, str] = {}
# Last processed closed-candle unix time per account/symbol/strategy (prevents same-bar re-entry).
_last_processed_bar: dict[str, int] = {}


def _acted_key(account_id: int, symbol: str, strategy: str) -> str:
    return f"{account_id}:{symbol.upper()}:{strategy}"


def _log_action(result: dict, message: str) -> None:
    logs = result.setdefault("logs", [])
    logs.append(message)
    logger.info("paper_auto %s", message)
    result["reason"] = " · ".join(logs)


def paper_performance_stats(
    db: Session,
    user: User,
    *,
    account: TradingAccount | None = None,
    strategy: str | None = None,
) -> dict:
    if account is None and strategy is not None:
        account = get_strategy_paper_account(db, user, strategy)
    if account is None:
        account = get_paper_account_for_user(db, user)

    sells = db.scalars(
        select(Trade)
        .options(joinedload(Trade.order).joinedload(Order.journal))
        .join(Order, Order.id == Trade.order_id)
        .where(
            Trade.trading_account_id == account.id,
            Trade.realized_pnl != 0,
        )
        .order_by(Trade.executed_at.asc(), Trade.id.asc())
    ).unique().all()
    # Closed trades = any fill that realized P&L (close LONG sell or cover SHORT buy).
    closed = list(sells)
    trade_count = len(closed)
    wins = [t for t in closed if to_decimal(t.realized_pnl) > 0]
    losses = [t for t in closed if to_decimal(t.realized_pnl) < 0]
    net = sum((to_decimal(t.realized_pnl) for t in closed), Decimal("0"))
    starting = to_decimal(account.starting_balance)

    gross_profit = sum((to_decimal(t.realized_pnl) for t in wins), Decimal("0"))
    gross_loss = abs(sum((to_decimal(t.realized_pnl) for t in losses), Decimal("0")))
    profit_factor = money(gross_profit / gross_loss) if gross_loss > 0 else None
    win_rate = (
        money((Decimal(len(wins)) / Decimal(trade_count)) * Decimal("100"))
        if trade_count
        else None
    )

    equity = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for trade in closed:
        equity += to_decimal(trade.realized_pnl)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    avg_win = (
        money(sum((to_decimal(t.realized_pnl) for t in wins), Decimal("0")) / len(wins))
        if wins
        else None
    )
    avg_loss = (
        money(sum((to_decimal(t.realized_pnl) for t in losses), Decimal("0")) / len(losses))
        if losses
        else None
    )
    last = closed[-1] if closed else None
    last_pnl = money(to_decimal(last.realized_pnl)) if last else None
    last_exit = None
    if last and last.order is not None:
        journal = getattr(last.order, "journal", None)
        last_exit = journal.exit_reason if journal is not None else None
    journaled = sum(
        1
        for t in closed
        if t.order and getattr(t.order, "journal", None) and t.order.journal.exit_reason
    )
    avg_rr: str | None = None
    if wins and losses and avg_win is not None and avg_loss is not None:
        loss_abs = abs(to_decimal(avg_loss))
        if loss_abs > 0:
            avg_rr = f"1:{(to_decimal(avg_win) / loss_abs):.2f}"
    elif trade_count == 0:
        avg_rr = "1:1.5"

    locked = False
    lock_reason = None
    rules = get_risk_rules(db, account)
    if not rules.trading_enabled:
        locked = True
        lock_reason = "Trading disabled in settings"
    if starting > 0 and max_dd > 0:
        dd_pct = max_dd / starting * 100
        if dd_pct >= 15:
            locked = True
            lock_reason = f"Drawdown lock: {dd_pct:.1f}% >= 15% of starting balance"

    return {
        "paper_only": True,
        "strategy": strategy,
        "account_id": account.id,
        "account_name": account.account_name,
        "closed_trades": trade_count,
        "win_rate": str(win_rate) if win_rate is not None else None,
        "net_profit": str(money(net)),
        "max_drawdown": str(money(max_dd)),
        "profit_factor": str(profit_factor) if profit_factor is not None else None,
        "practice_trades_min": PRACTICE_TRADES_MIN,
        "practice_trades_target": PRACTICE_TRADES_TARGET,
        "practice_progress_pct": min(100.0, round(trade_count / PRACTICE_TRADES_TARGET * 100, 1)),
        "ready_for_real_money_recommendation": False,
        "recommendation": (
            f"Stay on paper until {PRACTICE_TRADES_MIN}–{PRACTICE_TRADES_TARGET} closed trades "
            "and review win rate, profit factor, and drawdown."
        ),
        "trading_locked": locked,
        "lock_reason": lock_reason,
        "avg_win": str(avg_win) if avg_win is not None else None,
        "avg_loss": str(avg_loss) if avg_loss is not None else None,
        "wins": len(wins),
        "losses": len(losses),
        "last_trade_pnl": str(last_pnl) if last_pnl is not None else None,
        "last_exit_reason": last_exit,
        "journaled_exits": journaled,
        "avg_risk_reward": avg_rr,
        "planned_risk_reward": "1:1.5",
    }


def _metric_better(a: dict, b: dict) -> dict[str, bool]:
    def num(d: dict, key: str) -> float | None:
        raw = d.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "win_rate": (num(b, "win_rate") or 0) > (num(a, "win_rate") or 0),
        "profit_factor": (num(b, "profit_factor") or 0) > (num(a, "profit_factor") or 0),
        "net_profit": (num(b, "net_profit") or 0) > (num(a, "net_profit") or 0),
        "max_drawdown": (num(b, "max_drawdown") or 0) < (num(a, "max_drawdown") or 0),
        "closed_trades": (b.get("closed_trades") or 0) >= 5 and (a.get("closed_trades") or 0) >= 5,
    }


async def run_auto_tick(
    db: Session,
    user: User,
    symbol: str,
    interval: str = "15m",
    usd_amount: Decimal = Decimal(DEFAULT_AUTO_USD),
    *,
    strategy: str = "A",
    notify: bool = True,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    ema_sep_pct: float | None = None,
    leverage: Decimal = Decimal("5"),
) -> dict:
    """One paper auto step for strategy A (locked default) or B (experiment account)."""
    strategy_key = strategy.strip().upper()
    if strategy_key not in {"A", "B"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="strategy must be A or B",
        )

    account = get_strategy_paper_account(db, user, strategy_key)
    stats = paper_performance_stats(db, user, account=account, strategy=strategy_key)

    bars_held = 0
    asset_preview = db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if asset_preview is not None:
        buy = latest_filled_buy_order(db, account.id, asset_preview.id)
        if buy is not None:
            bars_held = bars_held_since(buy.filled_at, interval)

    if strategy_key == "B":
        verdict = await evaluate_daytrade_signal_b(
            db, symbol, interval, bars_held=bars_held
        )
        setup_name = VERSION_B_NAME
    else:
        verdict = await evaluate_daytrade_signal(
            db,
            symbol,
            interval,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            ema_sep_pct=ema_sep_pct,
        )
        setup_name = BRAIN_NAME
        # Optional min-hold (A3 = 0 → no deferral).
        if (
            MIN_HOLD_BARS_BEFORE_SIGNAL_SELL > 0
            and verdict.signal == "SELL"
            and bars_held < MIN_HOLD_BARS_BEFORE_SIGNAL_SELL
        ):
            from dataclasses import replace as _replace

            verdict = _replace(
                verdict,
                signal="WAIT",
                reason=(
                    f"WAIT: technical SELL deferred — min hold {bars_held}/"
                    f"{MIN_HOLD_BARS_BEFORE_SIGNAL_SELL} bars. SL/TP still honored."
                ),
                cofr=f"C:{verdict.confidence} | O:min-hold | F:WAIT | R:hold",
                short_reason=(
                    f"WAIT — hold {bars_held}/{MIN_HOLD_BARS_BEFORE_SIGNAL_SELL} "
                    "before signal SELL."
                ),
                stop_loss=None,
                take_profit=None,
                risk_reward=None,
            )

    # Store closed-bar ENTRY/HOLD/EXIT for MySQL analysis (deduped per bar).
    from app.services.coach_signal_store import persist_coach_signal
    from dataclasses import replace as dc_replace

    persist_coach_signal(db, verdict)

    if notify and strategy_key == "A":
        await notify_coach_signal(verdict, suggested_usd=float(usd_amount))

    phase = getattr(verdict, "phase", None) or "NONE"
    trend = getattr(verdict, "trend", None) or "NONE"
    entry = getattr(verdict, "entry", None) or "NONE"
    exit_kind = getattr(verdict, "exit", None) or "NONE"
    result: dict = {
        "paper_only": True,
        "strategy": strategy_key,
        "brain": verdict.brain,
        "account_id": account.id,
        "action": "none",
        "signal": verdict.signal,
        "confidence": verdict.confidence,
        "reason": verdict.reason,
        "cofr": verdict.cofr,
        "order_id": None,
        "stats": stats,
        "trend": trend,
        "entry": entry,
        "phase": phase,
        "exit": exit_kind,
        "position_state": getattr(verdict, "position", None) or "NEUTRAL",
        "logs": [],
    }

    if stats["trading_locked"]:
        result["action"] = "locked"
        result["reason"] = stats["lock_reason"] or "Trading locked by statistics"
        return result

    asset = db.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    position = db.scalar(
        select(Position)
        .options(joinedload(Position.asset))
        .where(
            Position.trading_account_id == account.id,
            Position.asset_id == asset.id,
        )
    )
    side = position_side_from_qty(position.quantity) if position is not None else None

    quote = await get_price_quote(db, symbol)
    price = to_decimal(quote.price)
    result["position_side"] = side or "flat"

    # --- Always honor SL/TP first (both LONG and SHORT), even on TREND-only ticks ---
    if position is not None and side is not None:
        entry_order = latest_entry_order(db, account.id, asset.id, side)
        if entry_order is None and side == "long":
            entry_order = latest_filled_buy_order(db, account.id, asset.id)
        sl = to_decimal(entry_order.stop_loss_price) if entry_order and entry_order.stop_loss_price else None
        tp = (
            to_decimal(entry_order.take_profit_price)
            if entry_order and entry_order.take_profit_price
            else None
        )
        abs_qty = abs(to_decimal(position.quantity))

        hit_sl = False
        hit_tp = False
        if side == "long":
            hit_sl = sl is not None and price <= sl
            hit_tp = tp is not None and price >= tp
        else:  # short
            hit_sl = sl is not None and price >= sl
            hit_tp = tp is not None and price <= tp

        if hit_sl or hit_tp:
            exit_kind_sl = "stop_loss" if hit_sl else "take_profit"
            log_msg = "Closed by Stop Loss" if hit_sl else "Closed by Take Profit"
            exit_phase = "EXIT_BUY" if side == "long" else "EXIT_SELL"
            if side == "long":
                req = OrderRequest(
                    symbol=symbol.upper(),
                    quantity=abs_qty,
                    exit_reason=f"{setup_name} {exit_kind_sl} | result=hit_{'SL' if hit_sl else 'TP'} | Closed LONG",
                    followed_plan=True,
                    emotional_state="calm",
                )
                order_resp = await execute_sell(db, user, req, account=account)
                result["action"] = f"close_long_{exit_kind_sl}"
            else:
                req = OrderRequest(
                    symbol=symbol.upper(),
                    quantity=abs_qty,
                    exit_reason=f"{setup_name} {exit_kind_sl} | result=hit_{'SL' if hit_sl else 'TP'} | Closed SHORT",
                    followed_plan=True,
                    emotional_state="calm",
                )
                order_resp = await execute_buy(db, user, req, account=account)
                result["action"] = f"close_short_{exit_kind_sl}"
            result["order_id"] = order_resp.id
            _log_action(result, f"{log_msg} — Closed {side.upper()}")

            # Override this bar's story to EXIT (SL/TP) for MySQL + Chat.
            exit_verdict = dc_replace(
                verdict,
                phase=exit_phase,
                position="NEUTRAL",
                entry="NONE",
                trend="NONE",
                exit=exit_phase,
                exit_reason=exit_kind_sl,
                signal="WAIT",
                reason=(
                    f"{exit_phase} ({exit_kind_sl}): closed {side.upper()} at ~{price}. "
                    f"{log_msg}."
                ),
                short_reason=f"{exit_phase} · {exit_kind_sl}",
                cofr=f"C:{verdict.confidence} | O:exit | F:{exit_phase} | R:{exit_kind_sl}",
                stop_loss=None,
                take_profit=None,
                risk_reward=None,
            )
            persist_coach_signal(db, exit_verdict)
            if notify and strategy_key == "A":
                await notify_coach_signal(
                    exit_verdict, suggested_usd=float(usd_amount), force=True
                )
            result["phase"] = exit_phase
            result["exit"] = exit_phase
            result["stats"] = paper_performance_stats(
                db, user, account=account, strategy=strategy_key
            )
            # After forced exit, do not also open on same tick.
            return result

    acted_key = _acted_key(account.id, symbol, strategy_key)

    # ENTRY opens only when flat; HOLD is display-only; EXIT closes on opposite signal.
    if not verdict.bar_closed:
        result["action"] = "wait"
        _log_action(result, "WAIT — forming candle (decide on closed bar only)")
        return result

    # --- Signal EXIT / same-bar FLIP ---
    if phase in {"EXIT_BUY", "FLIP_TO_SHORT"} and side == "long" and position is not None:
        abs_qty = abs(to_decimal(position.quantity))
        req = OrderRequest(
            symbol=symbol.upper(),
            quantity=abs_qty,
            exit_reason=(
                f"{setup_name} signal_exit | {phase} | Closed LONG"
                + (" → ENTRY SHORT" if phase == "FLIP_TO_SHORT" else "")
            ),
            followed_plan=True,
            emotional_state="calm",
        )
        order_resp = await execute_sell(db, user, req, account=account)
        result["action"] = (
            "flip_long_to_short_close" if phase == "FLIP_TO_SHORT" else "close_long_signal"
        )
        result["order_id"] = order_resp.id
        _log_action(
            result,
            "EXIT LONG → ENTRY SHORT — Closed LONG"
            if phase == "FLIP_TO_SHORT"
            else "EXIT BUY — Closed LONG on opposite signal",
        )
        result["stats"] = paper_performance_stats(
            db, user, account=account, strategy=strategy_key
        )
        _last_acted_signal.pop(acted_key, None)
        if phase != "FLIP_TO_SHORT":
            return result
        # Continue to open SHORT on same tick.
        side = None
        position = None

    if phase in {"EXIT_SELL", "FLIP_TO_LONG"} and side == "short" and position is not None:
        abs_qty = abs(to_decimal(position.quantity))
        req = OrderRequest(
            symbol=symbol.upper(),
            quantity=abs_qty,
            exit_reason=(
                f"{setup_name} signal_exit | {phase} | Closed SHORT"
                + (" → ENTRY LONG" if phase == "FLIP_TO_LONG" else "")
            ),
            followed_plan=True,
            emotional_state="calm",
        )
        order_resp = await execute_buy(db, user, req, account=account)
        result["action"] = (
            "flip_short_to_long_close" if phase == "FLIP_TO_LONG" else "close_short_signal"
        )
        result["order_id"] = order_resp.id
        _log_action(
            result,
            "EXIT SHORT → ENTRY LONG — Closed SHORT"
            if phase == "FLIP_TO_LONG"
            else "EXIT SELL — Closed SHORT on opposite signal",
        )
        result["stats"] = paper_performance_stats(
            db, user, account=account, strategy=strategy_key
        )
        _last_acted_signal.pop(acted_key, None)
        if phase != "FLIP_TO_LONG":
            return result
        side = None
        position = None

    if verdict.signal == "WAIT":
        result["action"] = "wait"
        if phase == "HOLD_LONG" or trend in {"HOLD_LONG", "BUY_TREND"}:
            _log_action(result, "HOLD LONG — no new ENTRY (no duplicate order)")
        elif phase == "HOLD_SHORT" or trend in {"HOLD_SHORT", "SELL_TREND"}:
            _log_action(result, "HOLD SHORT — no new ENTRY (no duplicate order)")
        elif phase in {"EXIT_BUY", "EXIT_SELL"}:
            _log_action(result, f"{phase} — flat / no open position to close")
        else:
            _last_acted_signal.pop(acted_key, None)
            _log_action(result, "WAIT — no ENTRY on this closed bar")
        return result

    bar_time = verdict.evaluated_bar_time
    if bar_time is not None and _last_processed_bar.get(acted_key) == bar_time:
        result["action"] = "skip_same_candle"
        _log_action(
            result,
            f"Skipped — candle {bar_time} already processed for ENTRY {verdict.signal}",
        )
        return result

    # Never open another LONG while already LONG (or SHORT while SHORT).
    if verdict.signal == "BUY" and side == "long":
        result["action"] = "skip_same_signal"
        _log_action(result, "Skipped because already LONG")
        return result
    if verdict.signal == "SELL" and side == "short":
        result["action"] = "skip_same_signal"
        _log_action(result, "Skipped because already SHORT")
        return result

    # Still in a position but phase is ENTRY the other way (desync) — hold / wait EXIT path.
    if side is not None:
        result["action"] = "hold_until_exit"
        _log_action(
            result,
            f"Holding {side.upper()} — ignore ENTRY {verdict.signal} until EXIT / SL / TP",
        )
        return result

    async def _size_stake() -> Decimal | None:
        """Fixed stake from Settings / request (usd_amount), capped by cash only."""
        cash = to_decimal(account.cash_balance)
        min_trade = Decimal(MIN_TRADE_USD)
        if cash < min_trade:
            result["action"] = "wait"
            _log_action(
                result,
                f"No order — paper cash ${cash} cannot fund minimum trade (${min_trade})",
            )
            return None
        requested = to_decimal(usd_amount)
        stake = money(min(requested, cash * Decimal("0.99")))
        if to_decimal(stake) < min_trade:
            result["action"] = "wait"
            _log_action(
                result,
                f"No order — fixed stake ${stake} below minimum ${min_trade}",
            )
            return None
        if to_decimal(stake) + Decimal("0.0001") < requested:
            _log_action(
                result,
                f"Stake capped by cash: requested ${requested} → using ${stake}",
            )
        return stake

    async def _open_long(stake: Decimal) -> None:
        sl = verdict.stop_loss
        tp = verdict.take_profit
        if sl is None or tp is None:
            result["action"] = "wait"
            _log_action(result, "BUY blocked — SL/TP must be locked for LONG")
            return
        entry_reason = (
            f"Opened LONG | {verdict.reason} | COFR {verdict.cofr} | "
            f"stake ${stake}"
        )
        req = OrderRequest(
            symbol=symbol.upper(),
            usd_amount=stake,
            leverage=leverage,
            stop_loss_price=sl,
            take_profit_price=tp,
            setup_name=setup_name,
            entry_reason=entry_reason,
            followed_plan=True,
            emotional_state="calm",
            confidence_score=min(5, max(1, verdict.confidence // 20)),
        )
        order_resp = await execute_buy(db, user, req, account=account)
        result["action"] = "open_long"
        result["order_id"] = order_resp.id
        result["stake_usd"] = str(stake)
        result["stop_loss"] = str(sl)
        result["take_profit"] = str(tp)
        result["position_side"] = "long"
        _log_action(result, f"Opened LONG @ ~{price} SL {sl} TP {tp}")
        _last_acted_signal[acted_key] = "BUY"
        if bar_time is not None:
            _last_processed_bar[acted_key] = bar_time

    async def _open_short(stake: Decimal) -> None:
        sl = verdict.stop_loss
        tp = verdict.take_profit
        if sl is None or tp is None:
            result["action"] = "wait"
            _log_action(result, "SELL blocked — SL/TP must be locked for SHORT")
            return
        entry_reason = (
            f"Opened SHORT | {verdict.reason} | COFR {verdict.cofr} | "
            f"stake ${stake}"
        )
        req = OrderRequest(
            symbol=symbol.upper(),
            usd_amount=stake,
            leverage=leverage,
            stop_loss_price=sl,
            take_profit_price=tp,
            setup_name=setup_name,
            entry_reason=entry_reason,
            followed_plan=True,
            emotional_state="calm",
            confidence_score=min(5, max(1, verdict.confidence // 20)),
        )
        order_resp = await execute_sell(db, user, req, account=account)
        result["action"] = "open_short"
        result["order_id"] = order_resp.id
        result["stake_usd"] = str(stake)
        result["stop_loss"] = str(sl)
        result["take_profit"] = str(tp)
        result["position_side"] = "short"
        _log_action(result, f"Opened SHORT @ ~{price} SL {sl} TP {tp}")
        _last_acted_signal[acted_key] = "SELL"
        if bar_time is not None:
            _last_processed_bar[acted_key] = bar_time

    if verdict.signal == "BUY":
        # Flat only — opposite side already returned hold_for_sl_tp above.
        stake = await _size_stake()
        if stake is None:
            return result
        await _open_long(stake)
        result["stats"] = paper_performance_stats(
            db, user, account=account, strategy=strategy_key
        )
        return result

    if verdict.signal == "SELL":
        stake = await _size_stake()
        if stake is None:
            return result
        await _open_short(stake)
        result["stats"] = paper_performance_stats(
            db, user, account=account, strategy=strategy_key
        )
        return result

    result["action"] = "hold"
    _log_action(result, verdict.reason)
    return result


async def run_ab_auto_tick(
    db: Session,
    user: User,
    symbol: str,
    interval: str = "15m",
    usd_amount: Decimal = Decimal(DEFAULT_AUTO_USD),
) -> dict:
    """Tick locked A and experiment B on the same symbol/interval/market time."""
    tick_a = await run_auto_tick(
        db, user, symbol, interval, usd_amount, strategy="A", notify=True
    )
    tick_b = await run_auto_tick(
        db, user, symbol, interval, usd_amount, strategy="B", notify=False
    )
    return {
        "paper_only": True,
        "symbol": symbol.upper(),
        "interval": interval,
        "market_time_shared": True,
        "a": tick_a,
        "b": tick_b,
        "main_strategy": "A",
        "note": "Version A remains locked main; B is isolated experiment account.",
    }


def compare_ab_paper_stats(db: Session, user: User) -> dict:
    stats_a = paper_performance_stats(db, user, strategy="A")
    stats_b = paper_performance_stats(db, user, strategy="B")
    better = _metric_better(stats_a, stats_b)
    score = sum(
        1
        for k in ("win_rate", "profit_factor", "net_profit", "max_drawdown")
        if better.get(k)
    )
    sample_ok = bool(better.get("closed_trades"))
    promo = promotion_status(
        paper_b_better_markets=1 if (sample_ok and score >= 3) else 0,
        markets_tested=1 if sample_ok else 0,
    )
    return {
        "paper_only": True,
        "main_strategy": "A",
        "a": stats_a,
        "b": stats_b,
        "b_better": better,
        "score_b_better_metrics": f"{score}/4",
        "promotion": promo,
        "conclusion": (
            "B_LOOKS_BETTER_ON_THIS_PAPER_BOOK — keep A locked until multi-market + human promote"
            if sample_ok and score >= 3
            else "KEEP_A_LOCKED_CONTINUE_PAPER_AB"
        ),
    }
