"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus } from "lucide-react";

import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import { api } from "@/lib/api";
import { feeCoverTpFrac } from "@/lib/coach-settings";
import { formatMoney, formatPercent, formatQty } from "@/lib/format";
import {
  exitPriceDigits,
  formatExitPrice,
  resolveSlTpPct,
} from "@/lib/sl-tp";
import { ApiError } from "@/lib/types";
import { cn } from "@/lib/utils";

type Side = "buy" | "sell";
type BottomTab = "position" | "balances" | "history";

const LEVERAGE_PRESETS = [1, 2, 3, 5, 10, 20, 25, 50] as const;
function buildDepthPreview(mid: number) {
  const asks = Array.from({ length: 8 }, (_, i) => {
    const price = mid * (1 + (i + 1) * 0.00012);
    const qty = 0.02 + (8 - i) * 0.35 + (i % 3) * 0.1;
    return { price, qty };
  }).reverse();
  const bids = Array.from({ length: 8 }, (_, i) => {
    const price = mid * (1 - (i + 1) * 0.00012);
    const qty = 0.05 + (8 - i) * 0.28 + (i % 2) * 0.15;
    return { price, qty };
  });
  const askVol = asks.reduce((s, r) => s + r.qty, 0);
  const bidVol = bids.reduce((s, r) => s + r.qty, 0);
  const total = askVol + bidVol || 1;
  return {
    asks,
    bids,
    bidPct: (bidVol / total) * 100,
    askPct: (askVol / total) * 100,
    maxQty: Math.max(...asks.map((a) => a.qty), ...bids.map((b) => b.qty)),
  };
}

export function PaperSpotDesk({ symbol = "BTC" }: { symbol?: string }) {
  const queryClient = useQueryClient();
  const { settings, update } = useCoachSettings();
  const [side, setSide] = useState<Side>("buy");
  const [pct, setPct] = useState(50);
  const [usdAmount, setUsdAmount] = useState(String(settings.autoStakeUsd));

  useEffect(() => {
    setUsdAmount(String(settings.autoStakeUsd));
  }, [settings.autoStakeUsd]);
  const [enableExits, setEnableExits] = useState(true);
  const [bottomTab, setBottomTab] = useState<BottomTab>("position");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const assetsQuery = useQuery({
    queryKey: ["assets"],
    queryFn: api.assets,
    staleTime: 60_000,
  });
  const assetMeta = useMemo(
    () => (assetsQuery.data ?? []).find((a) => a.symbol === symbol),
    [assetsQuery.data, symbol],
  );
  const priceDigits = exitPriceDigits(assetMeta?.price_precision ?? 2);
  const { slPct: effSlPct, tpPct: effTpPct } = useMemo(
    () => resolveSlTpPct(symbol, settings.slPct, settings.tpPct),
    [symbol, settings.slPct, settings.tpPct],
  );
  const priceQuery = useQuery({
    queryKey: ["price", symbol],
    queryFn: () => api.price(symbol),
    refetchInterval: 2_000,
  });
  const feedQuery = useQuery({
    queryKey: ["kraken-feed-status"],
    queryFn: api.krakenFeedStatus,
    refetchInterval: 1_000,
  });

  const accountQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: api.accountSummary,
    refetchInterval: 15_000,
  });
  const feeSettingsQuery = useQuery({
    queryKey: ["account-settings"],
    queryFn: api.accountSettings,
    staleTime: 60_000,
  });
  const positionQuery = useQuery({
    queryKey: ["position", symbol],
    queryFn: () => api.position(symbol).catch(() => null),
    refetchInterval: 10_000,
  });
  const labQuery = useQuery({
    queryKey: ["hypothesis-lab"],
    queryFn: api.hypothesisLab,
    staleTime: 30_000,
  });
  const promotedLab = (labQuery.data?.items ?? []).filter((item) => item.promoted_at);
  const activeLab =
    promotedLab.find((item) => item.id === settings.labHypothesisId) ?? promotedLab[0];

  const signalQuery = useQuery({
    queryKey: [
      "coach-signal",
      symbol,
      settings.interval,
      "lab",
      settings.labHypothesisId,
      activeLab?.id,
    ],
    queryFn: () =>
      api.coachSignal(symbol, settings.interval, {
        entrySource: "lab",
        hypothesisId: activeLab?.id,
      }),
    enabled: Boolean(activeLab?.id),
    refetchInterval: 15_000,
  });
  const tradesQuery = useQuery({
    queryKey: ["trades"],
    queryFn: api.trades,
    refetchInterval: 30_000,
  });

  // Prefer this symbol's quote. Kraken WS ticker is BTC-only — don't use it for other coins.
  const livePrice = Number(
    priceQuery.data?.price ??
      (symbol === "BTC"
        ? (feedQuery.data as { ticker_price?: string } | undefined)?.ticker_price
        : undefined) ??
      0,
  );

  const cash = Number(accountQuery.data?.cash_balance ?? 0);
  const pos = positionQuery.data;
  const qtyNum = pos ? Number(pos.quantity) : 0;
  const posSide = pos?.side || (qtyNum > 0 ? "long" : qtyNum < 0 ? "short" : "flat");
  const leverage = settings.leverage;
  const feePct = Number(feeSettingsQuery.data?.trading_fee_percent ?? 0.8);
  const feeUsd = Number(feeSettingsQuery.data?.trading_fee_usd ?? 0);
  const useFlatFee = feeUsd > 0;
  const signal = signalQuery.data?.signal ?? "WAIT";
  const trend = signalQuery.data?.trend ?? "NONE";
  const entry = signalQuery.data?.entry ?? "NONE";
  const phase = signalQuery.data?.phase ?? "NONE";
  const coachLabel =
    phase !== "NONE" && phase
      ? phase.replaceAll("_", " ")
      : entry === "ENTRY_BUY"
        ? "ENTRY BUY"
        : entry === "ENTRY_SELL"
          ? "ENTRY SELL"
          : trend === "HOLD_LONG" || trend === "BUY_TREND"
            ? "HOLD LONG"
            : trend === "HOLD_SHORT" || trend === "SELL_TREND"
              ? "HOLD SHORT"
              : signal;

  const liveUnrealized = useMemo(() => {
    if (!pos || !livePrice || qtyNum === 0) return null;
    const entryPx = Number(pos.average_entry_price);
    if (!(entryPx > 0) || !Number.isFinite(livePrice)) return null;
    return (livePrice - entryPx) * qtyNum;
  }, [pos, livePrice, qtyNum]);

  const liveUnrealizedPct = useMemo(() => {
    if (!pos || liveUnrealized == null) return null;
    const entryPx = Number(pos.average_entry_price);
    const notional = Math.abs(qtyNum) * entryPx;
    if (!(notional > 0)) return null;
    const onNotional = (liveUnrealized / notional) * 100;
    const posLev = Number(pos.leverage ?? leverage) || 1;
    const onMargin = onNotional * posLev;
    return { onNotional, onMargin, posLev };
  }, [pos, liveUnrealized, qtyNum, leverage]);

  const depth = useMemo(
    () => (livePrice > 0 ? buildDepthPreview(livePrice) : null),
    [livePrice],
  );

  const plannedSl = useMemo(() => {
    if (!livePrice || !enableExits) return null;
    return side === "buy"
      ? livePrice * (1 - effSlPct / 100)
      : livePrice * (1 + effSlPct / 100);
  }, [livePrice, enableExits, side, effSlPct]);

  const estMargin = Number(usdAmount || 0);
  const estNotional = estMargin > 0 ? estMargin * leverage : 0;
  const estFee = useFlatFee
    ? feeUsd
    : estNotional > 0
      ? (estNotional * feePct) / 100
      : 0;
  const estRoundTrip = estFee * 2;

  const setLeverage = (value: number) => {
    update({ leverage: value });
  };

  const plannedTp = useMemo(() => {
    if (!livePrice || !enableExits) return null;
    // Pad TP so a win still covers entry+exit fees (capped so tiny coins stay sane).
    const rawFeeFrac = useFlatFee
      ? estNotional > 0
        ? (2 * feeUsd) / estNotional
        : 0
      : feeCoverTpFrac(effTpPct, feePct) - effTpPct / 100;
    const feeFrac = Math.min(rawFeeFrac, effTpPct / 100);
    const tpFrac = effTpPct / 100 + feeFrac;
    return side === "buy" ? livePrice * (1 + tpFrac) : livePrice * (1 - tpFrac);
  }, [
    livePrice,
    enableExits,
    side,
    effTpPct,
    feePct,
    useFlatFee,
    feeUsd,
    estNotional,
  ]);

  const applyPct = (value: number) => {
    setPct(value);
    const feeReserve = useFlatFee ? feeUsd : 0;
    const cap = Math.max(0.5, cash - feeReserve);
    const spend = Math.max(0, (cap * value) / 100);
    setUsdAmount(spend.toFixed(2));
  };

  const nudgeUsd = (delta: number) => {
    const next = Math.max(0.5, Number(usdAmount || 0) + delta);
    setUsdAmount(next.toFixed(2));
  };

  const tradeMutation = useMutation({
    mutationFn: async () => {
      let amount = Number(usdAmount);
      if (!(amount > 0)) throw new Error("Enter a USD margin greater than 0");
      const feePart = useFlatFee ? feeUsd : (amount * leverage * feePct) / 100;
      // Leave room for flat/percent fee so full-cash margin still works.
      if (amount + feePart > cash + 0.0001) {
        amount = Math.max(0.5, cash - feePart);
        setUsdAmount(amount.toFixed(2));
      }
      const needed = amount + feePart;
      if (needed > cash + 0.0001 && side === "buy" && posSide !== "short") {
        throw new Error(
          `Not enough paper cash for margin+fee (need ~${formatMoney(needed)}, available ${formatMoney(cash)})`,
        );
      }
      // Leveraged shorts lock margin; 1x short uses spot-style proceeds (no margin lock).
      if (
        needed > cash + 0.0001 &&
        side === "sell" &&
        posSide !== "long" &&
        leverage > 1
      ) {
        throw new Error(
          `Not enough paper cash for short margin+fee (need ~${formatMoney(needed)}, available ${formatMoney(cash)})`,
        );
      }
      const payload = {
        symbol,
        usd_amount: String(amount),
        leverage,
        stop_loss_price: plannedSl ? formatExitPrice(plannedSl, priceDigits) : undefined,
        take_profit_price: plannedTp ? formatExitPrice(plannedTp, priceDigits) : undefined,
        entry_reason: `Paper desk ${side.toUpperCase()} · ${leverage}x · market · coach signal ${signal}`,
        followed_plan: true,
        emotional_state: "calm" as const,
        confidence_score: 4,
      };
      // Closing paths use full position qty — usd_amount at a new price leaves dust
      // (e.g. short 0.00142557 covered with $90 → leftover 4e-7 BTC → $0.0000 P/L).
      if (side === "buy" && posSide === "short" && pos) {
        return api.buy({
          symbol,
          quantity: String(Math.abs(Number(pos.quantity))),
          exit_reason: "Paper desk BUY · cover SHORT",
          followed_plan: true,
          emotional_state: "calm",
        });
      }
      if (side === "buy") return api.buy(payload);
      if (posSide === "long" && pos) {
        return api.sell({
          symbol,
          quantity: String(Math.abs(Number(pos.quantity))),
          exit_reason: "Paper desk SELL · close LONG",
          followed_plan: true,
          emotional_state: "calm",
        });
      }
      return api.sell(payload);
    },
    onSuccess: async (order) => {
      setErr(null);
      const feePart = order.fee_amount
        ? ` · fee ${formatMoney(order.fee_amount)} (${feePct}% taker)`
        : "";
      setMsg(
        `Paper ${order.side.toUpperCase()} filled · ${formatQty(order.filled_quantity)} ${symbol} @ ${formatMoney(order.filled_price)}${feePart}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["position", symbol] }),
        queryClient.invalidateQueries({ queryKey: ["trades"] }),
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
      ]);
    },
    onError: (error) => {
      setMsg(null);
      const raw =
        error instanceof ApiError ? error.message : (error as Error).message;
      setErr(
        /daily trade limit/i.test(raw)
          ? `${raw}. Go to Settings → Max trades / day to raise the paper-trading limit.`
          : raw,
      );
    },
  });

  const feedStatus = String(
    (feedQuery.data as { status?: string } | undefined)?.status ?? "disconnected",
  );
  const change24 = priceQuery.data?.change_24h_percent;
  const priceTone =
    Number(change24 ?? 0) < 0
      ? "text-red-600 dark:text-red-400"
      : Number(change24 ?? 0) > 0
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-foreground";

  const ctaLabel =
    side === "buy"
      ? posSide === "short"
        ? "Buy · cover SHORT"
        : `Buy ${symbol}`
      : posSide === "long"
        ? "Sell · close LONG"
        : "Sell · open SHORT";

  const posNotional =
    pos && livePrice > 0 ? Math.abs(qtyNum) * Number(pos.average_entry_price) : 0;
  const isDustPosition = pos != null && posNotional > 0 && posNotional < 0.05;

  if (priceQuery.isLoading || accountQuery.isLoading) {
    return <Skeleton className="h-[640px] w-full" />;
  }

  return (
    <div className="space-y-4">
      <PaperBanner />

      <div className="rounded-2xl border bg-card p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{symbol}/USD</h1>
              <Badge variant="secondary">Paper futures</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Kraken public price · no real orders ·{" "}
              <span className="font-medium text-foreground">
                Cash {formatMoney(cash)}
              </span>{" "}
              · {leverage}x · margin size below is not your balance
            </p>
          </div>
          <div className="text-right">
            <p className={cn("text-2xl font-semibold tabular-nums", priceTone)}>
              {livePrice ? formatMoney(livePrice) : "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              Feed {feedStatus}
              {change24 != null ? ` · 24h ${formatPercent(change24)}` : ""}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Badge
            variant="outline"
            className={cn(
              (entry === "ENTRY_BUY" ||
                phase === "ENTRY_BUY" ||
                phase === "HOLD_LONG" ||
                trend === "HOLD_LONG" ||
                trend === "BUY_TREND") &&
                "border-emerald-500 text-emerald-700",
              (entry === "ENTRY_SELL" ||
                phase === "ENTRY_SELL" ||
                phase === "HOLD_SHORT" ||
                trend === "HOLD_SHORT" ||
                trend === "SELL_TREND") &&
                "border-red-500 text-red-700",
              (phase === "EXIT_BUY" || phase === "EXIT_SELL") &&
                "border-slate-400 text-slate-600",
            )}
          >
            Coach {coachLabel}
          </Badge>
          <Badge variant="outline">Position {String(posSide).toUpperCase()}</Badge>
          <Badge variant="outline">
            Fee {feePct}% futures taker · RT {(feePct * 2).toFixed(2)}%
          </Badge>
          <Badge variant="outline">{leverage}x leverage</Badge>
          <Badge variant="outline">
            {symbol} SL {effSlPct}% / TP {effTpPct}%
            {effSlPct !== settings.slPct || effTpPct !== settings.tpPct ? " · scaled" : ""}
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        {/* Order ticket */}
        <div className="rounded-2xl border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              Paper futures · margin × leverage
            </span>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs">Market</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setSide("buy")}
              className={cn(
                "rounded-xl py-3 text-sm font-semibold transition",
                side === "buy"
                  ? "bg-emerald-600 text-white"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide("sell")}
              className={cn(
                "rounded-xl py-3 text-sm font-semibold transition",
                side === "sell"
                  ? "bg-red-600 text-white"
                  : "bg-muted text-muted-foreground hover:bg-muted/80",
              )}
            >
              Sell
            </button>
          </div>

          <div className="mt-4 space-y-3">
            <div className="rounded-xl border bg-muted/30 px-3 py-2">
              <p className="text-xs text-muted-foreground">Market price USD</p>
              <p className="font-medium tabular-nums">
                ≈ {livePrice ? formatMoney(livePrice) : "—"}
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="desk_leverage">Leverage</Label>
                <span className="text-xs tabular-nums text-muted-foreground">{leverage}x</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {LEVERAGE_PRESETS.map((lev) => (
                  <button
                    key={lev}
                    type="button"
                    onClick={() => setLeverage(lev)}
                    className={cn(
                      "rounded-lg px-2.5 py-1 text-xs font-medium transition",
                      leverage === lev
                        ? "bg-foreground text-background"
                        : "bg-muted text-muted-foreground hover:bg-muted/80",
                    )}
                  >
                    {lev}x
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="desk_usd">Margin USD</Label>
              <div className="flex items-center gap-2">
                <Button type="button" size="icon" variant="outline" onClick={() => nudgeUsd(-1)}>
                  <Minus className="h-4 w-4" />
                </Button>
                <Input
                  id="desk_usd"
                  type="number"
                  min={0.5}
                  step={0.5}
                  value={usdAmount}
                  onChange={(e) => setUsdAmount(e.target.value)}
                  className="text-center text-base font-medium"
                />
                <Button type="button" size="icon" variant="outline" onClick={() => nudgeUsd(1)}>
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Notional {formatMoney(estNotional)} · est. qty{" "}
                {livePrice > 0 ? formatQty(estNotional / livePrice) : "—"} {symbol}
              </p>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Use available cash</span>
                <span>{pct}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={100}
                step={5}
                value={pct}
                onChange={(e) => applyPct(Number(e.target.value))}
                className="w-full accent-emerald-600"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>0%</span>
                <span>50%</span>
                <span>100%</span>
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enableExits}
                onChange={(e) => setEnableExits(e.target.checked)}
              />
              TP / SL
            </label>
            {enableExits && (
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-xl border px-3 py-2">
                  <p className="text-xs text-muted-foreground">Stop Loss</p>
                  <p className="font-medium tabular-nums">
                    {plannedSl ? formatMoney(plannedSl, priceDigits) : "—"}
                  </p>
                </div>
                <div className="rounded-xl border px-3 py-2">
                  <p className="text-xs text-muted-foreground">Take Profit</p>
                  <p className="font-medium tabular-nums">
                    {plannedTp ? formatMoney(plannedTp, priceDigits) : "—"}
                  </p>
                </div>
              </div>
            )}

            <Button
              type="button"
              size="lg"
              className={cn(
                "h-12 w-full text-base font-semibold",
                side === "buy"
                  ? "bg-emerald-600 hover:bg-emerald-600/90"
                  : "bg-red-600 hover:bg-red-600/90",
              )}
              disabled={tradeMutation.isPending || !livePrice}
              onClick={() => tradeMutation.mutate()}
            >
              {tradeMutation.isPending ? "Working…" : ctaLabel}
            </Button>
            <p className="text-center text-[11px] text-muted-foreground">
              {useFlatFee
                ? `Flat fee ${formatMoney(feeUsd)} / fill · est. this fill ${formatMoney(estFee)} · round-trip ≈ ${formatMoney(estRoundTrip)}`
                : `Fee ${feePct}% · est. this fill ${formatMoney(estFee)} · round-trip ≈ ${formatMoney(estRoundTrip)}`}
            </p>
            <p className="text-center text-[11px] text-muted-foreground">
              Simulated fill only — never sent to Kraken private API
            </p>
          </div>
        </div>

        {/* Depth preview */}
        <div className="rounded-2xl border bg-card p-4 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium">Price ladder</p>
            <p className="text-[10px] text-muted-foreground">Paper preview around live mid</p>
          </div>
          {!depth ? (
            <Skeleton className="h-72 w-full" />
          ) : (
            <div className="space-y-1 font-mono text-xs">
              {depth.asks.map((row) => (
                <div key={`a-${row.price}`} className="relative flex justify-between px-2 py-1">
                  <span
                    className="absolute inset-y-0 right-0 bg-red-500/10"
                    style={{ width: `${(row.qty / depth.maxQty) * 100}%` }}
                  />
                  <span className="relative z-10 text-red-600 dark:text-red-400">
                    {row.price.toFixed(2)}
                  </span>
                  <span className="relative z-10 text-muted-foreground">{row.qty.toFixed(5)}</span>
                </div>
              ))}
              <div className="my-2 flex h-2 overflow-hidden rounded-full">
                <div className="bg-emerald-500" style={{ width: `${depth.bidPct}%` }} />
                <div className="bg-red-500" style={{ width: `${depth.askPct}%` }} />
              </div>
              <div className="mb-1 flex justify-between text-[10px] text-muted-foreground">
                <span className="text-emerald-600">{depth.bidPct.toFixed(1)}% bids</span>
                <span className="text-red-600">{depth.askPct.toFixed(1)}% asks</span>
              </div>
              {depth.bids.map((row) => (
                <div key={`b-${row.price}`} className="relative flex justify-between px-2 py-1">
                  <span
                    className="absolute inset-y-0 right-0 bg-emerald-500/10"
                    style={{ width: `${(row.qty / depth.maxQty) * 100}%` }}
                  />
                  <span className="relative z-10 text-emerald-600 dark:text-emerald-400">
                    {row.price.toFixed(2)}
                  </span>
                  <span className="relative z-10 text-muted-foreground">{row.qty.toFixed(5)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {(msg || err) && (
        <Alert variant={err ? "destructive" : "default"}>
          <AlertTitle>{err ? "Order blocked" : "Paper fill"}</AlertTitle>
          <AlertDescription>{err ?? msg}</AlertDescription>
        </Alert>
      )}

      {/* Bottom tabs */}
      <div className="rounded-2xl border bg-card shadow-sm">
        <div className="flex gap-1 overflow-x-auto border-b px-2 pt-2">
          {(
            [
              ["position", "Position"],
              ["balances", "Balances"],
              ["history", "Trade History"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setBottomTab(id)}
              className={cn(
                "rounded-t-lg px-3 py-2 text-sm",
                bottomTab === id
                  ? "bg-background font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="p-4 text-sm">
          {bottomTab === "position" && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
              <Stat label="Side" value={String(posSide).toUpperCase()} />
              <Stat
                label="Leverage"
                value={
                  pos
                    ? `${Number(pos.leverage ?? leverage)}x`
                    : `${leverage}x`
                }
              />
              <Stat
                label="Size"
                value={
                  pos
                    ? `${formatMoney(posNotional)} · ${formatQty(Math.abs(qtyNum))} ${symbol}`
                    : "—"
                }
              />
              <Stat
                label="Entry"
                value={pos ? formatMoney(pos.average_entry_price) : "—"}
              />
              <Stat
                label="SL / TP"
                value={
                  pos
                    ? `${pos.stop_loss_price ? formatMoney(pos.stop_loss_price) : "—"} / ${
                        pos.take_profit_price ? formatMoney(pos.take_profit_price) : "—"
                      }`
                    : "—"
                }
              />
              <div>
                <p className="text-xs text-muted-foreground">Unrealized P/L (live)</p>
                {pos && liveUnrealized != null ? (
                  <div>
                    <PnlText value={liveUnrealized} digits={isDustPosition ? 6 : undefined} />
                    {liveUnrealizedPct != null && (
                      <p
                        className={cn(
                          "mt-0.5 font-mono text-xs tabular-nums",
                          liveUnrealizedPct.onMargin > 0
                            ? "text-emerald-600"
                            : liveUnrealizedPct.onMargin < 0
                              ? "text-red-600"
                              : "text-muted-foreground",
                        )}
                      >
                        {liveUnrealizedPct.onMargin > 0 ? "+" : ""}
                        {liveUnrealizedPct.onMargin.toFixed(2)}% ROE ·{" "}
                        {liveUnrealizedPct.onNotional > 0 ? "+" : ""}
                        {liveUnrealizedPct.onNotional.toFixed(3)}% price · mark{" "}
                        {formatMoney(livePrice)}
                      </p>
                    )}
                    {isDustPosition && (
                      <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-300">
                        Dust leftover from a partial cover — size ≈ {formatMoney(posNotional)}.
                        Use Buy · cover SHORT to clear.
                      </p>
                    )}
                  </div>
                ) : pos ? (
                  <PnlText value={pos.unrealized_pnl} />
                ) : (
                  <p className="font-medium">—</p>
                )}
              </div>
            </div>
          )}
          {bottomTab === "balances" && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Paper cash" value={formatMoney(cash)} />
              <Stat
                label="Equity"
                value={formatMoney(accountQuery.data?.portfolio_value ?? cash)}
              />
              <Stat
                label="Realized P/L"
                value={formatMoney(accountQuery.data?.realized_pnl ?? 0)}
              />
            </div>
          )}
          {bottomTab === "history" && (
            <div className="space-y-2">
              {(tradesQuery.data ?? []).slice(0, 8).map((t) => (
                <div
                  key={t.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2"
                >
                  <div>
                    <p className="font-medium">
                      {t.side.toUpperCase()} {t.symbol} · {formatQty(t.quantity)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(t.executed_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p>{formatMoney(t.price)}</p>
                    <PnlText value={t.realized_pnl} className="text-xs" />
                  </div>
                </div>
              ))}
              {(tradesQuery.data ?? []).length === 0 && (
                <p className="text-muted-foreground">No paper trades yet.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
