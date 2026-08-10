"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { PnlText } from "@/components/pnl-text";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";

type Props = {
  className?: string;
};

/** Simple measurable dashboard — does not change strategy. */
export function PostTradeStats({ className }: Props) {
  const statsQuery = useQuery({
    queryKey: ["coach-stats"],
    queryFn: api.coachStats,
    refetchInterval: 30_000,
  });

  const stats = statsQuery.data;

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Simple performance dashboard</CardTitle>
        <CardDescription>
          Transparency only — strategy rules stay locked. Closed paper sells · goal 200–500 trades.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {statsQuery.isLoading ? (
          <Skeleton className="h-36 w-full" />
        ) : !stats ? (
          <p className="text-sm text-muted-foreground">No stats yet.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                label="Win rate"
                value={stats.win_rate != null ? formatPercent(stats.win_rate) : "—"}
              />
              <Stat label="Total P/L" value={<PnlText value={stats.net_profit} />} />
              <Stat
                label="Avg risk:reward"
                value={stats.avg_risk_reward ?? stats.planned_risk_reward ?? "1:2.5"}
              />
              <Stat
                label="Drawdown"
                value={stats.max_drawdown != null ? formatMoney(stats.max_drawdown) : "—"}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
              <Stat
                label="Closed trades"
                value={`${stats.closed_trades}/${stats.practice_trades_target}`}
              />
              <Stat label="Wins / losses" value={`${stats.wins ?? 0} / ${stats.losses ?? 0}`} />
              <Stat
                label="Journaled exits"
                value={`${stats.journaled_exits ?? 0}/${stats.closed_trades}`}
              />
              <Stat
                label="Last exit"
                value={
                  stats.last_trade_pnl != null ? <PnlText value={stats.last_trade_pnl} /> : "—"
                }
              />
            </div>
            {stats.last_exit_reason && (
              <p className="text-xs text-muted-foreground break-words">
                Last reason: {stats.last_exit_reason}
              </p>
            )}
            <div className="space-y-2">
              <p className="text-sm font-medium">Entry × filter-set paper comparison</p>
              {(stats.variant_stats ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No closed trades with an experiment snapshot yet.
                </p>
              ) : (
                (stats.variant_stats ?? []).map((variant) => (
                  <div key={variant.filter_set_id} className="rounded-md border px-3 py-2 text-xs">
                    <p className="font-medium">{variant.filter_set_id}</p>
                    <p className="mt-1 text-muted-foreground">
                      {variant.trades} trades · WR {variant.win_rate ?? "—"} · avg P/L{" "}
                      {variant.avg_pnl != null ? formatMoney(variant.avg_pnl) : "—"} · net{" "}
                      {variant.net_pnl != null ? formatMoney(variant.net_pnl) : "—"}
                    </p>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border bg-muted/20 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}
