import { computeEma } from "@/lib/ema";
import { PAPER_FEE_PCT } from "@/lib/coach-settings";

export type SignalSide = "buy" | "sell";

export type PhaseKind =
  | "ENTRY_BUY"
  | "ENTRY_SELL"
  | "HOLD_LONG"
  | "HOLD_SHORT"
  | "EXIT_BUY"
  | "EXIT_SELL"
  /** Same candle: close LONG and open SHORT */
  | "FLIP_TO_SHORT"
  /** Same candle: close SHORT and open LONG */
  | "FLIP_TO_LONG";

export type PositionState = "NEUTRAL" | "LONG" | "SHORT";

export interface CandleOHLC {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface EmaSignal {
  time: number;
  side: SignalSide;
  price: number;
  reason: string;
}

export interface PhaseEvent {
  time: number;
  phase: PhaseKind;
  price: number;
  reason: string;
  position: PositionState;
  sepPct: number;
}

export interface CompletedTrade {
  side: "LONG" | "SHORT";
  entryTime: number;
  exitTime: number;
  entryPrice: number;
  exitPrice: number;
  pnlPct: number;
  pnlUsdEstimate: number;
  durationBars: number;
  exitReason: "Signal";
}

/** Locked hypothesis A4 (must match apps/api coach_brain.py). */
export const BASIC_EMA_RULES = {
  id: "a4_ema9_close_sep_pct",
  label: "A4 story: ENTRY → HOLD → EXIT",
  buy:
    "ENTRY BUY: flat + uptrend (EMA9>EMA21) + close above EMA9 + |EMA gap| over 0.10% → LONG once",
  sell:
    "ENTRY SELL: flat + downtrend + close below EMA9 + gap → SHORT once · EXIT on opposite / SL / TP",
  alternate: "HOLD LONG/SHORT in history — chart shows ENTRY + EXIT only (no BUY spam)",
  exits: "EXIT BUY/SELL once · SL 2% / TP 3% + fee cover · fixed stake",
  journal: "Count ENTRY trades only; store entry/exit/PnL/duration/reason",
} as const;

/** |EMA9−EMA21| as percent of close (same as API EMA_SEPARATION_PCT_MIN). */
export const EMA_SEPARATION_PCT_MIN = 0.1;

/** Medium exits from entry (Buy): SL −2%, TP +3% + round-trip fee pad. */
export function suggestedExitsFromEntry(entryPrice: number): { sl: string; tp: string } {
  const feeRt = (PAPER_FEE_PCT * 2) / 100;
  const sl = entryPrice * 0.98;
  const tp = entryPrice * (1.03 + feeRt);
  return {
    sl: String(Math.round(sl)),
    tp: String(Math.round(tp)),
  };
}

function a4SideOk(
  ema9: number,
  ema21: number,
  close: number,
  sepMinPct: number,
): { buyOk: boolean; sellOk: boolean; sepPct: number } {
  const separation = Math.abs(ema9 - ema21);
  const sepPct = close > 0 ? (separation / close) * 100 : 0;
  const separationOk = sepPct > sepMinPct;
  const buyOk = ema9 > ema21 && close > ema9 && separationOk;
  const sellOk = ema9 < ema21 && close < ema9 && separationOk;
  return { buyOk, sellOk, sepPct };
}

function stepPosition(
  position: PositionState,
  buyOk: boolean,
  sellOk: boolean,
): { phase: PhaseKind | null; position: PositionState } {
  if (position === "NEUTRAL") {
    if (buyOk) return { phase: "ENTRY_BUY", position: "LONG" };
    if (sellOk) return { phase: "ENTRY_SELL", position: "SHORT" };
    return { phase: null, position: "NEUTRAL" };
  }
  if (position === "LONG") {
    // Full opposite A4 → flip same bar.
    if (sellOk) return { phase: "FLIP_TO_SHORT", position: "SHORT" };
    // Long setup broken (cross / close / gap) → EXIT, do not hold forever.
    if (!buyOk) return { phase: "EXIT_BUY", position: "NEUTRAL" };
    return { phase: "HOLD_LONG", position: "LONG" };
  }
  if (position === "SHORT") {
    if (buyOk) return { phase: "FLIP_TO_LONG", position: "LONG" };
    if (!sellOk) return { phase: "EXIT_SELL", position: "NEUTRAL" };
    return { phase: "HOLD_SHORT", position: "SHORT" };
  }
  return { phase: null, position: "NEUTRAL" };
}

function phaseLabel(phase: PhaseKind, sepPct: number): string {
  switch (phase) {
    case "ENTRY_BUY":
      return `ENTRY BUY · gap ${sepPct.toFixed(3)}%`;
    case "ENTRY_SELL":
      return `ENTRY SELL · gap ${sepPct.toFixed(3)}%`;
    case "HOLD_LONG":
      return `BUY · gap ${sepPct.toFixed(3)}%`;
    case "HOLD_SHORT":
      return `SELL · gap ${sepPct.toFixed(3)}%`;
    case "EXIT_BUY":
      return `EXIT LONG · setup broken · gap ${sepPct.toFixed(3)}%`;
    case "EXIT_SELL":
      return `EXIT SHORT · setup broken · gap ${sepPct.toFixed(3)}%`;
    case "FLIP_TO_SHORT":
      return `EXIT LONG → ENTRY SHORT · gap ${sepPct.toFixed(3)}%`;
    case "FLIP_TO_LONG":
      return `EXIT SHORT → ENTRY LONG · gap ${sepPct.toFixed(3)}%`;
  }
}

/**
 * Full ENTRY → HOLD → EXIT walk (matches API coach position state machine).
 * Skips the newest bar (often still forming).
 */
export function detectTradePhases(
  candles: CandleOHLC[],
  sepMinPct: number = EMA_SEPARATION_PCT_MIN,
): PhaseEvent[] {
  if (candles.length < 22) return [];

  const closes = candles.map((c) => c.close);
  const ema9 = computeEma(closes, 9);
  const ema21 = computeEma(closes, 21);
  const out: PhaseEvent[] = [];
  const end = Math.max(1, candles.length - 1);

  let position: PositionState = "NEUTRAL";

  for (let i = 21; i < end; i += 1) {
    const cur9 = ema9[i];
    const cur21 = ema21[i];
    if (cur9 == null || cur21 == null) continue;

    const candle = candles[i];
    const { buyOk, sellOk, sepPct } = a4SideOk(cur9, cur21, candle.close, sepMinPct);
    const stepped = stepPosition(position, buyOk, sellOk);
    position = stepped.position;
    if (!stepped.phase) continue;

    out.push({
      time: candle.time,
      phase: stepped.phase,
      price: candle.close,
      reason: phaseLabel(stepped.phase, sepPct),
      position: stepped.position,
      sepPct,
    });
  }

  return out;
}

/** ENTRY markers only (includes flip → new side). */
export function detectEntrySignals(
  candles: CandleOHLC[],
  sepMinPct: number = EMA_SEPARATION_PCT_MIN,
): EmaSignal[] {
  return detectTradePhases(candles, sepMinPct)
    .filter(
      (e) =>
        e.phase === "ENTRY_BUY" ||
        e.phase === "ENTRY_SELL" ||
        e.phase === "FLIP_TO_LONG" ||
        e.phase === "FLIP_TO_SHORT",
    )
    .map((e) => ({
      time: e.time,
      side:
        e.phase === "ENTRY_BUY" || e.phase === "FLIP_TO_LONG" ? "buy" : "sell",
      price: e.price,
      reason: e.reason,
    }));
}

/** EXIT markers only (includes flip closes). */
export function detectExitSignals(
  candles: CandleOHLC[],
  sepMinPct: number = EMA_SEPARATION_PCT_MIN,
): EmaSignal[] {
  return detectTradePhases(candles, sepMinPct)
    .filter(
      (e) =>
        e.phase === "EXIT_BUY" ||
        e.phase === "EXIT_SELL" ||
        e.phase === "FLIP_TO_SHORT" ||
        e.phase === "FLIP_TO_LONG",
    )
    .map((e) => ({
      time: e.time,
      side:
        e.phase === "EXIT_BUY" || e.phase === "FLIP_TO_SHORT" ? "buy" : "sell",
      price: e.price,
      reason: e.reason,
    }));
}

export type StoryChartMarker = {
  time: number;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "circle" | "arrowUp" | "arrowDown";
  text: string;
};

/**
 * Chart markers:
 * - ENTRY / EXIT / FLIP with clear labels (no overlap on same candle)
 * - While setup holds: classic BUY / SELL arrows (only when A4 still true)
 */
export function buildChartStoryMarkers(phases: PhaseEvent[]): StoryChartMarker[] {
  const byTime = new Map<number, PhaseEvent[]>();
  for (const ev of phases) {
    if (
      ev.phase !== "ENTRY_BUY" &&
      ev.phase !== "ENTRY_SELL" &&
      ev.phase !== "EXIT_BUY" &&
      ev.phase !== "EXIT_SELL" &&
      ev.phase !== "FLIP_TO_SHORT" &&
      ev.phase !== "FLIP_TO_LONG" &&
      ev.phase !== "HOLD_LONG" &&
      ev.phase !== "HOLD_SHORT"
    ) {
      continue;
    }
    const list = byTime.get(ev.time) ?? [];
    list.push(ev);
    byTime.set(ev.time, list);
  }

  const markers: StoryChartMarker[] = [];

  for (const [time, events] of byTime) {
    const kinds = new Set(events.map((e) => e.phase));
    const flipShort =
      kinds.has("FLIP_TO_SHORT") ||
      (kinds.has("EXIT_BUY") && kinds.has("ENTRY_SELL"));
    const flipLong =
      kinds.has("FLIP_TO_LONG") ||
      (kinds.has("EXIT_SELL") && kinds.has("ENTRY_BUY"));

    if (flipShort) {
      markers.push({
        time,
        position: "aboveBar",
        color: "#ff1744",
        shape: "arrowDown",
        text: "EXIT LONG → ENTRY SHORT",
      });
      continue;
    }
    if (flipLong) {
      markers.push({
        time,
        position: "belowBar",
        color: "#00e676",
        shape: "arrowUp",
        text: "EXIT SHORT → ENTRY LONG",
      });
      continue;
    }

    // Prefer ENTRY/EXIT labels over HOLD arrows on the same bar.
    if (kinds.has("EXIT_BUY") || kinds.has("EXIT_SELL")) {
      const exit = events.find((e) => e.phase === "EXIT_BUY" || e.phase === "EXIT_SELL")!;
      markers.push({
        time,
        position: "aboveBar",
        color: "#b0bec5",
        shape: "circle",
        text: exit.phase === "EXIT_BUY" ? "EXIT LONG" : "EXIT SHORT",
      });
      continue;
    }
    if (kinds.has("ENTRY_BUY")) {
      markers.push({
        time,
        position: "belowBar",
        color: "#00e676",
        shape: "circle",
        text: "ENTRY BUY",
      });
      continue;
    }
    if (kinds.has("ENTRY_SELL")) {
      markers.push({
        time,
        position: "aboveBar",
        color: "#ff1744",
        shape: "arrowDown",
        text: "↓ ENTRY SELL",
      });
      continue;
    }

    if (kinds.has("HOLD_LONG")) {
      markers.push({
        time,
        position: "belowBar",
        color: "#26a69a",
        shape: "arrowUp",
        text: "BUY",
      });
    } else if (kinds.has("HOLD_SHORT")) {
      markers.push({
        time,
        position: "aboveBar",
        color: "#ef5350",
        shape: "arrowDown",
        text: "SELL",
      });
    }
  }

  return markers.sort((a, b) => a.time - b.time);
}

/**
 * @deprecated Prefer detectTradePhases — old every-bar BUY/SELL spam.
 * Kept as HOLD-compatible list for any leftover callers.
 */
export function detectEmaCrossSignals(
  candles: CandleOHLC[],
  sepMinPct: number = EMA_SEPARATION_PCT_MIN,
): EmaSignal[] {
  return detectTradePhases(candles, sepMinPct)
    .filter((e) => e.phase === "HOLD_LONG" || e.phase === "HOLD_SHORT")
    .map((e) => ({
      time: e.time,
      side: e.phase === "HOLD_LONG" ? "buy" : "sell",
      price: e.price,
      reason: e.reason,
    }));
}

/** Completed trades from ENTRY→EXIT / FLIP pairs (Signal exits only on chart). */
export function buildCompletedTrades(
  phases: PhaseEvent[],
  stakeUsd = 100,
): CompletedTrade[] {
  const trades: CompletedTrade[] = [];
  let open: PhaseEvent | null = null;
  let barsSinceEntry = 0;

  const closeOpen = (exitEv: PhaseEvent, side: "LONG" | "SHORT") => {
    if (!open) return;
    const entryPrice = open.price;
    const exitPrice = exitEv.price;
    const pnlPct =
      side === "LONG"
        ? ((exitPrice - entryPrice) / entryPrice) * 100
        : ((entryPrice - exitPrice) / entryPrice) * 100;
    trades.push({
      side,
      entryTime: open.time,
      exitTime: exitEv.time,
      entryPrice,
      exitPrice,
      pnlPct,
      pnlUsdEstimate: (pnlPct / 100) * stakeUsd,
      durationBars: barsSinceEntry + 1,
      exitReason: "Signal",
    });
    open = null;
    barsSinceEntry = 0;
  };

  for (const ev of phases) {
    if (ev.phase === "ENTRY_BUY" || ev.phase === "ENTRY_SELL") {
      open = ev;
      barsSinceEntry = 0;
      continue;
    }
    if (ev.phase === "HOLD_LONG" || ev.phase === "HOLD_SHORT") {
      if (open) barsSinceEntry += 1;
      continue;
    }
    if (ev.phase === "EXIT_BUY" && open?.phase === "ENTRY_BUY") {
      closeOpen(ev, "LONG");
      continue;
    }
    if (ev.phase === "EXIT_SELL" && open?.phase === "ENTRY_SELL") {
      closeOpen(ev, "SHORT");
      continue;
    }
    if (ev.phase === "FLIP_TO_SHORT" && open?.phase === "ENTRY_BUY") {
      closeOpen(ev, "LONG");
      open = { ...ev, phase: "ENTRY_SELL" };
      barsSinceEntry = 0;
      continue;
    }
    if (ev.phase === "FLIP_TO_LONG" && open?.phase === "ENTRY_SELL") {
      closeOpen(ev, "SHORT");
      open = { ...ev, phase: "ENTRY_BUY" };
      barsSinceEntry = 0;
    }
  }
  return trades;
}

/** Keep BUY → SELL → BUY… (drop same-side repeats until opposite fires). */
export function alternateSignals(signals: EmaSignal[]): EmaSignal[] {
  const out: EmaSignal[] = [];
  let last: SignalSide | null = null;
  for (const signal of signals) {
    if (last === signal.side) continue;
    out.push(signal);
    last = signal.side;
  }
  return out;
}

export function formatPhaseDisplay(phase: string): string {
  const map: Record<string, string> = {
    ENTRY_BUY: "ENTRY BUY",
    ENTRY_SELL: "ENTRY SELL",
    HOLD_LONG: "BUY",
    HOLD_SHORT: "SELL",
    EXIT_BUY: "EXIT LONG",
    EXIT_SELL: "EXIT SHORT",
    FLIP_TO_SHORT: "EXIT LONG → ENTRY SHORT",
    FLIP_TO_LONG: "EXIT SHORT → ENTRY LONG",
    BUY_TREND: "HOLD LONG",
    SELL_TREND: "HOLD SHORT",
    NONE: "WAIT",
  };
  return map[phase] ?? phase;
}
