/**
 * Shared constants and types for Paper Crypto Coach.
 * Keep money amounts as strings to preserve Decimal precision across the wire.
 */

export const APP_NAME = "Paper Crypto Coach" as const;

export const ACCOUNT_MODE = "paper" as const;

export const DEFAULT_STARTING_BALANCE = "10.00" as const;
/** Kraken Pro Tier 1 taker (market) — percent points, e.g. 0.80 = 0.80%. */
export const DEFAULT_FEE_PERCENT = "0.80" as const;
export const DEFAULT_AUTO_STAKE_USD = "100" as const;

export const SUPPORTED_SYMBOLS = [
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

export type SupportedSymbol = (typeof SUPPORTED_SYMBOLS)[number];

export const ORDER_SIDES = ["buy", "sell"] as const;
export type OrderSide = (typeof ORDER_SIDES)[number];

export const ORDER_TYPES = ["market"] as const;
export type OrderType = (typeof ORDER_TYPES)[number];

export const ORDER_STATUSES = ["pending", "filled", "rejected", "cancelled"] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export const EMOTIONAL_STATES = [
  "calm",
  "confident",
  "fearful",
  "greedy",
  "impatient",
  "unsure",
] as const;
export type EmotionalState = (typeof EMOTIONAL_STATES)[number];

export type MoneyString = string;

export interface PaperModeBanner {
  title: string;
  messageEn: string;
}

export const PAPER_MODE_BANNER: PaperModeBanner = {
  title: "PAPER MODE — NO REAL ORDERS",
  messageEn:
    "All balances are simulated. Kraken public market data only — never private trading APIs or real orders.",
};
