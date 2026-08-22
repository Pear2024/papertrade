"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
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
import { coachSettingsToApiParams } from "@/lib/coach-settings";
import { computeEma } from "@/lib/ema";
import {
  buildCoachHistoryMarkers,
  mergeLiveCoachSignalMarker,
} from "@/lib/ema-signals";
import { formatMoney } from "@/lib/format";
import {
  chartEmasFromRules,
  emaColor,
} from "@/lib/lab-chart-emas";
import { formatLabProfileLabel, labProfileNumbers } from "@/lib/lab-profile-label";
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
  const { settings, update } = useCoachSettings();
  const [interval, setIntervalState] = useState<CandleInterval>(defaultInterval);
  const [followLive, setFollowLive] = useState(true);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<Map<number, ISeriesApi<"Line">>>(new Map());
  const shouldFitRef = useRef(true);
  const followLiveRef = useRef(true);
  const pinningRef = useRef(false);
  const dataLenRef = useRef(0);

  useEffect(() => {
    followLiveRef.current = followLive;
  }, [followLive]);

  useEffect(() => {
    setIntervalState(settings.interval);
  }, [settings.interval]);

  const setInterval = (next: CandleInterval) => {
    setIntervalState(next);
    update({ interval: next });
  };

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

  const labQuery = useQuery({
    queryKey: ["hypothesis-lab"],
    queryFn: api.hypothesisLab,
    staleTime: 30_000,
  });
  const activeLab = useMemo(() => {
    const promoted = (labQuery.data?.items ?? []).filter((item) => item.promoted_at);
    return promoted.find((item) => item.id === settings.labHypothesisId) ?? promoted[0] ?? null;
  }, [labQuery.data, settings.labHypothesisId]);
  const profileNumbers = useMemo(
    () => labProfileNumbers(labQuery.data?.items ?? []),
    [labQuery.data?.items],
  );
  const activeLabLabel = useMemo(
    () =>
      activeLab
        ? formatLabProfileLabel(activeLab, profileNumbers.get(activeLab.id) ?? null)
        : null,
    [activeLab, profileNumbers],
  );

  const emaPeriods = useMemo(
    () => chartEmasFromRules(activeLab?.structured_rules ?? null),
    [activeLab],
  );
  const emaPeriodsKey = emaPeriods.join(",");

  const ruleOpts = useMemo(
    () => coachSettingsToApiParams(settings, symbol),
    [settings, symbol],
  );

  const historyQuery = useQuery({
    queryKey: ["coach-signal-history", symbol, interval],
    queryFn: () => api.coachSignalHistory({ symbol, interval, limit: 500 }),
    refetchInterval: 30_000,
  });

  const signalQuery = useQuery({
    queryKey: [
      "coach-signal",
      symbol,
      interval,
      ruleOpts.sl_pct,
      ruleOpts.tp_pct,
      ruleOpts.min_net_rr,
      ruleOpts.slippage_bps,
      ruleOpts.spread_bps,
      "lab",
      activeLab?.id,
      settings.autoStakeUsd,
      settings.leverage,
    ],
    queryFn: () =>
      api.coachSignal(symbol, interval, {
        slPct: ruleOpts.sl_pct,
        tpPct: ruleOpts.tp_pct,
        minNetRr: ruleOpts.min_net_rr,
        slippageBps: ruleOpts.slippage_bps,
        spreadBps: ruleOpts.spread_bps,
        notionalUsd: settings.autoStakeUsd * settings.leverage,
        entrySource: "lab",
        hypothesisId: activeLab?.id,
      }),
    enabled: Boolean(activeLab?.id),
    staleTime: 15_000,
  });

  const candleSeries = useMemo(() => {
    const raw = candlesQuery.data?.candles ?? [];
    return raw.map((c) => ({
      time: Number(c.time),
      open: Number(c.open),
      high: Number(c.high),
      low: Number(c.low),
      close: Number(c.close),
    }));
  }, [candlesQuery.data]);

  const holdCard = useMemo(() => {
    const last = candleSeries.at(-1);
    const current = last?.close ?? null;
    const pos = positionQuery.data;
    const qty = pos ? Number(pos.quantity) : 0;
    const posSide =
      (pos?.side as string | undefined) ||
      (qty > 0 ? "long" : qty < 0 ? "short" : "flat");
    if (current == null || (posSide !== "long" && posSide !== "short")) return null;
    return {
      side: posSide as "long" | "short",
      entryPrice: Number(pos?.average_entry_price ?? current),
      currentPrice: current,
      entryTimeSec: Math.floor(Date.now() / 1000) - 60,
      note: activeLabLabel ? `Lab ${activeLabLabel}` : "Lab paper position",
    };
  }, [candleSeries, positionQuery.data, activeLabLabel]);

  const chartMarkers = useMemo(() => {
    const candleTimes = new Set(candleSeries.map((c) => c.time));
    const fromHistory = buildCoachHistoryMarkers(historyQuery.data?.items ?? []);
    const merged = mergeLiveCoachSignalMarker(fromHistory, signalQuery.data);
    return merged.filter((m) => candleTimes.has(m.time));
  }, [candleSeries, historyQuery.data, signalQuery.data]);

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

    const emaMap = new Map<number, ISeriesApi<"Line">>();
    for (let i = 0; i < emaPeriods.length; i += 1) {
      const period = emaPeriods[i];
      emaMap.set(
        period,
        chart.addLineSeries({
          color: emaColor(period, i),
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          title: "",
        }),
      );
    }

    chartRef.current = chart;
    candleRef.current = candles;
    emaSeriesRef.current = emaMap;

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
      emaSeriesRef.current = new Map();
    };
  }, [height, interval, symbol, emaPeriodsKey]);

  useEffect(() => {
    if (!candleSeries.length || !candleRef.current || emaSeriesRef.current.size === 0) {
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
    const timeScale = chartRef.current?.timeScale();
    dataLenRef.current = candleData.length;

    candleRef.current.setData(candleData);

    for (const [period, series] of emaSeriesRef.current) {
      const values = computeEma(closes, period);
      series.setData(
        candleData
          .map((c, i) =>
            values[i] == null ? null : { time: c.time, value: values[i] as number },
          )
          .filter((x): x is { time: UTCTimestamp; value: number } => x != null),
      );
    }

    pinningRef.current = true;
    if (shouldFitRef.current || followLiveRef.current) {
      timeScale?.scrollToRealTime();
      shouldFitRef.current = false;
    }
    requestAnimationFrame(() => {
      pinningRef.current = false;
    });
  }, [candleSeries, followLive, emaPeriodsKey]);

  useEffect(() => {
    if (!candleRef.current) return;
    candleRef.current.setMarkers(
      chartMarkers.map((m) => ({
        time: m.time as UTCTimestamp,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
      })),
    );
  }, [chartMarkers]);

  const last = candleSeries.at(-1);
  const lastClose = last?.close ?? null;
  const lastOpen = last?.open ?? null;
  const up = lastClose != null && lastOpen != null && lastClose >= lastOpen;

  if (candlesQuery.isLoading) {
    return <Skeleton className={cn("w-full", className)} style={{ height }} />;
  }

  if (candlesQuery.isError) {
    return (
      <Alert variant="destructive" className={className}>
        <AlertTitle>Chart unavailable</AlertTitle>
        <AlertDescription>{(candlesQuery.error as Error).message}</AlertDescription>
      </Alert>
    );
  }

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
            {activeLabLabel
              ? `Lab · ${activeLabLabel} · AUTO on Market/Coach`
              : "Lab · promote a profile to run paper AUTO"}
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
          {INTERVALS.map((item) => (
            <Button
              key={item.value}
              type="button"
              size="sm"
              variant={interval === item.value ? "default" : "ghost"}
              className={cn(
                "h-7 px-2 text-xs",
                interval !== item.value &&
                  "text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-white",
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
          >
            {followLive ? "Follow live · ON" : "Follow live"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs text-[#d1d4dc] hover:bg-[#2a2e39] hover:text-white"
            onClick={() => chartRef.current?.timeScale().fitContent()}
          >
            Fit
          </Button>
        </div>
      </div>

      <div
        className="border-b px-3 py-2"
        style={{ borderColor: TV.border, background: "#161a25" }}
      >
        <BarCountdown
          interval={interval}
          compact
          className="border-[#2a2e39] bg-[#1c2130] text-[#d1d4dc]"
        />
      </div>

      <div
        className="flex flex-wrap items-start gap-3 border-b px-3 py-2 text-[11px]"
        style={{ borderColor: TV.border, background: "#161a25", color: TV.muted }}
      >
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="font-medium" style={{ color: TV.text }}>
            Entry source: Hypothesis Lab (user prompts)
          </p>
          <p>
            Describe rules in{" "}
            <Link href="/lab" className="underline underline-offset-2" style={{ color: TV.text }}>
              Lab
            </Link>
            , promote a paper profile, then run AUTO on Market or Coach. EMA lines follow periods
            from your promoted Lab profile (visual context only).
          </p>
        </div>
        {holdCard && (
          <HoldStatusCard
            side={holdCard.side}
            entryPrice={holdCard.entryPrice}
            currentPrice={holdCard.currentPrice}
            entryTimeSec={holdCard.entryTimeSec}
            note={holdCard.note}
            className="max-w-xs shrink-0"
          />
        )}
      </div>

      <div ref={containerRef} style={{ height }} />

      <div
        className="flex flex-wrap items-center gap-4 border-t px-3 py-1.5 text-[11px]"
        style={{ borderColor: TV.border, background: TV.panel, color: TV.muted }}
      >
        {emaPeriods.map((period, index) => (
          <span
            key={period}
            className="inline-flex items-center gap-1.5"
            style={{ color: emaColor(period, index) }}
          >
            — EMA{period}
          </span>
        ))}
        <span className="ml-auto">
          Lab AUTO · Source: {candlesQuery.data?.source ?? "—"} · paper only
        </span>
      </div>
    </div>
  );
}
