"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";

import { PaperBanner } from "@/components/layout/paper-banner";
import { useCoachSettings } from "@/hooks/use-coach-settings";
import {
  type CoachSettings,
  normalizeCoachSettings,
  restoreCoachDefaults,
  saveCoachSettings,
} from "@/lib/coach-settings";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { ApiError, CandleInterval } from "@/lib/types";

const schema = z.object({
  starting_balance: z.string().min(1),
  max_risk_percent_per_trade: z.string().min(1),
  max_daily_loss_percent: z.string().min(1),
  max_trades_per_day: z.string().min(1),
  require_stop_loss: z.boolean(),
  trading_enabled: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

const INTERVAL_OPTIONS: CandleInterval[] = ["1m", "5m", "15m", "1h", "4h", "1d"];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { settings: coachSettings } = useCoachSettings();
  const [coachForm, setCoachForm] = useState<CoachSettings>(coachSettings);
  const [coachMsg, setCoachMsg] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetReason, setResetReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCoachForm(coachSettings);
  }, [coachSettings]);

  const settingsQuery = useQuery({
    queryKey: ["account-settings"],
    queryFn: api.accountSettings,
  });
  const historyQuery = useQuery({
    queryKey: ["reset-history"],
    queryFn: api.resetHistory,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  useEffect(() => {
    if (!settingsQuery.data) return;
    form.reset({
      starting_balance: String(Number(settingsQuery.data.starting_balance)),
      max_risk_percent_per_trade: String(
        Number(settingsQuery.data.max_risk_percent_per_trade),
      ),
      max_daily_loss_percent: String(Number(settingsQuery.data.max_daily_loss_percent)),
      max_trades_per_day: String(settingsQuery.data.max_trades_per_day),
      require_stop_loss: settingsQuery.data.require_stop_loss,
      trading_enabled: settingsQuery.data.trading_enabled,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.updateAccountSettings({
        starting_balance: values.starting_balance,
        risk_rules: {
          max_risk_percent_per_trade: values.max_risk_percent_per_trade,
          max_daily_loss_percent: values.max_daily_loss_percent,
          max_trades_per_day: Number(values.max_trades_per_day),
          require_stop_loss: values.require_stop_loss,
          trading_enabled: values.trading_enabled,
        },
      }),
    onSuccess: async () => {
      setMessage("Risk settings saved.");
      setError(null);
      await queryClient.invalidateQueries({ queryKey: ["account-settings"] });
      await queryClient.invalidateQueries({ queryKey: ["account-summary"] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Save failed");
    },
  });

  const resetMutation = useMutation({
    mutationFn: () =>
      api.resetAccount({
        confirm: true,
        reason: resetReason || "User reset from Settings",
      }),
    onSuccess: async (result) => {
      setResetOpen(false);
      setResetReason("");
      setMessage(result.message ?? "Account reset complete.");
      setError(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["account-settings"] }),
        queryClient.invalidateQueries({ queryKey: ["account-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["positions"] }),
        queryClient.invalidateQueries({ queryKey: ["trades"] }),
        queryClient.invalidateQueries({ queryKey: ["analytics-overview"] }),
        queryClient.invalidateQueries({ queryKey: ["reset-history"] }),
      ]);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Reset failed");
      setResetOpen(false);
    },
  });

  const saveCoach = () => {
    const { entrySignal: _entrySignal, ...editableSettings } =
      normalizeCoachSettings(coachForm);
    const next = saveCoachSettings(editableSettings);
    setCoachForm(next);
    setCoachMsg(
      `Coach auto saved · Lab · ${next.interval} · tick ${next.autoTickSeconds}s · stake $${next.autoStakeUsd} · ${next.leverage}x · SL ${next.slPct}% / TP ${next.tpPct}% · min net R:R ${next.minNetRr} · slip ${next.slippageBps}bps · spread ${next.spreadBps}bps`,
    );
  };

  const resetCoachDefaults = () => {
    const next = restoreCoachDefaults();
    setCoachForm(next);
    setCoachMsg("Coach auto restored to Lab defaults.");
  };

  if (settingsQuery.isLoading) return <Skeleton className="h-80 w-full" />;

  if (settingsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load settings</AlertTitle>
        <AlertDescription>{(settingsQuery.error as Error).message}</AlertDescription>
      </Alert>
    );
  }

  const settings = settingsQuery.data!;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Risk rules, coach auto defaults, and paper account controls. Starting balance
            default is $20,000.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href="/guide">Open User Guide</Link>
        </Button>
      </div>

      <PaperBanner message={settings.paper_mode_banner} />

      {message && (
        <Alert>
          <AlertTitle>Updated</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      {coachMsg && (
        <Alert>
          <AlertTitle>Coach auto</AlertTitle>
          <AlertDescription>{coachMsg}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Coach auto</CardTitle>
          <CardDescription>
            Risk defaults for Lab paper AUTO on Market / Coach. Entry rules come from your{" "}
            <Link href="/lab" className="underline underline-offset-4">
              Hypothesis Lab
            </Link>{" "}
            prompts (promoted profiles). Saved in this browser.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="coach_interval">Candle interval</Label>
              <Select
                value={coachForm.interval}
                onValueChange={(v) =>
                  setCoachForm((s) => ({ ...s, interval: v as CandleInterval }))
                }
              >
                <SelectTrigger id="coach_interval">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INTERVAL_OPTIONS.map((iv) => (
                    <SelectItem key={iv} value={iv}>
                      {iv}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_tick">Auto tick (seconds)</Label>
              <Input
                id="auto_tick"
                type="number"
                min={15}
                max={600}
                value={coachForm.autoTickSeconds}
                onChange={(e) =>
                  setCoachForm((s) => ({
                    ...s,
                    autoTickSeconds: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="auto_stake">Auto stake / margin (USD)</Label>
              <Input
                id="auto_stake"
                type="number"
                min={0.5}
                max={20000}
                step={1}
                value={coachForm.autoStakeUsd}
                onChange={(e) =>
                  setCoachForm((s) => ({
                    ...s,
                    autoStakeUsd: Number(e.target.value),
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Margin per auto entry (capped by cash). Notional = margin × leverage.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="leverage">Leverage (1x–50x)</Label>
              <Input
                id="leverage"
                type="number"
                min={1}
                max={50}
                step={1}
                value={coachForm.leverage}
                onChange={(e) =>
                  setCoachForm((s) => ({
                    ...s,
                    leverage: Number(e.target.value),
                  }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Paper futures-style. Default 5x. Desk and auto-trade both use this.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="sl_pct">Stop loss %</Label>
              <Input
                id="sl_pct"
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={coachForm.slPct}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, slPct: Number(e.target.value) }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="tp_pct">Take profit %</Label>
              <Input
                id="tp_pct"
                type="number"
                min={0.1}
                max={50}
                step={0.1}
                value={coachForm.tpPct}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, tpPct: Number(e.target.value) }))
                }
              />
              <p className="text-xs text-muted-foreground">
                With a 2% stop loss, set take profit to about 5% or more to clear net R:R 2.0.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="min_net_rr">Minimum net R:R</Label>
              <Input
                id="min_net_rr"
                type="number"
                min={0.1}
                max={20}
                step={0.1}
                value={coachForm.minNetRr}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, minNetRr: Number(e.target.value) }))
                }
              />
              <p className="text-xs text-muted-foreground">
                Blocks new entries below this R:R after fees, slippage, and spread.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="slippage_bps">Expected slippage / fill (bps)</Label>
              <Input
                id="slippage_bps"
                type="number"
                min={0}
                max={100}
                step={1}
                value={coachForm.slippageBps}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, slippageBps: Number(e.target.value) }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="spread_bps">Assumed full spread (bps)</Label>
              <Input
                id="spread_bps"
                type="number"
                min={0}
                max={100}
                step={1}
                value={coachForm.spreadBps}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, spreadBps: Number(e.target.value) }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="tp_usd">Take profit (USD)</Label>
              <Input
                id="tp_usd"
                type="number"
                min={0}
                max={1000000}
                step={1}
                value={coachForm.tpUsd}
                onChange={(e) =>
                  setCoachForm((s) => ({ ...s, tpUsd: Number(e.target.value) }))
                }
              />
              <p className="text-xs text-muted-foreground">
                AUTO closes when live unrealized P/L reaches this amount (default $70).
                Set 0 to disable. Works alongside % TP — whichever hits first.
              </p>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={coachForm.autoOnDefault}
              onChange={(e) =>
                setCoachForm((s) => ({ ...s, autoOnDefault: e.target.checked }))
              }
            />
            Start with AUTO ON when opening Market / Coach
          </label>
          <div className="rounded-md border bg-muted/20 px-3 py-2 text-sm">
            <p className="font-medium">
              Entry source: Lab
              {coachSettings.labHypothesisId
                ? ` · profile ${coachSettings.labHypothesisId}`
                : " · choose a promoted profile on Market/Coach"}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Built-in A4/CCR strategies are retired. Write rules in{" "}
              <Link href="/lab" className="underline underline-offset-4">
                Lab
              </Link>
              , promote a paper profile, then run AUTO on Market or Coach.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={saveCoach}>
              Save coach auto
            </Button>
            <Button type="button" variant="outline" onClick={resetCoachDefaults}>
              Restore Lab defaults
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risk & account</CardTitle>
          <CardDescription>
            Paper fee is <strong>0.80% of notional per fill</strong> (round-trip ≈ 1.60%
            before slippage/spread), matching the confirmed Kraken Pro receipt. Change{" "}
            <code className="text-xs">PAPER_TRADING_FEE_PERCENT</code> in server .env;
            <code className="ml-1 text-xs">PAPER_TRADING_FEE_USD</code> stays 0 unless an
            explicit flat-fee override is needed.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="starting_balance">Starting balance (USD)</Label>
                <Input id="starting_balance" {...form.register("starting_balance")} />
              </div>
              <div className="space-y-2">
                <Label>Current cash</Label>
                <Input value={formatMoney(settings.cash_balance)} disabled readOnly />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max_risk_percent_per_trade">Max risk % / trade</Label>
                <Input
                  id="max_risk_percent_per_trade"
                  {...form.register("max_risk_percent_per_trade")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max_daily_loss_percent">Max daily loss %</Label>
                <Input
                  id="max_daily_loss_percent"
                  {...form.register("max_daily_loss_percent")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="max_trades_per_day">Max trades / day</Label>
                <Input id="max_trades_per_day" {...form.register("max_trades_per_day")} />
              </div>
              <div className="space-y-2">
                <Label>Trading fee / fill</Label>
                <Input
                  value={
                    Number(settings.trading_fee_usd ?? 0) > 0
                      ? formatMoney(settings.trading_fee_usd)
                      : `${settings.trading_fee_percent}%`
                  }
                  disabled
                  readOnly
                />
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...form.register("require_stop_loss")} />
              Require stop loss on buys
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...form.register("trading_enabled")} />
              Trading enabled
            </label>

            <Button type="submit" disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Saving…" : "Save risk settings"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="border-warning/40">
        <CardHeader>
          <CardTitle>Reset paper account</CardTitle>
          <CardDescription>
            Clears open positions, restores cash to starting balance, and records a reset
            event. Trade history is kept; analytics focus on activity after the reset.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setResetOpen(true)}>
            Reset account to ${Number(settings.starting_balance).toFixed(2)}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Reset history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {(historyQuery.data ?? []).length === 0 ? (
            <p className="text-muted-foreground">No resets yet.</p>
          ) : (
            (historyQuery.data ?? []).map((row) => (
              <div key={row.id} className="rounded-md border px-3 py-2">
                <p className="font-medium">{formatDateTime(row.reset_at)}</p>
                <p className="text-muted-foreground">
                  {formatMoney(row.previous_balance)} → {formatMoney(row.reset_balance)}
                  {row.reason ? ` · ${row.reason}` : ""}
                </p>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Dialog open={resetOpen} onOpenChange={setResetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm account reset</DialogTitle>
            <DialogDescription>
              This clears positions and restores simulated cash. No real money is
              involved.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reset_reason">Reason (optional)</Label>
            <Textarea
              id="reset_reason"
              value={resetReason}
              onChange={(e) => setResetReason(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={resetMutation.isPending}
              onClick={() => resetMutation.mutate()}
            >
              {resetMutation.isPending ? "Resetting…" : "Confirm reset"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
