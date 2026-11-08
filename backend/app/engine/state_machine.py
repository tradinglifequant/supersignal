from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging

from sqlalchemy.orm import Session
from app.db.models import EngineStateRecord
from app.core.config import Settings

logger = logging.getLogger(__name__)

# States per rules.md §7
STATES = ["STOPPED", "STARTING", "READY", "RUNNING", "STOPPING", "DEGRADED", "HALTED_RISK", "EMERGENCY", "ERROR"]

TRANSITIONS = {
    "STOPPED": ["STARTING"],
    "STARTING": ["READY", "ERROR", "HALTED_RISK"],
    "READY": ["RUNNING", "ERROR", "STOPPED"],
    "RUNNING": ["STOPPING", "HALTED_RISK", "EMERGENCY", "DEGRADED", "ERROR"],
    "STOPPING": ["STOPPED"],
    "DEGRADED": ["RUNNING", "HALTED_RISK", "EMERGENCY", "STOPPING", "ERROR"],
    "HALTED_RISK": ["STOPPED", "STARTING", "ERROR"],
    "EMERGENCY": ["STOPPED", "HALTED_RISK", "ERROR"],
    "ERROR": ["STOPPED", "STARTING"],
}

class EngineStateMachine:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self._current: Optional[str] = None
        self._load()

    def _load(self):
        last = self.db.query(EngineStateRecord).order_by(EngineStateRecord.changed_at.desc()).first()
        if last:
            self._current = last.state
        else:
            self._current = "STOPPED"
            rec = EngineStateRecord(state="STOPPED", environment=self.settings.app_env, changed_at=datetime.now(timezone.utc), reason="init")
            self.db.add(rec)
            self.db.commit()

    @property
    def state(self) -> str:
        return self._current or "STOPPED"

    def can_transition(self, to_state: str) -> bool:
        if self._current is None:
            return True
        allowed = TRANSITIONS.get(self._current, [])
        return to_state in allowed

    def transition(self, to_state: str, reason: Optional[str] = None, force: bool = False) -> bool:
        if to_state not in STATES:
            raise ValueError(f"Invalid state {to_state}")
        if not force and not self.can_transition(to_state):
            logger.warning(f"Illegal transition {self._current} -> {to_state} reason={reason}")
            return False
        prev = self._current
        self._current = to_state
        rec = EngineStateRecord(state=to_state, environment=self.settings.app_env, changed_at=datetime.now(timezone.utc), reason=reason)
        self.db.add(rec)
        self.db.commit()
        logger.info(f"Engine state {prev} -> {to_state} reason={reason}")
        return True

    def get_history(self, limit: int = 20):
        return self.db.query(EngineStateRecord).order_by(EngineStateRecord.changed_at.desc()).limit(limit).all()

    def require_running(self) -> bool:
        return self.state == "RUNNING"

    def is_halted(self) -> bool:
        return self.state in ("HALTED_RISK", "EMERGENCY", "ERROR", "DEGRADED")

    def record_audit(self, actor: str, action: str, before: dict | None = None, after: dict | None = None):
        import json, uuid
        from app.db.models import AuditEvent
        ev = AuditEvent(id=str(uuid.uuid4()), actor=actor, action=action, before_json=json.dumps(before) if before else None, after_json=json.dumps(after) if after else None, correlation_id=str(uuid.uuid4()))
        self.db.add(ev)
        self.db.commit()
