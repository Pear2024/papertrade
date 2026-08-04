import type { CandleInterval } from "@/lib/types";
import { resolveSlTpPct } from "@/lib/sl-tp";

export const COACH_SETTINGS_KEY = "pcc_coach_settings";
export const COACH_SETTINGS_EVENT = "pcc-coach-settings";

export type CoachSettings = {
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
  /** Take profit fraction as percent points, e.g. 3 = 3%. */
  tpPct: number;
  /**
   * Absolute USD take-profit for AUTO exit (matches live unrealized P/L).
   * Close when unrealized ≥ this; 0 disables. Default $70.
   */
  tpUsd: number;
  /** Min |EMA9−EMA21| as % of close, e.g. 0.10. */
  emaSeparationPct: number;
  /** Paper futures leverage (1–50). Stake USD = margin; notional = margin × leverage. */
  leverage: number;
};

export const DEFAULT_COACH_SETTINGS: CoachSettings = {
  autoStakeUsd: 20000,
  autoTickSeconds: 60,
  interval: "15m",
  autoOnDefault: true,
  slPct: 2,
  tpPct: 3,
  tpUsd: 70,
  emaSeparationPct: 0.1,
  leverage: 5,
};

const INTERVALS: CandleInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

function clamp(n: number, min: number, max: number): number {
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, n));
}

export function normalizeCoachSettings(raw: Partial<CoachSettings> | null | undefined): CoachSettings {
  const d = DEFAULT_COACH_SETTINGS;
  const interval = INTERVALS.includes(raw?.interval as CandleInterval)
    ? (raw!.interval as CandleInterval)
    : d.interval;
  return {
    autoStakeUsd: clamp(Number(raw?.autoStakeUsd ?? d.autoStakeUsd), 0.5, 20000),
    autoTickSeconds: clamp(Number(raw?.autoTickSeconds ?? d.autoTickSeconds), 15, 600),
    interval,
    autoOnDefault: raw?.autoOnDefault ?? d.autoOnDefault,
    slPct: clamp(Number(raw?.slPct ?? d.slPct), 0.1, 20),
    tpPct: clamp(Number(raw?.tpPct ?? d.tpPct), 0.1, 50),
    tpUsd: clamp(Number(raw?.tpUsd ?? d.tpUsd), 0, 1_000_000),
    emaSeparationPct: clamp(Number(raw?.emaSeparationPct ?? d.emaSeparationPct), 0.01, 5),
    leverage: clamp(Number(raw?.leverage ?? d.leverage), 1, 50),
  };
}

export function loadCoachSettings(): CoachSettings {
  if (typeof window === "undefined") return { ...DEFAULT_COACH_SETTINGS };
  try {
    const raw = window.localStorage.getItem(COACH_SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_COACH_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<CoachSettings> & {
      stakeMigratedTo20?: boolean;
      stakeMigratedTo100?: boolean;
      stakeMigratedTo20000?: boolean;
    };
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
      const migrated = normalizeCoachSettings({ ...parsed, autoStakeUsd: 20000 });
      window.localStorage.setItem(
        COACH_SETTINGS_KEY,
        JSON.stringify({
          ...migrated,
          stakeMigratedTo20: true,
          stakeMigratedTo100: true,
          stakeMigratedTo20000: true,
        }),
      );
      return migrated;
    }
    return normalizeCoachSettings(parsed);
  } catch {
    return { ...DEFAULT_COACH_SETTINGS };
  }
}

export function saveCoachSettings(next: Partial<CoachSettings>): CoachSettings {
  const merged = normalizeCoachSettings({ ...loadCoachSettings(), ...next });
  if (typeof window !== "undefined") {
    window.localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(merged));
    window.dispatchEvent(new CustomEvent(COACH_SETTINGS_EVENT, { detail: merged }));
  }
  return merged;
}

/** Paper fee % points per side (matches API default / Kraken Futures Tier 1 taker). Round-trip = ×2. */
/** Prefer server account settings when available. */
export const PAPER_FEE_PCT = 0.05;

/** Extra TP fraction so a win still nets ~tpPct after entry+exit fees. */
export function feeCoverTpFrac(tpPctPoints: number, feePctPoints: number = PAPER_FEE_PCT): number {
  return tpPctPoints / 100 + (feePctPoints * 2) / 100;
}

/** Fraction forms for API (0.02 = 2%). Scales SL/TP by coin class when symbol given. */
export function coachSettingsToApiParams(
  s: CoachSettings,
  symbol = "BTC",
): {
  sl_pct: number;
  tp_pct: number;
  ema_sep_pct: number;
} {
  const { slPct, tpPct } = resolveSlTpPct(symbol, s.slPct, s.tpPct);
  return {
    sl_pct: slPct / 100,
    tp_pct: tpPct / 100,
    ema_sep_pct: s.emaSeparationPct,
  };
}
