"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type Props = {
  symbol: string;
  className?: string;
  limit?: number;
};

function formatTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatDuration(sec: number | null | undefined): string {
  if (sec == null || sec < 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${sec}s`;
}

export function TradeJournalPanel({ symbol, className, limit = 12 }: Props) {
  const journalQuery = useQuery({
    queryKey: ["coach-trade-journal", symbol, limit],
    queryFn: () => api.coachTradeJournal({ symbol, limit }),
    refetchInterval: 30_000,
  });

  const auditQuery = useQuery({
    queryKey: ["coach-decisions", symbol, limit],
    queryFn: () => api.coachDecisions({ symbol, limit: Math.min(limit, 20) }),
    refetchInterval: 60_000,
  });

  const items = journalQuery.data?.items ?? [];
  const audits = auditQuery.data?.items ?? [];

  return (
    <Card className={cn(className)}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Trade Journal</CardTitle>
        <CardDescription>
          Completed paper trades for {symbol} — net P/L after fees, exit reason, confidence,
          regime.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {journalQuery.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No closed trades yet for this symbol.</p>
        ) : (
          <ul className="space-y-2">
            {items.map((t) => {
              const pnl = Number(t.net_pnl ?? 0);
              const win = pnl >= 0;
              return (
                <li
                  key={t.id}
                  className="rounded-md border bg-muted/15 px-3 py-2.5 text-xs leading-relaxed"
                >
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold tracking-wide">
                      {t.side} · {t.symbol}
                    </span>
                    <span
                      className={cn(
                        "font-mono tabular-nums font-medium",
                        win ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
                      )}
                    >
                      {win ? "+" : ""}
                      {formatMoney(t.net_pnl ?? "0")}
                    </span>
                  </div>
                  <div className="grid gap-0.5 text-muted-foreground sm:grid-cols-2">
                    <span>
                      In {formatTs(t.entry_time)} @ {t.entry_price != null ? formatMoney(t.entry_price) : "—"}
                    </span>
                    <span>
                      Out {formatTs(t.exit_time)} @ {t.exit_price != null ? formatMoney(t.exit_price) : "—"}
                    </span>
                    <span>Duration {formatDuration(t.duration_sec)}</span>
                    <span>Exit: {t.exit_reason ?? "—"}</span>
                    <span>
                      Confidence{" "}
                      {t.confidence != null ? `${t.confidence}%` : "N/A"}
                    </span>
                    <span>Regime {t.regime_label ?? "N/A"}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <div className="border-t pt-3">
          <h3 className="mb-2 text-sm font-medium">Decision audit (closed bars)</h3>
          {auditQuery.isLoading ? (
            <Skeleton className="h-20 w-full" />
          ) : audits.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No audits yet — they appear after /coach/signal or AUTO tick on a closed bar.
            </p>
          ) : (
            <ul className="max-h-48 space-y-1.5 overflow-y-auto text-[11px]">
              {audits.slice(0, 10).map((a) => (
                <li
                  key={a.id}
                  className="flex flex-wrap items-baseline justify-between gap-2 rounded border px-2 py-1.5 font-mono"
                >
                  <span>
                    {new Date(a.evaluated_bar_time * 1000).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}{" "}
                    · <strong>{a.final_action}</strong>
                    {a.phase ? ` · ${a.phase}` : ""}
                  </span>
                  <span className="text-muted-foreground">
                    RF {a.rf_proba != null ? a.rf_proba.toFixed(2) : "N/A"} ·{" "}
                    {a.regime_label ?? "—"}
                    {a.rejection_reason
                      ? ` · skip: ${a.rejection_reason.slice(0, 48)}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
