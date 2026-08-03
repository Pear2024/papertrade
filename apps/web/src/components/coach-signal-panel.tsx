"use client";

import { useQuery } from "@tanstack/react-query";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TradeChecklist } from "@/components/trade-checklist";
import { BarCountdown } from "@/components/bar-countdown";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { CandleInterval } from "@/lib/types";
import { cn } from "@/lib/utils";

const INTERVALS: CandleInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

type Props = {
  symbol: string;
  interval?: CandleInterval;
  onIntervalChange?: (interval: CandleInterval) => void;
  onApplyExits?: (sl: string, tp: string) => void;
};

export function CoachSignalPanel({
  symbol,
  interval = "15m",
  onIntervalChange,
  onApplyExits,
}: Props) {
  const coachQuery = useQuery({
    queryKey: ["coach-signal", symbol, interval],
    queryFn: () => api.coachSignal(symbol, interval),
    refetchInterval: 20_000,
  });

  const data = coachQuery.data;
  const signal = data?.signal ?? "WAIT";
  const trend = data?.trend ?? "NONE";
  const entry = data?.entry ?? "NONE";
  const phase = data?.phase ?? "NONE";
  const exitKind = data?.exit ?? "NONE";
  const position = data?.position ?? "NEUTRAL";
  const display =
    phase !== "NONE" && phase
      ? phase.replaceAll("_", " ")
      : entry === "ENTRY_BUY"
        ? "ENTRY BUY"
        : entry === "ENTRY_SELL"
          ? "ENTRY SELL"
          : trend === "HOLD_LONG" || trend === "BUY_TREND"
            ? "HOLD LONG"
            : trend === "HOLD_SHORT" || trend === "SELL_TREND"
              ? "HOLD SHORT"
              : exitKind !== "NONE"
                ? exitKind.replaceAll("_", " ")
                : signal;
  const tone =
    phase === "ENTRY_BUY" ||
    phase === "HOLD_LONG" ||
    entry === "ENTRY_BUY" ||
    trend === "HOLD_LONG" ||
    trend === "BUY_TREND"
      ? "text-emerald-600"
      : phase === "ENTRY_SELL" ||
          phase === "HOLD_SHORT" ||
          entry === "ENTRY_SELL" ||
          trend === "HOLD_SHORT" ||
          trend === "SELL_TREND"
        ? "text-red-600"
        : phase.startsWith("EXIT") || exitKind.startsWith("EXIT")
          ? "text-slate-500"
          : "text-amber-600";

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>DayTradeCrypto Coach</CardTitle>
            <CardDescription>
              A4 story: ENTRY once → HOLD → EXIT (opposite / SL / TP). No BUY/SELL spam.
            </CardDescription>
          </div>
          <Badge variant="secondary">{symbol}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-1">
          {INTERVALS.map((iv) => (
            <Button
              key={iv}
              type="button"
              size="sm"
              variant={interval === iv ? "default" : "outline"}
              className="h-7 px-2 text-xs"
              onClick={() => onIntervalChange?.(iv)}
            >
              {iv}
            </Button>
          ))}
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-7 px-2 text-xs"
            onClick={() => coachQuery.refetch()}
          >
            Refresh
          </Button>
        </div>

        <BarCountdown interval={interval} />

        {coachQuery.isLoading && <Skeleton className="h-28 w-full" />}
        {coachQuery.isError && (
          <Alert variant="destructive">
            <AlertTitle>Coach unavailable</AlertTitle>
            <AlertDescription>{(coachQuery.error as Error).message}</AlertDescription>
          </Alert>
        )}

        {data && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className={cn("text-3xl font-semibold tracking-tight", tone)}>{display}</p>
                <p className="text-sm text-muted-foreground">
                  Phase {phase} · Position {position} · Exit {exitKind} · Act {signal}
                </p>
                <p className="text-sm text-muted-foreground">
                  Confidence: <strong>{data.confidence}%</strong>
                </p>
              </div>
              <div className="text-right text-sm">
                <p>Price {formatMoney(data.price)}</p>
                <p className="text-muted-foreground">
                  Bar {data.bar_closed ? "closed (can act)" : "still open → WAIT"}
                </p>
              </div>
            </div>

            <Alert variant={data.signal === "WAIT" ? "warning" : "default"}>
              <AlertTitle>Short reason</AlertTitle>
              <AlertDescription>
                {data.short_reason || data.reason}
                {data.short_reason && data.short_reason !== data.reason ? (
                  <span className="mt-2 block text-xs text-muted-foreground">{data.reason}</span>
                ) : null}
              </AlertDescription>
            </Alert>

            <p className="rounded-md border bg-muted/40 px-3 py-2 font-mono text-xs">
              COFR: {data.cofr}
            </p>

            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <p>EMA9: {data.ema9 ? formatMoney(data.ema9) : "—"}</p>
              <p>EMA21: {data.ema21 ? formatMoney(data.ema21) : "—"}</p>
              <p>Volume: {data.volume ?? "—"}</p>
              <p>Vol avg20: {data.volume_avg20 ?? "—"}</p>
              <p>Stop Loss: {data.stop_loss ? formatMoney(data.stop_loss) : "—"}</p>
              <p>Take Profit: {data.take_profit ? formatMoney(data.take_profit) : "—"}</p>
              <p>Risk:Reward: {data.risk_reward ?? "—"}</p>
              <p className="text-muted-foreground">Source: {data.source}</p>
            </div>

            {data.signal !== "WAIT" && data.stop_loss && data.take_profit && onApplyExits && (
              <Button
                type="button"
                size="sm"
                onClick={() =>
                  onApplyExits(
                    String(Math.round(Number(data.stop_loss))),
                    String(Math.round(Number(data.take_profit))),
                  )
                }
              >
                Apply coach SL/TP to form
              </Button>
            )}

            <p className="text-xs text-muted-foreground">
              Signal: <strong className={tone}>{data.signal}</strong> · Confidence{" "}
              <strong>{data.confidence}%</strong>
            </p>

            {data.checklist && data.checklist.length > 0 && (
              <TradeChecklist items={data.checklist} className="border-0 shadow-none" />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
