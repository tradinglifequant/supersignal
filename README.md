# Super Signal 🎯

Super Signal is an **experimental prototype** of an AI-assisted Binance USDⓈ-M Futures trading system. The specifications and phased roadmap are in `PRD.md`, `architecture.md`, `rules.md`, `phases.md`, `design.md`, and `memory.md`.

## Safety and current status

**The code path to real-money execution now exists, but it has never been exercised against a real exchange account. Do not run it with real funds until the verification in `docs/LIVE_TRADING.md` is complete.**

Order placement is controlled by an evaluated trading gate (`app/trading/gate.py`), not a hard block. It defaults to `TRADING_ENV=none`, in which case no exposure-increasing order can be placed. Reaching live trading requires four independent switches to agree — `TRADING_ENV=live`, `LIVE_TRADING_OPT_IN=true`, `LIVE_TRADING_ACKNOWLEDGEMENT` set to the exact required phrase, and `KILL_SWITCH` unset — plus a preflight that verifies the key can trade, **cannot withdraw**, that clock drift is within tolerance, that every risk limit is configured, and that the required testnet soak has elapsed. `GET /api/engine/preflight` reports each check and names what is blocking.

Requests marked reduce-only or close-position bypass the gate on purpose: being unable to close a position is strictly worse than being unable to open one. That is **not** a guarantee that protection, emergency closure, or exchange compatibility works — those paths remain unverified against real exchange accounts. Manage any real positions directly on the exchange.

Read [`docs/LIVE_TRADING.md`](docs/LIVE_TRADING.md) for the staged runbook before changing any of these settings.

Important outstanding blockers include:

- **No Binance endpoint has been verified against a real or testnet account** from this environment — there is no network path to Binance here. Portfolio Margin routing (`/papi/v1/um/*`), maintenance-margin interaction, position-side mode, per-symbol leverage, conditional orders and protective-order behaviour are all implemented against the published API but unexercised.
- ThreeRouter's actual API contract and external footprint/order-flow feeds remain unverified. With `AI_GATE_MODE=threerouter` and no `THREEROUTER_API_KEY`, the pipeline fails closed (`NO`). `AI_GATE_MODE=deterministic` uses the auditable local rule engine in `app/ai/deterministic_gate.py` instead.
- Authentication and deployment still need a full external security review, including distributed rate limiting and multi-worker/persistent session revocation. Never expose this prototype to an untrusted network or use real credentials.
- Phase exit gates in `phases.md` are goals, not evidence of completion. No testnet or live exchange validation is claimed.

## Local development

Prerequisites: Python 3.11+, Node.js 18+. Run only locally, without real credentials.

Backend (from the repository root):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r backend/requirements.txt
# Copy .env.example to .env (or backend/.env), then configure ADMIN_USERNAME,
# ADMIN_PASSWORD_HASH, and a unique JWT_SECRET_KEY (see below).
alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Relative `sqlite:///` URLs in `DATABASE_URL` are anchored to the repository root, and
`backend/alembic.ini` resolves its script directory from its own location, so migrations
and the API server use the same database whether you start them from the repository root
or from `backend/`.

### Configure the local operator

Copy `.env.example` to `.env` in the repository root (the backend resolves `.env` and `backend/.env`). Set a unique `JWT_SECRET_KEY` with at least 32 characters, for example generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Create the bcrypt `ADMIN_PASSWORD_HASH` with the following command; it prompts without echoing your password. Paste the resulting hash and signing key into `.env` locally, not into chat or version control:

```bash
python -c "import getpass; from passlib.hash import bcrypt; print(bcrypt.hash(getpass.getpass('Operator password: ')))"
```

There is no default password or development authentication bypass. Without a valid hash and signing key, login fails closed. The browser holds the session token in memory only; `POST /api/auth/logout` revokes the token's `jti` in-process until expiry (single-worker memory, not persistent across restarts). The process-wide login throttle is a single-process safeguard and not a distributed rate limiter. Health endpoints remain public; configure exact trusted `CORS_ORIGINS` for browser access.

Frontend (in another terminal):

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Tests and linting (from the repository root):

```bash
# Windows PowerShell: $env:PYTHONPATH='backend'; pytest backend/tests
# Linux/macOS:
PYTHONPATH=backend pytest backend/tests
cd frontend && npm run lint && npm test && npm run build
```

Tests use mocks and do not establish exchange compatibility or trading safety. See `docs/TESTING.md` and `docs/RESEARCH.md` for context, noting the verification warning in the latter.

## Risk disclosure

The modeled stop loss is not a guarantee against gaps, slippage, liquidation, outages, or other extreme conditions. See `rules.md` §4.2.
