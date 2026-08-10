"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading, apiError, logout, refresh } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [loading, isAuthenticated, router]);

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 px-4 py-10">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (apiError) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16">
        <div className="space-y-4 rounded-lg border border-destructive/40 bg-destructive/5 p-6">
          <div>
            <h1 className="text-lg font-semibold">The API is unavailable</h1>
            <p className="mt-1 text-sm text-muted-foreground">{apiError}</p>
          </div>
          <p className="text-sm text-muted-foreground">
            Start or restart the API, then retry. This page will not keep loading indefinitely.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => void refresh()}>
              Retry connection
            </Button>
            <Button type="button" variant="outline" onClick={logout}>
              Go to sign in
            </Button>
          </div>
        </div>
      </main>
    );
  }

  if (!isAuthenticated) return null;
  return <>{children}</>;
}
