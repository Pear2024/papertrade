/** Per-coin SL/TP helpers — same base % from Settings, scaled by coin class. */

export type SlTpPct = { slPct: number; tpPct: number };

/** Volatility class: majors tighter, memes wider. */
export function coinSlTpMultiplier(symbol: string): number {
  const s = symbol.toUpperCase();
  if (s === "BTC" || s === "ETH") return 1;
  if (["DOGE", "SHIB", "PEPE", "WIF"].includes(s)) return 2.5;
  if (["SOL", "BNB", "XRP", "ADA", "AVAX", "LINK", "DOT", "LTC", "TON"].includes(s)) {
    return 1.25;
  }
  return 1.5; // other alts
}

export function resolveSlTpPct(
  symbol: string,
  baseSlPct: number,
  baseTpPct: number,
): SlTpPct {
  const m = coinSlTpMultiplier(symbol);
  const slPct = Math.min(20, Math.max(0.1, Number((baseSlPct * m).toFixed(2))));
  const tpPct = Math.min(50, Math.max(0.1, Number((baseTpPct * m).toFixed(2))));
  return { slPct, tpPct };
}

/** Format an exit price with the asset's price precision (not always 2 dp). */
export function formatExitPrice(price: number, pricePrecision = 2): string {
  const digits = Math.min(8, Math.max(0, Math.floor(pricePrecision)));
  if (!Number.isFinite(price)) return "";
  return price.toFixed(digits);
}

export function exitPriceDigits(pricePrecision = 2): number {
  return Math.min(8, Math.max(0, Math.floor(pricePrecision)));
}
