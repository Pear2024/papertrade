"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

import { CoachSignalPanel } from "@/components/coach-signal-panel";
import { PaperBanner } from "@/components/layout/paper-banner";
import { PnlText } from "@/components/pnl-text";
import { TradingChart } from "@/components/trading-chart";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { suggestedExitsFromEntry } from "@/lib/ema-signals";
import { formatMoney, formatQty } from "@/lib/format";
import { ApiError, CandleInterval, OrderPayload, TradePreview } from "@/lib/types";

const emotions = ["calm", "confident", "fearful", "greedy", "impatient", "unsure"] as const;

const schema = z
  .object({
    usd_amount: z.string().optional(),
    quantity: z.string().optional(),
    stop_loss_price: z.string().optional(),
    take_profit_price: z.string().optional(),
    entry_reason: z.string().optional(),
    emotional_state: z.enum(emotions).optional(),
    confidence_score: z.string().optional(),
    followed_plan: z.boolean().optional(),
  })
  .superRefine((values, ctx) => {
    const hasUsd = !!values.usd_amount?.trim();
    const hasQty = !!values.quantity?.trim();
    if (!hasUsd && !hasQty) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Enter USD amount (recommended) — leave Quantity empty",
        path: ["usd_amount"],
      });
    }
    if (hasUsd && hasQty) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Fill only ONE: USD amount OR Quantity (not both)",
        path: ["quantity"],
      });
    }
  });

type FormValues = z.infer<typeof schema>;

function TradePageInner() {
  const params = useParams<{ symbol: string }>();
  const search = useSearchParams();
  const symbol = (params.symbol || "BTC").toUpperCase();
  const initialSide = search.get("side") === "sell" ? "sell" : "buy";
  const [side, setSide] = useState<"buy" | "sell">(initialSide);
  const [preview, setPreview] = useState<TradePreview | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [coachInterval, setCoachInterval] = useState<CandleInterval>("15m");
  const queryClient = useQueryClient();

  const priceQuery = useQuery({
    queryKey: ["price", symbol],
    queryFn: () => api.price(symbol),
    refetchInterval: 20_000,
  });
  const summaryQuery = useQuery({
    queryKey: ["account-summary"],
    queryFn: api.accountSummary,
  });
  const positionQuery = useQuery({
    queryKey: ["position", symbol],
    queryFn: () => api.position(symbol).catch(() => null),
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      followed_plan: true,
      confidence_score: "3",
      emotional_state: "calm",
      usd_amount: "",
      quantity: "",
      stop_loss_price: "",
      take_profit_price: "",
      entry_reason: "",
    },
  });
  const { errors } = form.formState;

  const requireStopLoss = summaryQuery.data?.account.require_stop_loss ?? true;
  const livePrice = priceQuery.data ? Number(priceQuery.data.price) : null;
  const [exitSl, setExitSl] = useState("");
  const [exitTp, setExitTp] = useState("");
  const [exitMsg, setExitMsg] = useState<string | null>(null);

  const mediumStopsFrom = (price: number) => suggestedExitsFromEntry(price);

  const applyMediumStops = () => {
    if (!livePrice || livePrice <= 0) {
      setFormError("Price not loaded yet — wait a second and try again");
      return;
    }
    const { sl, tp } = mediumStopsFrom(livePrice);
    form.setValue("stop_loss_price", sl, { shouldDirty: true, shouldValidate: true });
    form.setValue("take_profit_price", tp, { shouldDirty: true, shouldValidate: true });
    setFormError(null);
  };

  // Auto-fill Medium SL/TP once price is ready (only if fields still empty).
  useEffect(() => {
    if (!livePrice || livePrice <= 0) return;
    const sl = form.getValues("stop_loss_price");
    const tp = form.getValues("take_profit_price");
    if (sl?.trim() || tp?.trim()) return;
    const medium = mediumStopsFrom(livePrice);
    form.setValue("stop_loss_price", medium.sl);
    form.setValue("take_profit_price", medium.tp);
  }, [livePrice, form]);

  // Load exit plan from open position into the side editor.
  useEffect(() => {
    const pos = positionQuery.data;
    if (!pos) {
      setExitSl("");
      setExitTp("");
      return;
    }
    if (pos.stop_loss_price) setExitSl(String(Math.round(Number(pos.stop_loss_price))));
    else if (pos.average_entry_price) {
      setExitSl(mediumStopsFrom(Number(pos.average_entry_price)).sl);
    }
    if (pos.take_profit_price) setExitTp(String(Math.round(Number(pos.take_profit_price))));
    else if (pos.average_entry_price) {
      setExitTp(mediumStopsFrom(Number(pos.average_entry_price)).tp);
    }
  }, [positionQuery.data]);

  const exitsMutation = useMutation({
    mutationFn: () =>
      api.updatePositionExits(symbol, {
        stop_loss_price: exitSl.trim(),
        take_profit_price: exitTp.trim() || undefined,
      }),
    onSuccess: async () => {
      setExitMsg("Saved Stop Loss / Take Profit (Medium 2% / 3%) on your open position.");
      await queryClient.invalidateQueries({ queryKey: ["position", symbol] });
      await queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
    onError: (error) => {
      setExitMsg(error instanceof ApiError ? error.message : "Could not save exits");
    },
  });

  const buildPayload = (values: FormValues): OrderPayload => {
    const payload: OrderPayload = { symbol };
    if (values.usd_amount?.trim()) payload.usd_amount = values.usd_amount.trim();
    if (values.quantity?.trim()) payload.quantity = values.quantity.trim();
    if (values.stop_loss_price?.trim()) payload.stop_loss_price = values.stop_loss_price.trim();
    if (values.take_profit_price?.trim()) {
      payload.take_profit_price = values.take_profit_price.trim();
    }
    if (values.entry_reason?.trim()) payload.entry_reason = values.entry_reason.trim();
    if (values.emotional_state) payload.emotional_state = values.emotional_state;
    if (values.confidence_score) payload.confidence_score = Number(values.confidence_score);
    if (typeof values.followed_plan === "boolean") payload.followed_plan = values.followed_plan;
    return payload;
  };

  const onPreviewInvalid = (invalid: typeof errors) => {
    const first =
      invalid.usd_amount?.message ||
      invalid.quantity?.message ||
      invalid.stop_loss_price?.message ||
      "Check the form: fill USD amount (only), and Stop Loss for Buy";
    setFormError(first);
  };

  const previewMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = buildPayload(values);
      if (side === "buy" && requireStopLoss && !payload.stop_loss_price) {
        throw new ApiError("Stop loss is required by your risk rules", 422);
      }
      return side === "buy" ? api.previewBuy(payload) : api.previewSell(payload);
    },
    onSuccess: (data) => {
      setPreview(data);
      setConfirmOpen(true);
      setFormError(null);
    },
    onError: (error) => {
      setFormError(error instanceof ApiError ? error.message : "Preview failed");
    },
  });

  const submitMutation = useMutation({
    mutationFn: async () => {
      const values = form.getValues();
      const payload = buildPayload(values);
      return side === "buy" ? api.buy(payload) : api.sell(payload);
    },
    onSuccess: async () => {
      setConfirmOpen(false);
      setPreview(null);
      form.reset({
        followed_plan: true,
        confidence_score: "3",
        emotional_state: "calm",
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["trades"] }),
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
        queryClient.invalidateQueries({ queryKey: ["position", symbol] }),
        queryClient.invalidateQueries({ queryKey: ["orders"] }),
      ]);
    },
    onError: (error) => {
      setFormError(error instanceof ApiError ? error.message : "Order failed");
      setConfirmOpen(false);
    },
  });

  const position = positionQuery.data;
  const cash = summaryQuery.data?.cash_balance;
  const sideLabel = useMemo(() => (side === "buy" ? "Buy" : "Sell"), [side]);

  if (priceQuery.isLoading || summaryQuery.isLoading) {
    return <Skeleton className="h-96 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Trade {symbol}</h1>
          <p className="text-sm text-muted-foreground">
            Market order on paper account. Preview before confirming.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/market">Back to Market</Link>
        </Button>
      </div>

      <PaperBanner />

      <TradingChart symbol={symbol} height={440} defaultInterval="15m" />

      <CoachSignalPanel
        symbol={symbol}
        interval={coachInterval}
        onIntervalChange={setCoachInterval}
        onApplyExits={(sl, tp) => {
          form.setValue("stop_loss_price", sl, { shouldDirty: true });
          form.setValue("take_profit_price", tp, { shouldDirty: true });
          setFormError(null);
        }}
      />

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>Order ticket</CardTitle>
            <CardDescription>
              Current price {priceQuery.data ? formatMoney(priceQuery.data.price) : "—"}
              {" · "}
              Chart shows EMA 9/21 rule signals (arrows). Confirm yourself before ordering.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex gap-2">
              <Button
                type="button"
                variant={side === "buy" ? "default" : "outline"}
                onClick={() => setSide("buy")}
              >
                Buy
              </Button>
              <Button
                type="button"
                variant={side === "sell" ? "default" : "outline"}
                onClick={() => setSide("sell")}
              >
                Sell
              </Button>
            </div>

            <form
              className="space-y-4"
              onSubmit={form.handleSubmit((values) => {
                setFormError(null);
                if (side === "buy" && requireStopLoss && !values.stop_loss_price?.trim()) {
                  setFormError("Stop Loss is required for Buy — click “Fill SL/TP Medium 2% / 3%” or type a price below entry");
                  return;
                }
                previewMutation.mutate(values);
              }, onPreviewInvalid)}
            >
              <Alert>
                <AlertTitle>Quick fill (Buy)</AlertTitle>
                <AlertDescription className="space-y-2">
                  <p>
                    1) Type USD amount only (e.g. <strong>100</strong>) — leave Quantity empty
                    <br />
                    2) Click <strong>Fill SL/TP Medium 2% / 3%</strong>
                    <br />
                    3) Click <strong>Preview Buy</strong> — a confirm box should open in the center
                  </p>
                  <Button type="button" size="sm" variant="secondary" onClick={applyMediumStops}>
                    Fill SL/TP Medium 2% / 3%
                  </Button>
                </AlertDescription>
              </Alert>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="usd_amount">USD amount</Label>
                  <Input id="usd_amount" placeholder="e.g. 100" {...form.register("usd_amount")} />
                  {errors.usd_amount && (
                    <p className="text-sm text-destructive">{errors.usd_amount.message}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="quantity">Quantity (leave empty if using USD)</Label>
                  <Input id="quantity" placeholder="leave empty" {...form.register("quantity")} />
                  {errors.quantity && (
                    <p className="text-sm text-destructive">{errors.quantity.message}</p>
                  )}
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="stop_loss_price">
                    Stop Loss {requireStopLoss && side === "buy" ? "(required)" : "(optional)"}
                  </Label>
                  <Input
                    id="stop_loss_price"
                    placeholder="below entry price"
                    {...form.register("stop_loss_price")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="take_profit_price">Take Profit</Label>
                  <Input
                    id="take_profit_price"
                    placeholder="above entry price"
                    {...form.register("take_profit_price")}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="entry_reason">Entry / trade reason</Label>
                <Textarea id="entry_reason" {...form.register("entry_reason")} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="emotional_state">Emotional state</Label>
                  <select
                    id="emotional_state"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    {...form.register("emotional_state")}
                  >
                    {emotions.map((emotion) => (
                      <option key={emotion} value={emotion}>
                        {emotion}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confidence_score">Confidence (1–5)</Label>
                  <Input
                    id="confidence_score"
                    type="number"
                    min={1}
                    max={5}
                    {...form.register("confidence_score")}
                  />
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" {...form.register("followed_plan")} />
                I followed my plan
              </label>

              {formError && (
                <Alert variant="destructive">
                  <AlertTitle>Cannot preview yet</AlertTitle>
                  <AlertDescription>{formError}</AlertDescription>
                </Alert>
              )}

              <Button type="submit" disabled={previewMutation.isPending} className="w-full">
                {previewMutation.isPending ? "Preparing preview…" : `Preview ${sideLabel}`}
              </Button>
              <p className="text-center text-xs text-muted-foreground">
                After Preview, look for a popup in the middle of the screen → Confirm
              </p>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Account</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <p>Cash: {cash ? formatMoney(cash) : "—"}</p>
              <p>Trading enabled: {summaryQuery.data?.account.trading_enabled ? "Yes" : "No"}</p>
              <p>
                Trades today: {summaryQuery.data?.trades_today ?? "—"} /{" "}
                {summaryQuery.data?.account.max_trades_per_day ?? "—"}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Position · {symbol}</CardTitle>
              <CardDescription>
                Edit Stop Loss / Take Profit for the open position (was stuck on the old order values).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {position ? (
                <>
                  <p>Quantity: {formatQty(position.quantity)}</p>
                  <p>Avg entry: {formatMoney(position.average_entry_price)}</p>
                  <p>Current: {formatMoney(position.current_price)}</p>
                  <p>
                    Unrealized: <PnlText value={position.unrealized_pnl} />
                  </p>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <div className="space-y-1">
                      <Label htmlFor="exit_sl">Stop Loss</Label>
                      <Input
                        id="exit_sl"
                        value={exitSl}
                        onChange={(e) => setExitSl(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="exit_tp">Take Profit</Label>
                      <Input
                        id="exit_tp"
                        value={exitTp}
                        onChange={(e) => setExitTp(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        const base = Number(position.average_entry_price) || livePrice;
                        if (!base) return;
                        const medium = mediumStopsFrom(base);
                        setExitSl(medium.sl);
                        setExitTp(medium.tp);
                        setExitMsg(null);
                      }}
                    >
                      Fill Medium 2% / 3%
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      disabled={exitsMutation.isPending || !exitSl.trim()}
                      onClick={() => {
                        setExitMsg(null);
                        exitsMutation.mutate();
                      }}
                    >
                      {exitsMutation.isPending ? "Saving…" : "Save SL / TP"}
                    </Button>
                  </div>
                  {exitMsg && <p className="text-xs text-muted-foreground">{exitMsg}</p>}
                  <p className="text-xs text-muted-foreground">
                    Paper note: exits are saved as your plan. They do not auto-sell yet — sell manually
                    when price hits your levels.
                  </p>
                </>
              ) : (
                <p className="text-muted-foreground">No open position for {symbol}.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm paper {sideLabel.toLowerCase()}</DialogTitle>
            <DialogDescription>Simulated order only. No real funds will move.</DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="space-y-2 text-sm">
              <p>
                {preview.side.toUpperCase()} {preview.symbol}: {formatQty(preview.quantity)} @{" "}
                {formatMoney(preview.estimated_price)}
              </p>
              <p>Fee: {formatMoney(preview.fee_amount)}</p>
              <p>
                {side === "buy" ? "Total debit" : "Net proceeds"}: {formatMoney(preview.net_amount)}
              </p>
              <p>Cash after: {formatMoney(preview.cash_after)}</p>
              {preview.estimated_max_loss != null && (
                <p>
                  Est. max loss: <PnlText value={`-${preview.estimated_max_loss}`} />
                </p>
              )}
              {preview.risk_percent != null && <p>Risk: {preview.risk_percent}%</p>}
              {preview.estimated_realized_pnl != null && (
                <p>
                  Est. realized P&L: <PnlText value={preview.estimated_realized_pnl} />
                </p>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => submitMutation.mutate()} disabled={submitMutation.isPending}>
              {submitMutation.isPending ? "Submitting…" : `Confirm ${sideLabel}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function TradePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <TradePageInner />
    </Suspense>
  );
}
