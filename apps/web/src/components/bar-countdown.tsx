"use client";

import { useEffect, useState } from "react";

import { CandleInterval } from "@/lib/types";
import { cn } from "@/lib/utils";

const INTERVAL_SECONDS: Record<CandleInterval, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }
  return `${m}:${String(sec).padStart(2, "0")}`;
}

export type BarClock = {
  intervalSeconds: number;
  elapsed: number;
  remaining: number;
  progressPct: number;
  closesSoon: boolean;
  barClosedJustNow: boolean;
};

/** UTC-aligned candle clock (matches Binance bar boundaries). */
export function getBarClock(interval: CandleInterval, nowMs = Date.now()): BarClock {
  const intervalSeconds = INTERVAL_SECONDS[interval];
  const nowSec = Math.floor(nowMs / 1000);
  const elapsed = nowSec % intervalSeconds;
  const remaining = intervalSeconds - elapsed;
  const progressPct = (elapsed / intervalSeconds) * 100;
  return {
    intervalSeconds,
    elapsed,
    remaining,
    progressPct,
    closesSoon: remaining <= 60,
    barClosedJustNow: remaining === intervalSeconds || elapsed === 0,
  };
}

type Props = {
  interval: CandleInterval;
  className?: string;
  /** Emphasize when used on the primary 15m desk */
  compact?: boolean;
};

/**
 * Live countdown for the current candle — how much of the TF has passed / is left.
 */
export function BarCountdown({ interval, className, compact = false }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const clock = getBarClock(interval, now);
  const closing = clock.closesSoon;

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2.5",
        closing
          ? "border-amber-500/50 bg-amber-500/10"
          : "border-border bg-muted/40",
        className,
      )}
      aria-live="polite"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {interval} candle clock
        </p>
        <p
          className={cn(
            "font-mono text-xs",
            closing ? "font-semibold text-amber-700 dark:text-amber-300" : "text-muted-foreground",
          )}
        >
          {closing ? "Closing soon" : "In progress"}
        </p>
      </div>

      <div className={cn("mt-1 flex flex-wrap items-end justify-between gap-3", !compact && "mt-2")}>
        <div>
          <p className="text-xs text-muted-foreground">Time left</p>
          <p
            className={cn(
              "font-mono font-semibold tracking-tight tabular-nums",
              compact ? "text-2xl" : "text-3xl",
              closing && "text-amber-700 dark:text-amber-300",
            )}
          >
            {formatClock(clock.remaining)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Elapsed</p>
          <p className="font-mono text-lg tabular-nums text-foreground/90">
            {formatClock(clock.elapsed)}
            <span className="text-sm text-muted-foreground">
              {" "}
              / {formatClock(clock.intervalSeconds)}
            </span>
          </p>
        </div>
      </div>

      <div
        className="mt-2 h-2.5 overflow-hidden rounded-full bg-background/80"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(clock.progressPct)}
        aria-label={`${interval} candle progress`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-1000 ease-linear",
            closing ? "bg-amber-500" : "bg-primary",
          )}
          style={{ width: `${Math.min(100, clock.progressPct)}%` }}
        />
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">
        {Math.round(clock.progressPct)}% of this {interval} bar used
        {closing
          ? " — coach can act after close (WAIT until then)."
          : " — signal waits for a closed bar."}
      </p>
    </div>
  );
}
