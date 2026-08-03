"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, PauseCircle, PlayCircle, Zap } from "lucide-react";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PostTradeStats } from "@/components/post-trade-stats";
import { TradeChecklist } from "@/components/trade-checklist";
import { BarCountdown } from "@/components/bar-countdown";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { coachSettingsToApiParams } from "@/lib/coach-settings";
import { formatMoney } from "@/lib/format";
import { resolveSlTpPct } from "@/lib/sl-tp";
import { cn } from "@/lib/utils";

type Props = {
  symbol?: string;
  className?: string;
};

/**
 * One-button paper desk: you press → coach BUY/SELL with SL/TP locked.
 * Auto loop uses Settings → Coach auto (browser prefs).
 */
export function SignalAutoCard({ symbol = "BTC", className }: Props) {
  const { settings } = useCoachSettings();
  const ruleOpts = coachSettingsToApiParams(settings, symbol);
  const { slPct: effSlPct, tpPct: effTpPct } = resolveSlTpPct(
    symbol,
    settings.slPct,
    settings.tpPct,
  );
  const interval = settings.interval;
  const stake = settings.autoStakeUsd;
  const tickMs = settings.autoTickSeconds * 1000;

  const [autoEnabled, setAutoEnabled] = useState(settings.autoOnDefault);
  const [lastMsg, setLastMsg] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    setAutoEnabled(settings.autoOnDefault);
  }, [settings.autoOnDefault]);

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
  const positionQuery = useQuery({
    queryKey: ["position", symbol],
    queryFn: () => api.position(symbol).catch(() => null),
    refetchInterval: 20_000,
  });

  const actionMutation = useMutation({
    mutationFn: () =>
      api.coachAutoTick(symbol, interval, stake, {
        slPct: ruleOpts.sl_pct,
        tpPct: ruleOpts.tp_pct,
        emaSepPct: ruleOpts.ema_sep_pct,
        leverage: settings.leverage,
      }),
    onSuccess: async (data) => {
      const logLine = (data.logs && data.logs.length > 0 ? data.logs.join(" · ") : null) || data.reason;
      if (data.action.includes("long") || data.action === "buy" || data.action === "open_long") {
        const sl = data.stop_loss ? formatMoney(data.stop_loss) : `−${settings.slPct}%`;
        const tp = data.take_profit ? formatMoney(data.take_profit) : `+${settings.tpPct}%`;
        const filledStake = data.stake_usd ? `$${data.stake_usd}` : `~$${stake}`;
        setLastMsg(`${logLine} · stake ${filledStake} · SL ${sl} · TP ${tp}`);
      } else if (data.action.includes("short") || data.action === "open_short") {
        const sl = data.stop_loss ? formatMoney(data.stop_loss) : `+${settings.slPct}%`;
        const tp = data.take_profit ? formatMoney(data.take_profit) : `−${settings.tpPct}%`;
        setLastMsg(`${logLine} · SL ${sl} · TP ${tp}`);
      } else {
        setLastMsg(
          `${data.action.toUpperCase()} · signal ${data.signal} (${data.confidence}%) — ${logLine}`,
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["coach-signal", symbol, interval] }),
        queryClient.invalidateQueries({ queryKey: ["position", symbol] }),
        queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["coach-stats"] }),
        queryClient.invalidateQueries({ queryKey: ["trades"] }),
      ]);
    },
    onError: (error) => setLastMsg((error as Error).message),
  });

  useEffect(() => {
    if (!autoEnabled) return;
    const tick = () => {
      if (!actionMutation.isPending) actionMutation.mutate();
    };
    tick();
    const id = window.setInterval(tick, tickMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoEnabled, symbol, interval, stake, tickMs, ruleOpts.sl_pct, ruleOpts.tp_pct, ruleOpts.ema_sep_pct, settings.leverage]);

  const data = signalQuery.data;
  const signal = data?.signal ?? "WAIT";
  const trend = data?.trend ?? "NONE";
  const entryKind = data?.entry ?? "NONE";
  const phase = data?.phase ?? "NONE";
  const exitKind = data?.exit ?? "NONE";
  const pos = positionQuery.data;
  const qtyNum = pos ? Number(pos.quantity) : 0;
  const side =
    (pos?.side as string | undefined) ||
    (qtyNum > 0 ? "long" : qtyNum < 0 ? "short" : "flat");
  const hasLong = side === "long";
  const hasShort = side === "short";
  const hasPosition = hasLong || hasShort;
  const statusLabel = hasLong ? "LONG" : hasShort ? "SHORT" : "FLAT";

  const canBuy =
    (signal === "BUY" || entryKind === "ENTRY_BUY" || phase === "ENTRY_BUY") &&
    data?.bar_closed !== false &&
    !hasPosition;
  const canSell =
    (signal === "SELL" || entryKind === "ENTRY_SELL" || phase === "ENTRY_SELL") &&
    data?.bar_closed !== false &&
    !hasPosition;
  const canAct = canBuy || canSell;

  const displayLabel =
    phase !== "NONE" && phase
      ? phase.replaceAll("_", " ")
      : entryKind === "ENTRY_BUY"
        ? "ENTRY BUY"
        : entryKind === "ENTRY_SELL"
          ? "ENTRY SELL"
          : trend === "HOLD_LONG" || trend === "BUY_TREND"
            ? "HOLD LONG"
            : trend === "HOLD_SHORT" || trend === "SELL_TREND"
              ? "HOLD SHORT"
              : exitKind !== "NONE"
                ? exitKind.replaceAll("_", " ")
                : signal;

  const buttonLabel = actionMutation.isPending
    ? "Working…"
    : canBuy
      ? "ENTRY BUY · open LONG + lock SL/TP"
      : canSell
        ? "ENTRY SELL · open SHORT + lock SL/TP"
        : hasPosition
          ? `HOLD ${statusLabel} until EXIT / SL / TP`
          : phase === "HOLD_LONG" || trend === "HOLD_LONG" || trend === "BUY_TREND"
            ? "HOLD LONG — no new order"
            : phase === "HOLD_SHORT" || trend === "HOLD_SHORT" || trend === "SELL_TREND"
              ? "HOLD SHORT — no new order"
              : signal === "WAIT" || data?.bar_closed === false
                ? "Wait for closed candle + ENTRY"
                : "No action right now";

  const statusTone = hasLong
    ? "border-emerald-500/40 bg-emerald-500/10"
    : hasShort
      ? "border-red-500/40 bg-red-500/10"
      : "border-muted bg-muted/30";

  const signalTone =
    phase === "ENTRY_BUY" ||
    phase === "HOLD_LONG" ||
    entryKind === "ENTRY_BUY" ||
    trend === "HOLD_LONG" ||
    trend === "BUY_TREND"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
      : phase === "ENTRY_SELL" ||
          phase === "HOLD_SHORT" ||
          entryKind === "ENTRY_SELL" ||
          trend === "HOLD_SHORT" ||
          trend === "SELL_TREND"
        ? "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300"
        : phase.startsWith("EXIT") || exitKind.startsWith("EXIT")
          ? "border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300"
          : "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-200";

  const plannedSl = data?.stop_loss ? formatMoney(data.stop_loss) : null;
  const plannedTp = data?.take_profit ? formatMoney(data.take_profit) : null;
  const posSl = pos?.stop_loss_price ? formatMoney(pos.stop_loss_price) : "—";
  const posTp = pos?.take_profit_price ? formatMoney(pos.take_profit_price) : "—";
  const entryPrice = pos ? formatMoney(pos.average_entry_price) : "—";
  const uPnl = pos ? formatMoney(pos.unrealized_pnl) : "—";

  return (
    <div className={cn("space-y-4", className)}>
      <Card className="overflow-hidden">
        <CardHeader className="space-y-3 pb-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-primary" />
                <CardTitle>{symbol} · One-button paper desk</CardTitle>
              </div>
              <CardDescription className="mt-1">
                Paper LONG & SHORT. AUTO uses{" "}
                <Link href="/settings" className="underline underline-offset-4">
                  Settings
                </Link>
                : {interval}, tick {settings.autoTickSeconds}s, margin ${stake} ×{" "}
                {settings.leverage}x, SL{" "}
                {effSlPct}% / TP {effTpPct}% ({symbol}). Fixed margin ${stake}. ENTRY → HOLD → EXIT.
              </CardDescription>
            </div>
            <Badge variant={autoEnabled ? "default" : "secondary"}>
              {autoEnabled ? "AUTO ON" : "MANUAL"}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            ENTRY when flat → HOLD (no re-order) → EXIT on opposite signal / SL / TP · Chat on
            ENTRY+EXIT only
          </p>
        </CardHeader>

        <CardContent className="space-y-4">
          {signalQuery.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : signalQuery.isError ? (
            <Alert variant="destructive">
              <AlertTitle>Signal unavailable</AlertTitle>
              <AlertDescription>{(signalQuery.error as Error).message}</AlertDescription>
            </Alert>
          ) : (
            <div className={cn("rounded-lg border p-4", signalTone)}>
              <p className="text-xs font-medium uppercase tracking-wide opacity-80">
                Live coach · {interval} · closed-bar only
              </p>
              <p className="mt-1 text-3xl font-semibold tracking-tight">{displayLabel}</p>
              <p className="mt-1 text-xs opacity-80">
                Phase: {phase} · Position: {data?.position ?? "—"} · Exit: {exitKind} · Act:{" "}
                {signal}
              </p>
              <p className="mt-1 text-sm">
                Confidence {data?.confidence ?? 0}%
                {data?.bar_closed === false ? " · waiting for candle close" : ""}
              </p>
              <p className="mt-2 text-sm font-medium leading-snug">
                {data?.short_reason || data?.reason}
              </p>
            </div>
          )}

          <div className={cn("rounded-lg border p-4", statusTone)}>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Position status
            </p>
            <p className="mt-1 text-2xl font-semibold tracking-tight">{statusLabel}</p>
            <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
              <p>
                Avg entry: <span className="font-medium">{entryPrice}</span>
              </p>
              <p>
                Unrealized P/L: <span className="font-medium">{uPnl}</span>
              </p>
              <p>
                Stop Loss: <span className="font-medium">{posSl}</span>
              </p>
              <p>
                Take Profit: <span className="font-medium">{posTp}</span>
              </p>
            </div>
          </div>

          <BarCountdown interval={interval} />

          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div className="rounded-md border bg-muted/30 px-3 py-2">
              <p className="text-xs text-muted-foreground">Next button action</p>
              <p className="font-medium">
                {hasPosition
                  ? `${statusLabel} open — hold until SL/TP (no flip)`
                  : "FLAT — ENTRY BUY opens LONG · ENTRY SELL opens SHORT"}
              </p>
            </div>
            <div className="rounded-md border bg-muted/30 px-3 py-2">
              <p className="text-xs text-muted-foreground">Planned exits (new entry)</p>
              <p className="font-medium">
                {plannedSl && plannedTp
                  ? `SL ${plannedSl} · TP ${plannedTp}`
                  : `LONG: −${effSlPct}% / +${effTpPct}% · SHORT: +${effSlPct}% / −${effTpPct}%`}
              </p>
              {data?.price && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Signal price {formatMoney(data.price)}
                </p>
              )}
            </div>
          </div>
          <Button
            type="button"
            size="lg"
            className={cn(
              "h-14 w-full text-base font-semibold",
              canBuy && "bg-emerald-600 hover:bg-emerald-600/90",
              canSell && "bg-red-600 hover:bg-red-600/90",
            )}
            disabled={!canAct || actionMutation.isPending}
            onClick={() => actionMutation.mutate()}
          >
            <Zap className="mr-2 h-5 w-5" />
            {buttonLabel}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            Paper only — open when flat · hold to SL/TP · fixed stake · journaled · no real brokerage
          </p>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={autoEnabled ? "default" : "outline"}
              onClick={() => setAutoEnabled((v) => !v)}
            >
              {autoEnabled ? (
                <>
                  <PauseCircle className="mr-1.5 h-4 w-4" /> Pause auto loop
                </>
              ) : (
                <>
                  <PlayCircle className="mr-1.5 h-4 w-4" /> Optional: start auto loop
                </>
              )}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={signalQuery.isFetching}
              onClick={() => signalQuery.refetch()}
            >
              Refresh signal
            </Button>
          </div>

          {lastMsg && (
            <Alert>
              <AlertTitle>Last action</AlertTitle>
              <AlertDescription className="text-sm">{lastMsg}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {data?.checklist && data.checklist.length > 0 && <TradeChecklist items={data.checklist} />}
      <PostTradeStats />
    </div>
  );
}
