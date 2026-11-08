from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Callable, List, Optional
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.threerouter_client import AIOrchestrator
from app.api.websocket import broadcast_event
from app.core.config import get_settings
from app.core.logging import redact_str
from app.db.models import (
    ACTIVE_TRADE_STATUSES,
    SETTLED_TRADE_STATUSES,
    AgentLog,
    AppConfig,
    EquitySnapshot,
    MarginScalingEvent,
    SignalCandidate,
    SystemLog,
    Trade,
    ensure_utc,
    net_realized_pnl,
)
from app.engine.state_machine import EngineStateMachine
from app.exchange.binance_adapter import BinanceAdapter
from app.exchange.interface import ExchangeAdapter
from app.exchange.mock_adapter import MockBinanceAdapter
from app.execution.execution_engine import ExecutionEngine
from app.market.candidate_lifecycle import CandidateManager
from app.market.context_builder import build_market_snapshot
from app.market.price_history import PriceHistory
from app.market.symbol_universe import SymbolUniverseService
from app.market.trigger_engine import TriggerEngine
from app.trading.gate import TradingGate
from app.market.websocket_manager import MarketDataWebSocketManager
from app.monitor.cleaner import OrderCleaner
from app.monitor.position_monitor import PositionMonitor
from app.risk.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class EngineService:
    """
    Main orchestration: STARTING -> READY -> RUNNING loop.
    - Loads symbol universe
    - Starts WS (or deterministic local mock feed when running with MockBinanceAdapter)
    - On each price, evaluates trigger using active configuration
    - On trigger, builds snapshot, runs AI (fail-closed), enforces global & per-trade risk, executes idempotently
    - Monitors positions continuously
    """

    def __init__(
        self,
        db: Session,
        adapter: ExchangeAdapter,
        session_factory: Optional[Callable[[], Session]] = None,
    ):
        self._db = db
        self._session_factory = session_factory
        self.adapter = adapter
        self.settings = get_settings()
        self.state_machine = EngineStateMachine(db, self.settings)
        self.price_history = PriceHistory(max_age_seconds=600)
        self.symbol_service = SymbolUniverseService(adapter, db)
        self.trigger_engine = TriggerEngine(self.price_history, self.settings)
        self.candidate_mgr = CandidateManager(db, self.settings)
        self.risk_engine = RiskEngine(self.settings)
        self.exec_engine = ExecutionEngine(adapter, self.risk_engine, db, self.settings)
        self.position_monitor = PositionMonitor(
            adapter,
            db,
            self.exec_engine,
            session_factory=session_factory,
        )
        self.cleaner = OrderCleaner(adapter, db)
        self.ai_orchestrator = AIOrchestrator()
        self.ws_manager = MarketDataWebSocketManager(
            self.price_history,
            self.settings,
            on_price=self.on_price,
            mock_mode=isinstance(adapter, MockBinanceAdapter),
        )
        self.running_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._tick_lock = asyncio.Lock()

        # The adapter is expected to arrive with a gate attached (see
        # app.exchange.factory). If it does not - e.g. an adapter built directly
        # in a test - attach one so behaviour is identical rather than silently
        # refusing every entry with a confusing message.
        if getattr(adapter, "gate", None) is None and hasattr(adapter, "gate"):
            is_testnet = getattr(adapter, "testnet", isinstance(adapter, MockBinanceAdapter))
            adapter.gate = TradingGate(adapter, self.settings, is_testnet=is_testnet)
        self.gate: TradingGate | None = getattr(adapter, "gate", None)

    @property
    def db(self) -> Session:
        return self._db

    @db.setter
    def db(self, session: Session) -> None:
        self._db = session
        self.state_machine.db = session
        self.symbol_service.db = session
        self.candidate_mgr.db = session
        self.exec_engine.db = session
        self.cleaner.db = session
        # The monitor keeps its own per-iteration sessions when a session factory
        # is configured; only rebind it while it is sharing this service's session.
        if self.position_monitor.session_factory is None:
            self.position_monitor.rebind(session)

    def _active_cfg(self, db: Session):
        return db.query(AppConfig).first()

    def _emit_system_log(
        self,
        db: Session,
        level: str,
        event_code: str,
        message: str,
        symbol: Optional[str] = None,
        trade_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        try:
            db.add(
                SystemLog(
                    id=str(uuid.uuid4()),
                    level=level.upper(),
                    event_code=event_code,
                    message_redacted=redact_str(message),
                    correlation_id=correlation_id,
                    trade_id=trade_id,
                    symbol=symbol,
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        except Exception as e:
            logger.warning("Failed to persist SystemLog %s: %s", event_code, e)

    def _compute_global_risk_inputs(self, db: Session, ex_open_symbols: set[str]):
        closed_trades = (
            db.query(Trade)
            .filter(Trade.status.in_(SETTLED_TRADE_STATUSES))
            .order_by(Trade.closed_at.desc())
            .all()
        )
        today = datetime.now(timezone.utc).date()
        daily_realized_pnl = Decimal("0")
        for t in closed_trades:
            closed_dt = ensure_utc(t.closed_at)
            if closed_dt and closed_dt.date() == today and t.realized_pnl is not None:
                daily_realized_pnl += net_realized_pnl(t)

        # Consecutive losses from most recent closed trade backwards
        consecutive_losses = 0
        for t in closed_trades:
            if t.realized_pnl is None:
                continue
            net = net_realized_pnl(t)
            if net <= Decimal("0"):
                consecutive_losses += 1
            else:
                break

        # Drawdown % from equity snapshots
        drawdown_pct = Decimal("0")
        latest_snap = db.query(EquitySnapshot).order_by(EquitySnapshot.captured_at.desc()).first()
        peak_snap = db.query(EquitySnapshot).order_by(EquitySnapshot.account_equity.desc()).first()
        if latest_snap and peak_snap and peak_snap.account_equity > Decimal("0") and peak_snap.account_equity > latest_snap.account_equity:
            drawdown_pct = (peak_snap.account_equity - latest_snap.account_equity) / peak_snap.account_equity * Decimal("100")

        local_open_symbols = {
            t.symbol
            for t in db.query(Trade).filter(Trade.status.in_(ACTIVE_TRADE_STATUSES)).all()
        }
        open_positions_count = len(local_open_symbols | ex_open_symbols)
        return daily_realized_pnl, drawdown_pct, consecutive_losses, open_positions_count

    async def on_price(self, symbol: str, price: Decimal, exchange_time):
        if self.state_machine.state != "RUNNING":
            return

        async with self._tick_lock:
            own_session: Session | None = None
            prev_db = self._db
            try:
                if self._session_factory is not None:
                    own_session = self._session_factory()
                    self.db = own_session
                await self._process_tick(symbol)
            finally:
                if own_session is not None:
                    own_session.close()
                    self.db = prev_db

    async def _process_tick(self, symbol: str):
        cfg = self._active_cfg(self.db)
        trig_pct = cfg.trigger_percentage if cfg else self.settings.trigger_percentage
        win_sec = cfg.trigger_window_seconds if cfg else self.settings.trigger_window_seconds
        ttl_sec = cfg.candidate_ttl_seconds if cfg else self.settings.candidate_ttl_seconds
        cd_sec = cfg.cooldown_seconds if cfg else self.settings.cooldown_seconds

        self.candidate_mgr.expire_stale()
        result = self.trigger_engine.evaluate(
            symbol,
            now_wall=datetime.now(timezone.utc),
            trigger_percentage=trig_pct,
            window_seconds=win_sec,
        )
        if not result:
            return

        cand = self.candidate_mgr.create_candidate(result, ttl_seconds=ttl_sec)
        if not cand:
            return

        corr_id = str(uuid.uuid4())
        self._emit_system_log(
            self.db,
            "INFO",
            "SIGNAL_DETECTED",
            f"Candidate {cand.symbol} {cand.direction} Δ={cand.change_pct}% (now={cand.current_price}, ref={cand.reference_price})",
            symbol=cand.symbol,
            correlation_id=corr_id,
        )
        await broadcast_event(
            "signal_detected",
            {
                "id": cand.id,
                "symbol": cand.symbol,
                "direction": cand.direction,
                "change_pct": str(cand.change_pct),
                "status": cand.status,
            },
        )

        self.candidate_mgr.mark_processing(cand)
        snapshot = await build_market_snapshot(
            cand, self.price_history, self.adapter, self.settings, db=self.db
        )
        cand.snapshot_json = json.dumps(snapshot.model_dump(mode="json"), default=str)
        self.db.commit()

        try:
            prior, final = await self.ai_orchestrator.run_full_pipeline(snapshot)
            await self._persist_ai_logs(cand, prior, final, snapshot)
            if final.decision != "YES":
                reason = f"AI final decision {final.decision}: {final.rationale}"
                self.candidate_mgr.mark_rejected(cand, reason, cooldown_seconds=cd_sec)
                self._emit_system_log(
                    self.db,
                    "WARNING",
                    "CANDIDATE_REJECTED",
                    f"{cand.symbol} {cand.direction} rejected by AI gate: {final.rationale}",
                    symbol=cand.symbol,
                    correlation_id=corr_id,
                )
                await broadcast_event(
                    "candidate_rejected",
                    {"id": cand.id, "symbol": cand.symbol, "reason": reason},
                )
                return
            self.candidate_mgr.mark_approved(cand)
        except Exception as e:
            logger.error("AI pipeline error for %s: %s", cand.id, e)
            self.candidate_mgr.mark_rejected(cand, f"AI error: {e}", cooldown_seconds=cd_sec)
            self._emit_system_log(
                self.db,
                "ERROR",
                "AI_PIPELINE_ERROR",
                f"AI pipeline error for {cand.symbol}: {e}",
                symbol=cand.symbol,
                correlation_id=corr_id,
            )
            return

        # Fetch authoritative exchange balances & positions (fail closed on error)
        try:
            balances = await self.adapter.get_balances()
            ex_positions = await self.adapter.get_positions()
        except Exception as e:
            reason = f"Account state unavailable (fail-closed): {e}"
            self.candidate_mgr.mark_rejected(cand, reason, cooldown_seconds=cd_sec)
            self._emit_system_log(self.db, "ERROR", "ACCOUNT_STATE_ERROR", reason, symbol=cand.symbol, correlation_id=corr_id)
            return

        ex_open_symbols = {p.symbol for p in ex_positions if p.position_amt != Decimal("0")}
        open_notional = sum(
            (abs(p.position_amt) * p.mark_price for p in ex_positions if p.position_amt != Decimal("0")),
            Decimal("0"),
        )
        daily_pnl, dd_pct, loss_streak, open_cnt = self._compute_global_risk_inputs(self.db, ex_open_symbols)
        ok, blocks = self.risk_engine.check_global_limits(
            daily_realized_pnl=daily_pnl,
            drawdown_pct=dd_pct,
            consecutive_losses=loss_streak,
            open_positions_count=open_cnt,
            daily_loss_limit=cfg.daily_loss_limit if cfg else None,
            max_drawdown_pct=cfg.max_drawdown_pct if cfg else None,
            max_concurrent_trades=cfg.max_concurrent_trades if cfg else None,
            max_consecutive_losses=cfg.max_consecutive_losses if cfg else None,
        )
        if not ok:
            # Hard loss/drawdown/streak limits halt engine; max concurrent trades simply blocks this candidate
            hard_halt = any("limit hit" in b.lower() or "must be > 0" in b.lower() for b in blocks)
            if hard_halt:
                self.state_machine.transition("HALTED_RISK", reason=f"Global limits: {blocks}")
                self._emit_system_log(
                    self.db, "ERROR", "ENGINE_HALTED_RISK", f"Halted on global limits: {blocks}", correlation_id=corr_id
                )
            self.candidate_mgr.mark_rejected(cand, f"Risk gate blocked: {blocks}", cooldown_seconds=cd_sec)
            return

        meta = self.symbol_service.get_cached(snapshot.symbol)
        if not meta:
            try:
                await self.symbol_service.refresh()
                meta = self.symbol_service.get_cached(snapshot.symbol)
            except Exception:
                pass
        if not meta:
            self.candidate_mgr.mark_rejected(cand, "Missing symbol metadata", cooldown_seconds=cd_sec)
            return

        allocated = await self._get_next_margin(cfg)
        direction = cand.direction
        entry_price = Decimal(str(snapshot.trigger_price_now))
        if direction == "LONG":
            sl_price = entry_price * Decimal("0.99")
            tp_price = entry_price * Decimal("1.015")
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
            balances=balances,
            open_positions_notional=open_notional,
            leverage=cfg.leverage if cfg else None,
            taker_fee_bps=cfg.taker_fee_bps if cfg else None,
            slippage_bps=cfg.max_slippage_bps if cfg else None,
            max_aggregate_exposure=cfg.max_aggregate_exposure if cfg else None,
        )
        if not plan.approved:
            self.candidate_mgr.mark_rejected(cand, f"Risk rejected: {plan.reason}", cooldown_seconds=cd_sec)
            self._emit_system_log(
                self.db,
                "WARNING",
                "RISK_REJECTED",
                f"{snapshot.symbol} {direction} rejected by risk planner: {plan.reason}",
                symbol=snapshot.symbol,
                correlation_id=corr_id,
            )
            return

        if self.candidate_mgr.check_expiry(cand):
            return

        trade = await self.exec_engine.execute_entry(cand, plan, snapshot.symbol, direction)
        if trade:
            logger.info("Executed trade %s %s %s", trade.id, snapshot.symbol, direction)
            self._emit_system_log(
                self.db,
                "INFO",
                "TRADE_EXECUTED",
                f"Trade {trade.id} {snapshot.symbol} {direction} qty={trade.position_size} status={trade.status}",
                symbol=snapshot.symbol,
                trade_id=trade.id,
                correlation_id=corr_id,
            )
            await broadcast_event(
                "trade_executed",
                {"trade_id": trade.id, "symbol": trade.symbol, "direction": trade.direction, "status": trade.status},
            )

    async def _persist_ai_logs(self, cand, prior, final, snapshot):
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
                latency_ms=res.get("latency_ms"),
                error_message=res.get("error"),
            )
            self.db.add(log)
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
            latency_ms=0,
        )
        self.db.add(log6)
        self.db.commit()

    async def _get_next_margin(self, cfg: Optional[AppConfig] = None) -> Decimal:
        base_margin = cfg.base_margin if cfg else self.settings.base_margin
        reinvest_pct = cfg.profit_reinvestment_pct if cfg else self.settings.profit_reinvestment_pct
        max_alloc = cfg.max_trade_allocation if cfg else self.settings.max_trade_allocation
        last = (
            self.db.query(Trade)
            .filter(Trade.status.in_(SETTLED_TRADE_STATUSES))
            .order_by(Trade.closed_at.desc())
            .first()
        )
        if not last or last.realized_pnl is None:
            return base_margin
        net_profit = net_realized_pnl(last)
        next_margin = self.risk_engine.calculate_next_margin(
            base_margin,
            net_profit,
            reinvest_pct=reinvest_pct,
            max_allocation=max_alloc,
        )
        existing_ev = (
            self.db.query(MarginScalingEvent)
            .filter(MarginScalingEvent.closed_trade_id == last.id)
            .first()
        )
        if not existing_ev:
            self.db.add(
                MarginScalingEvent(
                    id=str(uuid.uuid4()),
                    closed_trade_id=last.id,
                    base_margin=base_margin,
                    realized_net_profit=net_profit,
                    reinvestment_pct=reinvest_pct,
                    next_margin=next_margin,
                    created_at=datetime.now(timezone.utc),
                )
            )
            self.db.commit()
        return next_margin

    async def readiness_checks(self) -> tuple[bool, List[str]]:
        # Do not start the real-exchange engine while order execution and its
        # safety gates are unverified, even on testnet. Read-only APIs remain usable.
        if isinstance(self.adapter, BinanceAdapter):
            return False, ["Binance entries are locked pending safety verification (testnet and live)"]
        issues = []
        ok, missing = self.settings.check_hard_limits_configured()
        if not ok:
            issues.extend(missing)
        try:
            connected = await self.adapter.test_connectivity()
            if not connected:
                issues.append("Binance connectivity failed")
        except Exception as e:
            issues.append(f"Binance check error: {e}")
        try:
            valid, msg, _acct = await self.adapter.validate_credentials()
            if not valid:
                issues.append(f"Credentials invalid: {msg}")
        except Exception as e:
            issues.append(f"Credentials check error: {e}")
        try:
            self.db.execute(text("SELECT 1"))
        except Exception as e:
            issues.append(f"DB connectivity failed: {e}")
        try:
            positions = await self.adapter.get_positions()
            unknown = [p.symbol for p in positions if p.position_amt != Decimal("0")]
            db_open = {
                t.symbol
                for t in self.db.query(Trade).filter(Trade.status.in_(ACTIVE_TRADE_STATUSES)).all()
            }
            for sym in unknown:
                if sym not in db_open:
                    issues.append(f"Unknown exchange position {sym} not in local DB - must be acknowledged")
        except Exception as e:
            issues.append(f"Reconciliation check failed: {e}")

        return (len(issues) == 0, issues)

    async def start(self, actor: str = "system") -> tuple[bool, List[str]]:
        if self.state_machine.state in ("RUNNING", "STARTING"):
            return False, ["Engine already running/starting"]
        prev_state = self.state_machine.state
        if prev_state in ("ERROR", "HALTED_RISK"):
            self.state_machine.transition("STOPPED", reason="reset before start", force=True)
        self.state_machine.transition("STARTING", reason="operator start")
        ok, issues = await self.readiness_checks()
        if not ok:
            self.state_machine.transition("ERROR", reason=f"Readiness failed: {issues}")
            self.state_machine.record_audit(actor, "engine.start_failed", {"state": prev_state}, {"issues": issues})
            self._emit_system_log(self.db, "ERROR", "ENGINE_START_FAILED", f"Readiness failed: {issues}")
            return False, issues

        try:
            symbols = await self.symbol_service.refresh()
            self.ws_manager.set_symbols([s.symbol for s in symbols])
            await self.ws_manager.start()
            await self.position_monitor.capture_equity_snapshot()
            await self.position_monitor.start()
            self.state_machine.transition("READY", reason="readiness passed")
            self.state_machine.transition("RUNNING", reason="engine started")
            self.state_machine.record_audit(
                actor, "engine.start", {"state": prev_state}, {"state": "RUNNING", "symbols": len(symbols)}
            )
            self._emit_system_log(
                self.db, "INFO", "ENGINE_STARTED", f"Engine RUNNING with {len(symbols)} eligible symbols"
            )
            await broadcast_event("engine_state", {"state": "RUNNING", "symbol_coverage": len(symbols)})
            logger.info("Engine RUNNING with %d symbols", len(symbols))
            return True, []
        except Exception as e:
            logger.error("Engine start failed: %s", e)
            self.state_machine.transition("ERROR", reason=str(e))
            self._emit_system_log(self.db, "ERROR", "ENGINE_ERROR", f"Engine start exception: {e}")
            return False, [str(e)]

    async def stop(self, reason: str = "operator stop", actor: str = "system"):
        if self.state_machine.state == "STOPPED":
            return
        prev_state = self.state_machine.state
        self.state_machine.transition("STOPPING", reason=reason, force=True)
        await self.ws_manager.stop()
        # Normal Stop blocks new entries while keeping position monitor/protection active
        self.state_machine.transition("STOPPED", reason=reason, force=True)
        self.state_machine.record_audit(
            actor, "engine.stop", {"state": prev_state}, {"state": "STOPPED", "reason": reason}
        )
        self._emit_system_log(self.db, "INFO", "ENGINE_STOPPED", f"Engine stopped ({reason}); position monitor active")
        await broadcast_event("engine_state", {"state": "STOPPED", "reason": reason})
        logger.info("Engine STOPPED (normal)")

    async def shutdown(self):
        """Full process shutdown on FastAPI lifespan exit."""
        await self.ws_manager.stop()
        await self.position_monitor.stop()
        if hasattr(self.adapter, "close"):
            await self.adapter.close()
        if self.ai_orchestrator and self.ai_orchestrator.client:
            await self.ai_orchestrator.client.close()

    async def emergency_stop(self, reason: str = "emergency", actor: str = "system"):
        prev_state = self.state_machine.state
        self.state_machine.transition("EMERGENCY", reason=reason, force=True)
        await self.ws_manager.stop()
        open_trades = self.db.query(Trade).filter(Trade.status.in_(ACTIVE_TRADE_STATUSES)).all()
        for t in open_trades:
            await self.exec_engine.emergency_close(t, reason="emergency_stop")
            await self.cleaner.cleanup_after_close(t)
        self.state_machine.transition("STOPPED", reason="emergency completed", force=True)
        self.state_machine.record_audit(
            actor,
            "engine.emergency_stop",
            {"state": prev_state, "open_trades": len(open_trades)},
            {"state": "STOPPED", "reason": reason},
        )
        self._emit_system_log(
            self.db, "ERROR", "EMERGENCY_STOP", f"Emergency stop executed ({reason}); flattened {len(open_trades)} trades"
        )
        await broadcast_event("engine_state", {"state": "STOPPED", "reason": f"emergency: {reason}"})
        logger.critical("Emergency stop completed: %s", reason)

    def get_status(self) -> dict:
        open_positions = self.db.query(Trade).filter(Trade.status.in_(ACTIVE_TRADE_STATUSES)).count()
        unprotected = self.db.query(Trade).filter(Trade.status == "OPEN").count()
        cfg = self._active_cfg(self.db)
        daily_pnl, dd_pct, loss_streak, open_cnt = self._compute_global_risk_inputs(self.db, set())
        _, blocks = self.risk_engine.check_global_limits(
            daily_realized_pnl=daily_pnl,
            drawdown_pct=dd_pct,
            consecutive_losses=loss_streak,
            open_positions_count=open_cnt,
            daily_loss_limit=cfg.daily_loss_limit if cfg else None,
            max_drawdown_pct=cfg.max_drawdown_pct if cfg else None,
            max_concurrent_trades=cfg.max_concurrent_trades if cfg else None,
            max_consecutive_losses=cfg.max_consecutive_losses if cfg else None,
        )
        hist = self.state_machine.get_history(limit=1)
        return {
            "state": self.state_machine.state,
            "environment": self.settings.app_env,
            "changed_at": hist[0].changed_at if hist else None,
            "reason": hist[0].reason if hist else None,
            "open_positions": open_positions,
            "unprotected_positions": unprotected,
            "symbol_coverage": len(self.ws_manager.symbols),
            "binance_connected": bool(self.ws_manager.connected),
            "risk_blocks": blocks,
            "trading_env": self.settings.trading_env,
            "ai_gate_mode": self.settings.ai_gate_mode,
            "portfolio_margin": self.settings.portfolio_margin,
            "live_armed": self.settings.live_armed,
        }
