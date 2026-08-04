"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BarCountdown } from "./bar-countdown";
import { HoldStatusCard } from "./hold-status-card";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { computeEma } from "@/lib/ema";
import {
  BASIC_EMA_RULES,
  buildChartStoryMarkers,
  buildCompletedTrades,
  detectExitSignals,
  detectEntrySignals,
  detectTradePhases,
  formatPhaseDisplay,
  type PhaseEvent,
} from "@/lib/ema-signals";
import { formatMoney } from "@/lib/format";
import { CandleInterval } from "@/lib/types";
import { cn } from "@/lib/utils";

const INTERVALS: { value: CandleInterval; label: string }[] = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1H" },
  { value: "4h", label: "4H" },
  { value: "1d", label: "1D" },
];

const TV = {
  bg: "#131722",
  panel: "#1e222d",
  border: "#2a2e39",
  text: "#d1d4dc",
  muted: "#787b86",
  grid: "#1e222d",
  up: "#26a69a",
  down: "#ef5350",
  ema9: "#f0b90b",
  ema21: "#2962ff",
};

type Props = {
  symbol: string;
  className?: string;
  height?: number;
  defaultInterval?: CandleInterval;
};

export function TradingChart({
  symbol,
  className,
  height = 420,
  defaultInterval = "15m",
}: Props) {
  const { settings } = useCoachSettings();
  const [interval, setInterval] = useState<CandleInterval>(defaultInterval);
  const [showAllSignals, setShowAllSignals] = useState(true);
  /** Keep chart glued to the latest candles on refresh (no manual scroll). */
  const [followLive, setFollowLive] = useState(true);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const ema9Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ema21Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const shouldFitRef = useRef(true);
  const followLiveRef = useRef(true);
  const pinningRef = useRef(false);
  const dataLenRef = useRef(0);

  useEffect(() => {
    followLiveRef.current = followLive;
  }, [followLive]);

  useEffect(() => {
    setInterval(settings.interval);
  }, [settings.interval]);

  const candlesQuery = useQuery({
    queryKey: ["candles", symbol, interval],
    queryFn: () => api.candles(symbol, interval, 500),
    refetchInterval: 30_000,
  });

  const positionQuery = useQuery({
    queryKey: ["position", symbol],
    queryFn: () => api.position(symbol).catch(() => null),
    refetchInterval: 15_000,
  });

  const candleSeries = useMemo(() => {
    const raw = candlesQuery.data?.candles ?? [];
    return raw.map((c) => ({
      time: c.time,
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    }));
  }, [candlesQuery.data]);

  const phases = useMemo(
    () => detectTradePhases(candleSeries, settings.emaSeparationPct),
    [candleSeries, settings.emaSeparationPct],
  );
  const entrySignals = useMemo(
    () => detectEntrySignals(candleSeries, settings.emaSeparationPct),
    [candleSeries, settings.emaSeparationPct],
  );
  const exitSignals = useMemo(
    () => detectExitSignals(candleSeries, settings.emaSeparationPct),
    [candleSeries, settings.emaSeparationPct],
  );
  const completedTrades = useMemo(
    () => buildCompletedTrades(phases, settings.autoStakeUsd),
    [phases, settings.autoStakeUsd],
  );
  const latestPhase = phases.at(-1) ?? null;
  const entryCount = entrySignals.length;
  const exitCount = exitSignals.length;
  const storyEvents = useMemo(
    () =>
      phases.filter(
        (p) =>
          p.phase === "ENTRY_BUY" ||
          p.phase === "ENTRY_SELL" ||
          p.phase === "EXIT_BUY" ||
          p.phase === "EXIT_SELL" ||
          p.phase === "FLIP_TO_LONG" ||
          p.phase === "FLIP_TO_SHORT",
      ),
    [phases],
  );
  const recentPhases = useMemo(
    () => [...storyEvents].reverse().slice(0, 24),
    [storyEvents],
  );
  const recentTrades = useMemo(
    () => [...completedTrades].reverse().slice(0, 8),
    [completedTrades],
  );

  const holdCard = useMemo(() => {
    const last = candleSeries.at(-1);
    const current = last?.close ?? null;
    if (current == null || !latestPhase) return null;

    const pos = positionQuery.data;
    const qty = pos ? Number(pos.quantity) : 0;
    const posSide =
      (pos?.side as string | undefined) ||
      (qty > 0 ? "long" : qty < 0 ? "short" : "flat");
    const paperSide =
      posSide === "long" || posSide === "short" ? (posSide as "long" | "short") : null;

    const findOpenEntry = (want: "ENTRY_BUY" | "ENTRY_SELL"): PhaseEvent | null => {
      const exitOf = want === "ENTRY_BUY" ? "EXIT_BUY" : "EXIT_SELL";
      const flipAway = want === "ENTRY_BUY" ? "FLIP_TO_SHORT" : "FLIP_TO_LONG";
      const flipInto = want === "ENTRY_BUY" ? "FLIP_TO_LONG" : "FLIP_TO_SHORT";
      for (let i = phases.length - 1; i >= 0; i -= 1) {
        const p = phases[i];
        if (p.phase === exitOf || p.phase === flipAway) return null;
        if (p.phase === want || p.phase === flipInto) {
          return p.phase === flipInto ? { ...p, phase: want } : p;
        }
      }
      return null;
    };

    // Only while A4 story is actively in a trade — never show leftover Desk fills alone.
    if (
      latestPhase.phase !== "HOLD_LONG" &&
      latestPhase.phase !== "HOLD_SHORT" &&
      latestPhase.phase !== "ENTRY_BUY" &&
      latestPhase.phase !== "ENTRY_SELL" &&
      latestPhase.phase !== "FLIP_TO_LONG" &&
      latestPhase.phase !== "FLIP_TO_SHORT"
    ) {
      return null;
    }

    const isLong =
      latestPhase.phase === "HOLD_LONG" ||
      latestPhase.phase === "ENTRY_BUY" ||
      latestPhase.phase === "FLIP_TO_LONG";
    const entryEv = isLong ? findOpenEntry("ENTRY_BUY") : findOpenEntry("ENTRY_SELL");
    if (!entryEv) return null;

    const side = isLong ? "long" : "short";
    const note =
      paperSide && paperSide !== side
        ? `Desk still ${paperSide.toUpperCase()} (not closed)`
        : null;

    return {
      side: side as "long" | "short",
      entryPrice: entryEv.price,
      currentPrice: current,
      entryTimeSec: entryEv.time,
      note,
    };
  }, [candleSeries, phases, latestPhase, positionQuery.data]);

  const formatSignalTime = (unixSec: number) => {
    try {
      return new Date(unixSec * 1000).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return String(unixSec);
    }
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    shouldFitRef.current = true;
    followLiveRef.current = true;
    setFollowLive(true);

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: TV.bg },
        textColor: TV.text,
        fontFamily: "Trebuchet MS, Roboto, Ubuntu, sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: TV.grid },
        horzLines: { color: TV.grid },
      },
      rightPriceScale: {
        borderColor: TV.border,
        scaleMargins: { top: 0.08, bottom: 0.12 },
      },
      timeScale: {
        borderColor: TV.border,
        timeVisible: true,
        secondsVisible: interval === "1m" || interval === "5m",
        rightOffset: 6,
        barSpacing: 8,
        minBarSpacing: 2,
        lockVisibleTimeRangeOnResize: true,
      },
      crosshair: {
        vertLine: { color: TV.muted, labelBackgroundColor: TV.panel },
        horzLine: { color: TV.muted, labelBackgroundColor: TV.panel },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: true,
        axisDoubleClickReset: true,
      },
    });

    const candles = chart.addCandlestickSeries({
      upColor: TV.up,
      downColor: TV.down,
      borderUpColor: TV.up,
      borderDownColor: TV.down,
      wickUpColor: TV.up,
      wickDownColor: TV.down,
    });
    const ema9 = chart.addLineSeries({
      color: TV.ema9,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "",
    });
    const ema21 = chart.addLineSeries({
      color: TV.ema21,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "",
    });

    chartRef.current = chart;
    candleRef.current = candles;
    ema9Ref.current = ema9;
    ema21Ref.current = ema21;

    const onRange = () => {
      if (pinningRef.current || !followLiveRef.current) return;
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range) return;
      const lastIdx = Math.max(0, dataLenRef.current - 1);
      if (range.to < lastIdx - 3) {
        followLiveRef.current = false;
        setFollowLive(false);
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);

    const ro = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      ema9Ref.current = null;
      ema21Ref.current = null;
    };
  }, [height, interval, symbol]);

  useEffect(() => {
    if (
      !candleSeries.length ||
      !candleRef.current ||
      !ema9Ref.current ||
      !ema21Ref.current
    ) {
      return;
    }

    const candleData = candleSeries.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const closes = candleData.map((c) => c.close);
    const ema9 = computeEma(closes, 9);
    const ema21 = computeEma(closes, 21);

    const timeScale = chartRef.current?.timeScale();
    dataLenRef.current = candleData.length;

    candleRef.current.setData(candleData);
    ema9Ref.current.setData(
      candleData
        .map((c, i) =>
          ema9[i] == null ? null : { time: c.time, value: ema9[i] as number },
        )
        .filter((x): x is { time: UTCTimestamp; value: number } => x != null),
    );
    ema21Ref.current.setData(
      candleData
        .map((c, i) =>
          ema21[i] == null ? null : { time: c.time, value: ema21[i] as number },
        )
        .filter((x): x is { time: UTCTimestamp; value: number } => x != null),
    );

    const storyMarkers = showAllSignals
      ? buildChartStoryMarkers(phases).map((m) => ({
          time: m.time as UTCTimestamp,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }))
      : [];
    // One marker per story event — combined flip labels prevent EXIT/ENTRY overlap.
    candleRef.current.setMarkers(storyMarkers);

    // Stick to the live right edge when Follow is on (keeps this corner view on refresh).
    pinningRef.current = true;
    if (shouldFitRef.current || followLiveRef.current) {
      timeScale?.scrollToRealTime();
      shouldFitRef.current = false;
    }
    requestAnimationFrame(() => {
      pinningRef.current = false;
    });
  }, [candleSeries, phases, showAllSignals, followLive]);

  const last = candleSeries.at(-1);
  const lastClose = last?.close ?? null;
  const lastOpen = last?.open ?? null;
  const up = lastClose != null && lastOpen != null && lastClose >= lastOpen;

  return (
    <div
      className={cn("overflow-hidden rounded-lg border", className)}
      style={{ borderColor: TV.border, background: TV.bg }}
    >
      <div
        className="flex flex-wrap items-center gap-2 border-b px-3 py-2"
        style={{ borderColor: TV.border, background: TV.panel }}
      >
        <div className="mr-2 flex min-w-0 flex-col">
          <span className="text-sm font-semibold tracking-wide" style={{ color: TV.text }}>
            {symbol}/USDT
          </span>
          <span className="text-[11px]" style={{ color: TV.muted }}>
            ENTRY → HOLD → EXIT · EMA9/21 · gap over 0.10%
          </span>
        </div>
        {lastClose != null && (
          <span
            className="mr-auto font-mono text-sm font-semibold"
            style={{ color: up ? TV.up : TV.down }}
          >
            {formatMoney(lastClose)}
          </span>
        )}
        <div className="flex flex-wrap gap-1">
          <Button
            type="button"
            size="sm"
            variant={showAllSignals ? "default" : "secondary"}
            className="h-7 px-2 text-xs"
            onClick={() => setShowAllSignals((v) => !v)}
          >
            {showAllSignals
              ? `Hide markers (${entryCount + exitCount})`
              : `Show ENTRY/EXIT (${entryCount + exitCount})`}
          </Button>
          {INTERVALS.map((item) => (
            <Button
              key={item.value}
              type="button"
              size="sm"
              variant={interval === item.value ? "default" : "ghost"}
              className={cn(
                "h-7 px-2 text-xs",
                interval !== item.value && "text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-white",
              )}
              onClick={() => setInterval(item.value)}
            >
              {item.label}
            </Button>
          ))}
          <Button
            type="button"
            size="sm"
            variant={followLive ? "default" : "secondary"}
            className="h-7 px-2 text-xs"
            onClick={() => {
              setFollowLive(true);
              followLiveRef.current = true;
              pinningRef.current = true;
              chartRef.current?.timeScale().scrollToRealTime();
              requestAnimationFrame(() => {
                pinningRef.current = false;
              });
            }}
            title="Keep view on the latest candles when data updates"
          >
            {followLive ? "Follow live · ON" : "Follow live"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-white"
            onClick={() => chartRef.current?.timeScale().fitContent()}
            title="Fit all candles"
          >
            Fit
          </Button>
        </div>
      </div>

      <div className="border-b px-3 py-2" style={{ borderColor: TV.border, background: "#161a25" }}>
        <BarCountdown interval={interval} compact className="border-[#2a2e39] bg-[#1c2130] text-[#d1d4dc]" />
      </div>

      <div
        className="flex flex-wrap items-start gap-3 border-b px-3 py-2 text-[11px]"
        style={{ borderColor: TV.border, background: "#161a25", color: TV.muted }}
      >
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="font-medium" style={{ color: TV.text }}>
            Active rule: {BASIC_EMA_RULES.label}
          </p>
          <p>
            <span style={{ color: "#00e676" }}>ENTRY</span> — {BASIC_EMA_RULES.buy}
          </p>
          <p>
            <span style={{ color: "#b0bec5" }}>EXIT</span> — {BASIC_EMA_RULES.exits}
          </p>
          <p>{BASIC_EMA_RULES.alternate}</p>
        </div>
        <div className="shrink-0 text-right">
          {latestPhase ? (
            <>
              <p
                className="text-sm font-semibold"
                style={{
                  color:
                    latestPhase.phase.startsWith("ENTRY") || latestPhase.phase.includes("LONG")
                      ? latestPhase.phase.includes("SHORT") || latestPhase.phase === "EXIT_SELL"
                        ? TV.down
                        : TV.up
                      : latestPhase.phase.includes("SHORT") || latestPhase.phase === "EXIT_SELL"
                        ? TV.down
                        : TV.muted,
                }}
              >
                {formatPhaseDisplay(latestPhase.phase)}
              </p>
              <p>{formatMoney(latestPhase.price)}</p>
              <p className="max-w-[220px]">{latestPhase.reason}</p>
              <p className="mt-1">
                {showAllSignals
                  ? `${entryCount} ENTRY · ${exitCount} EXIT · ${completedTrades.length} closed trades`
                  : "Press “Show ENTRY/EXIT” to draw markers"}
              </p>
            </>
          ) : (
            <p>No phase on this window yet</p>
          )}
        </div>
      </div>

      <div className="relative">
        {candlesQuery.isLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#131722]/80">
            <Skeleton className="h-8 w-40 bg-[#2a2e39]" />
          </div>
        )}
        {candlesQuery.isError && (
          <div className="p-4">
            <Alert variant="destructive">
              <AlertTitle>Chart unavailable</AlertTitle>
              <AlertDescription>{(candlesQuery.error as Error).message}</AlertDescription>
            </Alert>
          </div>
        )}
        {holdCard && (
          <HoldStatusCard
            side={holdCard.side}
            entryPrice={holdCard.entryPrice}
            currentPrice={holdCard.currentPrice}
            entryTimeSec={holdCard.entryTimeSec}
            note={holdCard.note}
          />
        )}
        <div ref={containerRef} style={{ height }} />
      </div>

      {showAllSignals && recentPhases.length > 0 && (
        <div
          className="max-h-48 overflow-auto border-t px-3 py-2 text-[11px]"
          style={{ borderColor: TV.border, background: "#161a25", color: TV.muted }}
        >
          <p className="mb-1.5 font-medium" style={{ color: TV.text }}>
            Trade story — ENTRY / EXIT only (latest {recentPhases.length} of{" "}
            {storyEvents.length})
          </p>
          <ul className="space-y-1">
            {recentPhases.map((s) => {
              const color =
                s.phase === "ENTRY_BUY" || s.phase === "FLIP_TO_LONG"
                  ? "#00e676"
                  : s.phase === "ENTRY_SELL" || s.phase === "FLIP_TO_SHORT"
                    ? "#ff1744"
                    : "#b0bec5";
              return (
                <li key={`${s.phase}-${s.time}`} className="flex flex-wrap gap-x-2 gap-y-0.5">
                  <span className="font-semibold" style={{ color }}>
                    {formatPhaseDisplay(s.phase)}
                  </span>
                  <span>{formatSignalTime(s.time)}</span>
                  <span>{formatMoney(s.price)}</span>
                  <span className="opacity-80">{s.reason}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {showAllSignals && recentTrades.length > 0 && (
        <div
          className="max-h-40 overflow-auto border-t px-3 py-2 text-[11px]"
          style={{ borderColor: TV.border, background: "#161a25", color: TV.muted }}
        >
          <p className="mb-1.5 font-medium" style={{ color: TV.text }}>
            Completed trades (ENTRY count {entryCount} · closed {completedTrades.length})
          </p>
          <ul className="space-y-1">
            {recentTrades.map((t) => (
              <li
                key={`${t.side}-${t.entryTime}-${t.exitTime}`}
                className="flex flex-wrap gap-x-2 gap-y-0.5"
              >
                <span
                  className="font-semibold"
                  style={{ color: t.pnlPct >= 0 ? TV.up : TV.down }}
                >
                  {t.side}
                </span>
                <span>
                  {formatSignalTime(t.entryTime)} → {formatSignalTime(t.exitTime)}
                </span>
                <span>
                  {formatMoney(t.entryPrice)} → {formatMoney(t.exitPrice)}
                </span>
                <span>
                  {t.pnlPct >= 0 ? "+" : ""}
                  {t.pnlPct.toFixed(2)}% · ${t.pnlUsdEstimate.toFixed(2)}
                </span>
                <span>
                  {t.durationBars} bars · {t.exitReason}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div
        className="flex flex-wrap items-center gap-4 border-t px-3 py-1.5 text-[11px]"
        style={{ borderColor: TV.border, background: TV.panel, color: TV.muted }}
      >
        <span className="inline-flex items-center gap-1.5" style={{ color: TV.up }}>
          ▲ BUY (while setup holds)
        </span>
        <span className="inline-flex items-center gap-1.5" style={{ color: TV.down }}>
          ▼ SELL (while setup holds)
        </span>
        <span className="inline-flex items-center gap-1.5" style={{ color: "#00e676" }}>
          ● ENTRY
        </span>
        <span className="inline-flex items-center gap-1.5" style={{ color: "#b0bec5" }}>
          ● EXIT (setup broken)
        </span>
        <span className="ml-auto">
          {showAllSignals ? "Showing" : "Hidden"} · EXIT when A4 breaks · Source:{" "}
          {candlesQuery.data?.source ?? "—"} · paper only
        </span>
      </div>
    </div>
  );
}
