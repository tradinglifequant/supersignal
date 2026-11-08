# Super Signal 🎯

Super Signal is an **experimental prototype** of an AI-assisted Binance USDⓈ-M Futures trading system. The specifications and phased roadmap are in `PRD.md`, `architecture.md`, `rules.md`, `phases.md`, `design.md`, and `memory.md`.

## Safety and current status

**Not ready for testnet order execution, live trading, or public deployment.** The real Binance adapter blocks all exposure-increasing orders, and the engine refuses to start with that adapter in both testnet and live modes. There is deliberately no configuration switch to unlock entries. The in-memory mock adapter is still available for development and tests; it is not a faithful exchange simulator.

The adapter still permits requests marked reduce-only or close-position so existing exposure is not intentionally stranded by the entry lock. This is **not** a guarantee that protection, emergency closure, or exchange compatibility works: those paths remain unverified. Manage any real positions directly on the exchange.

Important outstanding blockers include:

- Real account mode, Portfolio Margin risk/headroom, conditional order contracts, and protective order behavior have not been verified.
- Risk checks use placeholder P&L and drawdown values; hard limits and concurrency are not comprehensively enforced.
- Ambiguous order submissions, fills, protection failures, restart/reconciliation, and emergency handling are not adequately safe or tested.
- ThreeRouter's actual API contract and the required market-data feeds remain unverified; the current client contains assumptions, not a confirmed integration.
- Authentication and deployment still need a full security review, including distributed rate limiting and server-side session revocation. Never expose this prototype to an untrusted network or use real credentials.
- Phase exit gates in `phases.md` are goals, not evidence of completion. No testnet or live exchange validation is claimed.

## Local development

Prerequisites: Python 3.11+, Node.js 18+. Run only locally, without real credentials.

Backend (from the repository root):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
# Copy .env.example to backend/.env, then configure ADMIN_USERNAME,
# ADMIN_PASSWORD_HASH and a unique JWT_SECRET_KEY (see below).
cd backend
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Configure the local operator

Copy `.env.example` to `backend/.env` (the backend reads `.env` from its working directory). Set a unique `JWT_SECRET_KEY` with at least 32 characters, for example generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Create the bcrypt `ADMIN_PASSWORD_HASH` with the following command; it prompts without echoing your password. Paste the resulting hash and signing key into `backend/.env` locally, not into chat or version control:

```bash
python -c "import getpass; from passlib.hash import bcrypt; print(bcrypt.hash(getpass.getpass('Operator password: ')))"
```

There is no default password or development authentication bypass. Without a valid hash and signing key, login fails closed. The browser holds the session token in memory; reload or sign-out clears it locally, but an already issued token remains valid until expiration. The process-wide login throttle is only a development safeguard, resets on restart and is not a distributed rate limiter. Health endpoints remain public; configure exact trusted `CORS_ORIGINS` for browser access.

Frontend (in another terminal):

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Backend tests (from the repository root):

```bash
# Windows PowerShell: $env:PYTHONPATH='backend'; pytest backend/tests
# Linux/macOS:
PYTHONPATH=backend pytest backend/tests
```

Tests use mocks and do not establish exchange compatibility or trading safety. See `docs/TESTING.md` and `docs/RESEARCH.md` for context, noting the verification warning in the latter.

## Risk disclosure

The modeled stop loss is not a guarantee against gaps, slippage, liquidation, outages, or other extreme conditions. See `rules.md` §4.2.
