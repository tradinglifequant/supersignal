"""
Central application settings.
All monetary values use Decimal; secrets never logged.
"""
from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    max_slippage_bps: Decimal = Field(default=Decimal("50"))
    taker_fee_bps: Decimal = Field(default=Decimal("4"))
    candidate_ttl_seconds: int = Field(default=30)
    cooldown_seconds: int = Field(default=300)
    protection_deadline_seconds: int = Field(default=10)

    # Risk global limits must be configured before live start
    require_hard_limits: bool = Field(default=True)

    # Frontend
    cors_origins: str = Field(default="http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000")

    @field_validator("trigger_percentage", "base_margin", "profit_reinvestment_pct", mode="before")
    @classmethod
    def _coerce_decimal(cls, v):
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

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
        return (len(missing) == 0, missing)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
