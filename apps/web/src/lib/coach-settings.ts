import type { CandleInterval } from "@/lib/types";
import { resolveSlTpPct } from "@/lib/sl-tp";

export const COACH_SETTINGS_KEY = "pcc_coach_settings";
export const COACH_SETTINGS_EVENT = "pcc-coach-settings";
/**
 * Legacy key — always forced to "lab" on load. Kept so old A4/CCR values are
 * overwritten instead of resurrecting built-in strategies.
 */
export const ENTRY_SIGNAL_KEY = "pcc_entry_signal";
/**
 * Session AUTO on/off shared by Market + Coach so pausing on one tab is not
 * undone when opening the other. Falls back to `autoOnDefault` when unset.
 */
export const AUTO_SESSION_KEY = "pcc_auto_session";
export const AUTO_SESSION_EVENT = "pcc-auto-session";

/** Paper AUTO entry is Lab-only (user-prompted / promoted hypotheses). */
export type EntrySignal = "lab";

export type CoachSettings = {
  /** Always Lab — built-in A4/CCR entry sources are retired. */
  entrySignal: EntrySignal;
  /** Optional promoted Lab version; API falls back to latest promoted when unset. */
  labHypothesisId: string | null;
  /** Fixed USD stake passed to auto-tick (capped by cash only). */
  autoStakeUsd: number;
  /** How often the Market/Coach auto loop calls the API. */
  autoTickSeconds: number;
  /** Candle timeframe for signal + auto. */
  interval: CandleInterval;
  /** Start AUTO ON when opening Market/Coach. */
  autoOnDefault: boolean;
  /** Stop loss fraction as percent points, e.g. 2 = 2%. */
  slPct: number;
  /** Take profit fraction as percent points, e.g. 7.5 = 7.5%. */
  tpPct: number;
  /**
   * Absolute USD take-profit for AUTO exit (matches live unrealized P/L).
   * Close when unrealized ≥ this; 0 disables. Default $70.
   */
  tpUsd: number;
  /** Paper futures leverage (1–50). Stake USD = margin; notional = margin × leverage. */
  leverage: number;
  /** Minimum execution-cost-adjusted R:R required to open an entry. */
  minNetRr: number;
  /** Assumed adverse slippage for each fill when no execution model exists. */
  slippageBps: number;
  /** Assumed full bid/ask spread when no live order book is available. */
  spreadBps: number;
};

type CoachSettingsUpdate = Partial<Omit<CoachSettings, "entrySignal">>;

export const DEFAULT_COACH_SETTINGS: CoachSettings = {
  entrySignal: "lab",
  labHypothesisId: null,
  autoStakeUsd: 20000,
  autoTickSeconds: 60,
  interval: "15m",
  autoOnDefault: true,
  slPct: 2,
  tpPct: 7.5,
  tpUsd: 70,
  leverage: 5,
  minNetRr: 2,
  slippageBps: 3,
  spreadBps: 2,
};

const INTERVALS: CandleInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

function clamp(n: number, min: number, max: number): number {
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, n));
}

export function normalizeCoachSettings(
  raw: Partial<CoachSettings> | null | undefined,
): CoachSettings {
  const d = DEFAULT_COACH_SETTINGS;
  const interval = INTERVALS.includes(raw?.interval as CandleInterval)
    ? (raw!.interval as CandleInterval)
    : d.interval;
  return {
    entrySignal: "lab",
    labHypothesisId: typeof raw?.labHypothesisId === "string" ? raw.labHypothesisId : null,
    autoStakeUsd: clamp(Number(raw?.autoStakeUsd ?? d.autoStakeUsd), 0.5, 20000),
    autoTickSeconds: clamp(Number(raw?.autoTickSeconds ?? d.autoTickSeconds), 15, 600),
    interval,
    autoOnDefault: raw?.autoOnDefault ?? d.autoOnDefault,
    slPct: clamp(Number(raw?.slPct ?? d.slPct), 0.1, 20),
    tpPct: clamp(Number(raw?.tpPct ?? d.tpPct), 0.1, 50),
    tpUsd: clamp(Number(raw?.tpUsd ?? d.tpUsd), 0, 1_000_000),
    leverage: clamp(Number(raw?.leverage ?? d.leverage), 1, 50),
    minNetRr: clamp(Number(raw?.minNetRr ?? d.minNetRr), 0.1, 20),
    slippageBps: clamp(Number(raw?.slippageBps ?? d.slippageBps), 0, 100),
    spreadBps: clamp(Number(raw?.spreadBps ?? d.spreadBps), 0, 100),
  };
}

function persistMigratedLab(settings: CoachSettings): CoachSettings {
  if (typeof window === "undefined") return settings;
  window.localStorage.setItem(ENTRY_SIGNAL_KEY, "lab");
  window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(settings));
  return settings;
}

export function loadCoachSettings(): CoachSettings {
  if (typeof window === "undefined") return { ...DEFAULT_COACH_SETTINGS };
  try {
    const raw = window.localStorage.getItem(COACH_SETTINGS_KEY);
    if (!raw) {
      return persistMigratedLab({ ...DEFAULT_COACH_SETTINGS });
    }
    const parsed = JSON.parse(raw) as Record<string, unknown> & {
      stakeMigratedTo20?: boolean;
      stakeMigratedTo100?: boolean;
      stakeMigratedTo20000?: boolean;
      autoStakeUsd?: number;
      labHypothesisId?: string | null;
    };
    const legacyEntrySignal =
      typeof parsed.entrySignal === "string" ? parsed.entrySignal : null;
    // One-time: old default $5 → $20, then $20 → $100, then $100 → $20000 (user choice).
    if (!parsed.stakeMigratedTo20 && Number(parsed.autoStakeUsd) === 5) {
      parsed.autoStakeUsd = 20;
      parsed.stakeMigratedTo20 = true;
    }
    if (!parsed.stakeMigratedTo100 && Number(parsed.autoStakeUsd) === 20) {
      parsed.autoStakeUsd = 100;
      parsed.stakeMigratedTo100 = true;
    }
    if (!parsed.stakeMigratedTo20000 && Number(parsed.autoStakeUsd) === 100) {
      parsed.autoStakeUsd = 20000;
      parsed.stakeMigratedTo20000 = true;
    }
    const normalized = normalizeCoachSettings(parsed as Partial<CoachSettings>);
    const legacyEntry = window.localStorage.getItem(ENTRY_SIGNAL_KEY);
    const needsMigrate =
      legacyEntry !== "lab" ||
      legacyEntrySignal === "a4" ||
      legacyEntrySignal === "ccr" ||
      legacyEntrySignal == null;
    if (needsMigrate) {
      return persistMigratedLab(normalized);
    }
    return normalized;
  } catch {
    return persistMigratedLab({ ...DEFAULT_COACH_SETTINGS });
  }
}

/** @deprecated Entry is Lab-only; kept so callers still sync labHypothesisId flows. */
export function saveEntrySignal(_entrySignal: EntrySignal = "lab"): CoachSettings {
  if (typeof window === "undefined") {
    return { ...DEFAULT_COACH_SETTINGS };
  }
  const next = { ...loadCoachSettings(), entrySignal: "lab" as const };
  window.localStorage.setItem(ENTRY_SIGNAL_KEY, "lab");
  window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent(COACH_SETTINGS_EVENT, { detail: next }));
  return next;
}

export function loadAutoSession(defaultOn: boolean): boolean {
  if (typeof window === "undefined") return defaultOn;
  const raw = window.localStorage.getItem(AUTO_SESSION_KEY);
  if (raw === "1") return true;
  if (raw === "0") return false;
  return defaultOn;
}

export function saveAutoSession(enabled: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTO_SESSION_KEY, enabled ? "1" : "0");
  window.dispatchEvent(new CustomEvent(AUTO_SESSION_EVENT, { detail: enabled }));
}

export function saveLabHypothesisId(labHypothesisId: string | null): CoachSettings {
  const current = loadCoachSettings();
  const next = { ...current, entrySignal: "lab" as const, labHypothesisId };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ENTRY_SIGNAL_KEY, "lab");
    window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent(COACH_SETTINGS_EVENT, { detail: next }));
  }
  return next;
}

/**
 * Saves editable Coach settings only. Entry source is always Lab.
 */
export function saveCoachSettings(next: CoachSettingsUpdate): CoachSettings {
  const { entrySignal: _ignored, ...editable } = next as Partial<CoachSettings>;
  const current = loadCoachSettings();
  const merged = normalizeCoachSettings({
    ...current,
    ...editable,
    entrySignal: "lab",
  });
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ENTRY_SIGNAL_KEY, "lab");
    window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(merged));
    window.dispatchEvent(new CustomEvent(COACH_SETTINGS_EVENT, { detail: merged }));
  }
  return merged;
}

/** Explicitly restore Lab-oriented coach defaults. */
export function restoreCoachDefaults(): CoachSettings {
  if (typeof window === "undefined") return { ...DEFAULT_COACH_SETTINGS };
  const next = { ...DEFAULT_COACH_SETTINGS };
  window.localStorage.setItem(ENTRY_SIGNAL_KEY, "lab");
  window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(next));
  window.localStorage.removeItem(AUTO_SESSION_KEY);
  window.dispatchEvent(new CustomEvent(AUTO_SESSION_EVENT, { detail: next.autoOnDefault }));
  window.dispatchEvent(new CustomEvent(COACH_SETTINGS_EVENT, { detail: next }));
  return next;
}

/** Receipt-backed Kraken Pro paper fee % points per side. Round-trip = ×2. */
export const PAPER_FEE_PCT = 0.8;

/** Extra TP fraction so a win still nets ~tpPct after entry+exit fees. */
export function feeCoverTpFrac(
  tpPctPoints: number,
  feePctPoints: number = PAPER_FEE_PCT,
): number {
  return tpPctPoints / 100 + (feePctPoints * 2) / 100;
}

/** Fraction forms for API (0.02 = 2%). Scales SL/TP by coin class when symbol given. */
export function coachSettingsToApiParams(
  s: CoachSettings,
  symbol = "BTC",
): {
  sl_pct: number;
  tp_pct: number;
  min_net_rr: number;
  slippage_bps: number;
  spread_bps: number;
  entry_source: "lab";
  hypothesis_id: string | null;
} {
  const { slPct, tpPct } = resolveSlTpPct(symbol, s.slPct, s.tpPct);
  return {
    sl_pct: slPct / 100,
    tp_pct: tpPct / 100,
    min_net_rr: s.minNetRr,
    slippage_bps: s.slippageBps,
    spread_bps: s.spreadBps,
    entry_source: "lab",
    hypothesis_id: s.labHypothesisId,
  };
}
