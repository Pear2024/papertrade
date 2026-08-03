"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type FeedStatus = {
  status: "connected" | "reconnecting" | "disconnected" | string;
  ticker_price?: string | null;
  last_error?: string | null;
  last_closed_candle_time_15m?: number | null;
  paper_only?: boolean;
  private_api_used?: boolean;
  symbol?: string;
  source?: string;
};

export function KrakenFeedStatus() {
  const feedQuery = useQuery({
    queryKey: ["kraken-feed-status"],
    queryFn: () => api.krakenFeedStatus() as Promise<FeedStatus>,
    refetchInterval: 5_000,
  });

  const data = feedQuery.data;
  const status = data?.status ?? "disconnected";
  const tone =
    status === "connected"
      ? "bg-emerald-600"
      : status === "reconnecting"
        ? "bg-amber-500"
        : "bg-red-600";

  const closedAt = data?.last_closed_candle_time_15m
    ? new Date(data.last_closed_candle_time_15m * 1000).toLocaleString()
    : "—";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">Kraken public feed</CardTitle>
          <Badge className={cn("capitalize text-white", tone)}>{status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Live BTC/USD</p>
          <p className="font-semibold">
            {data?.ticker_price ? formatMoney(data.ticker_price) : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Pair</p>
          <p className="font-semibold">{data?.symbol ?? "BTC/USD"}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Last closed 15m candle</p>
          <p className="font-semibold text-xs sm:text-sm">{closedAt}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Safety</p>
          <p className="font-semibold">
            Paper only · private API {data?.private_api_used ? "USED (!)" : "never"}
          </p>
        </div>
        {data?.last_error && (
          <p className="sm:col-span-2 lg:col-span-4 text-xs text-amber-700 dark:text-amber-300">
            Last error: {data.last_error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
