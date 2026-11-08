# Super Signal 🎯

AI-powered Binance USDT-M Futures trading bot with 6-agent ThreeRouter verification, deterministic risk engine, and real-time React dashboard.

## Architecture

```
Binance WebSocket → Symbol Universe → Trigger Engine (1.5%/180s) → AI Agents 1-5 (parallel) → Agent 6 YES/NO → Risk Gate → Execution → TP/SL Monitor → Cleaner
```

See `architecture.md`, `PRD.md`, `rules.md`, `phases.md`, `design.md`, `memory.md` for full specs.

## Quick Start (Windows / Linux / macOS)

### Prerequisites
- Python 3.11+
- Node 18+
- SQLite (local) / Aiven PostgreSQL (prod)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ..
cp ../.env.example ../.env  # edit values
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health: http://localhost:8000/api/health
Docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard: http://localhost:5173

### Tests

```bash
pytest backend/tests -v
cd frontend && npm test
```

## Key Features

- **Market Scanner**: Full USDT-M perpetual universe, WebSocket last-price, 180s rolling trigger, deduplication & cooldown
- **AI Pipeline**: ThreeRouter Agents 1-5 parallel + Agent 6 final YES/NO, fail-closed, schema-validated
- **Risk Engine**: Decimal-based sizing, exchange filters, modeled loss ≤ allocated margin incl. fees/slippage, Portfolio Margin aware
- **Execution**: Market entry, idempotent clientOrderId, fill reconciliation, TP/SL verification, emergency close, cleaner
- **Dashboard**: Live scanner, positions, history, AI trace, config, engine controls, emergency stop
- **Security**: JWT auth, Fernet credential encryption, redacted logs, no withdrawal, IP allowlist guidance
- **Persistence**: SQLAlchemy + Alembic, SQLite local, Aiven PostgreSQL prod (TLS)

## Environment Modes

| Mode | Binance | DB | Purpose |
|------|---------|----|---------|
| development | Testnet | SQLite | Local dev |
| testnet | Testnet | SQLite/PG | Integration tests |
| production | Live | Aiven PG | Online trading |

Never enable `APP_ENV=production` without setting hard risk limits (`DAILY_LOSS_LIMIT`, `MAX_DRAWDOWN_PCT`, `MAX_AGGREGATE_EXPOSURE`).

## Emergency

Dashboard → **Emergency Stop** immediately blocks new entries and applies configured flatten/protect policy. Requires confirmation + audit log.

## Deployment

See `deploy/README.md` — Aiven PostgreSQL + Aiven Runtime / VPS container. One trading worker initially. TLS + migrations required.

## Disclaimer

Modeled stop-loss is not a guarantee against gaps, liquidation, outages, or extreme slippage. Start with minimum allocation. See `rules.md` §4.2.
