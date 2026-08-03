import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/** Large permanent safety banner — paper only, never real Kraken orders. */
export function PaperBanner({ message }: { message?: string }) {
  return (
    <Alert
      variant="warning"
      className="mb-6 border-2 border-amber-500/70 bg-amber-50 py-4 dark:bg-amber-950/40"
    >
      <AlertTitle className="text-lg font-bold tracking-wide sm:text-xl">
        PAPER MODE — NO REAL ORDERS
      </AlertTitle>
      <AlertDescription className="mt-1 text-sm leading-relaxed sm:text-base">
        {message ??
          "All balances are simulated. Kraken is used for public market data only (ticker/OHLC). No API keys. No private Kraken balance, orders, withdrawals, or transfers."}
      </AlertDescription>
    </Alert>
  );
}
