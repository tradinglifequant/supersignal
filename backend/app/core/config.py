"""
Central application settings.
All monetary values use Decimal; secrets never logged.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / ".env"), str(_REPO_ROOT / "backend" / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: Literal["development", "testnet", "production"] = Field(default="development")
    app_secret_key: str = Field(default="dev-secret-key-change-in-production-32chars")
    log_level: str = Field(default="INFO")
    app_name: str = Field(default="Super Signal")
    app_version: str = Field(default="0.1.0")

    # Database
    database_url: str = Field(default="sqlite:///./data/supersignal.db")

    # Binance
    binance_api_key: str = Field(default="")
    binance_api_secret: str = Field(default="")
    binance_testnet: bool = Field(default=True)
    binance_recv_window: int = Field(default=5000)
    binance_base_url: str = Field(default="https://fapi.binance.com")
    binance_testnet_base_url: str = Field(default="https://testnet.binancefuture.com")

    # AI decision gate
    # "threerouter"     - call the configured LLM agents (default). Fails closed with no key.
    # "deterministic"   - local rule engine. Explicit opt-in; conservative, auditable, no LLM.
    # "reject_all"      - never approve. The safe default when nothing is configured.
    ai_gate_mode: Literal["threerouter", "deterministic", "reject_all"] = Field(default="threerouter")

    # ThreeRouter
    threerouter_api_key: str = Field(default="")
    threerouter_base_url: str = Field(default="https://api.threerouter.com")
    threerouter_timeout_seconds: int = Field(default=15)
    threerouter_max_concurrency: int = Field(default=5)

    # Security
    admin_username: str = Field(default="admin")
    admin_password_hash: str = Field(default="")
    jwt_secret_key: str = Field(default="")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60)
    credentials_encryption_key: str = Field(default="")
    encryption_key_version: int = Field(default=1)

    # Trading defaults (must match PRD)
    trigger_percentage: Decimal = Field(default=Decimal("1.5"))
    trigger_window_seconds: int = Field(default=180)
    base_margin: Decimal = Field(default=Decimal("3"))
    leverage: int = Field(default=10)
    max_concurrent_trades: int = Field(default=3)
    profit_reinvestment_pct: Decimal = Field(default=Decimal("25"))
    max_trade_allocation: Decimal = Field(default=Decimal("100"))
    daily_loss_limit: Decimal = Field(default=Decimal("50"))
    max_drawdown_pct: Decimal = Field(default=Decimal("10"))
    max_aggregate_exposure: Decimal = Field(default=Decimal("1000"))
    max_consecutive_losses: int = Field(default=5)
    max_slippage_bps: Decimal = Field(default=Decimal("50"))
    taker_fee_bps: Decimal = Field(default=Decimal("4"))
    candidate_ttl_seconds: int = Field(default=30)
    cooldown_seconds: int = Field(default=300)
    protection_deadline_seconds: int = Field(default=10)

    # Risk global limits must be configured before live start
    require_hard_limits: bool = Field(default=True)

    # --- Real-money execution gate -------------------------------------------
    # Which exchange environment the engine is allowed to touch:
    #   "none"    - never place an order (default; mock fills still work in dev)
    #   "testnet" - Binance USD-M futures testnet only
    #   "live"    - production fapi.binance.com with real funds
    trading_env: Literal["none", "testnet", "live"] = Field(default="none")

    # Portfolio Margin accounts route USD-M futures orders to /papi/v1/um/order
    # and expose a different account/balance/position surface. Set explicitly:
    # guessing from a 404 is not safe when real margin is involved.
    portfolio_margin: bool = Field(default=False)

    # Live trading additionally requires BOTH of these. Two independent switches
    # so that one stray env var can never arm real money on its own.
    live_trading_opt_in: bool = Field(default=False)
    live_trading_acknowledgement: str = Field(default="")

    # A testnet soak must be recorded before live can arm.
    require_testnet_soak_hours: int = Field(default=24)

    # Refuse to run if the API key can withdraw. A trading bot key must not.
    reject_key_with_withdrawal: bool = Field(default=True)
    # Refuse to run if local clock drift exceeds this (signed requests fail).
    max_clock_drift_ms: int = Field(default=1000)

    # Hard per-order and aggregate notional ceilings, in quote currency (USDT).
    max_order_notional: Decimal = Field(default=Decimal("100"))
    kill_switch: bool = Field(default=False)

    # Frontend
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000")

    @field_validator("database_url", mode="after")
    @classmethod
    def _resolve_sqlite_path(cls, v: str) -> str:
        """Anchor relative SQLite files to the repository root.

        A bare ``sqlite:///./data/supersignal.db`` resolves against the process
        working directory, so ``alembic upgrade head`` run from ``backend/`` and
        ``uvicorn`` started from the repository root silently used two different
        databases. Absolute URLs (including PostgreSQL) are returned unchanged.
        """
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if not v.startswith(prefix):
                continue
            path = v[len(prefix):]
            if not path or ":memory:" in path or path.startswith("/"):
                return v
            return f"{prefix}{(_REPO_ROOT / path).resolve().as_posix()}"
        return v

    @field_validator(
        "trigger_percentage",
        "base_margin",
        "profit_reinvestment_pct",
        "max_trade_allocation",
        "daily_loss_limit",
        "max_drawdown_pct",
        "max_aggregate_exposure",
        "max_slippage_bps",
        "taker_fee_bps",
        "max_order_notional",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, v):
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    LIVE_ACKNOWLEDGEMENT_PHRASE: ClassVar[str] = "I_UNDERSTAND_REAL_MONEY_RISK"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def live_armed(self) -> bool:
        """Real money is only reachable when every independent switch agrees."""
        return (
            self.trading_env == "live"
            and self.live_trading_opt_in
            and self.live_trading_acknowledgement.strip() == self.LIVE_ACKNOWLEDGEMENT_PHRASE
            and not self.kill_switch
        )

    @property
    def is_testnet(self) -> bool:
        return self.binance_testnet

    @property
    def binance_api_url(self) -> str:
        return self.binance_testnet_base_url if self.binance_testnet else self.binance_base_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def check_hard_limits_configured(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if self.daily_loss_limit <= Decimal("0"):
            missing.append("DAILY_LOSS_LIMIT must be > 0")
        if self.max_drawdown_pct <= Decimal("0"):
            missing.append("MAX_DRAWDOWN_PCT must be > 0")
        if self.max_aggregate_exposure <= Decimal("0"):
            missing.append("MAX_AGGREGATE_EXPOSURE must be > 0")
        if self.max_trade_allocation <= Decimal("0"):
            missing.append("MAX_TRADE_ALLOCATION must be > 0")
        if self.max_slippage_bps <= Decimal("0"):
            missing.append("MAX_SLIPPAGE_BPS must be > 0")
        if self.max_consecutive_losses <= 0:
            missing.append("MAX_CONSECUTIVE_LOSSES must be > 0")
        return (len(missing) == 0, missing)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
