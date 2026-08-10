"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/empty-state";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney, formatPercent, formatQty } from "@/lib/format";

export default function PortfolioPage() {
  const summaryQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: api.accountSummary,
  });
  const positionsQuery = useQuery({
    queryKey: ["positions"],
    queryFn: api.positions,
  });

  const rows = useMemo(() => {
    const portfolio = Number(summaryQuery.data?.portfolio_value ?? 0);
    return (positionsQuery.data ?? []).map((p) => {
      const unrealizedPct =
        Number(p.average_entry_price) === 0
          ? 0
          : ((Number(p.current_price) - Number(p.average_entry_price)) /
              Number(p.average_entry_price)) *
            100;
      const allocation =
        portfolio === 0 ? 0 : (Number(p.market_value) / portfolio) * 100;
      return { ...p, unrealizedPct, allocation };
    });
  }, [positionsQuery.data, summaryQuery.data]);

  if (summaryQuery.isLoading || positionsQuery.isLoading) {
    return <Skeleton className="h-80 w-full" />;
  }

  if (summaryQuery.isError || positionsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load portfolio</AlertTitle>
        <AlertDescription>
          {((summaryQuery.error || positionsQuery.error) as Error).message}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Portfolio</h1>
        <p className="text-sm text-muted-foreground">
          Holdings on your $20,000 paper account.
        </p>
      </div>

      <PaperBanner message={summaryQuery.data?.paper_mode_banner} />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Portfolio value
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {formatMoney(summaryQuery.data?.portfolio_value)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Cash</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {formatMoney(summaryQuery.data?.cash_balance)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Unrealized P&L
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            <PnlText value={summaryQuery.data?.unrealized_pnl} />
          </CardContent>
        </Card>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No holdings"
          description="Open the market and place a paper buy to build a portfolio."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b bg-muted/40">
              <tr>
                <th className="px-3 py-3 font-medium">Symbol</th>
                <th className="px-3 py-3 font-medium">Quantity</th>
                <th className="px-3 py-3 font-medium">Avg entry</th>
                <th className="px-3 py-3 font-medium">Current</th>
                <th className="px-3 py-3 font-medium">Market value</th>
                <th className="px-3 py-3 font-medium">Unrealized</th>
                <th className="px-3 py-3 font-medium">Unrealized %</th>
                <th className="px-3 py-3 font-medium">Allocation</th>
                <th className="px-3 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol} className="border-b last:border-0">
                  <td className="px-3 py-3">
                    <Badge>{row.symbol}</Badge>
                  </td>
                  <td className="px-3 py-3 tabular-nums">{formatQty(row.quantity)}</td>
                  <td className="px-3 py-3 tabular-nums">
                    {formatMoney(row.average_entry_price)}
                  </td>
                  <td className="px-3 py-3 tabular-nums">{formatMoney(row.current_price)}</td>
                  <td className="px-3 py-3 tabular-nums">{formatMoney(row.market_value)}</td>
                  <td className="px-3 py-3">
                    <PnlText value={row.unrealized_pnl} />
                  </td>
                  <td className="px-3 py-3">
                    <PnlText value={row.unrealizedPct} asPercent />
                  </td>
                  <td className="px-3 py-3 tabular-nums">{formatPercent(row.allocation)}</td>
                  <td className="px-3 py-3">
                    <Button asChild size="sm" variant="outline">
                      <Link href={`/trade/${row.symbol}?side=sell`}>Sell</Link>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
