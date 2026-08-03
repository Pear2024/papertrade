"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PaperSpotDesk } from "@/components/paper-spot-desk";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function DeskPage() {
  const [selected, setSelected] = useState("BTC");
  const assetsQuery = useQuery({ queryKey: ["assets"], queryFn: api.assets });
  const symbols = useMemo(
    () => (assetsQuery.data ?? []).map((a) => a.symbol),
    [assetsQuery.data],
  );
  const active = symbols.includes(selected) ? selected : symbols[0] ?? "BTC";

  return (
    <div className="space-y-3">
      <div>
        <h1 className="sr-only">Paper trading desk</h1>
        <p className="text-sm text-muted-foreground">
          Simple Buy / Sell desk for paper practice — pick a coin, fills stay simulated.
        </p>
      </div>
      {assetsQuery.isLoading ? (
        <Skeleton className="h-8 w-full" />
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {symbols.map((sym) => (
            <Button
              key={sym}
              type="button"
              size="sm"
              variant={active === sym ? "default" : "outline"}
              className={cn("h-7 px-2 text-xs", active === sym && "font-semibold")}
              onClick={() => setSelected(sym)}
            >
              {sym}
            </Button>
          ))}
        </div>
      )}
      <PaperSpotDesk key={active} symbol={active} />
    </div>
  );
}
