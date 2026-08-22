import { HypothesisLabItem } from "@/lib/types";

/** Stable #1..#N by creation time (oldest first). */
export function labProfileNumbers(items: HypothesisLabItem[]): Map<string, number> {
  const sorted = [...items].sort(
    (a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime() ||
      a.id.localeCompare(b.id),
  );
  return new Map(sorted.map((item, index) => [item.id, index + 1]));
}

export function labProfileNumber(
  items: HypothesisLabItem[] | undefined,
  id: string | null | undefined,
): number | null {
  if (!items?.length || !id) return null;
  return labProfileNumbers(items).get(id) ?? null;
}

/** e.g. "#3 · BTCUSDT 15m… v1.0.0" */
export function formatLabProfileLabel(
  item: HypothesisLabItem,
  number: number | null,
  opts?: { includeVersion?: boolean },
): string {
  const includeVersion = opts?.includeVersion !== false;
  const prefix = number != null ? `#${number} · ` : "";
  const version = includeVersion ? ` v${item.version}` : "";
  return `${prefix}${item.name}${version}`;
}
