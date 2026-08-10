"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Prefer monorepo root .env, then apps/api/.env
_parents = Path(__file__).resolve().parents
_ROOT_ENV = (_parents[4] if len(_parents) > 4 else _parents[-1]) / ".env"
_API_ENV = Path(__file__).resolve().parents[2] / ".env"
_ENV_FILES = tuple(str(path) for path in (_ROOT_ENV, _API_ENV) if path.exists())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Paper Crypto Coach API"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str = (
        "mysql+pymysql://paper_user:change_me_paper_password@db:3306/paper_crypto_coach"
    )
    mysql_host: str = "db"
    mysql_port: int = 3306

    jwt_secret: str = "change_me_to_a_long_random_secret"
    jwt_expire_minutes: int = 1440
    # Google OAuth / OpenID Connect. Leave client ID or secret empty to disable
    # the provider without affecting email/password authentication.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    # Browser origin that receives the short-lived OAuth completion redirect.
    web_app_url: str = "http://localhost:3001"

    # Kraken Pro receipt-backed paper fee: 0.80% of each fill's notional.
    # A positive flat fee is supported only as an explicit override.
    paper_trading_fee_usd: str = "0"
    # Percentage points: 0.80 means 0.80%, not a fractional 0.008 rate.
    paper_trading_fee_percent: str = "0.80"
    paper_starting_balance: str = "20000.00"

    public_price_api_url: str = "https://api.coingecko.com/api/v3"
    # Kraken PUBLIC market data only â€” never set private API credentials here.
    kraken_rest_url: str = "https://api.kraken.com"
    kraken_ws_url: str = "wss://ws.kraken.com/v2"
    kraken_feed_enabled: bool = True

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3001"

    # Google Chat incoming webhook (optional). Never commit the real URL.
    google_chat_webhook_url: str | None = None

# MetaAlpha Quantum Engine — optional ENTRY meta-label filter (default OFF).
    meta_alpha_enabled: bool = False
    meta_alpha_threshold: float = 0.75
    meta_alpha_model_path: str = (
        "apps/api/app/services/meta_alpha/artifacts/meta_labeler.joblib"
    )
    meta_alpha_mode: str = "feature"
    meta_alpha_fail_closed: bool = True
    meta_alpha_min_bars: int = 120

    # Hypothesis Lab uses free local/free-tier LLMs opportunistically. Parsing
    # remains fully functional through its deterministic rules engine.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"
    gemini_api_key: str | None = None
    google_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"

    # Stripe Billing (optional). Leave blank to disable checkout; API stays up.
    # Never log these values. Prefer Droplet `.env` only — never commit secrets.
    stripe_secret_key: str | None = None
    stripe_publishable_key: str | None = None
    # Alias used by some Next.js setups; either publishable key is accepted.
    next_public_stripe_publishable_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id_pro: str | None = None

    @property
    def resolved_stripe_publishable_key(self) -> str | None:
        return self.stripe_publishable_key or self.next_public_stripe_publishable_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
