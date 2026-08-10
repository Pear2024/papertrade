"""Tradable paper crypto catalog (majors with CoinGecko + Binance USDT candles)."""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class AssetDef(TypedDict):
    symbol: str
    name: str
    price_precision: int
    quantity_precision: int
    seed_price: Decimal
    coingecko_id: str
    binance_pair: str


# Broad liquid majors — not literally every coin on earth (that would break feeds).
ASSETS_CATALOG: list[AssetDef] = [
    {"symbol": "BTC", "name": "Bitcoin", "price_precision": 2, "quantity_precision": 8, "seed_price": Decimal("65000"), "coingecko_id": "bitcoin", "binance_pair": "BTCUSDT"},
    {"symbol": "ETH", "name": "Ethereum", "price_precision": 2, "quantity_precision": 8, "seed_price": Decimal("3500"), "coingecko_id": "ethereum", "binance_pair": "ETHUSDT"},
    {"symbol": "SOL", "name": "Solana", "price_precision": 2, "quantity_precision": 6, "seed_price": Decimal("150"), "coingecko_id": "solana", "binance_pair": "SOLUSDT"},
    {"symbol": "XRP", "name": "XRP", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("0.60"), "coingecko_id": "ripple", "binance_pair": "XRPUSDT"},
    {"symbol": "BNB", "name": "BNB", "price_precision": 2, "quantity_precision": 6, "seed_price": Decimal("600"), "coingecko_id": "binancecoin", "binance_pair": "BNBUSDT"},
    {"symbol": "ADA", "name": "Cardano", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("0.45"), "coingecko_id": "cardano", "binance_pair": "ADAUSDT"},
    {"symbol": "DOGE", "name": "Dogecoin", "price_precision": 5, "quantity_precision": 0, "seed_price": Decimal("0.12"), "coingecko_id": "dogecoin", "binance_pair": "DOGEUSDT"},
    {"symbol": "AVAX", "name": "Avalanche", "price_precision": 2, "quantity_precision": 4, "seed_price": Decimal("35"), "coingecko_id": "avalanche-2", "binance_pair": "AVAXUSDT"},
    {"symbol": "DOT", "name": "Polkadot", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("7"), "coingecko_id": "polkadot", "binance_pair": "DOTUSDT"},
    {"symbol": "LINK", "name": "Chainlink", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("15"), "coingecko_id": "chainlink", "binance_pair": "LINKUSDT"},
    {"symbol": "MATIC", "name": "Polygon", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("0.50"), "coingecko_id": "matic-network", "binance_pair": "MATICUSDT"},
    {"symbol": "ATOM", "name": "Cosmos", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("8"), "coingecko_id": "cosmos", "binance_pair": "ATOMUSDT"},
    {"symbol": "LTC", "name": "Litecoin", "price_precision": 2, "quantity_precision": 6, "seed_price": Decimal("80"), "coingecko_id": "litecoin", "binance_pair": "LTCUSDT"},
    {"symbol": "UNI", "name": "Uniswap", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("8"), "coingecko_id": "uniswap", "binance_pair": "UNIUSDT"},
    {"symbol": "APT", "name": "Aptos", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("10"), "coingecko_id": "aptos", "binance_pair": "APTUSDT"},
    {"symbol": "ARB", "name": "Arbitrum", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("0.80"), "coingecko_id": "arbitrum", "binance_pair": "ARBUSDT"},
    {"symbol": "OP", "name": "Optimism", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("2"), "coingecko_id": "optimism", "binance_pair": "OPUSDT"},
    {"symbol": "SUI", "name": "Sui", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("1.50"), "coingecko_id": "sui", "binance_pair": "SUIUSDT"},
    {"symbol": "NEAR", "name": "NEAR", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("5"), "coingecko_id": "near", "binance_pair": "NEARUSDT"},
    {"symbol": "TRX", "name": "TRON", "price_precision": 5, "quantity_precision": 0, "seed_price": Decimal("0.12"), "coingecko_id": "tron", "binance_pair": "TRXUSDT"},
    {"symbol": "SHIB", "name": "Shiba Inu", "price_precision": 8, "quantity_precision": 0, "seed_price": Decimal("0.00002"), "coingecko_id": "shiba-inu", "binance_pair": "SHIBUSDT"},
    {"symbol": "TON", "name": "Toncoin", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("5"), "coingecko_id": "the-open-network", "binance_pair": "TONUSDT"},
    {"symbol": "ICP", "name": "Internet Computer", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("10"), "coingecko_id": "internet-computer", "binance_pair": "ICPUSDT"},
    {"symbol": "FIL", "name": "Filecoin", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("5"), "coingecko_id": "filecoin", "binance_pair": "FILUSDT"},
    {"symbol": "AAVE", "name": "Aave", "price_precision": 2, "quantity_precision": 4, "seed_price": Decimal("150"), "coingecko_id": "aave", "binance_pair": "AAVEUSDT"},
    {"symbol": "PEPE", "name": "Pepe", "price_precision": 8, "quantity_precision": 0, "seed_price": Decimal("0.00001"), "coingecko_id": "pepe", "binance_pair": "PEPEUSDT"},
    {"symbol": "INJ", "name": "Injective", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("25"), "coingecko_id": "injective-protocol", "binance_pair": "INJUSDT"},
    {"symbol": "SEI", "name": "Sei", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("0.40"), "coingecko_id": "sei-network", "binance_pair": "SEIUSDT"},
    {"symbol": "WIF", "name": "dogwifhat", "price_precision": 4, "quantity_precision": 2, "seed_price": Decimal("2"), "coingecko_id": "dogwifcoin", "binance_pair": "WIFUSDT"},
    {"symbol": "RENDER", "name": "Render", "price_precision": 3, "quantity_precision": 4, "seed_price": Decimal("7"), "coingecko_id": "render-token", "binance_pair": "RENDERUSDT"},
]


def symbol_to_coingecko() -> dict[str, str]:
    return {a["symbol"]: a["coingecko_id"] for a in ASSETS_CATALOG}


def symbol_to_binance() -> dict[str, str]:
    return {a["symbol"]: a["binance_pair"] for a in ASSETS_CATALOG}


def seed_rows() -> list[dict]:
    return [
        {
            "symbol": a["symbol"],
            "name": a["name"],
            "price_precision": a["price_precision"],
            "quantity_precision": a["quantity_precision"],
            "seed_price": a["seed_price"],
        }
        for a in ASSETS_CATALOG
    ]


# Common exchange / UI aliases → catalog base symbols (BTC, ETH, …).
_SYMBOL_ALIASES: dict[str, str] = {
    "XBT": "BTC",
    "XBTUSD": "BTC",
    "XXBTZUSD": "BTC",
    "BTCUSD": "BTC",
    "BTCUSDT": "BTC",
    "BTC/USD": "BTC",
    "BTC/USDT": "BTC",
    "XBT/USD": "BTC",
    "ETHUSD": "ETH",
    "ETHUSDT": "ETH",
    "ETH/USD": "ETH",
    "ETH/USDT": "ETH",
    "SOLUSD": "SOL",
    "SOLUSDT": "SOL",
    "SOL/USD": "SOL",
    "SOL/USDT": "SOL",
}


def normalize_symbol(symbol: str) -> str:
    """Map pair aliases (BTCUSD, XBTUSD, BTC/USD) to catalog symbols like BTC."""
    raw = (symbol or "").strip().upper().replace(" ", "")
    if not raw:
        return raw
    if raw in _SYMBOL_ALIASES:
        return _SYMBOL_ALIASES[raw]
    # Strip common quote suffixes when base is a catalog symbol.
    for quote in ("USDT", "USD", "USDC"):
        if raw.endswith(quote) and len(raw) > len(quote):
            base = raw[: -len(quote)]
            if base == "XBT":
                return "BTC"
            if any(a["symbol"] == base for a in ASSETS_CATALOG):
                return base
    if "/" in raw:
        base = raw.split("/", 1)[0]
        if base == "XBT":
            return "BTC"
        if any(a["symbol"] == base for a in ASSETS_CATALOG):
            return base
    return raw
