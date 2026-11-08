# Testing status

From the repository root, install `backend/requirements.txt` and run `PYTHONPATH=backend pytest backend/tests`. In `frontend`, run `npm ci`, `npm run lint`, `npm test`, and `npm run build`. Or run `bash scripts/run_tests.sh` from the repository root to execute both suites plus TypeScript/Vite build verification.

The backend suite contains unit, integration, and mock tests for:
- Trigger engine math, exact thresholds, stale feeds, and out-of-order tick blocking (`test_trigger_engine.py`).
- Risk sizing, quantization, post-rounding stop validation, fee/slippage inclusion, reinvestment caps, consecutive loss circuit breakers, and portfolio margin headroom (`test_risk_engine.py`).
- Execution idempotency, ambiguous `query_order` non-retry safety, unfilled/zero-fill handling, protective order repair vs. emergency flatten, residual order cleanup, and symbol universe stale-deactivation (`test_execution_idempotency.py`, `test_audit_fixes.py`).
- AI schema validation, symbol/direction mismatch rejection, timeout/malformed fail-closed behavior, and deterministic Agent 6 rejection when any mandatory Agent 1–5 fails or rejects (`test_ai_pipeline.py`, `test_audit_fixes.py`).
- Authentication boundaries, JWT `jti` logout revocation, WebSocket first-message authentication/origin/expiry/revocation, secret redaction (including dict format arguments), encryption roundtrips, and Alembic upgrade/downgrade migrations (`test_auth_boundary.py`, `test_security.py`, `test_api.py`, `test_audit_fixes.py`).
- Real-exchange entry lock enforcement (`test_exchange_entry_lock.py`).
- Second-audit regressions: equity-curve windowing, net-of-fee win/loss consistency between `/api/metrics` and `/api/metrics/performance`, the single shared `ACTIVE_TRADE_STATUSES` definition across the positions API, engine status and metrics, market-feed queue saturation/drop accounting and ordered dispatch, per-iteration session isolation in the position monitor, stale `RUNNING` state reset on process restart, and working-directory-independent SQLite URL resolution, token acceptance via `X-Access-Token` when `Authorization` is stripped, rejection of garbage/revoked tokens on either header, `/api/auth/diagnose` header reporting without leaking the token, and that successful logins do not consume the throttle window (`test_audit_round2.py`).

`test_live_trading_phases.py` covers the execution path: every trading-gate
branch (env modes, env/adapter mismatch, the four live switches, kill switch,
testnet soak, per-order notional ceiling, withdrawal-capable key, clock drift,
preflight caching), adapter behaviour with and without a gate, Portfolio Margin
endpoint routing, the deterministic AI gate (approval, missing-feed fail-closed,
stale data, blow-off triggers, all five agents emitted, mode selection, and the
missing-key warning firing once rather than five times per candidate), the
market-context feeds, the context builder recording a failing feed as missing
instead of raising, and the preflight endpoint including a no-credentials-leak
assertion.

The frontend tests exercise WebSocket authentication/cleanup (`useWebSocket.test.tsx`), unauthenticated login gating, form submission, and logout behavior (`App.test.tsx`), and the axios request/response interceptors against a stub adapter — dual `Authorization`/`X-Access-Token` attachment, no headers when signed out, session clearing on 401, a stale in-flight 401 not clearing a newer login, and `diagnoseAuth` (`services/__tests__/api.test.ts`). `App.test.tsx` mocks `api.get` wholesale, so without `api.test.ts` the code that attaches the bearer token would have no coverage at all.

These tests do **not** establish real-exchange compatibility, real-account permissions, Portfolio Margin behavior, or production readiness. Still required by `phases.md`: live exchange and ThreeRouter contract verification; recorded market replay and reconnect soak tests; real testnet lifecycle and 24-hour observation; Windows and PostgreSQL staging rehearsals; security, recovery, and load reviews. No testnet or live success is claimed.
