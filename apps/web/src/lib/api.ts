import { getApiBaseUrl } from "@/lib/utils";
import {
  AccountResetRecord,
  AccountSettings,
  AccountSummary,
  AnalyticsOverview,
  ApiError,
  Asset,
  AssetPerformance,
  AuthResponse,
  AuthUser,
  CandleInterval,
  CandleResponse,
  CoachAutoTick,
  CoachDecisionAudit,
  CoachPrompt,
  CoachSignal,
  CoachSignalHistory,
  CoachStats,
  CoachTradeJournal,
  DisciplineStats,
  EmotionPerformance,
  JournalEntry,
  Order,
  OrderPayload,
  Position,
  PriceQuote,
  Trade,
  TradePreview,
  HypothesisLabItem,
  HypothesisBacktest,
  HypothesisLabAccess,
  BillingStatus,
  CheckoutSessionResponse,
  PortalSessionResponse,
} from "@/lib/types";

const TOKEN_KEY = "pcc_access_token";
const API_REQUEST_TIMEOUT_MS = 10_000;
const AUTH_REQUEST_TIMEOUT_MS = 5_000;

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  auth = false,
  timeoutMs = API_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (!token) throw new ApiError("Not authenticated", 401);
    headers.set("Authorization", `Bearer ${token}`);
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError("API request timed out. Please check that the API is running.", 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as { detail?: string | { msg?: string }[] };
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    } catch {
      // ignore
    }
    // Stale JWT after API restart — clear and send user to login once.
    if (response.status === 401 && auth && typeof window !== "undefined") {
      setToken(null);
      const onLogin = window.location.pathname.startsWith("/login");
      if (!onLogin) {
        window.location.assign("/login?reason=expired");
      }
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  googleAuthConfig: () => apiFetch<{ enabled: boolean }>("/auth/google/config"),
  googleAuthStartUrl: () => `${getApiBaseUrl()}/auth/google/start`,
  register: (body: { email: string; password: string; display_name: string }) =>
    apiFetch<AuthResponse>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    apiFetch<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  // Auth is required before any protected route can render. Keep this short so
  // a stopped API results in a recoverable error screen, not a frozen shell.
  me: () => apiFetch<AuthUser>("/auth/me", {}, true, AUTH_REQUEST_TIMEOUT_MS),
  assets: () => apiFetch<Asset[]>("/assets"),
  prices: () => apiFetch<PriceQuote[]>("/prices"),
  price: (symbol: string) => apiFetch<PriceQuote>(`/prices/${symbol}`),
  candles: (symbol: string, interval: CandleInterval = "15m", limit = 200) =>
    apiFetch<CandleResponse>(
      `/prices/${symbol}/candles?interval=${encodeURIComponent(interval)}&limit=${limit}`,
    ),
  accountSummary: () => apiFetch<AccountSummary>("/account/summary", {}, true),
  positions: () => apiFetch<Position[]>("/positions", {}, true),
  position: (symbol: string) => apiFetch<Position>(`/positions/${symbol}`, {}, true),
  updatePositionExits: (
    symbol: string,
    payload: { stop_loss_price: string; take_profit_price?: string },
  ) =>
    apiFetch<Position>(`/positions/${symbol}/exits`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }, true),
  trades: () => apiFetch<Trade[]>("/trades", {}, true),
  orders: () => apiFetch<Order[]>("/orders", {}, true),
  previewBuy: (payload: OrderPayload) =>
    apiFetch<TradePreview>("/orders/buy/preview", { method: "POST", body: JSON.stringify(payload) }, true),
  previewSell: (payload: OrderPayload) =>
    apiFetch<TradePreview>("/orders/sell/preview", { method: "POST", body: JSON.stringify(payload) }, true),
  buy: (payload: OrderPayload) =>
    apiFetch<Order>("/orders/buy", { method: "POST", body: JSON.stringify(payload) }, true),
  sell: (payload: OrderPayload) =>
    apiFetch<Order>("/orders/sell", { method: "POST", body: JSON.stringify(payload) }, true),
  journals: () => apiFetch<JournalEntry[]>("/journal", {}, true),
  createJournal: (payload: Record<string, unknown>) =>
    apiFetch<JournalEntry>("/journal", { method: "POST", body: JSON.stringify(payload) }, true),
  updateJournal: (id: number, payload: Record<string, unknown>) =>
    apiFetch<JournalEntry>(`/journal/${id}`, { method: "PATCH", body: JSON.stringify(payload) }, true),
  deleteJournal: (id: number) =>
    apiFetch<void>(`/journal/${id}`, { method: "DELETE" }, true),
  analyticsOverview: () => apiFetch<AnalyticsOverview>("/analytics/overview", {}, true),
  analyticsDiscipline: () => apiFetch<DisciplineStats>("/analytics/discipline", {}, true),
  analyticsByAsset: () => apiFetch<AssetPerformance[]>("/analytics/by-asset", {}, true),
  analyticsByEmotion: () => apiFetch<EmotionPerformance[]>("/analytics/by-emotion", {}, true),
  accountSettings: () => apiFetch<AccountSettings>("/account/settings", {}, true),
  updateAccountSettings: (payload: Record<string, unknown>) =>
    apiFetch<AccountSettings>("/account/settings", { method: "PATCH", body: JSON.stringify(payload) }, true),
  coachSettings: () =>
    apiFetch<{ settings: Record<string, unknown>; auto_session_enabled: boolean | null }>(
      "/account/coach-settings",
      {},
      true,
    ),
  updateCoachSettings: (payload: {
    settings?: Record<string, unknown>;
    auto_session_enabled?: boolean | null;
    clear_auto_session?: boolean;
  }) =>
    apiFetch<{ settings: Record<string, unknown>; auto_session_enabled: boolean | null }>(
      "/account/coach-settings",
      { method: "PUT", body: JSON.stringify(payload) },
      true,
    ),
  restoreCoachSettings: () =>
    apiFetch<{ settings: Record<string, unknown>; auto_session_enabled: boolean | null }>(
      "/account/coach-settings/restore",
      { method: "POST" },
      true,
    ),
  resetAccount: (payload: { confirm: boolean; reason?: string }) =>
    apiFetch<AccountResetRecord>("/account/reset", { method: "POST", body: JSON.stringify(payload) }, true),
  resetHistory: () => apiFetch<AccountResetRecord[]>("/account/reset-history", {}, true),
  krakenFeedStatus: () => apiFetch<Record<string, unknown>>("/prices/feed/status", {}, false),
  coachSignal: (
    symbol: string,
    interval: CandleInterval = "15m",
    opts?: {
      slPct?: number;
      tpPct?: number;
      minNetRr?: number;
      slippageBps?: number;
      spreadBps?: number;
      notionalUsd?: number;
      entrySource?: "lab";
      hypothesisId?: string | null;
    },
  ) => {
    const q = new URLSearchParams({
      symbol,
      interval,
      entry_source: "lab",
    });
    if (opts?.slPct != null) q.set("sl_pct", String(opts.slPct));
    if (opts?.tpPct != null) q.set("tp_pct", String(opts.tpPct));
    if (opts?.minNetRr != null) q.set("min_net_rr", String(opts.minNetRr));
    if (opts?.slippageBps != null) q.set("slippage_bps", String(opts.slippageBps));
    if (opts?.spreadBps != null) q.set("spread_bps", String(opts.spreadBps));
    if (opts?.notionalUsd != null) q.set("notional_usd", String(opts.notionalUsd));
    if (opts?.hypothesisId) q.set("hypothesis_id", opts.hypothesisId);
    return apiFetch<CoachSignal>(`/coach/signal?${q}`, {}, true);
  },
  coachSignalHistory: (opts?: {
    symbol?: string;
    interval?: CandleInterval;
    entryOnly?: boolean;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (opts?.symbol) q.set("symbol", opts.symbol);
    if (opts?.interval) q.set("interval", opts.interval);
    if (opts?.entryOnly) q.set("entry_only", "true");
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return apiFetch<CoachSignalHistory>(
      `/coach/signals/history${qs ? `?${qs}` : ""}`,
      {},
      true,
    );
  },
  coachPrompt: () => apiFetch<CoachPrompt>("/coach/prompt", {}, true),
  coachStats: () => apiFetch<CoachStats>("/coach/stats", {}, true),
  coachDecisions: (opts?: {
    symbol?: string;
    interval?: CandleInterval;
    strategy?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (opts?.symbol) q.set("symbol", opts.symbol);
    if (opts?.interval) q.set("interval", opts.interval);
    if (opts?.strategy) q.set("strategy", opts.strategy);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return apiFetch<CoachDecisionAudit>(
      `/coach/decisions${qs ? `?${qs}` : ""}`,
      {},
      true,
    );
  },
  coachTradeJournal: (opts?: {
    symbol?: string;
    strategy?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (opts?.symbol) q.set("symbol", opts.symbol);
    if (opts?.strategy) q.set("strategy", opts.strategy);
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    const qs = q.toString();
    return apiFetch<CoachTradeJournal>(
      `/coach/trade-journal${qs ? `?${qs}` : ""}`,
      {},
      true,
    );
  },
  coachAutoTick: (
    symbol: string,
    interval: CandleInterval = "15m",
    usdAmount = 100,
    opts?: {
      slPct?: number;
      tpPct?: number;
      tpUsd?: number;
      leverage?: number;
      minNetRr?: number;
      slippageBps?: number;
      spreadBps?: number;
      entrySource?: "lab";
      hypothesisId?: string | null;
    },
  ) => {
    const q = new URLSearchParams({
      symbol,
      interval,
      usd_amount: String(usdAmount),
      entry_source: "lab",
    });
    if (opts?.slPct != null) q.set("sl_pct", String(opts.slPct));
    if (opts?.tpPct != null) q.set("tp_pct", String(opts.tpPct));
    if (opts?.tpUsd != null) q.set("tp_usd", String(opts.tpUsd));
    if (opts?.leverage != null) q.set("leverage", String(opts.leverage));
    if (opts?.minNetRr != null) q.set("min_net_rr", String(opts.minNetRr));
    if (opts?.slippageBps != null) q.set("slippage_bps", String(opts.slippageBps));
    if (opts?.spreadBps != null) q.set("spread_bps", String(opts.spreadBps));
    if (opts?.hypothesisId) q.set("hypothesis_id", opts.hypothesisId);
    return apiFetch<CoachAutoTick>(`/coach/auto-tick?${q}`, { method: "POST" }, true);
  },
  hypothesisLab: () => apiFetch<{ items: HypothesisLabItem[] }>("/hypothesis-lab", {}, true),
  hypothesisLabAccess: () => apiFetch<HypothesisLabAccess>("/hypothesis-lab/access", {}, true),
  createHypothesis: (payload: {
    prompt: string; name?: string; structured_rules?: Record<string, unknown>;
  }) => apiFetch<HypothesisLabItem>("/hypothesis-lab", {
    method: "POST", body: JSON.stringify(payload),
  }, true),
  backtestHypothesis: (id: string, bars = 3000) =>
    apiFetch<HypothesisBacktest>(`/hypothesis-lab/${encodeURIComponent(id)}/backtest`, {
      method: "POST", body: JSON.stringify({ bars }),
    }, true, 60_000),
  promoteHypothesis: (id: string) =>
    apiFetch<HypothesisLabItem>(`/hypothesis-lab/${encodeURIComponent(id)}/promote`, {
      method: "POST",
    }, true),
  billingStatus: () => apiFetch<BillingStatus>("/billing/status", {}, true),
  createCheckoutSession: (payload?: { success_url?: string; cancel_url?: string }) =>
    apiFetch<CheckoutSessionResponse>(
      "/billing/checkout",
      { method: "POST", body: JSON.stringify(payload ?? {}) },
      true,
    ),
  createBillingPortalSession: (payload?: { return_url?: string }) =>
    apiFetch<PortalSessionResponse>(
      "/billing/portal",
      { method: "POST", body: JSON.stringify(payload ?? {}) },
      true,
    ),
};
