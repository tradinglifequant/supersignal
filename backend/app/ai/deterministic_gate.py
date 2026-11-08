"""
Deterministic (non-LLM) decision gate.

This exists so the trading pipeline has an auditable, offline decision path that
does not depend on an external LLM provider. It is *not* a bypass: it emits the
same five per-agent verdicts plus the agent-6 aggregate that the LLM path
produces, so agent logs, the fail-closed aggregation and the audit trail all
work identically.

It is deliberately conservative. Every rule that cannot be evaluated from real
data yields ``INSUFFICIENT_DATA``, and the orchestrator's existing aggregation
turns any non-YES mandatory verdict into a final NO.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from app.ai.schemas import Agent6ResponseSchema, AgentResponse, MarketSnapshot

logger = logging.getLogger(__name__)


def _dec(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class DeterministicGate:
    """Rule-based stand-in for the five LLM agents plus the aggregator."""

    # Tunables; conservative defaults.
    MAX_DATA_AGE_SECONDS = 10.0
    MIN_CANDLES = 30
    MIN_QUOTE_VOLUME_24H = Decimal("5_000_000")
    MAX_SPREAD_BPS = Decimal("10")
    MAX_TRIGGER_PCT = Decimal("6")  # beyond this treat the move as a blow-off, not an entry
    MAX_ABS_FUNDING = Decimal("0.003")  # 0.3% - extreme funding is a crowd signal
    MIN_IMBALANCE_EDGE = Decimal("0.55")  # bid/ask volume share favouring the direction
    REQUIRED_FEEDS = ("candles_1m", "orderbook", "funding_rate", "volume_24h")

    def __init__(self, settings=None):
        self.settings = settings

    # ------------------------------------------------------------------
    def _agent(self, name, snapshot, decision, evidence, missing, rationale, confidence=None):
        return AgentResponse(
            agent_name=name,
            schema_version="1.0",
            symbol=snapshot.symbol,
            direction=snapshot.direction,
            decision=decision,
            confidence=confidence,
            evidence=evidence,
            missing_data=missing,
            rationale=rationale,
            created_at=datetime.now(timezone.utc),
            provider_metadata={"provider": "deterministic-gate"},
        )

    # ------------------------------------------------------------------
    def evaluate(self, snapshot: MarketSnapshot) -> dict[str, AgentResponse]:
        missing = set(snapshot.missing_data or [])
        gaps = sorted(missing & set(self.REQUIRED_FEEDS))
        if gaps:
            verdict = "INSUFFICIENT_DATA"
            reason = f"required feeds unavailable: {', '.join(gaps)}"
        else:
            verdict = "YES"
            reason = "all required feeds present"

        out: dict[str, AgentResponse] = {}

        # --- agent-1: opportunity validation (trigger + liquidity) ---------
        pct = abs(_dec(snapshot.trigger_change_pct) or Decimal("0"))
        qv = _dec(snapshot.volume_24h)
        ev, mi = [], []
        decision = "INSUFFICIENT_DATA"
        rationale = reason
        if verdict == "YES":
            ev.append(f"trigger {snapshot.trigger_change_pct}% over {snapshot.window_seconds}s")
            if pct > self.MAX_TRIGGER_PCT:
                decision = "NO"
                rationale = f"trigger {pct}% exceeds max {self.MAX_TRIGGER_PCT}% (blow-off risk)"
            elif qv is None or qv < self.MIN_QUOTE_VOLUME_24H:
                decision = "NO"
                rationale = f"24h quote volume {qv} below {self.MIN_QUOTE_VOLUME_24H} liquidity floor"
            else:
                decision = "YES"
                rationale = f"trigger plausible and 24h quote volume {qv} clears liquidity floor"
                ev.append(f"24h quote volume {qv}")
        elif gaps:
            mi = gaps
        out["agent-1"] = self._agent("agent-1", snapshot, decision, ev, mi, rationale,
                                     confidence=0.6 if decision == "YES" else None)

        # --- agent-2: market structure from the 1m candles -----------------
        decision, rationale, ev, mi = "INSUFFICIENT_DATA", reason, [], list(gaps)
        candles = snapshot.candles_1m or []
        if verdict == "YES" and len(candles) >= self.MIN_CANDLES:
            closes = [(_dec(c.get("close")) or Decimal("0")) for c in candles]
            closes = [c for c in closes if c > 0]
            if len(closes) >= self.MIN_CANDLES:
                window = closes[-20:]
                rising = window[-1] > window[0]
                want_long = snapshot.direction.upper() == "LONG"
                trend_agrees = rising if want_long else not rising
                ev.append(f"20-bar drift {'up' if rising else 'down'} "
                          f"({window[0]} -> {window[-1]})")
                if trend_agrees:
                    decision = "YES"
                    rationale = "1m structure drifts with the signal direction"
                else:
                    decision = "NO"
                    rationale = "1m structure drifts against the signal direction"
            else:
                rationale = "insufficient usable candle closes"
        elif verdict == "YES":
            rationale = f"fewer than {self.MIN_CANDLES} candles available"
        out["agent-2"] = self._agent("agent-2", snapshot, decision, ev, mi, rationale,
                                     confidence=0.6 if decision == "YES" else None)

        # --- agent-3: funding / positioning --------------------------------
        decision, rationale, ev, mi = "INSUFFICIENT_DATA", reason, [], list(gaps)
        funding = _dec(snapshot.funding_rate)
        if verdict == "YES" and funding is not None:
            ev.append(f"funding rate {funding}")
            if abs(funding) > self.MAX_ABS_FUNDING:
                decision = "NO"
                rationale = f"funding {funding} beyond +/-{self.MAX_ABS_FUNDING} (crowded)"
            else:
                crowded_against = (
                    snapshot.direction.upper() == "LONG" and funding > self.MAX_ABS_FUNDING / 2
                ) or (
                    snapshot.direction.upper() == "SHORT" and funding < -self.MAX_ABS_FUNDING / 2
                )
                if crowded_against:
                    decision = "NO"
                    rationale = "funding is already paying the signal direction heavily"
                else:
                    decision = "YES"
                    rationale = "funding within normal bounds and not crowded against direction"
            if snapshot.open_interest:
                ev.append(f"open interest {snapshot.open_interest}")
        elif verdict == "YES":
            rationale = "funding rate unavailable"
        out["agent-3"] = self._agent("agent-3", snapshot, decision, ev, mi, rationale,
                                     confidence=0.6 if decision == "YES" else None)

        # --- agent-4: order-flow / depth imbalance --------------------------
        decision, rationale, ev, mi = "INSUFFICIENT_DATA", reason, [], list(gaps)
        book = snapshot.orderbook_snapshot or {}
        bids = book.get("top_bids") or []
        asks = book.get("top_asks") or []
        if verdict == "YES" and bids and asks:
            bid_v = sum((_dec(b.get("qty")) or Decimal("0")) for b in bids)
            ask_v = sum((_dec(a.get("qty")) or Decimal("0")) for a in asks)
            total = bid_v + ask_v
            share = (bid_v / total) if total > 0 else Decimal("0.5")
            ev.append(f"bid share {share:.3f} (bid {bid_v} vs ask {ask_v})")
            want_long = snapshot.direction.upper() == "LONG"
            favourable = share if want_long else (Decimal("1") - share)
            if favourable >= self.MIN_IMBALANCE_EDGE:
                decision = "YES"
                rationale = f"top-10 depth favours the direction ({favourable:.3f})"
            else:
                decision = "NO"
                rationale = f"top-10 depth does not favour the direction ({favourable:.3f})"
            spread = _dec(book.get("bid_ask_spread"))
            top_bid = _dec(bids[0].get("price"))
            if spread is not None and top_bid:
                bps = spread / top_bid * Decimal("10000")
                ev.append(f"spread {bps:.2f} bps")
                if bps > self.MAX_SPREAD_BPS and decision == "YES":
                    decision = "NO"
                    rationale = f"spread {bps:.1f} bps exceeds {self.MAX_SPREAD_BPS} bps"
        elif verdict == "YES":
            rationale = "order book depth unavailable"
        out["agent-4"] = self._agent("agent-4", snapshot, decision, ev, mi, rationale,
                                     confidence=0.6 if decision == "YES" else None)

        # --- agent-5: data integrity / freshness ----------------------------
        decision, rationale, ev, mi = "INSUFFICIENT_DATA", reason, [], list(gaps)
        age = snapshot.data_freshness_seconds
        if verdict == "YES":
            ev.append(f"feed age {age}s" if age is not None else "feed age unknown")
            if age is None or age > self.MAX_DATA_AGE_SECONDS:
                decision = "NO"
                rationale = f"price feed stale or unknown (age={age}s, max {self.MAX_DATA_AGE_SECONDS}s)"
            elif (snapshot.symbol_status or "TRADING").upper() != "TRADING":
                decision = "NO"
                rationale = f"symbol status {snapshot.symbol_status} is not TRADING"
            else:
                decision = "YES"
                rationale = f"data fresh ({age:.2f}s) and symbol tradable"
        out["agent-5"] = self._agent("agent-5", snapshot, decision, ev, mi, rationale,
                                     confidence=0.6 if decision == "YES" else None)

        return out

    # ------------------------------------------------------------------
    def aggregate(self, snapshot: MarketSnapshot, agents: dict[str, AgentResponse]) -> Agent6ResponseSchema:
        """Mirror the orchestrator's fail-closed rule: any non-YES => NO."""
        blockers = [
            f"{name}:{resp.decision}" for name, resp in agents.items() if resp.decision != "YES"
        ]
        if blockers:
            decision = "NO"
            rationale = (
                "Deterministic gate rejected: " + ", ".join(blockers)
            )
            confidence = 0.0
        else:
            decision = "YES"
            rationale = "Deterministic gate: all five rule checks passed"
            confidence = 0.6

        return Agent6ResponseSchema(
            agent_name="agent-6",
            schema_version="1.0",
            symbol=snapshot.symbol,
            direction=snapshot.direction,
            decision=decision,
            confidence=confidence,
            rationale=rationale,
            invalidation_conditions=(
                "Feed staleness, adverse depth imbalance, extreme funding, or a "
                "trigger beyond the configured band"
            ),
            created_at=datetime.now(timezone.utc),
            aggregated_from=list(agents.keys()),
            evidence_summary="; ".join(
                f"{name}: {resp.rationale}" for name, resp in agents.items()
            ),
        )
