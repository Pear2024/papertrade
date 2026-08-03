"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

import { EmptyState } from "@/components/empty-state";
import { PaperBanner } from "@/components/layout/paper-banner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { ApiError, JournalEntry } from "@/lib/types";

const emotions = ["calm", "confident", "fearful", "greedy", "impatient", "unsure"] as const;

const JOURNAL_SYMBOLS = [
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

const schema = z.object({
  symbol: z.enum(JOURNAL_SYMBOLS),
  setup_name: z.string().optional(),
  entry_reason: z.string().optional(),
  exit_reason: z.string().optional(),
  emotional_state: z.enum(emotions),
  confidence_score: z.string().optional(),
  followed_plan: z.boolean().optional(),
  lesson_learned: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const defaultFormValues: FormValues = {
  symbol: "BTC",
  setup_name: "",
  entry_reason: "",
  exit_reason: "",
  emotional_state: "calm",
  confidence_score: "3",
  followed_plan: true,
  lesson_learned: "",
};

export default function JournalPage() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<JournalEntry | null>(null);
  const [error, setError] = useState<string | null>(null);

  const journalsQuery = useQuery({
    queryKey: ["journals"],
    queryFn: api.journals,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaultFormValues,
  });

  const saveMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = {
        symbol: values.symbol,
        setup_name: values.setup_name || undefined,
        entry_reason: values.entry_reason || undefined,
        exit_reason: values.exit_reason || undefined,
        emotional_state: values.emotional_state,
        confidence_score: values.confidence_score
          ? Number(values.confidence_score)
          : undefined,
        followed_plan: values.followed_plan,
        lesson_learned: values.lesson_learned || undefined,
      };
      if (editing) {
        return api.updateJournal(editing.id, {
          setup_name: payload.setup_name,
          entry_reason: payload.entry_reason,
          exit_reason: payload.exit_reason,
          emotional_state: payload.emotional_state,
          confidence_score: payload.confidence_score,
          followed_plan: payload.followed_plan,
          lesson_learned: payload.lesson_learned,
        });
      }
      return api.createJournal(payload);
    },
    onSuccess: async () => {
      setEditing(null);
      setError(null);
      form.reset(defaultFormValues);
      await queryClient.invalidateQueries({ queryKey: ["journals"] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Save failed");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteJournal(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["journals"] });
    },
  });

  const startEdit = (journal: JournalEntry) => {
    setEditing(journal);
    const emotion = emotions.includes(
      journal.emotional_state as (typeof emotions)[number],
    )
      ? (journal.emotional_state as (typeof emotions)[number])
      : "calm";
    form.reset({
      symbol: (JOURNAL_SYMBOLS as readonly string[]).includes(journal.symbol)
        ? (journal.symbol as (typeof JOURNAL_SYMBOLS)[number])
        : "BTC",
      setup_name: journal.setup_name ?? "",
      entry_reason: journal.entry_reason ?? "",
      exit_reason: journal.exit_reason ?? "",
      emotional_state: emotion,
      confidence_score: String(journal.confidence_score ?? 3),
      followed_plan: journal.followed_plan ?? true,
      lesson_learned: journal.lesson_learned ?? "",
    });
  };

  if (journalsQuery.isLoading) {
    return <Skeleton className="h-80 w-full" aria-label="Loading journals" />;
  }

  if (journalsQuery.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Could not load journals</AlertTitle>
        <AlertDescription>{(journalsQuery.error as Error).message}</AlertDescription>
      </Alert>
    );
  }

  const journals = journalsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Trading Journal</h1>
        <p className="text-sm text-muted-foreground">
          Reflect on entries, emotions, and lessons — paper trading only.
        </p>
      </div>

      <PaperBanner />

      <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <Card>
          <CardHeader>
            <CardTitle>{editing ? `Edit journal #${editing.id}` : "New journal entry"}</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={form.handleSubmit((values) => saveMutation.mutate(values))}
            >
              <div className="space-y-2">
                <Label htmlFor="symbol">Symbol</Label>
                <select
                  id="symbol"
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  disabled={!!editing}
                  {...form.register("symbol")}
                >
                  {JOURNAL_SYMBOLS.map((sym) => (
                    <option key={sym} value={sym}>
                      {sym}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="setup_name">Setup name</Label>
                <Input id="setup_name" {...form.register("setup_name")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="entry_reason">Entry reason</Label>
                <Textarea id="entry_reason" {...form.register("entry_reason")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="exit_reason">Exit reason</Label>
                <Textarea id="exit_reason" {...form.register("exit_reason")} />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="emotional_state">Emotion</Label>
                  <select
                    id="emotional_state"
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    {...form.register("emotional_state")}
                  >
                    {emotions.map((e) => (
                      <option key={e} value={e}>
                        {e}
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
                Followed plan
              </label>
              <div className="space-y-2">
                <Label htmlFor="lesson_learned">Lesson learned</Label>
                <Textarea id="lesson_learned" {...form.register("lesson_learned")} />
              </div>
              {error && (
                <Alert variant="destructive">
                  <AlertTitle>Could not save</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}
              <div className="flex gap-2">
                <Button type="submit" disabled={saveMutation.isPending}>
                  {saveMutation.isPending ? "Saving…" : editing ? "Update" : "Create"}
                </Button>
                {editing && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setEditing(null);
                      form.reset(defaultFormValues);
                    }}
                  >
                    Cancel edit
                  </Button>
                )}
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-3">
          {journals.length === 0 ? (
            <EmptyState
              title="No journal entries"
              description="Write why you entered a trade and what you learned."
            />
          ) : (
            journals.map((journal) => (
              <Card key={journal.id}>
                <CardContent className="space-y-2 p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge>{journal.symbol}</Badge>
                      {journal.emotional_state && (
                        <span className="text-muted-foreground">{journal.emotional_state}</span>
                      )}
                      {journal.followed_plan != null && (
                        <span className="text-muted-foreground">
                          {journal.followed_plan ? "Followed plan" : "Did not follow plan"}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {formatDateTime(journal.created_at)}
                    </span>
                  </div>
                  {journal.setup_name && <p className="font-medium">{journal.setup_name}</p>}
                  {journal.entry_reason && <p>Entry: {journal.entry_reason}</p>}
                  {journal.exit_reason && <p>Exit: {journal.exit_reason}</p>}
                  {journal.lesson_learned && (
                    <p className="text-muted-foreground">Lesson: {journal.lesson_learned}</p>
                  )}
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" variant="outline" onClick={() => startEdit(journal)}>
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => {
                        if (window.confirm("Delete this journal entry?")) {
                          deleteMutation.mutate(journal.id);
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
