# Research & Technical Verification (Phase 0)

> **Verification warning:** This document was carried forward from the initial prototype and its endpoint, limit, and compatibility claims have not been independently verified in this session. In particular, Portfolio Margin fallback and conditional-order behavior must not be relied upon. The ThreeRouter contract is unconfirmed. Treat the material below as research leads, not approved integration contracts; re-check current official documentation and account-specific behavior before use. Real Binance entries are locked on both testnet and live.

## Binance USD-M Futures API — Verified 2026-01-08

**Official Docs:**
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api
- https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams
- Testnet: https://testnet.binancefuture.com — futures testnet REST `https://testnet.binancefuture.com`, WS `wss://stream.binancefuture.com`

**Verified Endpoints Used:**
| Purpose | Method | Path | Auth |
|---------|--------|------|------|
| Connectivity | GET | /fapi/v1/ping | no |
| Exchange Info | GET | /fapi/v1/exchangeInfo | no |
| Ticker price | GET | /fapi/v1/ticker/price | no |
| Balance | GET | /fapi/v2/balance | signed |
| Account | GET | /fapi/v2/account | signed |
| PositionRisk | GET | /fapi/v2/positionRisk | signed |
| Create Order | POST | /fapi/v1/order | signed |
| Query Order | GET | /fapi/v1/order | signed |
| Open Orders | GET | /fapi/v1/openOrders | signed |
| Cancel Order | DELETE | /fapi/v1/order | signed |
| Cancel All | DELETE | /fapi/v1/allOpenOrders | signed |

**Portfolio Margin Compatibility:**
- Portfolio Margin endpoints: `/papi/v1/*` — try papi first, fallback to fapi if 404.
- Validated: account mode must be checked via `/papi/v1/account` or `/fapi/v2/account` + `accountType` detection.
- Risk: Portfolio Margin is account-level cross-collateralized; do not treat allocated margin as isolated. Implementation reads actual balances/positions and calculates headroom; blocks trading if risk cannot be measured.

**WebSocket Streams:**
- Base Mainnet: `wss://fstream.binance.com`
- Base Testnet: `wss://stream.binancefuture.com`
- Streams used: `<symbol>@aggTrade` for last price (verified), alternative `<symbol>@ticker`.
- Limits: 1024 streams per connection, 5 connections/IP; implementation shards at 200 streams/shard.
- Heartbeat: ping/pong via websockets library.

**Rate Limits:**
- REST: 1200 weight/min (exchangeInfo is 1, balance/account is 5-10). Respect `X-MBX-USED-WEIGHT`.
- Orders: 10 orders/sec, 100k/day. Implementation uses bounded retry with backoff, never bursts.

**Order Types Supported (Verified):**
- `MARKET` for entry (requested).
- `STOP_MARKET`, `TAKE_PROFIT_MARKET` with `reduceOnly`/`closePosition` for protection.
- `workingType` supports `MARK_PRICE` or `CONTRACT_PRICE`; we use `MARK_PRICE` to mitigate manipulation.
- `newClientOrderId` constraints: 1-36 chars alphanumeric + hyphen/underscore.

## ThreeRouter API — Verification Status

**Status:** ⚠️ Mock / Interface Only — Pending Official Verification
- Provider claims `threerouter.com` — no public docs found at standard crawl depth.
- Decision: Implement adapter interface with OpenAI-like `/v1/chat/completions` generic; keep base URL, agent IDs, schemas configurable.
- Never hardcode undocumented endpoints; treat as injectable.
- Deliverable: Pydantic schemas for 6 agents, timeout/retry, fail-closed, prompt versioning, latency/cost tracking ready for when contract confirmed.
- **Action Required Before Production:** Verify with provider: base URL, auth (Bearer/X-API-Key), endpoint paths, model/agent IDs, request/response schemas, rate limits, pricing.

**Agent Responsibilities (per PRD/rules):**
- Agents 1-5 parallel, Agent6 strict YES/NO.
- Each returns structured JSON with `decision` YES/NO/INSUFFICIENT_DATA, confidence, evidence, missing_data, rationale, invalidation.
- INSUFFICIENT_DATA fails closed to NO.

## Python Libraries Evaluated

| Library | Decision | Reason |
|---------|----------|--------|
| FastAPI | ✅ | Async, OpenAPI, Pydantic v2, proven |
| httpx | ✅ | Async REST for Binance + ThreeRouter, http2 support |
| websockets | ✅ | Async WS, ping/pong |
| SQLAlchemy 2.0 + Alembic | ✅ | Async-compatible, SQLite→PG migration |
| psycopg (v3) | ✅ | Modern PG driver, binary |
| python-jose + passlib | ✅ | JWT + bcrypt |
| cryptography.Fernet | ✅ | Credential encryption, key rotation |
| pytest + pytest-asyncio | ✅ | Test coverage |

**Rejected:** ccxt (abstracts but hides Binance specifics needed for Portfolio Margin nuances), python-binance (sync, not fully async).

## Aiven PostgreSQL & Deployment

- Aiven PG: https://aiven.io/docs/products/postgresql — TLS required, `sslmode=require`.
- Aiven Runtime: https://aiven.io/docs/products/runtime/deploy-apps — optional app runtime; verify current capability before choosing.
- Fallback: VPS/container host (Docker Compose provided) + Aiven PG.
- Constraint: Single trading worker initially; no distributed locking until tested.

## Technical Risks Identified

1. **ThreeRouter contract unknown** → Mitigation: interface + mocks + feature flag.
2. **Portfolio Margin risk measurement** → Mitigation: read actual account endpoints, reserve headroom, block if unverifiable.
3. **Stop-market slippage** → Disclosure: modeled loss is not guarantee; UI + docs warn.
4. **WS gaps** → Mitigation: bounded queues, stale detection, reconnect backoff, reconciliation on reconnect.
5. **Duplicate orders on timeout** → Mitigation: clientOrderId idempotency, query-before-retry, max 2 retries.
