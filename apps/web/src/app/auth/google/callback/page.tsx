"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { setToken } from "@/lib/api";
import { clearCoachLocalCache } from "@/lib/coach-settings";

export default function GoogleAuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("access_token");
    if (!token) {
      setError("Google sign-in did not return a session. Please try again.");
      return;
    }
    clearCoachLocalCache();
    setToken(token);
    router.replace("/dashboard");
  }, [router]);

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <p className="text-sm text-muted-foreground">
        {error ?? "Completing Google sign-in…"}
      </p>
    </main>
  );
}
