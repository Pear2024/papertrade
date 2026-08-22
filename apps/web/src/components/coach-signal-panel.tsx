"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TradeChecklist } from "@/components/trade-checklist";
import { BarCountdown } from "@/components/bar-countdown";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { coachSettingsToApiParams } from "@/lib/coach-settings";
import { formatMoney } from "@/lib/format";
import { formatLabProfileLabel, labProfileNumbers } from "@/lib/lab-profile-label";
import { CandleInterval } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const INTERVALS: CandleInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

type Props = {
  symbol: string;
  interval?: CandleInterval;
  onIntervalChange?: (interval: CandleInterval) => void;
  onApplyExits?: (sl: string, tp: string) => void;
};

export function CoachSignalPanel({
  symbol,
  interval: intervalProp,
  onIntervalChange,
  onApplyExits,
}: Props) {
  const { settings, update } = useCoachSettings();
  const interval = intervalProp ?? settings.interval;
  const ruleOpts = coachSettingsToApiParams(settings, symbol);

  const labQuery = useQuery({
    queryKey: ["hypothesis-lab"],
    queryFn: api.hypothesisLab,
    staleTime: 30_000,
  });
  const promotedLab = (labQuery.data?.items ?? []).filter((item) => item.promoted_at);
  const profileNumbers = useMemo(
    () => labProfileNumbers(labQuery.data?.items ?? []),
    [labQuery.data?.items],
  );
  const activeLab =
    promotedLab.find((item) => item.id === settings.labHypothesisId) ?? promotedLab[0];

  const coachQuery = useQuery({
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
    ],
    queryFn: () =>
      api.coachSignal(symbol, interval, {
        slPct: ruleOpts.sl_pct,
        tpPct: ruleOpts.tp_pct,
        minNetRr: ruleOpts.min_net_rr,
        slippageBps: ruleOpts.slippage_bps,
        spreadBps: ruleOpts.spread_bps,
        entrySource: "lab",
        hypothesisId: activeLab?.id,
      }),
    enabled: Boolean(activeLab?.id),
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
        : trend === "HOLD_LONG" || trend === "BUY_TREND"
          ? "HOLD LONG"
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
      : phase.startsWith("EXIT") || exitKind.startsWith("EXIT")
        ? "text-slate-500"
        : "text-amber-600";

  const handleInterval = (iv: CandleInterval) => {
    if (onIntervalChange) onIntervalChange(iv);
    else update({ interval: iv });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>Hypothesis Lab signal</CardTitle>
            <CardDescription>
              Paper signals from your promoted Lab profile. Create prompts in{" "}
              <Link href="/lab" className="underline underline-offset-4">
                Lab
              </Link>
              .
            </CardDescription>
          </div>
          <Badge variant="secondary">{symbol}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {INTERVALS.map((iv) => (
            <Button
              key={iv}
              type="button"
              size="sm"
              variant={interval === iv ? "default" : "outline"}
              className="h-7 px-2 text-xs"
              onClick={() => handleInterval(iv)}
            >
              {iv}
            </Button>
          ))}
          {promotedLab.length > 0 ? (
            <Select
              value={activeLab?.id ?? ""}
              onValueChange={(id) => update({ labHypothesisId: id })}
            >
              <SelectTrigger className="h-7 min-w-44 text-xs">
                <SelectValue placeholder="Lab profile" />
              </SelectTrigger>
              <SelectContent>
                {promotedLab.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {formatLabProfileLabel(item, profileNumbers.get(item.id) ?? null)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <Button asChild size="sm" variant="outline" className="h-7 text-xs">
              <Link href="/lab">Promote a Lab profile</Link>
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            variant="secondary"
            className="h-7 px-2 text-xs"
            disabled={!activeLab}
            onClick={() => coachQuery.refetch()}
          >
            Refresh
          </Button>
        </div>

        <BarCountdown interval={interval} />

        {!activeLab ? (
          <Alert>
            <AlertTitle>No promoted Lab profile</AlertTitle>
            <AlertDescription>
              Open Lab, write your rules, backtest, then save a paper profile.
            </AlertDescription>
          </Alert>
        ) : coachQuery.isLoading ? (
          <Skeleton className="h-28 w-full" />
        ) : coachQuery.isError ? (
          <Alert variant="destructive">
            <AlertTitle>Coach unavailable</AlertTitle>
            <AlertDescription>{(coachQuery.error as Error).message}</AlertDescription>
          </Alert>
        ) : data ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className={cn("text-3xl font-semibold tracking-tight", tone)}>{display}</p>
                <p className="text-sm text-muted-foreground">
                  Phase {phase} · Position {position} · Exit {exitKind} · Act {signal}
                </p>
                <p className="text-sm text-muted-foreground">
                  Confidence: <strong>{data.confidence}%</strong>
                  {activeLab
                    ? ` · ${formatLabProfileLabel(activeLab, profileNumbers.get(activeLab.id) ?? null)}`
                    : ""}
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
                {data.signal === "WAIT" ? (
                  <span className="mt-2 block text-xs text-muted-foreground">
                    Quality over quantity: WAIT / NO TRADE is correct when trend, confirmation, or RR ≥ 1:2 is missing.
                  </span>
                ) : null}
              </AlertDescription>
            </Alert>

            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <p>Stop Loss: {data.stop_loss ? formatMoney(data.stop_loss) : "—"}</p>
              <p>Take Profit: {data.take_profit ? formatMoney(data.take_profit) : "—"}</p>
              <p>Gross R:R: {data.gross_risk_reward ?? data.risk_reward ?? "—"}</p>
              <p>
                Net R:R: {data.net_risk_reward ?? "—"}
                {data.rr_blocked ? " · blocked" : ""}
              </p>
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

            {data.checklist && data.checklist.length > 0 && (
              <TradeChecklist items={data.checklist} className="border-0 shadow-none" />
            )}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
