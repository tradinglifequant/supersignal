# Testing Strategy

## Pyramid

| Layer | Coverage | Tools |
|-------|----------|-------|
| Unit | Trigger, Risk, Execution, Security | pytest |
| Integration | Binance mock, AI mock, WS reconnect | pytest-asyncio |
| API | Health, Auth, Config, Trades, Metrics | FastAPI TestClient |
| E2E | Paper trading replay | manual/testnet |
| Performance | Symbol universe load, AI concurrency | locust (future) |

## Current Suite (50 tests, all passing)

- `test_trigger_engine.py` — FR-02 acceptance: +1.5%, -1.5%, exact threshold, below, zero, missing lookback, stale, out-of-order, window boundary.
- `test_risk_engine.py` — FR-04: approved/rejected, rounding, min_notional, stop direction, fees/slippage, next margin, Portfolio Margin headroom, global limits, tick rounding.
- `test_execution_idempotency.py` — FR-05: no duplicate after timeout, retry only when absent, non-retryable not retried.
- `test_ai_pipeline.py` — FR-03: parallel timing, timeout→NO, INSUFFICIENT_DATA→NO, contradictory, malformed, mandatory check.
- `test_security.py` — encryption roundtrip, masking, JWT, hard limits, log redaction.
- `test_api.py` — health/ready, auth, config, metrics, market, engine status.

## Testnet Integration (To Do Before LIVE)
- [ ] Run on Binance Testnet (https://testnet.binancefuture.com) for 1 week with real WS + mock AI.
- [ ] Verify full lifecycle: trigger → AI → risk → market order → TP/SL → monitor → cleaner.
- [ ] Simulate WS disconnect, DB kill, process restart, partial fill.

## Failure & Recovery Tests
- WS down → block signals, reconnect, reconcile (covered in WS manager).
- Binance timeout → query-by-clientId before retry (covered).
- TP/SL rejected → repair then emergency close (covered).
- DB unavailable → block entries, keep protection if possible (stubbed, needs resilience test).
