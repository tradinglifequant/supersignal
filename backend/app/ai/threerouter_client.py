from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import httpx
from pydantic import ValidationError

from app.ai.deterministic_gate import DeterministicGate
from app.ai.schemas import Agent6ResponseSchema, AgentRequest, AgentResponse, MarketSnapshot
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ThreeRouterClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.threerouter_api_key
        self.base_url = (base_url or settings.threerouter_base_url).rstrip("/")
        self.timeout = timeout or settings.threerouter_timeout_seconds
        self.max_concurrency = settings.threerouter_max_concurrency
        self._missing_key_logged = False
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self.client = httpx.AsyncClient(timeout=self.timeout + 5)

    class MissingKeyError(ValueError):
        """
        THREEROUTER_API_KEY is unset. A configuration state, not an agent fault.
        Subclasses ValueError on purpose: the handler in call_agent catches
        (JSONDecodeError, ValidationError, ValueError), and a RuntimeError would
        escape it and surface unhandled instead of failing closed.
        """

    async def _post(self, path: str, payload: dict) -> dict:
        if not self.api_key:
            raise ThreeRouterClient.MissingKeyError("ThreeRouter API key not configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        resp = await self.client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            logger.error("ThreeRouter error %s %s: %s", resp.status_code, path, body)
            raise httpx.HTTPStatusError(f"ThreeRouter {resp.status_code}", request=resp.request, response=resp)
        return resp.json()

    async def call_agent(self, agent_name: str, snapshot: MarketSnapshot, prompt_version: str = "v1") -> AgentResponse:
        """
        Calls a single AI agent. Provider output is treated as untrusted input and schema-validated.
        """
        async with self._semaphore:
            start = time.monotonic()
            request = AgentRequest(
                agent_name=agent_name,
                snapshot=snapshot,
                prompt_version=prompt_version,
                timeout_seconds=self.timeout,
            )
            system_prompt = self._get_system_prompt(agent_name, prompt_version)
            user_content = json.dumps(request.model_dump(mode="json"), default=str)

            payload = {
                "model": self._get_model_for_agent(agent_name),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            path = "/v1/chat/completions"
            try:
                raw = await asyncio.wait_for(self._post(path, payload), timeout=self.timeout)
                latency_ms = int((time.monotonic() - start) * 1000)
                content = self._extract_content(raw)
                parsed = json.loads(content)
                agent_resp = AgentResponse.model_validate(parsed)
                if agent_resp.symbol.upper() != snapshot.symbol.upper():
                    raise ValueError(
                        f"Agent symbol mismatch: expected {snapshot.symbol}, got {agent_resp.symbol}"
                    )
                if agent_resp.direction.upper() != snapshot.direction.upper():
                    raise ValueError(
                        f"Agent direction mismatch: expected {snapshot.direction}, got {agent_resp.direction}"
                    )
                logger.info("Agent %s decision=%s latency=%dms", agent_name, agent_resp.decision, latency_ms)
                return agent_resp
            except asyncio.TimeoutError:
                logger.warning("Agent %s timeout", agent_name)
                raise
            except (json.JSONDecodeError, ValidationError, ValueError) as e:
                if isinstance(e, ThreeRouterClient.MissingKeyError):
                    # One warning per process, not five ERRORs per candidate.
                    if not self._missing_key_logged:
                        self._missing_key_logged = True
                        logger.warning(
                            "THREEROUTER_API_KEY is not configured; the LLM gate will "
                            "fail closed. Set it, or set AI_GATE_MODE=deterministic."
                        )
                else:
                    logger.error("Agent %s invalid response: %s", agent_name, e)
                raise ValueError(f"Invalid agent response: {e}") from e

    def _extract_content(self, raw: dict) -> str:
        if "choices" in raw:
            return raw["choices"][0]["message"]["content"]
        if "content" in raw:
            return raw["content"]
        if "response" in raw:
            r = raw["response"]
            if isinstance(r, dict):
                return json.dumps(r)
            return str(r)
        return json.dumps(raw)

    def _get_system_prompt(self, agent_name: str, prompt_version: str) -> str:
        prompts = {
            "agent-1": "You are Agent 1 - Opportunity Validation for Super Signal. Verify trigger plausibility, liquidity, spread, volatility. Return JSON matching AgentResponse schema with decision YES/NO/INSUFFICIENT_DATA, confidence 0-1, evidence, missing_data, rationale, invalidation_conditions. Never fabricate data; if unavailable list in missing_data.",
            "agent-2": "You are Agent 2 - Market Structure & Trend. Evaluate trend, support/resistance, invalidation. Return JSON per schema. Distinguish calculated vs observed levels.",
            "agent-3": "You are Agent 3 - Smart Money / Volume Analysis. Evaluate volume, open interest, funding, liquidation proxies. State sources available. Never invent whale activity.",
            "agent-4": "You are Agent 4 - Order Flow. Analyze trade aggressor flow, order book imbalance, spread, depth. Include snapshot age and depth limitations. Reject if feed stale.",
            "agent-5": "You are Agent 5 - Footprint / Volume-at-Price. Analyze only supported footprint data. If Binance/footprint unavailable return INSUFFICIENT_DATA. Do not invent bid/ask volume at price.",
            "agent-6": "You are Agent 6 - Final Confirmation. Receive 5 agent outputs + snapshot; return YES only if all mandatory agents valid and no hard rejection; INSUFFICIENT_DATA from mandatory means NO. Return strict YES/NO, confidence, rationale, invalidation_conditions.",
        }
        return prompts.get(agent_name.lower(), "You are a Super Signal trading analyst. Return JSON per AgentResponse schema.")

    def _get_model_for_agent(self, agent_name: str) -> str:
        return "threerouter-default"

    async def close(self):
        if hasattr(self, "client") and self.client is not None:
            await self.client.aclose()

    def hash_request(self, snapshot: MarketSnapshot, agent_name: str) -> str:
        h = hashlib.sha256(
            json.dumps(snapshot.model_dump(mode="json"), default=str, sort_keys=True).encode()
        ).hexdigest()
        return f"{agent_name}:{h[:16]}"


class AIOrchestrator:
    """
    Runs Agents 1-5 concurrently, then Agent 6.
    Fail-closed: timeout, invalid schema, missing mandatory, or any mandatory NO => final NO.
    """

    def __init__(self, client: ThreeRouterClient | None = None):
        self.client = client or ThreeRouterClient()
        self.settings = get_settings()
        self.deterministic = DeterministicGate(self.settings)
        self._missing_key_warned = False

    async def run_agents_1_to_5(self, snapshot: MarketSnapshot) -> Dict[str, Any]:
        agents = ["agent-1", "agent-2", "agent-3", "agent-4", "agent-5"]
        tasks = {ag: asyncio.create_task(self._timed_agent_call(ag, snapshot)) for ag in agents}
        results: Dict[str, Any] = {}
        for ag, task in tasks.items():
            results[ag] = await task
        return results

    async def _timed_agent_call(self, agent_name: str, snapshot: MarketSnapshot) -> Dict[str, Any]:
        start = time.monotonic()
        try:
            resp = await self._run_with_timeout(agent_name, snapshot)
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"status": "success", "response": resp, "latency_ms": latency_ms}
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"status": "timeout", "error": "timeout", "response": None, "latency_ms": latency_ms}
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"status": "error", "error": str(e), "response": None, "latency_ms": latency_ms}

    async def _run_with_timeout(self, agent_name: str, snapshot: MarketSnapshot) -> AgentResponse:
        timeout = self.client.timeout
        try:
            return await asyncio.wait_for(self.client.call_agent(agent_name, snapshot), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("%s timed out after %ss", agent_name, timeout)
            raise

    async def run_agent_6(self, snapshot: MarketSnapshot, prior_results: Dict[str, Any]) -> Agent6ResponseSchema:
        failure_reasons: list[str] = []
        for ag in ["agent-1", "agent-2", "agent-3", "agent-4", "agent-5"]:
            r = prior_results.get(ag)
            if not r or r["status"] != "success" or r["response"] is None:
                failure_reasons.append(f"{ag}:{r['status'] if r else 'missing'}")
                continue
            resp: AgentResponse = r["response"]
            if resp.decision == "INSUFFICIENT_DATA":
                failure_reasons.append(f"{ag}:INSUFFICIENT_DATA")
            elif resp.decision == "NO":
                failure_reasons.append(f"{ag}:NO")

        if failure_reasons:
            logger.info("Agent6 deterministic fail-closed NO due to %s", failure_reasons)
            return Agent6ResponseSchema(
                agent_name="agent-6",
                schema_version="1.0",
                symbol=snapshot.symbol,
                direction=snapshot.direction,
                decision="NO",
                confidence=0.0,
                rationale=f"Fail-closed: mandatory agent rejection or incomplete evidence ({', '.join(failure_reasons)})",
                invalidation_conditions="Await complete affirmative evidence from all mandatory agents",
                created_at=datetime.now(timezone.utc),
                aggregated_from=list(prior_results.keys()),
                evidence_summary="Deterministic fail-closed rejection",
            )

        try:
            if not self.client.api_key:
                return self._deterministic_agent6(snapshot, prior_results)

            prior_json = {
                k: (v["response"].model_dump(mode="json") if v["response"] else None)
                for k, v in prior_results.items()
            }
            system_prompt = self.client._get_system_prompt("agent-6", "v1")
            user_content = json.dumps(
                {"snapshot": snapshot.model_dump(mode="json"), "prior_results": prior_json},
                default=str,
            )

            payload = {
                "model": self.client._get_model_for_agent("agent-6"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            }
            raw = await asyncio.wait_for(self.client._post("/v1/chat/completions", payload), timeout=self.client.timeout)
            content = self.client._extract_content(raw)
            parsed = json.loads(content)
            if "decision" in parsed and parsed["decision"] in ("YES", "NO"):
                parsed.setdefault("aggregated_from", list(prior_results.keys()))
                parsed.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                parsed.setdefault("symbol", snapshot.symbol)
                parsed.setdefault("direction", snapshot.direction)
                resp = Agent6ResponseSchema.model_validate(parsed)
                if resp.symbol.upper() != snapshot.symbol.upper() or resp.direction.upper() != snapshot.direction.upper():
                    raise ValueError("Agent6 symbol/direction mismatch")
                return resp
            raise ValueError(f"Agent6 unexpected shape: {parsed}")
        except Exception as e:
            logger.error("Agent6 provider error, failing closed to NO: %s", e)
            return Agent6ResponseSchema(
                agent_name="agent-6",
                schema_version="1.0",
                symbol=snapshot.symbol,
                direction=snapshot.direction,
                decision="NO",
                confidence=0.0,
                rationale=f"Agent6 provider failure: {e}",
                created_at=datetime.now(timezone.utc),
                aggregated_from=list(prior_results.keys()),
            )

    def _deterministic_agent6(self, snapshot: MarketSnapshot, prior_results: Dict[str, Any]) -> Agent6ResponseSchema:
        votes = [
            v["response"].decision
            for v in prior_results.values()
            if v["status"] == "success" and v["response"] is not None
        ]
        if len(votes) == 5 and all(d == "YES" for d in votes):
            decision = "YES"
            rationale = "Fallback: all mandatory agents YES"
        else:
            decision = "NO"
            rationale = "Fallback: incomplete or rejected mandatory evidence => NO"
        return Agent6ResponseSchema(
            agent_name="agent-6",
            schema_version="1.0",
            symbol=snapshot.symbol,
            direction=snapshot.direction,
            decision=decision,  # type: ignore
            confidence=0.85 if decision == "YES" else 0.1,
            rationale=rationale,
            created_at=datetime.now(timezone.utc),
            aggregated_from=list(prior_results.keys()),
        )

    def _deterministic_pipeline(
        self, snapshot: MarketSnapshot
    ) -> tuple[Dict[str, Any], Agent6ResponseSchema]:
        """Offline rule-engine path. Same shapes as the LLM path, so logs persist identically."""
        agents = self.deterministic.evaluate(snapshot)
        prior = {
            name: {"status": "success", "response": resp, "latency_ms": 0}
            for name, resp in agents.items()
        }
        final = self.deterministic.aggregate(snapshot, agents)
        logger.info(
            "Deterministic gate %s for %s %s: %s",
            final.decision, snapshot.symbol, snapshot.direction, final.rationale,
        )
        return prior, final

    async def run_full_pipeline(self, snapshot: MarketSnapshot) -> tuple[Dict[str, Any], Agent6ResponseSchema]:
        mode = self.settings.ai_gate_mode
        if mode == "deterministic":
            return self._deterministic_pipeline(snapshot)
        if mode == "reject_all":
            now = datetime.now(timezone.utc)
            return (
                {},
                Agent6ResponseSchema(
                    agent_name="agent-6",
                    schema_version="1.0",
                    symbol=snapshot.symbol,
                    direction=snapshot.direction,
                    decision="NO",
                    confidence=0.0,
                    rationale="AI_GATE_MODE=reject_all: the gate is configured to approve nothing",
                    created_at=now,
                    aggregated_from=[],
                ),
            )
        prior = await self.run_agents_1_to_5(snapshot)
        final = await self.run_agent_6(snapshot, prior)
        return prior, final
