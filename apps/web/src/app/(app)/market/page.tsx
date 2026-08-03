"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { PaperBanner } from "@/components/layout/paper-banner";
import { KrakenFeedStatus } from "@/components/kraken-feed-status";
import { SignalAutoCard } from "@/components/signal-auto-card";
import { TradingChart } from "@/components/trading-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { BASIC_EMA_RULES } from "@/lib/ema-signals";
import { cn } from "@/lib/utils";

const FOCUS_SYMBOL = "BTC";

export default function MarketPage() {
  const [selected, setSelected] = useState(FOCUS_SYMBOL);
  const assetsQuery = useQuery({ queryKey: ["assets"], queryFn: api.assets });

  const loading = assetsQuery.isLoading;
  const error = assetsQuery.error;
  const others = (assetsQuery.data ?? [])
    .map((a) => a.symbol)
    .filter((s) => s !== FOCUS_SYMBOL);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Market</h1>
        <p className="text-sm text-muted-foreground">
          Same EMA / ENTRY–HOLD–EXIT formula on every listed coin — pick a symbol to test if the
          setup holds beyond BTC.
        </p>
      </div>

      <PaperBanner />

      <KrakenFeedStatus />

      {error && (
        <Alert variant="warning">
          <AlertTitle>Asset data unavailable</AlertTitle>
          <AlertDescription>{(error as Error).message}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant={selected === FOCUS_SYMBOL ? "default" : "outline"}
          onClick={() => setSelected(FOCUS_SYMBOL)}
        >
          {FOCUS_SYMBOL} (active)
        </Button>
        {others.map((sym) => (
          <Button
            key={sym}
            type="button"
            size="sm"
            variant={selected === sym ? "default" : "outline"}
            onClick={() => setSelected(sym)}
          >
            {sym}
          </Button>
        ))}
        <Button asChild size="sm" variant="secondary" className="ml-auto">
          <Link href={`/trade/${selected}`}>Manual ticket · {selected}</Link>
        </Button>
      </div>

      <TradingChart symbol={selected} height={460} defaultInterval="15m" />

      {loading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_0.8fr]">
          <SignalAutoCard symbol={selected} />

          <Card className="border-dashed opacity-80">
            <CardHeader>
              <CardTitle className="text-base">Other coins</CardTitle>
              <CardDescription>
                Same rules (EMA9/21 + gap) on every coin. Select above to compare signals / auto
                paper fills for that symbol only.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground leading-relaxed">
                Active rule: {BASIC_EMA_RULES.label}. Auto desk buys/sells only when the coach signal
                matches (closed bar). Google Chat notifies on ENTRY and EXIT only.
              </p>
              <div className={cn("rounded-md border bg-muted/20 px-3 py-3 text-sm text-muted-foreground")}>
                <p className="font-medium text-foreground">{others.length} extra pairs listed</p>
                <p>Same paper engine · public prices</p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
