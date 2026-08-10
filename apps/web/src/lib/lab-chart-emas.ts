/** Resolve which EMA periods the Market/Coach chart should draw from Lab rules. */

export const DEFAULT_CHART_EMAS = [9, 21] as const;
export const MAX_CHART_EMAS = 5;

const EMA_COLORS: Record<number, string> = {
  9: "#f0b90b",
  12: "#26a69a",
  21: "#2962ff",
  26: "#7e57c2",
  50: "#ab47bc",
  100: "#00acc1",
  200: "#ff7043",
};

const FALLBACK_COLORS = ["#f0b90b", "#2962ff", "#ab47bc", "#26a69a", "#ff7043"];

export function emaColor(period: number, index = 0): string {
  return EMA_COLORS[period] ?? FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

export function normalizeChartEmas(values: unknown): number[] {
  if (!Array.isArray(values)) return [];
  const seen = new Set<number>();
  const out: number[] = [];
  for (const raw of values) {
    const period = Number(raw);
    if (!Number.isFinite(period)) continue;
    const n = Math.round(period);
    if (n < 2 || n > 500 || seen.has(n)) continue;
    seen.add(n);
    out.push(n);
  }
  return out.sort((a, b) => a - b).slice(0, MAX_CHART_EMAS);
}

/** Read chart EMA periods from Lab structured rules / paper profile (fallback 9+21). */
export function chartEmasFromRules(rules: Record<string, unknown> | null | undefined): number[] {
  if (!rules) return [...DEFAULT_CHART_EMAS];
  const fromField = normalizeChartEmas(rules.chart_emas);
  if (fromField.length) return fromField;

  const filters = (rules.filters ?? {}) as Record<string, unknown>;
  const periods: number[] = [];
  if (filters.ema_trend) periods.push(9, 21);
  if (filters.htf_ema200) periods.push(200);
  const derived = normalizeChartEmas(periods);
  return derived.length ? derived : [...DEFAULT_CHART_EMAS];
}
