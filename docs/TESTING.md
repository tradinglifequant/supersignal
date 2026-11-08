# Testing status

From the repository root, install `backend/requirements.txt` and run `PYTHONPATH=backend pytest backend/tests`. In `frontend`, run `npm ci`, `npm run lint`, `npm test`, and `npm run build`. Or run `bash scripts/run_tests.sh` from the repository root to execute both suites plus TypeScript/Vite build verification.

The backend suite contains unit, integration, and mock tests for:
- Trigger engine math, exact thresholds, stale feeds, and out-of-order tick blocking (`test_trigger_engine.py`).
- Risk sizing, quantization, post-rounding stop validation, fee/slippage inclusion, reinvestment caps, consecutive loss circuit breakers, and portfolio margin headroom (`test_risk_engine.py`).
- Execution idempotency, ambiguous `query_order` non-retry safety, unfilled/zero-fill handling, protective order repair vs. emergency flatten, residual order cleanup, and symbol universe stale-deactivation (`test_execution_idempotency.py`, `test_audit_fixes.py`).
- AI schema validation, symbol/direction mismatch rejection, timeout/malformed fail-closed behavior, and deterministic Agent 6 rejection when any mandatory Agent 1–5 fails or rejects (`test_ai_pipeline.py`, `test_audit_fixes.py`).
- Authentication boundaries, JWT `jti` logout revocation, WebSocket first-message authentication/origin/expiry/revocation, secret redaction (including dict format arguments), encryption roundtrips, and Alembic upgrade/downgrade migrations (`test_auth_boundary.py`, `test_security.py`, `test_api.py`, `test_audit_fixes.py`).
- Real-exchange entry lock enforcement (`test_exchange_entry_lock.py`).

The frontend tests exercise WebSocket authentication/cleanup (`useWebSocket.test.tsx`) and unauthenticated login gating, form submission, and logout behavior (`App.test.tsx`).

These tests do **not** establish real-exchange compatibility, real-account permissions, Portfolio Margin behavior, or production readiness. Still required by `phases.md`: live exchange and ThreeRouter contract verification; recorded market replay and reconnect soak tests; real testnet lifecycle and 24-hour observation; Windows and PostgreSQL staging rehearsals; security, recovery, and load reviews. No testnet or live success is claimed.
