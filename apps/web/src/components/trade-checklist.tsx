"use client";

import { Check, X } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type ChecklistRow = {
  id: string;
  label: string;
  passed: boolean;
};

type Props = {
  items: ChecklistRow[];
  title?: string;
  description?: string;
  className?: string;
};

export function TradeChecklist({
  items,
  title = "Entry / exit checklist",
  description = "A4 — BUY: uptrend + close above EMA9 + EMA gap over 0.10%. SELL: downtrend + close below EMA9 + gap over 0.10%.",
  className,
}: Props) {
  const entryIds = new Set([
    "bar_closed",
    "uptrend",
    "close_above_ema9",
    "separation",
    "sl_tp_lock",
  ]);
  const entry = items.filter((i) => entryIds.has(i.id));
  const exit = items.filter((i) => !entryIds.has(i.id));

  const renderList = (rows: ChecklistRow[]) => (
    <ul className="space-y-2">
      {rows.map((item) => (
        <li key={item.id} className="flex items-start gap-2 text-sm">
          <span
            className={cn(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
              item.passed
                ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                : "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300",
            )}
          >
            {item.passed ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
          </span>
          <span className={cn(!item.passed && "text-muted-foreground")}>{item.label}</span>
        </li>
      ))}
    </ul>
  );

  return (
    <Card className={className}>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            BUY gate
          </p>
          {entry.length ? renderList(entry) : <p className="text-sm text-muted-foreground">—</p>}
        </div>
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            SELL / exit cues
          </p>
          {exit.length ? renderList(exit) : <p className="text-sm text-muted-foreground">—</p>}
        </div>
      </CardContent>
    </Card>
  );
}
