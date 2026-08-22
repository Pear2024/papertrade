"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/types";

function siteOrigin(): string {
  if (typeof window === "undefined") return "";
  return window.location.origin;
}

export async function startProCheckout(): Promise<void> {
  const origin = siteOrigin();
  const session = await api.createCheckoutSession({
    success_url: `${origin}/settings?billing=success`,
    cancel_url: `${origin}/settings?billing=cancel`,
  });
  window.location.assign(session.checkout_url);
}

export function UpgradeToProButton({
  variant = "default",
  size = "default",
  className,
  label = "Upgrade to Pro",
}: {
  variant?: "default" | "outline" | "secondary" | "ghost" | "destructive";
  size?: "default" | "sm" | "lg" | "icon";
  className?: string;
  label?: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: startProCheckout,
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : "Unable to start checkout");
    },
  });

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant={variant}
        size={size}
        className={className}
        disabled={mutation.isPending}
        onClick={() => {
          setError(null);
          mutation.mutate();
        }}
      >
        {mutation.isPending ? "Redirecting to Stripe…" : label}
      </Button>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}

export function BillingPlanCard({
  billingNotice,
}: {
  billingNotice?: "success" | "cancel" | null;
}) {
  const statusQuery = useQuery({
    queryKey: ["billing-status"],
    queryFn: api.billingStatus,
  });
  const [portalError, setPortalError] = useState<string | null>(null);

  const portalMutation = useMutation({
    mutationFn: async () => {
      const origin = siteOrigin();
      const session = await api.createBillingPortalSession({
        return_url: `${origin}/settings`,
      });
      window.location.assign(session.portal_url);
    },
    onError: (err) => {
      setPortalError(err instanceof ApiError ? err.message : "Unable to open billing portal");
    },
  });

  const status = statusQuery.data;
  const planLabel = (status?.plan ?? "free").toUpperCase();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Subscription</CardTitle>
        <CardDescription>
          Paper Lab testing is free for now. Pro billing coming later —
          upgrades stay optional and do not block Save paper profile.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {billingNotice === "success" && (
          <Alert>
            <AlertTitle>Payment received</AlertTitle>
            <AlertDescription>
              Stripe checkout completed. Your Pro plan activates when the webhook
              confirms payment — refresh in a few seconds if the plan still shows Free.
            </AlertDescription>
          </Alert>
        )}
        {billingNotice === "cancel" && (
          <Alert>
            <AlertTitle>Checkout canceled</AlertTitle>
            <AlertDescription>No charge was made. You can upgrade anytime.</AlertDescription>
          </Alert>
        )}

        {statusQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading plan…</p>
        ) : statusQuery.isError ? (
          <p className="text-sm text-destructive">
            {(statusQuery.error as Error).message}
          </p>
        ) : (
          <>
            <p className="text-sm">
              Current plan: <span className="font-medium">{planLabel}</span>
            </p>
            {status?.message && (
              <p className="text-sm text-muted-foreground">{status.message}</p>
            )}
            <div className="flex flex-wrap gap-2">
              {status?.plan !== "pro" && status?.billing_enabled && <UpgradeToProButton />}
              {status?.plan !== "pro" && !status?.billing_enabled && (
                <Button type="button" disabled>
                  Pro billing coming later
                </Button>
              )}
              {status?.can_manage_billing && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={portalMutation.isPending}
                  onClick={() => {
                    setPortalError(null);
                    portalMutation.mutate();
                  }}
                >
                  {portalMutation.isPending ? "Opening…" : "Manage billing"}
                </Button>
              )}
            </div>
            {portalError && <p className="text-sm text-destructive">{portalError}</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
