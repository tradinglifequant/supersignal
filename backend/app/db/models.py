from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def uuid_str() -> str:
    return str(uuid.uuid4())


# Trade statuses that represent live or in-flight exposure.
#
# Every place that asks "how many positions are open?" must use this one tuple.
# Previously the concurrency gate, the engine status endpoint, the position
# monitor, the duplicate-entry guard and the /api/positions endpoint each kept
# their own list, so a PENDING or CLOSING trade could occupy exposure while being
# invisible to the operator and to the status endpoint.
ACTIVE_TRADE_STATUSES: tuple[str, ...] = ("PENDING", "OPEN", "PROTECTED", "CLOSING")

# Terminal statuses whose realized P&L counts toward daily loss / win-rate maths.
SETTLED_TRADE_STATUSES: tuple[str, ...] = ("CLOSED", "EMERGENCY_CLOSED")


def net_realized_pnl(trade: "Trade") -> Decimal:
    """Realized P&L after fees and funding. Single source of truth for win/loss maths."""
    if trade.realized_pnl is None:
        return Decimal("0")
    return trade.realized_pnl - (trade.fees or Decimal("0")) - (trade.funding or Decimal("0"))


class UTCDateTime(TypeDecorator):
    """Ensures timezone-aware UTC datetimes round-trip consistently on both SQLite and PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return ensure_utc(value)

    def process_result_value(self, value, dialect):
        return ensure_utc(value)


class AppConfig(Base):
    __tablename__ = "app_config"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    environment: Mapped[str] = mapped_column(String(20), default="development")
    trigger_percentage: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("1.5"))
    trigger_window_seconds: Mapped[int] = mapped_column(Integer, default=180)
    base_margin: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("3"))
    leverage: Mapped[int] = mapped_column(Integer, default=10)
    max_concurrent_trades: Mapped[int] = mapped_column(Integer, default=3)
    profit_reinvestment_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("25"))
    max_trade_allocation: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("100"))
    daily_loss_limit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("50"))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("10"))
    max_aggregate_exposure: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1000"))
    max_consecutive_losses: Mapped[int] = mapped_column(Integer, default=5)
    max_slippage_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("50"))
    taker_fee_bps: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("4"))
    candidate_ttl_seconds: Mapped[int] = mapped_column(Integer, default=30)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300)
    protection_deadline_seconds: Mapped[int] = mapped_column(Integer, default=10)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ExchangeCredential(Base):
    __tablename__ = "exchange_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    environment: Mapped[str] = mapped_column(String(20), default="testnet")
    api_key_ciphertext: Mapped[str] = mapped_column(Text)
    api_secret_ciphertext: Mapped[str] = mapped_column(Text)
    encryption_key_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class SignalCandidate(Base):
    __tablename__ = "signal_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    event_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    current_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reference_price: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    change_pct: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    window_seconds: Mapped[int] = mapped_column(Integer, default=180)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    exchange_event_time: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(30), default="DETECTED", index=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    trades: Mapped[list["Trade"]] = relationship(back_populates="candidate")


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signal_candidates.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    direction: Mapped[str] = mapped_column(String(10))
    entry_order_client_id: Mapped[str] = mapped_column(String(64), unique=True)
    entry_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    position_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    notional: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    margin_allocation: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    leverage: Mapped[int] = mapped_column(Integer)
    take_profit: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    modeled_max_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    realized_pnl: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    fees: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True, default=Decimal("0"))
    funding: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True, default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    close_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)

    candidate: Mapped[Optional[SignalCandidate]] = relationship(back_populates="trades")
    orders: Mapped[list["Order"]] = relationship(back_populates="trade", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    trade_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("trades.id"), nullable=True, index=True)
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20))
    order_type: Mapped[str] = mapped_column(String(30))
    side: Mapped[str] = mapped_column(String(10))
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    trigger_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="NEW")
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    trade: Mapped[Optional[Trade]] = relationship(back_populates="orders")


class AgentLog(Base):
    __tablename__ = "agent_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signal_candidates.id"), nullable=True, index=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(50), default="threerouter")
    model_or_agent_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    request_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    response_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    level: Mapped[str] = mapped_column(String(20))
    event_code: Mapped[str] = mapped_column(String(50), index=True)
    message_redacted: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    trade_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class EngineStateRecord(Base):
    __tablename__ = "engine_state"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    state: Mapped[str] = mapped_column(String(30), index=True)
    environment: Mapped[str] = mapped_column(String(20), default="testnet")
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), index=True)
    before_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    account_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    available_balance: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class MarginScalingEvent(Base):
    __tablename__ = "margin_scaling_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    closed_trade_id: Mapped[str] = mapped_column(String(36), ForeignKey("trades.id"))
    base_margin: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    realized_net_profit: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    reinvestment_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    next_margin: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SymbolMetadata(Base):
    __tablename__ = "symbol_metadata"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20))
    contract_type: Mapped[str] = mapped_column(String(30))
    margin_asset: Mapped[str] = mapped_column(String(20))
    price_precision: Mapped[int] = mapped_column(Integer)
    quantity_precision: Mapped[int] = mapped_column(Integer)
    price_tick: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    qty_step: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    min_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    min_notional: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    max_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    is_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    ineligibility_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# Indexes
Index("ix_trades_status_created", Trade.status, Trade.created_at)
Index("ix_trades_symbol_created", Trade.symbol, Trade.created_at)
Index("ix_agent_logs_candidate", AgentLog.candidate_id, AgentLog.created_at)
