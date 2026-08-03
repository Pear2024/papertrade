"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export type HoldSide = "long" | "short";

type Props = {
  side: HoldSide;
  entryPrice: number;
  currentPrice: number;
  /** Unix seconds when this hold started (ENTRY bar / fill time). */
  entryTimeSec: number;
  /** Optional note when Desk paper side differs from signal story. */
  note?: string | null;
  className?: string;
};

function formatHoldDuration(entryUnixSec: number, nowMs: number): string {
  const sec = Math.max(0, Math.floor((nowMs - entryUnixSec * 1000) / 1000));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${sec}s`;
}

function formatPx(n: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(n);
}

export function HoldStatusCard({
  side,
  entryPrice,
  currentPrice,
  entryTimeSec,
  note,
  className,
}: Props) {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const isLong = side === "long";
  const pnlPct = isLong
    ? ((currentPrice - entryPrice) / entryPrice) * 100
    : ((entryPrice - currentPrice) / entryPrice) * 100;
  const pnlPositive = pnlPct >= 0;
  const accent = isLong ? "#00e676" : "#ff1744";
  const label = isLong ? "HOLD LONG" : "HOLD SHORT";
  const timeLabel = formatHoldDuration(entryTimeSec, nowMs);

  return (
    <div
      className={cn(
        "pointer-events-none absolute left-3 top-3 z-20 min-w-[168px] rounded-xl border px-3.5 py-3 shadow-lg backdrop-blur-md",
        className,
      )}
      style={{
        background: "rgba(19, 23, 34, 0.88)",
        borderColor: isLong ? "rgba(0, 230, 118, 0.35)" : "rgba(255, 23, 68, 0.35)",
        boxShadow: isLong
          ? "0 0 24px rgba(0, 230, 118, 0.12)"
          : "0 0 24px rgba(255, 23, 68, 0.12)",
      }}
      aria-live="polite"
    >
      <div className="mb-2.5 flex items-center gap-2">
        <span
          className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
          style={{
            background: accent,
            boxShadow: `0 0 10px ${accent}, 0 0 18px ${accent}`,
          }}
        />
        <span className="text-sm font-semibold tracking-wide" style={{ color: accent }}>
          {label}
        </span>
      </div>
      <dl
        className="space-y-1 font-mono text-[12px] leading-relaxed"
        style={{ color: "#c4b59a" }}
      >
        <div className="flex justify-between gap-4">
          <dt className="opacity-80">Entry:</dt>
          <dd className="tabular-nums">{formatPx(entryPrice)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="opacity-80">Current:</dt>
          <dd className="tabular-nums">{formatPx(currentPrice)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="opacity-80">PnL:</dt>
          <dd
            className="tabular-nums font-semibold"
            style={{ color: pnlPositive ? "#00e676" : "#ff1744" }}
          >
            {pnlPositive ? "+" : ""}
            {pnlPct.toFixed(2)}%
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="opacity-80">Time:</dt>
          <dd className="tabular-nums">{timeLabel}</dd>
        </div>
      </dl>
      {note ? (
        <p className="mt-2 max-w-[200px] text-[10px] leading-snug" style={{ color: "#ef5350" }}>
          {note}
        </p>
      ) : null}
    </div>
  );
}
