"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { chartEmasFromRules } from "@/lib/lab-chart-emas";
import { formatLabProfileLabel, labProfileNumbers } from "@/lib/lab-profile-label";
import { HypothesisBacktest, HypothesisLabAccess, HypothesisLabItem } from "@/lib/types";

const EXAMPLE =
  "BTCUSDT 15m: buy when EMA9 is above EMA21, 1h close above EMA200, volume > 1.5x average, RSI 50-70, stop 1 ATR, target 2R";

/** Higher-low + swing-high break (structure stop) — not Donchian N-bar breakout. */
const STRUCTURE_HL_EXAMPLE =
  "BTCUSDT 15m: long only when 1h close is above EMA200, EMA9 is above EMA21, " +
  "price forms a confirmed higher low, then a 15m candle closes above the previous swing high, " +
  "volume > 1.5x 20-bar average, stop below the confirmed higher low, target 2R. " +
  "No entry before the breakout candle closes.";

/** Matches apps/api TRADE_TO_LIVE_PROMPT — quality-first paper practice, not income claims. */
const TRADE_TO_LIVE_TEMPLATE =
  "BTCUSDT 15m Trade-to-Live single setup: LONG only in a clear uptrend " +
  "(EMA9 above EMA21 and close above EMA9; 1h close above EMA200). " +
  "Treat support/resistance as zones — never enter only because price touches a level. " +
  "Confirm on the closed 15m bar (bullish rejection / reclaim of EMA9, buyers defending the zone, " +
  "volume at least 1.5x). ATR 1x stop below structure; take profit at least 2R (prefer 2.5–3R). " +
  "If trend is unclear, no closed-bar confirmation, or RR below 1:2 → WAIT / NO TRADE. " +
  "Quality over quantity (~1–3 high-quality paper setups per week).";

function assistantBadge(rules: Record<string, unknown>): string | null {
  const assistant = rules.assistant as Record<string, unknown> | undefined;
  if (!assistant || assistant.philosophy !== "trade_to_live") return null;
  const minRr = typeof assistant.min_rr === "number" ? assistant.min_rr : 2;
  return `Trade-to-Live · WAIT unless RR ≥ 1:${minRr} · closed-bar confirmation`;
}

function MetricRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return <div className="flex justify-between gap-4 border-b py-1 text-sm"><span className="text-muted-foreground">{label}</span><span>{value ?? "—"}</span></div>;
}

function ParserBadge({ parser }: { parser: string }) {
  const label = parser === "ollama"
    ? "Parsed by Ollama"
    : parser === "groq"
      ? "Parsed by Groq"
      : parser === "gemini"
        ? "Parsed by Gemini"
        : "Parsed by rules engine";
  return <span className="rounded-full border px-2 py-0.5 text-xs font-normal text-muted-foreground">{label}</span>;
}

function ChartEmaBadge({ rules }: { rules: Record<string, unknown> }) {
  const periods = chartEmasFromRules(rules);
  return (
    <p className="text-sm text-muted-foreground">
      Chart EMAs:{" "}
      <span className="font-medium text-foreground">
        {periods.map((period) => `EMA${period}`).join(", ")}
      </span>
      <span className="mt-1 block text-xs">
        EMAs mentioned in your prompt appear on the Market chart.
      </span>
    </p>
  );
}

function BacktestResult({ result }: { result: HypothesisBacktest }) {
  return (
    <div className="space-y-3 rounded-md border bg-muted/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong>Verdict: {result.verdict}</strong>
        <span className="text-xs text-muted-foreground">{result.bars.toLocaleString()} candles · {result.trade_count} trades</span>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {Object.entries(result.periods).map(([period, metrics]) => (
          <div key={period} className="rounded border bg-background p-3">
            <p className="mb-2 font-medium capitalize">{period}</p>
            <MetricRow label="Trades" value={metrics.trades} />
            <MetricRow label="Win rate" value={`${(metrics.win_rate * 100).toFixed(1)}%`} />
            <MetricRow label="Net P&L" value={`$${metrics.net_pnl.toFixed(2)}`} />
            <MetricRow label="Expectancy" value={`${metrics.expectancy.toFixed(3)}R`} />
            <MetricRow label="Profit factor" value={metrics.profit_factor?.toFixed(2)} />
            <MetricRow label="Max drawdown" value={`${(metrics.max_drawdown * 100).toFixed(1)}%`} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{result.methodology}</p>
    </div>
  );
}

function HypothesisCard({
  item,
  profileNumber,
  access,
}: {
  item: HypothesisLabItem;
  profileNumber: number;
  access?: HypothesisLabAccess;
}) {
  const queryClient = useQueryClient();
  const [lastResult, setLastResult] = useState<HypothesisBacktest | null>(
    item.backtests[item.backtests.length - 1] ?? null,
  );
  const backtest = useMutation({
    mutationFn: () => api.backtestHypothesis(item.id),
    onSuccess: (result) => {
      setLastResult(result);
      void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab"] });
      void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab-access"] });
    },
  });
  const promote = useMutation({
    mutationFn: () => api.promoteHypothesis(item.id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab"] }),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteHypothesis(item.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab"] });
      void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab-access"] });
    },
  });
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-lg">
          <span className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-primary/10 px-2 py-0.5 text-sm font-semibold tabular-nums text-primary">
              #{profileNumber}
            </span>
            <span>
              {item.name}{" "}
              <span className="text-xs font-normal text-muted-foreground">v{item.version}</span>
            </span>
          </span>
          <ParserBadge parser={item.parser} />
        </CardTitle>
        <CardDescription>{item.natural_language_prompt || "Structured rule set"}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ChartEmaBadge rules={item.structured_rules} />
        {assistantBadge(item.structured_rules) && (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-950 dark:text-amber-100">
            {assistantBadge(item.structured_rules)}
          </p>
        )}
        <pre className="max-h-56 overflow-auto rounded border bg-muted/30 p-3 text-xs">{JSON.stringify(item.structured_rules, null, 2)}</pre>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => backtest.mutate()} disabled={backtest.isPending || remove.isPending}>
            {backtest.isPending ? "Fetching candles & testing…" : "Backtest"}
          </Button>
          <Button variant="outline" onClick={() => promote.mutate()} disabled={promote.isPending || remove.isPending || access?.can_promote === false}>
            {item.promoted_at ? "Paper profile saved" : "Save paper profile"}
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              if (
                window.confirm(
                  `Delete profile #${profileNumber} “${item.name}” v${item.version}? This cannot be undone.`,
                )
              ) {
                remove.mutate();
              }
            }}
            disabled={remove.isPending}
          >
            {remove.isPending ? "Deleting…" : "Delete"}
          </Button>
        </div>
        {backtest.error && <p className="text-sm text-destructive">{(backtest.error as Error).message}</p>}
        {remove.error && <p className="text-sm text-destructive">{(remove.error as Error).message}</p>}
        {access?.can_promote === false && (
          <p className="text-xs text-muted-foreground">Saving this paper profile is temporarily unavailable.</p>
        )}
        {promote.isSuccess && (
          <Alert>
            <AlertTitle>Paper profile saved</AlertTitle>
            <AlertDescription>
              This immutable version is ready for paper AUTO. Open Market or Coach, choose this
              profile, then turn AUTO on. It evaluates closed candles and fills an eligible long at
              the next candle open.
            </AlertDescription>
          </Alert>
        )}
        {lastResult && <BacktestResult result={lastResult} />}
      </CardContent>
    </Card>
  );
}

export default function HypothesisLabPage() {
  const [prompt, setPrompt] = useState(EXAMPLE);
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["hypothesis-lab"], queryFn: api.hypothesisLab });
  const access = useQuery({ queryKey: ["hypothesis-lab-access"], queryFn: api.hypothesisLabAccess });
  const create = useMutation({
    mutationFn: () => api.createHypothesis({ prompt }),
    onSuccess: () => {
      setPrompt("");
      void queryClient.invalidateQueries({ queryKey: ["hypothesis-lab"] });
    },
  });
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Hypothesis Lab</h1>
        <p className="text-sm text-muted-foreground">Turn a rule idea into an immutable, causal paper-research version.</p>
      </div>
      <Alert>
        <AlertTitle>Research only · no profitability claims</AlertTitle>
        <AlertDescription>Tests include 0.80% fees per fill, spread, slippage, next-open entries, and an out-of-sample split. Paper trading is still required.</AlertDescription>
      </Alert>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Lab plan: {access.data?.plan?.toUpperCase() ?? "…"}</CardTitle>
          <CardDescription>
            {access.data?.daily_backtest_limit == null
              ? "Unlimited backtests and Save paper profile — free for paper testing."
              : `${access.data?.backtests_today ?? 0}/${access.data?.daily_backtest_limit ?? 3} free backtests used today.`}
          </CardDescription>
        </CardHeader>
        {access.data?.upgrade_message && (
          <CardContent className="space-y-3 pt-0">
            <p className="text-sm text-muted-foreground">{access.data.upgrade_message}</p>
          </CardContent>
        )}
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Describe a hypothesis</CardTitle>
          <CardDescription>
            Describe a hypothesis, for example: “EMA9 crosses above EMA21, volume 1.5x, RSI 50–70, ATR 1x stop, 2R target.”
            Structure setups are supported too: confirmed higher low → close above prior swing high, stop below the HL
            (not a 20-bar Donchian breakout). EMAs mentioned in your prompt appear on the Market chart. Prefer WAIT /
            NO TRADE when the setup is incomplete — quality over forced paper entries.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" size="sm" onClick={() => setPrompt(TRADE_TO_LIVE_TEMPLATE)}>
              Use Trade-to-Live template
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setPrompt(STRUCTURE_HL_EXAMPLE)}>
              Use HL + swing break example
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setPrompt(EXAMPLE)}>
              Use simple EMA example
            </Button>
          </div>
          <textarea className="min-h-28 w-full rounded-md border bg-background p-3 text-sm" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          <Button onClick={() => create.mutate()} disabled={!prompt.trim() || create.isPending}>
            {create.isPending ? "Generating…" : "Generate testable version"}
          </Button>
          {create.error && <p className="text-sm text-destructive">{(create.error as Error).message}</p>}
        </CardContent>
      </Card>
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Your versions</h2>
        <p className="text-xs text-muted-foreground">
          Profiles are numbered #1, #2, … by creation time (oldest first). The same number appears in
          Market when you choose a paper profile.
        </p>
        {list.isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : list.data?.items.length ? (
          (() => {
            const numbers = labProfileNumbers(list.data.items);
            return list.data.items.map((item) => (
              <HypothesisCard
                key={item.id}
                item={item}
                profileNumber={numbers.get(item.id) ?? 0}
                access={access.data}
              />
            ));
          })()
        ) : (
          <p className="text-sm text-muted-foreground">
            Create a hypothesis to see its structured rules and backtest results.
          </p>
        )}
      </div>
    </div>
  );
}
