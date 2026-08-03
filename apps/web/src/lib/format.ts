export function formatMoney(value: string | number | null | undefined, digits = 2): string {
  const n = Number(value ?? 0);
  if (Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

export function formatQty(value: string | number | null | undefined, digits = 8): string {
  const n = Number(value ?? 0);
  if (Number.isNaN(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value: string | number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function pnlTone(value: string | number | null | undefined): "profit" | "loss" | "flat" {
  const n = Number(value ?? 0);
  if (n > 0) return "profit";
  if (n < 0) return "loss";
  return "flat";
}

export function pnlLabel(value: string | number | null | undefined): string {
  const tone = pnlTone(value);
  if (tone === "profit") return "Profit";
  if (tone === "loss") return "Loss";
  return "Flat";
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
