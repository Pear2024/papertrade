"use client";

import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/empty-state";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="text-xl font-semibold tracking-tight">{children}</CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const overviewQuery = useQuery({
    queryKey: ["analytics-overview"],
    queryFn: api.analyticsOverview,
  });
  const disciplineQuery = useQuery({
    queryKey: ["analytics-discipline"],
    queryFn: api.analyticsDiscipline,
  });
  const byAssetQuery = useQuery({
    queryKey: ["analytics-by-asset"],
    queryFn: api.analyticsByAsset,
  });
  const byEmotionQuery = useQuery({
    queryKey: ["analytics-by-emotion"],
    queryFn: api.analyticsByEmotion,
  });

  const loading =
    overviewQuery.isLoading ||
    disciplineQuery.isLoading ||
    byAssetQuery.isLoading ||
    byEmotionQuery.isLoading;

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  if (overviewQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load analytics</AlertTitle>
        <AlertDescription>{(overviewQuery.error as Error).message}</AlertDescription>
      </Alert>
    );
  }

  const overview = overviewQuery.data!;
  const discipline = disciplineQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <p className="text-sm text-muted-foreground">
          Learning metrics from your paper trades after the last account reset.
        </p>
      </div>

      <PaperBanner />

      {overview.sample_size_note && (
        <Alert variant="warning">
          <AlertTitle>More data helps</AlertTitle>
          <AlertDescription>{overview.sample_size_note}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total trades">{overview.total_trades}</Metric>
        <Metric label="Winning trades">{overview.winning_trades}</Metric>
        <Metric label="Losing trades">{overview.losing_trades}</Metric>
        <Metric label="Win rate">{formatPercent(overview.win_rate)}</Metric>
        <Metric label="Average win">{formatMoney(overview.average_win)}</Metric>
        <Metric label="Average loss">
          <PnlText value={overview.average_loss} />
        </Metric>
        <Metric label="Profit factor">
          {overview.profit_factor == null ? "—" : overview.profit_factor}
        </Metric>
        <Metric label="Max drawdown">
          <PnlText value={`-${overview.maximum_drawdown}`} />
        </Metric>
        <Metric label="Largest win">
          <PnlText value={overview.largest_win} />
        </Metric>
        <Metric label="Largest loss">
          <PnlText value={overview.largest_loss} />
        </Metric>
        <Metric label="Avg risk / trade">
          {overview.average_risk_per_trade == null
            ? "—"
            : formatPercent(overview.average_risk_per_trade)}
        </Metric>
        <Metric label="Followed plan">
          {overview.followed_plan_count}/{overview.followed_plan_total}
          {overview.followed_plan_rate != null
            ? ` (${formatPercent(overview.followed_plan_rate)})`
            : ""}
        </Metric>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Discipline</CardTitle>
            <CardDescription>Plan adherence and stop-loss habits</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {discipline ? (
              <>
                <p>
                  Followed plan: {discipline.followed_plan_count}/{discipline.followed_plan_total}
                  {discipline.followed_plan_rate != null
                    ? ` · ${formatPercent(discipline.followed_plan_rate)}`
                    : ""}
                </p>
                <p>
                  Stop loss usage:{" "}
                  {discipline.stop_loss_usage_rate == null
                    ? "—"
                    : formatPercent(discipline.stop_loss_usage_rate)}{" "}
                  ({discipline.trades_with_stop_loss}/{discipline.buy_orders} buys)
                </p>
                <p>
                  Average confidence:{" "}
                  {discipline.average_confidence == null
                    ? "—"
                    : Number(discipline.average_confidence).toFixed(2)}
                </p>
              </>
            ) : (
              <p className="text-muted-foreground">No discipline data yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>By asset</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(byAssetQuery.data ?? []).length === 0 ? (
              <EmptyState title="No sell trades yet" description="Close some paper trades to see asset performance." />
            ) : (
              (byAssetQuery.data ?? []).map((row) => (
                <div key={row.symbol} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
                  <div>
                    <p className="font-medium">{row.symbol}</p>
                    <p className="text-muted-foreground">
                      {row.trades} sells · win {formatPercent(row.win_rate)}
                    </p>
                  </div>
                  <PnlText value={row.realized_pnl} />
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>By emotion</CardTitle>
          <CardDescription>
            Journals grouped by emotional state (linked sell P&L when available)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {(byEmotionQuery.data ?? []).length === 0 ? (
            <EmptyState
              title="No emotion tags yet"
              description="Add emotional state in the journal or when placing trades."
            />
          ) : (
            (byEmotionQuery.data ?? []).map((row) => (
              <div
                key={row.emotional_state}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <div>
                  <p className="font-medium capitalize">{row.emotional_state}</p>
                  <p className="text-muted-foreground">
                    {row.journals} journals · {row.linked_sells} linked sells
                    {row.followed_plan_rate != null
                      ? ` · followed plan ${formatPercent(row.followed_plan_rate)}`
                      : ""}
                  </p>
                </div>
                {row.average_realized_pnl != null ? (
                  <PnlText value={row.average_realized_pnl} />
                ) : (
                  <span className="text-muted-foreground">No linked P&L</span>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
