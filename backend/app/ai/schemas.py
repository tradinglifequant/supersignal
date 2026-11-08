from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator

Decision = Literal["YES", "NO", "INSUFFICIENT_DATA"]
FinalDecision = Literal["YES", "NO"]

class MarketSnapshot(BaseModel):
    snapshot_id: str
    symbol: str
    direction: str  # LONG/SHORT
    trigger_price_now: str
    trigger_price_ref: str
    trigger_change_pct: str
    window_seconds: int
    detected_at: datetime
    exchange_event_time: datetime
    # context
    last_price: str
    symbol_status: Optional[str] = None
    price_precision: Optional[int] = None
    qty_precision: Optional[int] = None
    # candles etc.
    candles_1m: Optional[List[dict]] = None
    volume_24h: Optional[str] = None
    funding_rate: Optional[str] = None
    open_interest: Optional[str] = None
    orderbook_snapshot: Optional[dict] = None  # bids/asks
    recent_trades: Optional[List[dict]] = None
    # data quality
    missing_data: List[str] = Field(default_factory=list)
    data_freshness_seconds: Optional[float] = None
    provenance: dict = Field(default_factory=dict)  # source timestamps

class AgentRequest(BaseModel):
    agent_name: str
    schema_version: str = "1.0"
    snapshot: MarketSnapshot
    prompt_version: str = "v1"
    timeout_seconds: int = 15

class AgentResponse(BaseModel):
    agent_name: str
    schema_version: str
    symbol: str
    direction: str
    decision: Decision
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    invalidation_conditions: Optional[str] = None
    created_at: datetime
    provider_metadata: Optional[dict] = None

    @field_validator("agent_name")
    @classmethod
    def _name_valid(cls, v):
        allowed = {"agent-1", "agent-2", "agent-3", "agent-4", "agent-5", "agent-6", "opportunity", "structure", "smart_money", "order_flow", "footprint"}
        # allow any but warn; we normalize
        return v.lower()

class Agent6Request(BaseModel):
    agent_name: str = "agent-6"
    schema_version: str = "1.0"
    snapshot: MarketSnapshot
    agent_1_result: Optional[AgentResponse] = None
    agent_2_result: Optional[AgentResponse] = None
    agent_3_result: Optional[AgentResponse] = None
    agent_4_result: Optional[AgentResponse] = None
    agent_5_result: Optional[AgentResponse] = None
    prompt_version: str = "v1"

class Agent6ResponseSchema(BaseModel):
    agent_name: str = "agent-6"
    schema_version: str = "1.0"
    symbol: str
    direction: str
    decision: FinalDecision
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    rationale: Optional[str] = None
    invalidation_conditions: Optional[str] = None
    created_at: datetime
    aggregated_from: List[str] = Field(default_factory=list)
    evidence_summary: Optional[str] = None

# ThreeRouter provider-agnostic wrapper
class ThreeRouterPayload(BaseModel):
    # Generic - provider may expect different fields; we keep configurable
    model: Optional[str] = None
    agent_id: Optional[str] = None
    messages: List[dict]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    response_format: Optional[dict] = None  # json_schema
