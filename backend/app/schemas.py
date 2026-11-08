from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ---------- Common ----------

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, Any]
    timestamp: datetime


# ---------- Config ----------

class ConfigResponse(BaseModel):
    environment: str
    trigger_percentage: str
    trigger_window_seconds: int
    base_margin: str
    leverage: int
    max_concurrent_trades: int
    profit_reinvestment_pct: str
    max_trade_allocation: str
    daily_loss_limit: str
    max_drawdown_pct: str
    max_aggregate_exposure: str
    max_consecutive_losses: int = 5
    max_slippage_bps: str
    taker_fee_bps: str
    candidate_ttl_seconds: int
    cooldown_seconds: int
    protection_deadline_seconds: int
    binance_testnet: bool
    binance_configured: bool
    threerouter_configured: bool


class ConfigUpdateRequest(BaseModel):
    trigger_percentage: Optional[Decimal] = None
    trigger_window_seconds: Optional[int] = None
    base_margin: Optional[Decimal] = None
    leverage: Optional[int] = None
    max_concurrent_trades: Optional[int] = None
    profit_reinvestment_pct: Optional[Decimal] = None
    max_trade_allocation: Optional[Decimal] = None
    daily_loss_limit: Optional[Decimal] = None
    max_drawdown_pct: Optional[Decimal] = None
    max_aggregate_exposure: Optional[Decimal] = None
    max_consecutive_losses: Optional[int] = None
    max_slippage_bps: Optional[Decimal] = None
    taker_fee_bps: Optional[Decimal] = None
    candidate_ttl_seconds: Optional[int] = None
    cooldown_seconds: Optional[int] = None
    protection_deadline_seconds: Optional[int] = None


# ---------- Credentials ----------

class CredentialTestRequest(BaseModel):
    exchange: str = Field(default="binance")
    api_key: str
    api_secret: str
    testnet: bool = True


class CredentialTestResponse(BaseModel):
    valid: bool
    account_info: Optional[dict] = None
    message: str


class CredentialsSaveRequest(BaseModel):
    exchange: str = "binance"
    environment: str = "testnet"
    api_key: str
    api_secret: str


# ---------- Engine ----------

class EngineStatusResponse(BaseModel):
    state: str
    environment: str
    changed_at: Optional[datetime] = None
    reason: Optional[str] = None
    risk_blocks: list[str] = Field(default_factory=list)
    binance_connected: bool = False
    ai_connected: bool = False
    db_connected: bool = True
    symbol_coverage: int = 0
    open_positions: int = 0
    unprotected_positions: int = 0


class EngineActionRequest(BaseModel):
    confirm: bool = False
    reason: Optional[str] = None


# ---------- Market ----------

class SymbolInfo(BaseModel):
    symbol: str
    status: str
    contract_type: str
    margin_asset: str
    price_tick: str
    qty_step: str
    min_qty: str
    min_notional: str
    is_eligible: bool
    ineligibility_reason: Optional[str] = None
    last_price: Optional[str] = None
    change_pct_180s: Optional[str] = None


# ---------- Signals ----------

class SignalCandidateResponse(BaseModel):
    id: str
    event_key: str
    symbol: str
    direction: str
    current_price: str
    reference_price: str
    change_pct: str
    window_seconds: int
    detected_at: datetime
    exchange_event_time: Optional[datetime] = None
    expires_at: datetime
    status: str
    rejection_reason: Optional[str] = None


# ---------- AI ----------

class AIAgentResponseBase(BaseModel):
    agent_name: str
    schema_version: str = "1.0"
    symbol: str
    direction: str
    decision: Literal["YES", "NO", "INSUFFICIENT_DATA"]
    confidence: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    invalidation_conditions: Optional[str] = None
    created_at: datetime

    @field_validator("confidence")
    @classmethod
    def _check_conf(cls, v):
        if v is not None and not (0 <= v <= 1):
            raise ValueError("confidence must be 0-1")
        return v


class Agent6Response(BaseModel):
    agent_name: str = "agent-6"
    schema_version: str = "1.0"
    symbol: str
    direction: str
    decision: Literal["YES", "NO"]
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    invalidation_conditions: Optional[str] = None
    created_at: datetime
    aggregated_from: list[str] = Field(default_factory=list)


# ---------- Risk ----------

class RiskApproval(BaseModel):
    approved: bool
    reason: Optional[str] = None
    quantity: Optional[str] = None
    notional: Optional[str] = None
    gross_loss: Optional[str] = None
    modeled_loss: Optional[str] = None
    allocated_margin: str
    take_profit: Optional[str] = None
    stop_loss: Optional[str] = None


# ---------- Trades ----------

class TradeResponse(BaseModel):
    id: str
    candidate_id: Optional[str] = None
    symbol: str
    side: str
    direction: str
    entry_order_client_id: str
    entry_order_id: Optional[str] = None
    entry_price: Optional[str] = None
    exit_price: Optional[str] = None
    position_size: Optional[str] = None
    notional: Optional[str] = None
    margin_allocation: str
    leverage: int
    take_profit: Optional[str] = None
    stop_loss: Optional[str] = None
    modeled_max_loss: Optional[str] = None
    realized_pnl: Optional[str] = None
    fees: Optional[str] = None
    status: str
    close_reason: Optional[str] = None
    created_at: datetime
    closed_at: Optional[datetime] = None


class OrderResponse(BaseModel):
    id: str
    trade_id: Optional[str] = None
    client_order_id: str
    exchange_order_id: Optional[str] = None
    symbol: str
    order_type: str
    side: str
    reduce_only: bool
    quantity: str
    price: Optional[str] = None
    trigger_price: Optional[str] = None
    status: str
    submitted_at: datetime
    updated_at: datetime


# ---------- Logs ----------

class SystemLogResponse(BaseModel):
    id: str
    level: str
    event_code: str
    message_redacted: str
    correlation_id: Optional[str] = None
    trade_id: Optional[str] = None
    symbol: Optional[str] = None
    created_at: datetime


class AgentLogResponse(BaseModel):
    id: str
    candidate_id: Optional[str] = None
    agent_name: str
    provider: str
    model_or_agent_id: Optional[str] = None
    prompt_version: Optional[str] = None
    schema_version: str
    response_json: Optional[str] = None
    validation_status: str
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime


# ---------- Metrics ----------

class MetricsResponse(BaseModel):
    starting_balance: str
    current_equity: str
    realized_pnl: str
    unrealized_pnl: str
    win_rate: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    open_positions: int
    max_concurrent: int
    current_drawdown: str
    daily_pnl: str


# ---------- Auth ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- WebSocket ----------

class WSEvent(BaseModel):
    type: str
    payload: dict
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
