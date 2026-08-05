"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CoachSignalPanel } from "@/components/coach-signal-panel";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { TradeJournalPanel } from "@/components/trade-journal-panel";
import { TradingChart } from "@/components/trading-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { coachSettingsToApiParams } from "@/lib/coach-settings";
import { formatMoney, formatPercent } from "@/lib/format";
import { resolveSlTpPct } from "@/lib/sl-tp";
import { CandleInterval } from "@/lib/types";

const SYMBOLS = [
  "BTC",
  "ETH",
  "SOL",
  "XRP",
  "BNB",
  "ADA",
  "DOGE",
  "AVAX",
  "DOT",
  "LINK",
  "MATIC",
  "ATOM",
  "LTC",
  "UNI",
  "APT",
  "ARB",
  "OP",
  "SUI",
  "NEAR",
  "TRX",
  "SHIB",
  "TON",
  "ICP",
  "FIL",
  "AAVE",
  "PEPE",
  "INJ",
  "SEI",
  "WIF",
  "RENDER",
] as const;

export default function CoachPage() {
  const { settings } = useCoachSettings();
  const [symbol, setSymbol] = useState<(typeof SYMBOLS)[number]>("BTC");
  const ruleOpts = coachSettingsToApiParams(settings, symbol);
  const { slPct: effSlPct, tpPct: effTpPct } = resolveSlTpPct(
    symbol,
    settings.slPct,
    settings.tpPct,
  );
  const [interval, setInterval] = useState<CandleInterval>(settings.interval);
  const [autoEnabled, setAutoEnabled] = useState(settings.autoOnDefault);
  const [autoMsg, setAutoMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    setInterval(settings.interval);
  }, [settings.interval]);

  useEffect(() => {
    setAutoEnabled(settings.autoOnDefault);
  }, [settings.autoOnDefault]);

  const promptQuery = useQuery({ queryKey: ["coach-prompt"], queryFn: api.coachPrompt });
  const statsQuery = useQuery({
    queryKey: ["coach-stats"],
    queryFn: api.coachStats,
    refetchInterval: 30_000,
  });
  const signalQuery = useQuery({
    queryKey: [
      "coach-signal",
      symbol,
      interval,
      ruleOpts.sl_pct,
      ruleOpts.tp_pct,
      ruleOpts.ema_sep_pct,
    ],
    queryFn: () =>
      api.coachSignal(symbol, interval, {
        slPct: ruleOpts.sl_pct,
        tpPct: ruleOpts.tp_pct,
        emaSepPct: ruleOpts.ema_sep_pct,
      }),
    refetchInterval: 15_000,
  });

  const autoMutation = useMutation({
    mutationFn: () =>
      api.coachAutoTick(symbol, interval, settings.autoStakeUsd, {
        slPct: ruleOpts.sl_pct,
        tpPct: ruleOpts.tp_pct,
        tpUsd: settings.tpUsd,
        emaSepPct: ruleOpts.ema_sep_pct,
        leverage: settings.leverage,
      }),
    onSuccess: async (data) => {
      if (data.action === "buy") {
        const sl = data.stop_loss ? formatMoney(data.stop_loss) : `−${settings.slPct}%`;
        const tp = data.take_profit ? formatMoney(data.take_profit) : `+${settings.tpPct}%`;
        setAutoMsg(
          `BUY filled · Stop Loss ${sl} · Take Profit ${tp} locked for you. ${data.reason}`,
        );
      } else {
        setAutoMsg(
          `Action: ${data.action} · Signal ${data.signal} (${data.confidence}%) — ${data.reason}`,
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["coach-stats"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-signal"] }),
        queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["trades"] }),
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
        queryClient.invalidateQueries({ queryKey: ["position", symbol] }),
      ]);
    },
    onError: (error) => {
      setAutoMsg((error as Error).message);
    },
  });

  useEffect(() => {
    if (!autoEnabled || statsQuery.data?.trading_locked) return;
    const tick = () => {
      if (!autoMutation.isPending) autoMutation.mutate();
    };
    tick();
    const id = window.setInterval(tick, settings.autoTickSeconds * 1000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    autoEnabled,
    symbol,
    interval,
    settings.autoStakeUsd,
    settings.leverage,
    settings.autoTickSeconds,
    settings.tpUsd,
    ruleOpts.sl_pct,
    ruleOpts.tp_pct,
    ruleOpts.ema_sep_pct,
    statsQuery.data?.trading_locked,
  ]);

  const stats = statsQuery.data;
  const sig = signalQuery.data;
  const canBuy = sig?.signal === "BUY" && sig.bar_closed;
  const canSell = sig?.signal === "SELL" && sig.bar_closed;
  const canAct = Boolean(canBuy || canSell) && !stats?.trading_locked;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">AI Coach</h1>
        <p className="text-sm text-muted-foreground">
          DayTradeCryptoCoach — rules only, paper only, no emotions.
        </p>
      </div>

      <PaperBanner />

      <Alert>
        <AlertTitle>Practice goal</AlertTitle>
        <AlertDescription>
          Complete <strong>200–500 paper trades</strong> first. Review win rate, profit factor, and
          drawdown before ever thinking about real money. This app never trades real money.
        </AlertDescription>
      </Alert>

      <Alert>
        <AlertTitle>Auto paper buy/sell (default ON)</AlertTitle>
        <AlertDescription>
          Keep this page open while logged in. Every ~{settings.autoTickSeconds}s the coach checks the
          closed candle; on every ENTRY (when flat) it opens and locks{" "}
          <strong>
            Stop Loss −{effSlPct}%
          </strong>{" "}
          and{" "}
          <strong>
            Take Profit +{effTpPct}%
          </strong>{" "}
          plus{" "}
          <strong>USD TP ${settings.tpUsd}</strong>{" "}
          for <strong>{symbol}</strong> (base Settings {settings.slPct}%/{settings.tpPct}%, scaled by
          coin · cap ${settings.autoStakeUsd}). Change defaults in Settings. Pause auto anytime, or
          use the big button manually.
        </AlertDescription>
      </Alert>

      {statsQuery.isLoading ? (
        <Skeleton className="h-28 w-full" />
      ) : stats ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Win rate</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.win_rate != null ? formatPercent(stats.win_rate) : "—"}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Net profit</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              <PnlText value={stats.net_profit} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Max drawdown</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.max_drawdown != null ? formatMoney(stats.max_drawdown) : "—"}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Paper trades</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.closed_trades}/{stats.practice_trades_target}
              <p className="text-xs font-normal text-muted-foreground">
                {stats.practice_progress_pct}% of practice goal
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {stats?.trading_locked && (
        <Alert variant="destructive">
          <AlertTitle>Trading locked by stats</AlertTitle>
          <AlertDescription>{stats.lock_reason}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        {SYMBOLS.map((sym) => (
          <Button
            key={sym}
            type="button"
            size="sm"
            variant={symbol === sym ? "default" : "outline"}
            onClick={() => setSymbol(sym)}
          >
            {sym}
          </Button>
        ))}
        <Button
          type="button"
          size="sm"
          variant={autoEnabled ? "default" : "outline"}
          className="ml-auto"
          disabled={!!stats?.trading_locked}
          onClick={() => setAutoEnabled((v) => !v)}
        >
          {autoEnabled
            ? `Auto ON ($${settings.autoStakeUsd} / ${settings.autoTickSeconds}s)`
            : "Auto OFF (manual)"}
        </Button>
      </div>

      <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
        <p className="font-medium">
          Planned on BUY:{" "}
          {sig?.signal === "BUY" && sig.stop_loss && sig.take_profit
            ? `SL ${formatMoney(sig.stop_loss)} · TP ${formatMoney(sig.take_profit)}`
            : "SL −2% / TP +3% (set automatically when you press BUY)"}
        </p>
        {sig?.price && (
          <p className="mt-1 text-xs text-muted-foreground">
            Signal price {formatMoney(sig.price)} · {sig.signal}
            {sig.bar_closed === false ? " · candle still open" : ""}
          </p>
        )}
      </div>

      <Button
        type="button"
        size="lg"
        className="h-14 w-full text-base font-semibold sm:w-auto sm:min-w-[280px]"
        disabled={!canAct || autoMutation.isPending}
        onClick={() => autoMutation.mutate()}
      >
        {autoMutation.isPending
          ? "Working…"
          : canBuy
            ? "BUY now · lock SL/TP for me"
            : canSell
              ? "SELL now · close position"
              : "Wait for BUY/SELL signal"}
      </Button>

      {autoMsg && (
        <Alert>
          <AlertTitle>Last action</AlertTitle>
          <AlertDescription>{autoMsg}</AlertDescription>
        </Alert>
      )}

      <TradingChart symbol={symbol} height={420} defaultInterval={interval} />

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <CoachSignalPanel symbol={symbol} interval={interval} onIntervalChange={setInterval} />
        <TradeJournalPanel symbol={symbol} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>AI brain prompt</CardTitle>
          <CardDescription>
            Exact instructions used by {promptQuery.data?.name ?? "DayTradeCryptoCoach"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {promptQuery.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-xs leading-relaxed">
              {promptQuery.data?.prompt}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
