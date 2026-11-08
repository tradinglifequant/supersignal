# Testing status

From the repository root, install `backend/requirements.txt` and run `PYTHONPATH=backend pytest backend/tests`. In `frontend`, run `npm ci`, `npm test` and `npm run build`. The frontend tests run without coverage reporting. Frontend `npm run lint` currently has no ESLint configuration and is not yet usable.

The backend suite contains unit and mock tests for trigger, risk, execution, AI, security and API behavior. `test_auth_boundary.py` additionally checks private HTTP endpoints, configuration failures, login throttling, token validation, WebSocket authentication/origin/expiry and credential-test response redaction. The frontend hook tests exercise WebSocket authentication and cleanup.

These tests do **not** establish execution idempotency, protection, recovery, real-account permissions, Portfolio Margin compatibility, or production readiness. In particular, current execution tests do not adequately simulate all ambiguous submissions and reconciliation failures. The Binance entry lock remains in place on testnet and live.

Still required by `phases.md`: exchange and provider contract verification; recorded market replay and reconnect tests; comprehensive risk, order ambiguity, partial-fill, protection, emergency and restart tests; real testnet lifecycle and long observation; Windows and PostgreSQL migration rehearsals; frontend coverage/accessibility; security, recovery and load reviews. No testnet or live success is claimed.
