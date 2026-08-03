import { formatMoney, formatPercent, pnlLabel, pnlTone } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PnlText({
  value,
  asPercent = false,
  digits,
  className,
}: {
  value: string | number | null | undefined;
  asPercent?: boolean;
  /** Money decimal places (auto: 4 when |value| < 1, else 2). */
  digits?: number;
  className?: string;
}) {
  const tone = pnlTone(value);
  const label = pnlLabel(value);
  const n = Number(value ?? 0);
  const moneyDigits =
    digits ?? (Number.isFinite(n) && Math.abs(n) > 0 && Math.abs(n) < 1 ? 4 : 2);
  const text = asPercent ? formatPercent(value) : formatMoney(value, moneyDigits);

  return (
    <span
      className={cn(
        "font-medium tabular-nums",
        tone === "profit" && "text-success",
        tone === "loss" && "text-destructive",
        tone === "flat" && "text-muted-foreground",
        className,
      )}
    >
      <span className="sr-only">{label}: </span>
      {text}
      <span className="ml-1 text-xs font-normal text-muted-foreground">({label})</span>
    </span>
  );
}
