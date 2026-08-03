"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EmptyState } from "@/components/empty-state";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatDateTime, formatMoney, formatQty } from "@/lib/format";

export default function HistoryPage() {
  const tradesQuery = useQuery({ queryKey: ["trades"], queryFn: api.trades });
  const [symbol, setSymbol] = useState("all");
  const [side, setSide] = useState("all");
  const [pnl, setPnl] = useState("all");
  const [dateFrom, setDateFrom] = useState("");

  const filtered = useMemo(() => {
    return (tradesQuery.data ?? []).filter((trade) => {
      if (symbol !== "all" && trade.symbol !== symbol) return false;
      if (side !== "all" && trade.side !== side) return false;
      if (pnl === "profit" && !(trade.side === "sell" && Number(trade.realized_pnl) > 0)) {
        return false;
      }
      if (pnl === "loss" && !(trade.side === "sell" && Number(trade.realized_pnl) < 0)) {
        return false;
      }
      if (dateFrom) {
        const day = trade.executed_at.slice(0, 10);
        if (day < dateFrom) return false;
      }
      return true;
    });
  }, [tradesQuery.data, symbol, side, pnl, dateFrom]);

  if (tradesQuery.isLoading) return <Skeleton className="h-80 w-full" />;

  if (tradesQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load trade history</AlertTitle>
        <AlertDescription>{(tradesQuery.error as Error).message}</AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Trade History</h1>
        <p className="text-sm text-muted-foreground">
          Filled paper trades with fees and realized P&L.
        </p>
      </div>

      <PaperBanner />

      <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-2">
          <Label>Symbol</Label>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="BTC">BTC</SelectItem>
              <SelectItem value="ETH">ETH</SelectItem>
              <SelectItem value="SOL">SOL</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>Side</Label>
          <Select value={side} onValueChange={setSide}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="buy">Buy</SelectItem>
              <SelectItem value="sell">Sell</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label>P&L</Label>
          <Select value={pnl} onValueChange={setPnl}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="profit">Profit</SelectItem>
              <SelectItem value="loss">Loss</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="dateFrom">From date</Label>
          <Input
            id="dateFrom"
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
          />
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="No matching trades"
          description="Adjust filters or place a paper trade from the Market page."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="border-b bg-muted/40">
              <tr>
                <th className="px-3 py-3 font-medium">Time</th>
                <th className="px-3 py-3 font-medium">Symbol</th>
                <th className="px-3 py-3 font-medium">Side</th>
                <th className="px-3 py-3 font-medium">Quantity</th>
                <th className="px-3 py-3 font-medium">Price</th>
                <th className="px-3 py-3 font-medium">Fee</th>
                <th className="px-3 py-3 font-medium">P&L</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((trade) => (
                <tr key={trade.id} className="border-b last:border-0">
                  <td className="px-3 py-3 text-muted-foreground">
                    {formatDateTime(trade.executed_at)}
                  </td>
                  <td className="px-3 py-3 font-medium">{trade.symbol}</td>
                  <td className="px-3 py-3 uppercase">{trade.side}</td>
                  <td className="px-3 py-3 tabular-nums">{formatQty(trade.quantity)}</td>
                  <td className="px-3 py-3 tabular-nums">{formatMoney(trade.price)}</td>
                  <td className="px-3 py-3 tabular-nums">{formatMoney(trade.fee_amount)}</td>
                  <td className="px-3 py-3">
                    {trade.side === "sell" ? (
                      <PnlText value={trade.realized_pnl} />
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
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
