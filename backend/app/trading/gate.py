"""
Pre-trade execution gate.

This module replaces the previous blanket "entries are locked" exception with an
evaluated, auditable decision. Every order that would *increase* exposure must
pass; reduce-only and close-position orders always pass, because being unable to
close a position is itself a safety hazard.

The gate is deliberately boring and fails closed: an unknown or unreadable state
is a rejection, never a pass.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.core.config import Settings, get_settings
from app.exchange.interface import ExchangeAdapter

logger = logging.getLogger(__name__)


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    checks: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "checks": self.checks}


class TradingGate:
    """
    Decides whether an exposure-increasing order may reach the exchange.

    Live real money requires *four* independent things to agree, so that no
    single stray environment variable can arm it:

    1. ``TRADING_ENV=live``
    2. ``LIVE_TRADING_OPT_IN=true``
    3. ``LIVE_TRADING_ACKNOWLEDGEMENT`` matching the exact required phrase
    4. ``KILL_SWITCH`` not set

    ...and then the preflight must also verify the account, key permissions,
    clock drift and symbol state against the exchange itself.
    """

    def __init__(
        self,
        adapter: ExchangeAdapter,
        settings: Optional[Settings] = None,
        is_testnet: bool = False,
    ):
        self.adapter = adapter
        self.settings = settings or get_settings()
        self.is_testnet = is_testnet
        self._preflight_cache: dict[str, Any] | None = None
        self._preflight_at: float = 0.0
        self.preflight_ttl_seconds = 300.0
        # Records how long the adapter has been pointed at testnet, used to
        # enforce a soak period before live can be armed.
        self.testnet_armed_at: float | None = None

    # ------------------------------------------------------------------
    def _env_allowed(self) -> tuple[bool, str]:
        env = self.settings.trading_env
        if env == "none":
            return False, "TRADING_ENV=none: order placement is disabled"
        if env == "testnet":
            if not self.is_testnet:
                return False, "TRADING_ENV=testnet but adapter targets production fapi"
            return True, "testnet"
        if env == "live":
            if self.is_testnet:
                return False, "TRADING_ENV=live but adapter targets testnet"
            if not self.settings.live_trading_opt_in:
                return False, "live trading requires LIVE_TRADING_OPT_IN=true"
            if self.settings.live_trading_acknowledgement.strip() != (
                Settings.LIVE_ACKNOWLEDGEMENT_PHRASE
            ):
                return False, (
                    "LIVE_TRADING_ACKNOWLEDGEMENT must exactly equal "
                    f"{Settings.LIVE_ACKNOWLEDGEMENT_PHRASE}"
                )
            return True, "live"
        return False, f"unknown TRADING_ENV {env!r}"

    # ------------------------------------------------------------------
    async def preflight(self, force: bool = False) -> dict[str, Any]:
        """
        Verify the account against the exchange. Cached for ``preflight_ttl_seconds``
        because it costs several signed round trips.
        """
        now = time.time()
        if (
            not force
            and self._preflight_cache is not None
            and now - self._preflight_at < self.preflight_ttl_seconds
        ):
            return self._preflight_cache

        checks: dict[str, Any] = {
            "trading_env": self.settings.trading_env,
            "is_testnet": self.is_testnet,
            "portfolio_margin": self.settings.portfolio_margin,
            "live_armed": self.settings.live_armed,
            "kill_switch": self.settings.kill_switch,
        }

        # 1. connectivity
        try:
            checks["connectivity"] = await self.adapter.test_connectivity()
        except Exception:
            checks["connectivity"] = False

        # 2. hard risk limits configured
        ok, missing = self.settings.check_hard_limits_configured()
        checks["hard_limits_configured"] = ok
        if not ok:
            checks["hard_limits_missing"] = missing

        # 3. API key permissions
        try:
            perms = await self.adapter.get_api_key_permissions()
        except Exception:
            perms = None
        checks["api_key_permissions"] = perms
        if perms is None:
            checks["can_trade"] = False
            checks["can_withdraw"] = None
        else:
            checks["can_trade"] = bool(perms.get("can_trade"))
            checks["can_withdraw"] = perms.get("can_withdraw")

        # 4. clock drift - signed requests are rejected when it is too large
        drift: Optional[int] = None
        try:
            server_ms = await self.adapter.get_server_time()
        except Exception:
            server_ms = None
        if server_ms is not None:
            drift = abs(int(time.time() * 1000) - int(server_ms))
        checks["clock_drift_ms"] = drift
        if drift is not None:
            checks["clock_drift_ok"] = drift <= self.settings.max_clock_drift_ms

        result = {
            "checked_at": now,
            "checks": checks,
            "blocking": self._blocking_reasons(checks),
        }
        result["passed"] = not result["blocking"]
        self._preflight_cache = result
        self._preflight_at = now
        return result

    def _blocking_reasons(self, checks: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if checks.get("kill_switch"):
            reasons.append("KILL_SWITCH is set")
        if not checks.get("connectivity"):
            reasons.append("exchange connectivity check failed")
        if not checks.get("hard_limits_configured"):
            reasons.append(f"risk limits not configured: {checks.get('hard_limits_missing')}")
        if checks.get("can_trade") is False:
            reasons.append("API key cannot trade (canTrade=false)")
        if self.settings.reject_key_with_withdrawal and checks.get("can_withdraw") is True:
            reasons.append(
                "API key can WITHDRAW funds; revoke that permission before using it here"
            )
        if checks.get("clock_drift_ok") is False:
            reasons.append(
                f"clock drift {checks.get('clock_drift_ms')}ms exceeds "
                f"{self.settings.max_clock_drift_ms}ms"
            )
        return reasons

    # ------------------------------------------------------------------
    def _soak_satisfied(self) -> tuple[bool, str]:
        required = self.settings.require_testnet_soak_hours
        if required <= 0:
            return True, "soak not required"
        if self.testnet_armed_at is None:
            return False, (
                f"no recorded testnet soak; {required}h on testnet is required before live"
            )
        hours = (time.time() - self.testnet_armed_at) / 3600.0
        if hours < required:
            return False, (
                f"testnet soak {hours:.1f}h < required {required}h"
            )
        return True, f"testnet soak {hours:.1f}h >= {required}h"

    # ------------------------------------------------------------------
    async def authorize_entry(
        self,
        symbol: str,
        notional: Decimal,
        price: Optional[Decimal] = None,
    ) -> GateDecision:
        """Gate a single exposure-increasing order."""
        env_ok, env_reason = self._env_allowed()
        if not env_ok:
            return GateDecision(False, env_reason, {"env": env_reason})

        # Per-order notional ceiling is independent of the risk engine.
        if notional is not None and notional > self.settings.max_order_notional:
            return GateDecision(
                False,
                f"order notional {notional} exceeds MAX_ORDER_NOTIONAL "
                f"{self.settings.max_order_notional}",
                {"notional": str(notional)},
            )

        pre = await self.preflight()
        if not pre["passed"]:
            return GateDecision(
                False,
                "preflight failed: " + "; ".join(pre["blocking"]),
                {"preflight": pre["blocking"]},
            )

        # Live additionally requires the recorded testnet soak.
        if self.settings.trading_env == "live":
            ok, soak_reason = self._soak_satisfied()
            if not ok:
                return GateDecision(False, soak_reason, {"soak": soak_reason})

        return GateDecision(
            True,
            f"entry authorized ({env_reason}){f' ref={price}' if price is not None else ''}",
            {"env": env_reason, "notional": str(notional) if notional is not None else None},
        )

    async def authorize_exit(self, symbol: str) -> GateDecision:
        """
        Closing or reducing exposure is always permitted.

        Blocking an exit would strand real margin in an unprotected position,
        which is strictly worse than allowing the order.
        """
        return GateDecision(True, "reduce-only/close-position orders are always permitted", {"symbol": symbol})
