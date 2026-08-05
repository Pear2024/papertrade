"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Prefer monorepo root .env, then apps/api/.env
_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"
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

    # Flat paper fee in USD per fill (preferred). Set 0 to use percent instead.
    paper_trading_fee_usd: str = "9"
    # Used only when paper_trading_fee_usd is 0.
    paper_trading_fee_percent: str = "0.05"
    paper_starting_balance: str = "20000.00"

    public_price_api_url: str = "https://api.coingecko.com/api/v3"
    # Kraken PUBLIC market data only — never set private API credentials here.
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
