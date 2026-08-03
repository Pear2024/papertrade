/** Exponential moving average — seed with SMA of the first `period` closes. */
export function computeEma(closes: number[], period: number): (number | null)[] {
  if (period < 1 || closes.length === 0) return closes.map(() => null);
  const k = 2 / (period + 1);
  const out: (number | null)[] = Array(closes.length).fill(null);
  if (closes.length < period) return out;

  let sum = 0;
  for (let i = 0; i < period; i += 1) sum += closes[i];
  let prev = sum / period;
  out[period - 1] = prev;

  for (let i = period; i < closes.length; i += 1) {
    prev = closes[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}
