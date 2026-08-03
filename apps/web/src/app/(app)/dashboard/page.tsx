"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/empty-state";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatDateTime, formatMoney, formatQty } from "@/lib/format";

function StatCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
      </CardHeader>
      <CardContent className="text-2xl font-semibold tracking-tight">{children}</CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const summaryQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: api.accountSummary,
    refetchInterval: 30_000,
  });
  const tradesQuery = useQuery({
    queryKey: ["trades"],
    queryFn: api.trades,
  });

  const winRate = useMemo(() => {
    const sells = (tradesQuery.data ?? []).filter((t) => t.side === "sell");
    if (sells.length === 0) return null;
    const wins = sells.filter((t) => Number(t.realized_pnl) > 0).length;
    return (wins / sells.length) * 100;
  }, [tradesQuery.data]);

  const chartData = useMemo(() => {
    const trades = [...(tradesQuery.data ?? [])].reverse();
    let equity = Number(summaryQuery.data?.account.starting_balance ?? 10);
    const points = [{ label: "Start", value: equity }];
    for (const trade of trades) {
      if (trade.side === "buy") equity -= Number(trade.net_amount);
      else equity += Number(trade.net_amount);
      points.push({
        label: new Date(trade.executed_at).toLocaleDateString(),
        value: Number(equity.toFixed(2)),
      });
    }
    if (summaryQuery.data) {
      points.push({
        label: "Now",
        value: Number(Number(summaryQuery.data.portfolio_value).toFixed(2)),
      });
    }
    return points;
  }, [tradesQuery.data, summaryQuery.data]);

  if (summaryQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-20 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      </div>
    );
  }

  if (summaryQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load dashboard</AlertTitle>
        <AlertDescription>
          {(summaryQuery.error as Error).message}. Check that the API is running on port 8000.
        </AlertDescription>
      </Alert>
    );
  }

  const summary = summaryQuery.data!;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Paper portfolio overview for learning — not live trading.
          </p>
        </div>
        <Button asChild>
          <Link href="/market">Go to Market</Link>
        </Button>
      </div>

      <PaperBanner message={summary.paper_mode_banner} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Portfolio Value">{formatMoney(summary.portfolio_value)}</StatCard>
        <StatCard label="Cash Balance">{formatMoney(summary.cash_balance)}</StatCard>
        <StatCard label="Unrealized P&L">
          <PnlText value={summary.unrealized_pnl} />
        </StatCard>
        <StatCard label="Realized P&L">
          <PnlText value={summary.realized_pnl} />
        </StatCard>
        <StatCard label="Daily P&L">
          <PnlText value={summary.daily_pnl} />
        </StatCard>
        <StatCard label="Trades today">{summary.trades_today}</StatCard>
        <StatCard label="Win Rate">
          {winRate === null ? "—" : `${winRate.toFixed(1)}%`}
        </StatCard>
        <StatCard label="Positions">{summary.positions.length}</StatCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Portfolio value</CardTitle>
          <CardDescription>
            Approximate equity path from starting balance and filled trades.
          </CardDescription>
        </CardHeader>
        <CardContent className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis dataKey="label" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} domain={["auto", "auto"]} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="value"
                stroke="hsl(var(--primary))"
                fill="hsl(var(--primary) / 0.15)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Open positions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {summary.positions.length === 0 ? (
              <EmptyState
                title="No positions yet"
                description="Buy BTC, ETH, or SOL from the Market page to open a paper position."
              />
            ) : (
              summary.positions.map((p) => (
                <div
                  key={p.symbol}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-3"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <Badge>{p.symbol}</Badge>
                      <span className="text-sm text-muted-foreground">
                        {formatQty(p.quantity)} @ {formatMoney(p.average_entry_price)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm">
                      Market {formatMoney(p.market_value)} ·{" "}
                      <PnlText value={p.unrealized_pnl} />
                    </p>
                  </div>
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/trade/${p.symbol}?side=sell`}>Sell</Link>
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent trades</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(tradesQuery.data ?? []).slice(0, 6).length === 0 ? (
              <EmptyState
                title="No trades yet"
                description="Your filled paper trades will appear here."
              />
            ) : (
              (tradesQuery.data ?? []).slice(0, 6).map((t) => (
                <div key={t.id} className="rounded-md border px-3 py-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">
                      {t.side.toUpperCase()} {t.symbol}
                    </span>
                    <span className="text-muted-foreground">{formatDateTime(t.executed_at)}</span>
                  </div>
                  <p className="mt-1 text-muted-foreground">
                    {formatQty(t.quantity)} @ {formatMoney(t.price)} · fee {formatMoney(t.fee_amount)}
                  </p>
                  {t.side === "sell" && (
                    <p className="mt-1">
                      <PnlText value={t.realized_pnl} />
                    </p>
                  )}
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
