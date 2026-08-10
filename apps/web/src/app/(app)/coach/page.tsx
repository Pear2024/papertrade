"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { SignalAutoCard } from "@/components/signal-auto-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";

const SYMBOLS = [
  "BTC",
  "ETH",
  "SOL",
  "XRP",
  "BNB",
  "ADA",
  "DOGE",
  "AVAX",
  "DOT",
  "LINK",
  "MATIC",
  "ATOM",
  "LTC",
  "UNI",
  "APT",
  "ARB",
  "OP",
  "SUI",
  "NEAR",
  "TRX",
  "SHIB",
  "TON",
  "ICP",
  "FIL",
  "AAVE",
  "PEPE",
  "INJ",
  "SEI",
  "WIF",
  "RENDER",
] as const;

export default function CoachPage() {
  const { settings } = useCoachSettings();
  const [symbol, setSymbol] = useState<(typeof SYMBOLS)[number]>("BTC");

  const promptQuery = useQuery({ queryKey: ["coach-prompt"], queryFn: api.coachPrompt });
  const statsQuery = useQuery({
    queryKey: ["coach-stats"],
    queryFn: api.coachStats,
    refetchInterval: 30_000,
  });

  const stats = statsQuery.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">AI Coach</h1>
        <p className="text-sm text-muted-foreground">
          Lab paper AUTO — same desk as Market. Your Hypothesis Lab prompts drive entries.
        </p>
      </div>

      <PaperBanner />

      <Alert>
        <AlertTitle>Practice goal</AlertTitle>
        <AlertDescription>
          Complete <strong>200–500 paper trades</strong> first. Review win rate, profit factor, and
          drawdown before ever thinking about real money. This app never trades real money.
        </AlertDescription>
      </Alert>

      <Alert>
        <AlertTitle>Lab-only paper AUTO · default {settings.autoOnDefault ? "ON" : "OFF"}</AlertTitle>
        <AlertDescription>
          Write rules in{" "}
          <Link href="/lab" className="underline underline-offset-4">
            Lab
          </Link>
          , promote a paper profile, then run AUTO here or on Market. Risk defaults live in{" "}
          <Link href="/settings" className="underline underline-offset-4">
            Settings
          </Link>
          . Tick every ~{settings.autoTickSeconds}s while this page stays open.
        </AlertDescription>
      </Alert>

      {statsQuery.isLoading ? (
        <Skeleton className="h-28 w-full" />
      ) : stats ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Win rate</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.win_rate != null ? formatPercent(stats.win_rate) : "—"}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Net profit</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              <PnlText value={stats.net_profit} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Max drawdown</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.max_drawdown != null ? formatMoney(stats.max_drawdown) : "—"}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Paper trades</CardDescription>
            </CardHeader>
            <CardContent className="text-2xl font-semibold">
              {stats.closed_trades}/{stats.practice_trades_target}
              <p className="text-xs font-normal text-muted-foreground">
                {stats.practice_progress_pct}% of practice goal
              </p>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {stats?.trading_locked && (
        <Alert variant="destructive">
          <AlertTitle>Trading locked by stats</AlertTitle>
          <AlertDescription>{stats.lock_reason}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        {SYMBOLS.map((sym) => (
          <Button
            key={sym}
            type="button"
            size="sm"
            variant={symbol === sym ? "default" : "outline"}
            onClick={() => setSymbol(sym)}
            disabled={!!stats?.trading_locked}
          >
            {sym}
          </Button>
        ))}
      </div>

      <SignalAutoCard symbol={symbol} />

      <Card>
        <CardHeader>
          <CardTitle>Legacy coach prompt (reference)</CardTitle>
          <CardDescription>
            Historical DayTradeCryptoCoach text — live entries use your Lab profiles, not this
            prompt.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {promptQuery.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-xs leading-relaxed">
              {promptQuery.data?.prompt}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
