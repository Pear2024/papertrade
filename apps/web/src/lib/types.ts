export type MoneyString = string;

export interface AuthUser {
  id: number;
  email: string;
  display_name: string;
  subscription_plan?: "free" | "pro" | string;
  created_at: string;
  trading_account: {
    id: number;
    account_name: string;
    account_mode: string;
    starting_balance: MoneyString;
    cash_balance: MoneyString;
    realized_pnl: MoneyString;
    currency: string;
    is_active: boolean;
  } | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface Asset {
  id: number;
  symbol: string;
  name: string;
  asset_type: string;
  price_precision: number;
  quantity_precision: number;
  is_active: boolean;
}

export interface PriceQuote {
  symbol: string;
  price: MoneyString;
  change_24h_percent: MoneyString | null;
  source: string;
  captured_at: string;
}

export type CandleInterval = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

export interface CandleBar {
  time: number;
  open: MoneyString;
  high: MoneyString;
  low: MoneyString;
  close: MoneyString;
  volume?: MoneyString | null;
}

export interface CandleResponse {
  symbol: string;
  interval: string;
  source: string;
  candles: CandleBar[];
}

export interface AccountSummary {
  account: {
    id: number;
    account_name: string;
    account_mode: string;
    starting_balance: MoneyString;
    cash_balance: MoneyString;
    realized_pnl: MoneyString;
    currency: string;
    is_active: boolean;
    trading_enabled: boolean;
    require_stop_loss: boolean;
    max_risk_percent_per_trade: MoneyString;
    max_daily_loss_percent: MoneyString;
    max_trades_per_day: number;
  };
  portfolio_value: MoneyString;
  cash_balance: MoneyString;
  positions_value: MoneyString;
  unrealized_pnl: MoneyString;
  realized_pnl: MoneyString;
  daily_pnl: MoneyString;
  trades_today: number;
  positions: PositionSummary[];
  paper_mode_banner: string;
}

export interface PositionSummary {
  symbol: string;
  quantity: MoneyString;
  average_entry_price: MoneyString;
  current_price: MoneyString;
  market_value: MoneyString;
  unrealized_pnl: MoneyString;
  side?: "long" | "short" | "flat" | string;
  leverage?: MoneyString | number;
}

export interface Position extends PositionSummary {
  id: number;
  updated_at: string;
  stop_loss_price?: MoneyString | null;
  take_profit_price?: MoneyString | null;
  exit_plan_order_id?: number | null;
  abs_quantity?: MoneyString | null;
}

export interface Trade {
  id: number;
  order_id: number;
  symbol: string;
  side: "buy" | "sell" | string;
  quantity: MoneyString;
  price: MoneyString;
  gross_amount: MoneyString;
  fee_amount: MoneyString;
  net_amount: MoneyString;
  realized_pnl: MoneyString;
  executed_at: string;
}

export interface Order {
  id: number;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  requested_quantity: MoneyString;
  filled_quantity: MoneyString;
  requested_price: MoneyString | null;
  filled_price: MoneyString | null;
  stop_loss_price: MoneyString | null;
  take_profit_price: MoneyString | null;
  fee_amount: MoneyString;
  rejection_reason: string | null;
  created_at: string;
  filled_at: string | null;
  cancelled_at: string | null;
}

export interface TradePreview {
  side: "buy" | "sell";
  symbol: string;
  quantity: MoneyString;
  estimated_price: MoneyString;
  gross_amount: MoneyString;
  fee_amount: MoneyString;
  net_amount: MoneyString;
  cash_after: MoneyString;
  estimated_max_loss: MoneyString | null;
  estimated_realized_pnl: MoneyString | null;
  risk_percent: MoneyString | null;
}

export interface OrderPayload {
  symbol: string;
  quantity?: string;
  usd_amount?: string;
  leverage?: number | string;
  stop_loss_price?: string;
  take_profit_price?: string;
  setup_name?: string;
  entry_reason?: string;
  exit_reason?: string;
  emotional_state?: string;
  confidence_score?: number;
  followed_plan?: boolean;
  lesson_learned?: string;
}

export interface JournalEntry {
  id: number;
  symbol: string;
  order_id: number | null;
  setup_name: string | null;
  entry_reason: string | null;
  exit_reason: string | null;
  emotional_state: string | null;
  confidence_score: number | null;
  followed_plan: boolean | null;
  lesson_learned: string | null;
  created_at: string;
  updated_at: string;
}

export interface AnalyticsOverview {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: MoneyString;
  average_win: MoneyString;
  average_loss: MoneyString;
  profit_factor: MoneyString | null;
  largest_win: MoneyString;
  largest_loss: MoneyString;
  maximum_drawdown: MoneyString;
  average_risk_per_trade: MoneyString | null;
  followed_plan_count: number;
  followed_plan_total: number;
  followed_plan_rate: MoneyString | null;
  sample_size_note: string | null;
}

export interface DisciplineStats {
  followed_plan_count: number;
  followed_plan_total: number;
  followed_plan_rate: MoneyString | null;
  stop_loss_usage_rate: MoneyString | null;
  average_confidence: MoneyString | null;
  trades_with_stop_loss: number;
  buy_orders: number;
}

export interface AssetPerformance {
  symbol: string;
  trades: number;
  realized_pnl: MoneyString;
  win_rate: MoneyString;
}

export interface EmotionPerformance {
  emotional_state: string;
  journals: number;
  linked_sells: number;
  average_realized_pnl: MoneyString | null;
  followed_plan_rate: MoneyString | null;
}

export interface AccountSettings {
  starting_balance: MoneyString;
  cash_balance: MoneyString;
  trading_fee_percent: MoneyString;
  /** Optional flat USD fee per fill; when > 0, overrides the percent model. */
  trading_fee_usd?: MoneyString;
  trading_fee_editable: boolean;
  max_risk_percent_per_trade: MoneyString;
  max_daily_loss_percent: MoneyString;
  max_trades_per_day: number;
  require_stop_loss: boolean;
  trading_enabled: boolean;
  paper_mode_banner: string;
}

export interface AccountResetRecord {
  id: number;
  previous_balance: MoneyString;
  reset_balance: MoneyString;
  reason: string | null;
  reset_at: string;
  message?: string;
}

export interface CoachSignal {
  symbol: string;
  interval: string;
  /** Actionable once: BUY/SELL only on ENTRY; WAIT while TREND holds. */
  signal: "BUY" | "SELL" | "WAIT" | string;
  confidence: number;
  reason: string;
  cofr: string;
  price: MoneyString;
  ema9: MoneyString | null;
  ema21: MoneyString | null;
  volume: MoneyString | null;
  volume_avg20: MoneyString | null;
  bar_closed: boolean;
  stop_loss: MoneyString | null;
  take_profit: MoneyString | null;
  risk_reward: string | null;
  source: string;
  evaluated_bar_time: number | null;
  paper_only: boolean;
  brain?: string;
  checklist?: { id: string; label: string; passed: boolean }[];
  short_reason?: string;
  /** ENTRY_BUY|ENTRY_SELL|HOLD_LONG|HOLD_SHORT|EXIT_BUY|EXIT_SELL|NONE */
  phase?: string;
  /** NEUTRAL|LONG|SHORT after this bar */
  position?: string;
  /** HOLD_LONG|HOLD_SHORT|NONE (legacy BUY_TREND/SELL_TREND) */
  trend?: string;
  /** ENTRY_BUY|ENTRY_SELL|NONE */
  entry?: string;
  /** EXIT_BUY|EXIT_SELL|NONE */
  exit?: string;
  exit_reason?: string | null;
  entry_setup?: "a4" | "ccr" | string | null;
  entry_fill?: "close" | "next_open" | string | null;
  entry_fill_price?: MoneyString | null;
  gross_risk_reward?: string | null;
  net_risk_reward?: string | null;
  rr_blocked?: boolean;
  filter_blocked?: boolean;
  filters_enabled?: Record<string, boolean>;
  filter_results?: {
    id: string; label: string; enabled: boolean; passed: boolean; applicable: boolean; reason: string;
  }[];
  filter_set_id?: string | null;
}

export interface CoachSignalHistoryItem {
  id: number;
  symbol: string;
  interval: string;
  brain: string;
  signal: string;
  entry: string;
  trend: string;
  phase?: string | null;
  position_state?: string | null;
  exit_kind?: string | null;
  exit_reason?: string | null;
  alert_side?: string | null;
  seq_from_entry?: number | null;
  entry_price?: MoneyString | null;
  pnl_pct_vs_entry?: MoneyString | null;
  still_profit?: boolean | null;
  confidence: number;
  reason: string | null;
  short_reason: string | null;
  cofr: string | null;
  price: MoneyString;
  ema9: MoneyString | null;
  ema21: MoneyString | null;
  stop_loss: MoneyString | null;
  take_profit: MoneyString | null;
  risk_reward: string | null;
  source: string | null;
  bar_closed: boolean;
  evaluated_bar_time: number;
  created_at: string | null;
}

export interface CoachSignalHistory {
  paper_only: boolean;
  count: number;
  items: CoachSignalHistoryItem[];
}

export interface CoachPrompt {
  name: string;
  prompt: string;
  min_confidence: number;
  sl_pct: number;
  tp_pct: number;
  practice_trades_min: number;
  practice_trades_target: number;
  default_auto_usd?: number;
}

export interface CoachStats {
  paper_only: boolean;
  closed_trades: number;
  win_rate: MoneyString | null;
  net_profit: MoneyString;
  max_drawdown: MoneyString | null;
  profit_factor: MoneyString | null;
  practice_trades_min: number;
  practice_trades_target: number;
  practice_progress_pct: number;
  ready_for_real_money_recommendation: boolean;
  recommendation: string;
  trading_locked: boolean;
  lock_reason: string | null;
  avg_win?: MoneyString | null;
  avg_loss?: MoneyString | null;
  wins?: number;
  losses?: number;
  last_trade_pnl?: MoneyString | null;
  last_exit_reason?: string | null;
  journaled_exits?: number;
  avg_risk_reward?: string | null;
  planned_risk_reward?: string;
  variant_stats?: {
    filter_set_id: string;
    entry_signal: string | null;
    filters_enabled: Record<string, boolean>;
    trades: number;
    win_rate: MoneyString | null;
    avg_pnl: MoneyString | null;
    net_pnl: MoneyString | null;
  }[];
}

export interface CoachAutoTick {
  trend?: string | null;
  entry?: string | null;
  phase?: string | null;
  exit?: string | null;
  position_state?: string | null;
  paper_only: boolean;
  action: string;
  signal: string;
  confidence: number;
  reason: string;
  cofr: string;
  order_id: number | null;
  stats: CoachStats;
  stake_usd?: string | null;
  stop_loss?: string | null;
  take_profit?: string | null;
  position_side?: string | null;
  logs?: string[];
  gross_risk_reward?: string | null;
  net_risk_reward?: string | null;
  rr_blocked?: boolean;
  filter_blocked?: boolean;
  filters_enabled?: Record<string, boolean>;
  filter_results?: {
    id: string; label: string; enabled: boolean; passed: boolean; applicable: boolean; reason: string;
  }[];
  filter_set_id?: string | null;
  entry_source?: "a4" | "ccr" | "lab" | string | null;
  hypothesis_id?: string | null;
  hypothesis_version?: string | null;
}

export interface HypothesisBacktest {
  id: string;
  ran_at: string;
  bars: number;
  verdict: string;
  trade_count: number;
  methodology: string;
  periods: Record<string, {
    trades: number; win_rate: number; net_pnl: number; expectancy: number;
    profit_factor: number | null; max_drawdown: number;
  }>;
}

export interface HypothesisLabItem {
  id: string;
  version: string;
  name: string;
  natural_language_prompt: string;
  structured_rules: Record<string, unknown>;
  parser: "ollama" | "groq" | "gemini" | "regex" | string;
  created_at: string;
  updated_at: string;
  backtests: HypothesisBacktest[];
  promoted_at: string | null;
  paper_profile?: Record<string, unknown> | null;
}

export interface HypothesisLabAccess {
  plan: "free" | "pro" | string;
  backtests_today: number;
  daily_backtest_limit: number | null;
  can_promote: boolean;
  upgrade_message: string | null;
}

export interface BillingStatus {
  plan: "free" | "pro" | string;
  billing_enabled: boolean;
  stripe_customer_id: string | null;
  can_manage_billing: boolean;
  publishable_key: string | null;
  message: string | null;
}

export interface CheckoutSessionResponse {
  checkout_url: string;
  session_id: string;
}

export interface PortalSessionResponse {
  portal_url: string;
}


export interface CoachTradeJournalItem {
  id: number;
  symbol: string;
  side: string;
  entry_time: string | null;
  exit_time: string | null;
  entry_price: string | null;
  exit_price: string | null;
  net_pnl: string | null;
  exit_reason: string | null;
  confidence: number | null;
  regime_label: string | null;
  duration_sec: number | null;
  order_id: number | null;
}

export interface CoachTradeJournal {
  items: CoachTradeJournalItem[];
}

export interface CoachDecisionAuditItem {
  id: number;
  symbol: string;
  interval: string;
  brain?: string | null;
  strategy?: string | null;
  evaluated_bar_time: number;
  signal?: string | null;
  signal_candidate?: string | null;
  phase?: string | null;
  position_state?: string | null;
  final_action: string;
  rejection_reason?: string | null;
  confidence?: number | null;
  rf_proba?: number | null;
  regime?: string | null;
  regime_label?: string | null;
  reasons?: string[];
  price?: string | null;
  order_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CoachDecisionAudit {
  items: CoachDecisionAuditItem[];
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
