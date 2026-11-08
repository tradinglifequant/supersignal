from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import SignalCandidate, ensure_utc
from app.market.trigger_engine import TriggerResult

logger = logging.getLogger(__name__)


class CandidateManager:
    """
    Deduplication, cooldown, TTL, persistence.
    Rules:
    - One active candidate per symbol/direction
    - Configurable cooldown after rejection/closure
    - Candidate TTL (default 30s) - expired cannot execute
    """

    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.cooldowns: Dict[str, Dict[str, datetime]] = {}

    def _is_cooldown(self, symbol: str, direction: str, now: datetime) -> bool:
        d = self.cooldowns.get(symbol, {}).get(direction)
        if d and d > now:
            return True
        return False

    def set_cooldown(self, symbol: str, direction: str, cooldown_seconds: Optional[int] = None):
        now = datetime.now(timezone.utc)
        secs = cooldown_seconds if cooldown_seconds is not None else self.settings.cooldown_seconds
        expiry = now + timedelta(seconds=secs)
        if symbol not in self.cooldowns:
            self.cooldowns[symbol] = {}
        self.cooldowns[symbol][direction] = expiry

    def has_active_candidate(self, symbol: str, direction: str) -> bool:
        now = datetime.now(timezone.utc)
        q = self.db.query(SignalCandidate).filter(
            SignalCandidate.symbol == symbol,
            SignalCandidate.direction == direction,
            SignalCandidate.status.in_(["DETECTED", "PROCESSING"]),
            SignalCandidate.expires_at > now,
        )
        return q.first() is not None

    def create_candidate(
        self,
        trigger: TriggerResult,
        snapshot_json: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[SignalCandidate]:
        now = datetime.now(timezone.utc)
        if self._is_cooldown(trigger.symbol, trigger.direction, now):
            logger.info("Cooldown active for %s %s, skipping", trigger.symbol, trigger.direction)
            return None
        if self.has_active_candidate(trigger.symbol, trigger.direction):
            logger.info("Active candidate exists for %s %s, dedup", trigger.symbol, trigger.direction)
            return None

        ttl = ttl_seconds if ttl_seconds is not None else self.settings.candidate_ttl_seconds
        expires_at = now + timedelta(seconds=ttl)
        existing = self.db.query(SignalCandidate).filter(SignalCandidate.event_key == trigger.event_key).first()
        if existing:
            logger.info("event_key collision %s", trigger.event_key)
            return None

        cand = SignalCandidate(
            id=trigger.event_id,
            event_key=trigger.event_key,
            symbol=trigger.symbol,
            direction=trigger.direction,
            current_price=trigger.price_now,
            reference_price=trigger.price_ref,
            change_pct=trigger.change_pct,
            window_seconds=trigger.window_seconds,
            detected_at=trigger.detected_at,
            exchange_event_time=trigger.exchange_event_time,
            expires_at=expires_at,
            status="DETECTED",
            snapshot_json=snapshot_json,
        )
        self.db.add(cand)
        self.db.commit()
        logger.info("Created candidate %s %s %s %s%%", cand.id, cand.symbol, cand.direction, cand.change_pct)
        return cand

    def mark_processing(self, candidate: SignalCandidate):
        candidate.status = "PROCESSING"
        self.db.commit()

    def mark_approved(self, candidate: SignalCandidate):
        candidate.status = "APPROVED"
        self.db.commit()

    def mark_rejected(self, candidate: SignalCandidate, reason: str, cooldown_seconds: Optional[int] = None):
        candidate.status = "REJECTED"
        candidate.rejection_reason = reason
        self.db.commit()
        self.set_cooldown(candidate.symbol, candidate.direction, cooldown_seconds=cooldown_seconds)

    def mark_expired(self, candidate: SignalCandidate):
        if candidate.status in ("DETECTED", "PROCESSING"):
            candidate.status = "EXPIRED"
            self.db.commit()

    def expire_stale(self) -> int:
        now = datetime.now(timezone.utc)
        stale = (
            self.db.query(SignalCandidate)
            .filter(
                SignalCandidate.expires_at <= now,
                SignalCandidate.status.in_(["DETECTED", "PROCESSING"]),
            )
            .all()
        )
        for c in stale:
            c.status = "EXPIRED"
        if stale:
            self.db.commit()
        return len(stale)

    def check_expiry(self, candidate: SignalCandidate) -> bool:
        now = datetime.now(timezone.utc)
        exp = ensure_utc(candidate.expires_at)
        if exp is not None and exp <= now:
            self.mark_expired(candidate)
            return True
        return False
