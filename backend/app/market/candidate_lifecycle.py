from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
import logging

from sqlalchemy.orm import Session

from app.db.models import SignalCandidate
from app.market.trigger_engine import TriggerResult
from app.core.config import Settings

logger = logging.getLogger(__name__)

class CandidateManager:
    """
    Deduplication, cooldown, TTL, persistence.
    Rules:
    - One active candidate per symbol/direction
    - One open bot position per symbol (checked via execution layer, but we can also block)
    - Configurable cooldown after rejection/closure
    - Candidate TTL (default 30s) - expired cannot execute
    """

    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        # in-memory cooldown tracker: symbol -> direction -> expiry
        self.cooldowns: Dict[str, Dict[str, datetime]] = {}

    def _is_cooldown(self, symbol: str, direction: str, now: datetime) -> bool:
        d = self.cooldowns.get(symbol, {}).get(direction)
        if d and d > now:
            return True
        return False

    def set_cooldown(self, symbol: str, direction: str):
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(seconds=self.settings.cooldown_seconds)
        if symbol not in self.cooldowns:
            self.cooldowns[symbol] = {}
        self.cooldowns[symbol][direction] = expiry

    def has_active_candidate(self, symbol: str, direction: str) -> bool:
        # active = DETECTED or PROCESSING, not expired, not rejected
        now = datetime.now(timezone.utc)
        q = self.db.query(SignalCandidate).filter(
            SignalCandidate.symbol == symbol,
            SignalCandidate.direction == direction,
            SignalCandidate.status.in_(["DETECTED", "PROCESSING"]),
            SignalCandidate.expires_at > now,
        )
        return q.first() is not None

    def create_candidate(self, trigger: TriggerResult, snapshot_json: Optional[str] = None) -> Optional[SignalCandidate]:
        now = datetime.now(timezone.utc)
        if self._is_cooldown(trigger.symbol, trigger.direction, now):
            logger.info(f"Cooldown active for {trigger.symbol} {trigger.direction}, skipping")
            return None
        if self.has_active_candidate(trigger.symbol, trigger.direction):
            logger.info(f"Active candidate exists for {trigger.symbol} {trigger.direction}, dedup")
            return None

        expires_at = now + timedelta(seconds=self.settings.candidate_ttl_seconds)
        # Check unique event_key collision
        existing = self.db.query(SignalCandidate).filter(SignalCandidate.event_key == trigger.event_key).first()
        if existing:
            logger.info(f"event_key collision {trigger.event_key}")
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
        logger.info(f"Created candidate {cand.id} {cand.symbol} {cand.direction} {cand.change_pct}%")
        return cand

    def mark_processing(self, candidate: SignalCandidate):
        candidate.status = "PROCESSING"
        self.db.commit()

    def mark_approved(self, candidate: SignalCandidate):
        candidate.status = "APPROVED"
        self.db.commit()

    def mark_rejected(self, candidate: SignalCandidate, reason: str):
        candidate.status = "REJECTED"
        candidate.rejection_reason = reason
        self.db.commit()
        self.set_cooldown(candidate.symbol, candidate.direction)

    def mark_expired(self, candidate: SignalCandidate):
        if candidate.status in ("DETECTED", "PROCESSING"):
            candidate.status = "EXPIRED"
            self.db.commit()

    def expire_stale(self) -> int:
        now = datetime.now(timezone.utc)
        stale = self.db.query(SignalCandidate).filter(
            SignalCandidate.expires_at <= now,
            SignalCandidate.status.in_(["DETECTED", "PROCESSING"]),
        ).all()
        for c in stale:
            c.status = "EXPIRED"
        if stale:
            self.db.commit()
        return len(stale)

    def check_expiry(self, candidate: SignalCandidate) -> bool:
        now = datetime.now(timezone.utc)
        if candidate.expires_at <= now:
            self.mark_expired(candidate)
            return True
        return False
