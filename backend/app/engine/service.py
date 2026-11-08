from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_sync_session_factory
from app.db.models import SignalCandidate, Trade
from app.exchange.interface import ExchangeAdapter
from app.market.symbol_universe import SymbolUniverseService
from app.market.price_history import PriceHistory
from app.market.websocket_manager import MarketDataWebSocketManager
from app.market.trigger_engine import TriggerEngine
from app.market.candidate_lifecycle import CandidateManager
from app.market.context_builder import build_market_snapshot
from app.ai.threerouter_client import AIOrchestrator, ThreeRouterClient
from app.ai.schemas import MarketSnapshot
from app.risk.risk_engine import RiskEngine
from app.execution.execution_engine import ExecutionEngine
from app.monitor.position_monitor import PositionMonitor
from app.monitor.cleaner import OrderCleaner
from app.engine.state_machine import EngineStateMachine

logger = logging.getLogger(__name__)

class EngineService:
    """
    Main orchestration: STARTING -> READY -> RUNNING loop.
    - Loads symbol universe
    - Starts WS
    - On each price, evaluates trigger
    - On trigger, builds snapshot, runs AI, risk, execution
    - Monitors positions continuously
    """

    def __init__(self, db: Session, adapter: ExchangeAdapter):
        self.db = db
        self.adapter = adapter
        self.settings = get_settings()
        self.state_machine = EngineStateMachine(db, self.settings)
        self.price_history = PriceHistory(max_age_seconds=600)
        self.symbol_service = SymbolUniverseService(adapter, db)
        self.trigger_engine = TriggerEngine(self.price_history, self.settings)
        self.candidate_mgr = CandidateManager(db, self.settings)
        self.risk_engine = RiskEngine(self.settings)
        self.exec_engine = ExecutionEngine(adapter, self.risk_engine, db, self.settings)
        self.position_monitor = PositionMonitor(adapter, db, self.exec_engine)
        self.cleaner = OrderCleaner(adapter, db)
        self.ai_orchestrator = AIOrchestrator()
        self.ws_manager = MarketDataWebSocketManager(self.price_history, self.settings, on_price=self.on_price)
        self.running_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def on_price(self, symbol: str, price: Decimal, exchange_time):
        # Called for every tick; we evaluate trigger
        if self.state_machine.state != "RUNNING":
            return
        result = self.trigger_engine.evaluate(symbol, now_wall=datetime.now(timezone.utc))
        if result:
            # Candidate lifecycle
            cand = self.candidate_mgr.create_candidate(result)
            if not cand:
                return
            self.candidate_mgr.mark_processing(cand)
            # Build snapshot
            snapshot = await build_market_snapshot(cand, self.price_history, self.adapter, self.settings)
            # Run AI pipeline
            try:
                prior, final = await self.ai_orchestrator.run_full_pipeline(snapshot)
                # Persist agent logs
                await self._persist_ai_logs(cand, prior, final, snapshot)
                if final.decision != "YES":
                    self.candidate_mgr.mark_rejected(cand, f"AI final decision {final.decision}: {final.rationale}")
                    return
                self.candidate_mgr.mark_approved(cand)
            except Exception as e:
                logger.error(f"AI pipeline error for {cand.id}: {e}")
                self.candidate_mgr.mark_rejected(cand, f"AI error: {e}")
                return

            # Check global risk limits before planning
            ok, blocks = self.risk_engine.check_global_limits(
                daily_realized_pnl=Decimal("0"),  # fetch from DB
                drawdown_pct=Decimal("0"),
                consecutive_losses=0,
                open_positions_count=self.db.query(Trade).filter(Trade.status.in_(["OPEN","PROTECTED"])).count(),
            )
            if not ok:
                self.state_machine.transition("HALTED_RISK", reason=f"Global limits: {blocks}")
                self.candidate_mgr.mark_rejected(cand, f"Risk halted: {blocks}")
                return

            # Plan position: use candidate price as entry reference
            # Need symbol metadata
            meta = self.symbol_service.get_cached(snapshot.symbol)
            if not meta:
                # Try refresh
                try:
                    await self.symbol_service.refresh()
                    meta = self.symbol_service.get_cached(snapshot.symbol)
                except Exception:
                    pass
            if not meta:
                self.candidate_mgr.mark_rejected(cand, "Missing symbol metadata")
                return

            # Determine allocated margin: base_margin + scaling if profitable previous trade
            allocated = await self._get_next_margin()
            # AI may propose TP/SL; for now compute deterministic: SL 1% away, TP 1.5% (RR 1.5)
            direction = cand.direction
            entry_price = Decimal(str(snapshot.trigger_price_now))
            if direction == "LONG":
                sl_price = entry_price * Decimal("0.99")  # 1% SL
                tp_price = entry_price * Decimal("1.015")  # 1.5% TP
            else:
                sl_price = entry_price * Decimal("1.01")
                tp_price = entry_price * Decimal("0.985")

            plan = self.risk_engine.plan_position(
                symbol=snapshot.symbol,
                direction=direction,
                entry_price=entry_price,
                stop_price=sl_price,
                take_profit_price=tp_price,
                symbol_meta=meta,
                allocated_margin=allocated,
            )
            if not plan.approved:
                self.candidate_mgr.mark_rejected(cand, f"Risk rejected: {plan.reason}")
                return

            # Execute
            trade = await self.exec_engine.execute_entry(cand, plan, snapshot.symbol, direction)
            if trade:
                logger.info(f"Executed trade {trade.id} {snapshot.symbol} {direction}")

    async def _persist_ai_logs(self, cand, prior, final, snapshot):
        import json, uuid
        from app.db.models import AgentLog, SystemLog
        for ag_name, res in prior.items():
            status = "VALID" if res["status"] == "success" else "INVALID"
            if res["status"] == "timeout":
                status = "TIMEOUT"
            log = AgentLog(
                id=str(uuid.uuid4()),
                candidate_id=cand.id,
                agent_name=ag_name,
                provider="threerouter",
                model_or_agent_id=ag_name,
                prompt_version="v1",
                schema_version="1.0",
                request_hash=self.ai_orchestrator.client.hash_request(snapshot, ag_name) if self.ai_orchestrator.client else ag_name,
                response_json=json.dumps(res["response"].model_dump(mode="json"), default=str) if res.get("response") else json.dumps({"error": res.get("error")}),
                validation_status=status,
                latency_ms=None,
            )
            self.db.add(log)
        # Agent6
        log6 = AgentLog(
            id=str(uuid.uuid4()),
            candidate_id=cand.id,
            agent_name="agent-6",
            provider="threerouter",
            model_or_agent_id="agent-6",
            prompt_version="v1",
            schema_version="1.0",
            response_json=json.dumps(final.model_dump(mode="json"), default=str),
            validation_status="VALID",
        )
        self.db.add(log6)
        self.db.commit()

    async def _get_next_margin(self) -> Decimal:
        # Implements margin scaling per rules.md §4.5
        # Find last closed trade
        last = self.db.query(Trade).filter(Trade.status == "CLOSED").order_by(Trade.closed_at.desc()).first()
        if not last or last.realized_pnl is None or last.realized_pnl <= Decimal("0"):
            return self.settings.base_margin
        # Winning trade: next = base + profit * reinvest%
        return self.risk_engine.calculate_next_margin(self.settings.base_margin, last.realized_pnl)

    async def readiness_checks(self) -> tuple[bool, List[str]]:
        issues = []
        # Hard limits configured
        ok, missing = self.settings.check_hard_limits_configured()
        if not ok:
            issues.extend(missing)
        # Binance connectivity
        try:
            connected = await self.adapter.test_connectivity()
            if not connected:
                issues.append("Binance connectivity failed")
        except Exception as e:
            issues.append(f"Binance check error: {e}")
        # Credentials
        try:
            valid, msg, acct = await self.adapter.validate_credentials()
            if not valid:
                issues.append(f"Credentials invalid: {msg}")
        except Exception as e:
            issues.append(f"Credentials check error: {e}")
        # DB connectivity
        try:
            self.db.execute("SELECT 1")  # type: ignore
        except Exception as e:
            issues.append(f"DB connectivity failed: {e}")
        # Unknown positions
        try:
            positions = await self.adapter.get_positions()
            unknown = [p.symbol for p in positions if p.position_amt != Decimal("0")]
            # Check against DB open trades
            db_open = {t.symbol for t in self.db.query(Trade).filter(Trade.status.in_(["OPEN","PROTECTED"])).all()}
            for sym in unknown:
                if sym not in db_open:
                    issues.append(f"Unknown exchange position {sym} not in local DB - must be acknowledged")
        except Exception as e:
            logger.warning(f"Reconciliation check warning: {e}")

        return (len(issues) == 0, issues)

    async def start(self) -> tuple[bool, List[str]]:
        if self.state_machine.state in ("RUNNING", "STARTING"):
            return False, ["Engine already running/starting"]
        self.state_machine.transition("STARTING", reason="operator start")
        ok, issues = await self.readiness_checks()
        if not ok:
            self.state_machine.transition("ERROR", reason=f"Readiness failed: {issues}")
            return False, issues

        # Load symbols
        try:
            symbols = await self.symbol_service.refresh()
            self.ws_manager.set_symbols([s.symbol for s in symbols])
            await self.ws_manager.start()
            await self.position_monitor.start()
            self.state_machine.transition("READY", reason="readiness passed")
            self.state_machine.transition("RUNNING", reason="engine started")
            logger.info(f"Engine RUNNING with {len(symbols)} symbols")
            return True, []
        except Exception as e:
            logger.error(f"Engine start failed: {e}")
            self.state_machine.transition("ERROR", reason=str(e))
            return False, [str(e)]

    async def stop(self, reason: str = "operator stop"):
        if self.state_machine.state == "STOPPED":
            return
        self.state_machine.transition("STOPPING", reason=reason)
        await self.ws_manager.stop()
        # Note: keep position monitor active per spec (normal Stop keeps protection)
        # We don't stop monitor on normal stop; only on full shutdown we could.
        self.state_machine.transition("STOPPED", reason=reason)
        logger.info("Engine STOPPED (normal)")

    async def emergency_stop(self, reason: str = "emergency"):
        self.state_machine.transition("EMERGENCY", reason=reason, force=True)
        await self.ws_manager.stop()
        # Flatten open positions
        open_trades = self.db.query(Trade).filter(Trade.status.in_(["OPEN","PROTECTED"])).all()
        for t in open_trades:
            await self.exec_engine.emergency_close(t, reason="emergency_stop")
            await self.cleaner.cleanup_after_close(t)
        self.state_machine.transition("STOPPED", reason="emergency completed")
        logger.critical(f"Emergency stop completed: {reason}")

    def get_status(self) -> dict:
        open_positions = self.db.query(Trade).filter(Trade.status.in_(["OPEN","PROTECTED"])).count()
        # Check binance connected via last WS? Simplify
        return {
            "state": self.state_machine.state,
            "environment": self.settings.app_env,
            "changed_at": self.state_machine.get_history(limit=1)[0].changed_at if self.state_machine.get_history(limit=1) else None,
            "reason": self.state_machine.get_history(limit=1)[0].reason if self.state_machine.get_history(limit=1) else None,
            "open_positions": open_positions,
            "symbol_coverage": len(self.ws_manager.symbols),
        }
