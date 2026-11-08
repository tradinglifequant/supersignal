"""
AI pipeline tests - FR-03 acceptance: parallel invocation, timeouts, malformed, missing data, Agent6 rejection.
"""
import pytest
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

from app.ai.schemas import MarketSnapshot
from app.ai.threerouter_client import AIOrchestrator, ThreeRouterClient, AgentResponse
from app.core.config import Settings

def make_snapshot(symbol="BTCUSDT", direction="LONG"):
    now = datetime.now(timezone.utc)
    return MarketSnapshot(
        snapshot_id="test-snap",
        symbol=symbol,
        direction=direction,
        trigger_price_now="65000",
        trigger_price_ref="64000",
        trigger_change_pct="1.56",
        window_seconds=180,
        detected_at=now,
        exchange_event_time=now,
        last_price="65000",
        missing_data=[],
    )

class MockSuccessClient(ThreeRouterClient):
    def __init__(self, decisions=None):
        # Avoid init real settings - set api_key empty to force deterministic fallback for Agent6
        self.api_key = ""
        self.base_url = "https://mock"
        self.timeout = 2
        self.max_concurrency = 5
        self._semaphore = asyncio.Semaphore(5)
        self.decisions = decisions or {}

    async def call_agent(self, agent_name, snapshot, prompt_version="v1"):
        await asyncio.sleep(0.01)
        decision = self.decisions.get(agent_name, "YES")
        if decision == "TIMEOUT":
            await asyncio.sleep(10)
            raise asyncio.TimeoutError()
        return AgentResponse(
            agent_name=agent_name,
            schema_version="1.0",
            symbol=snapshot.symbol,
            direction=snapshot.direction,
            decision=decision,  # type: ignore
            confidence=0.9,
            evidence=["mock evidence"],
            missing_data=[],
            rationale="mock",
            created_at=datetime.now(timezone.utc),
        )
    async def _post(self, path, payload):
        return {"choices": [{"message": {"content": '{"decision":"YES"}'}}]}

class MockMissingClient(ThreeRouterClient):
    def __init__(self):
        self.api_key = ""
        self.base_url = "https://mock"
        self.timeout = 1
        self.max_concurrency = 5
        self._semaphore = asyncio.Semaphore(5)
    async def call_agent(self, agent_name, snapshot, prompt_version="v1"):
        if agent_name == "agent-5":
            # Return INSUFFICIENT_DATA
            return AgentResponse(
                agent_name=agent_name, schema_version="1.0", symbol=snapshot.symbol, direction=snapshot.direction,
                decision="INSUFFICIENT_DATA", confidence=0.0, evidence=[], missing_data=["footprint"], rationale="No footprint feed", created_at=datetime.now(timezone.utc)
            )
        return AgentResponse(
            agent_name=agent_name, schema_version="1.0", symbol=snapshot.symbol, direction=snapshot.direction,
            decision="YES", confidence=0.9, evidence=["ok"], missing_data=[], rationale="ok", created_at=datetime.now(timezone.utc)
        )
    async def _post(self, *a, **kw):
        # Return minimal valid Agent6 JSON for fallback if somehow called
        return {"choices": [{"message": {"content": '{"decision":"YES","symbol":"BTCUSDT","direction":"LONG","rationale":"mock","created_at":"2026-01-01T00:00:00+00:00"}'}}]}

@pytest.mark.asyncio
async def test_parallel_invocation_timing():
    snap = make_snapshot()
    client = MockSuccessClient()
    orch = AIOrchestrator(client)
    import time
    start = time.monotonic()
    prior, final = await orch.run_full_pipeline(snap)
    elapsed = time.monotonic() - start
    # Parallel 5 agents each 0.01s should take ~0.01-0.05, not 0.05*5 sequential
    assert elapsed < 0.2
    assert len(prior) == 5
    assert final.decision == "YES"

@pytest.mark.asyncio
async def test_agent_timeout_causes_final_no():
    snap = make_snapshot()
    client = MockSuccessClient(decisions={"agent-2": "TIMEOUT", "agent-1": "YES", "agent-3": "YES", "agent-4": "YES", "agent-5": "YES"})
    # Need to override timeout handling: orchestrator's run_agents_1_to_5 catches timeout
    orch = AIOrchestrator(client)
    # With mock TIMEOUT, agent-2 will timeout => final NO
    prior, final = await orch.run_full_pipeline(snap)
    assert prior["agent-2"]["status"] == "error" or "timeout" in str(prior["agent-2"].get("error","")).lower() or prior["agent-2"]["status"] in ("timeout","error")
    assert final.decision == "NO"

@pytest.mark.asyncio
async def test_missing_footprint_fails_closed():
    snap = make_snapshot()
    client = MockMissingClient()
    orch = AIOrchestrator(client)
    prior, final = await orch.run_full_pipeline(snap)
    assert prior["agent-5"]["response"].decision == "INSUFFICIENT_DATA"
    assert final.decision == "NO"

@pytest.mark.asyncio
async def test_contradictory_agents_final_no():
    # Agent1 YES, Agent2 NO => fallback deterministic => NO (conservative)
    snap = make_snapshot()
    client = MockSuccessClient(decisions={"agent-1": "YES", "agent-2": "NO", "agent-3": "YES", "agent-4": "YES", "agent-5": "YES"})
    orch = AIOrchestrator(client)
    prior, final = await orch.run_full_pipeline(snap)
    # Agent6 fallback will see NO and return NO
    assert final.decision == "NO"

@pytest.mark.asyncio
async def test_invalid_json_handled():
    class BadClient(ThreeRouterClient):
        def __init__(self):
            self.api_key = ""
            self.base_url = "https://mock"
            self.timeout = 1
            self.max_concurrency = 5
            self._semaphore = asyncio.Semaphore(5)
        async def call_agent(self, agent_name, snapshot, prompt_version="v1"):
            # Simulate malformed response via ValidationError
            raise ValueError("Invalid JSON")
        async def _post(self, *a, **kw):
            return {}
    snap = make_snapshot()
    orch = AIOrchestrator(BadClient())  # type: ignore
    prior, final = await orch.run_full_pipeline(snap)
    assert final.decision == "NO"

@pytest.mark.asyncio
async def test_agent6_requires_all_mandatory():
    snap = make_snapshot()
    # All YES => YES
    client = MockSuccessClient()
    orch = AIOrchestrator(client)
    prior, final = await orch.run_full_pipeline(snap)
    assert final.decision == "YES"
    # Now one INSUFFICIENT_DATA => NO even though others YES
    client2 = MockMissingClient()
    orch2 = AIOrchestrator(client2)
    prior2, final2 = await orch2.run_full_pipeline(snap)
    assert final2.decision == "NO"
