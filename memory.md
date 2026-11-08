# Super Signal 🎯 — Project Memory and AI Coding Agent Context

This document is the persistent project brief for future AI coding sessions. Read it before making changes. Treat `PRD.md`, `architecture.md`, `rules.md`, `phases.md`, and `design.md` as the detailed specifications.

## 1. Project identity

- Name: Super Signal 🎯
- Purpose: AI-assisted automated Binance USDⓈ-M Futures trading bot.
- Initial operator model: single operator.
- Initial development machine: Windows PC.
- Production target: online deployment with Aiven-managed PostgreSQL; application compute may be Aiven Runtime or a separate VPS/container host.
- Frontend: React + TypeScript.
- Backend: Python + FastAPI + asyncio.
- Local database: SQLite.
- Production database: PostgreSQL on Aiven.
- AI provider: ThreeRouter (`threerouter.com`), subject to its actual published API contract.
- Exchange: Binance USDⓈ-M Futures.
- Account context: Portfolio Margin; verify exact account/product support before implementation.

## 2. Locked product decisions

| Item | Locked decision |
|---|---|
| Market | USDT-M Futures |
| Entry | Market order |
| Trigger source | Last traded price |
| Trigger threshold | 1.5% default |
| Trigger window | Rolling 3 minutes / 180 seconds |
| AI topology | Agents 1–5 parallel; Agent 6 final confirmation |
| Base margin | 3 USDT default |
| Leverage | 10x default |
| Concurrent positions | 3 default |
| Risk | Modeled maximum loss <= allocated trade margin, including estimated fees and slippage |
| Winning trade | Increase next margin by base + configured percentage of realized net profit |
| Losing trade | Reset next margin to base |
| Reinvestment | 25% default |
| Dashboard | React + FastAPI |
| Local development | Windows PC |
| Production DB | Aiven PostgreSQL |
| Live mode | Automated after readiness and risk gates pass |

## 3. Critical interpretation notes

1. The trigger is a rolling price return, not a sum of candle returns:

   `((last_price_now - last_price_180s_ago) / last_price_180s_ago) * 100`

2. The 1-minute timeframe is used for market context and candle analytics; the trigger itself uses last price over the 180-second rolling window.

3. Agents 1–5 run in parallel. Agent 6 aggregates their validated outputs. Missing required evidence means final rejection.

4. Agent 5 must not fabricate footprint data. If the selected data source cannot provide footprint/volume-at-price inputs, report insufficient data and fail closed.

5. AI never controls order placement or risk approval. It supplies analysis; deterministic code sizes, validates, and executes.

6. “Maximum loss <= allocated margin” is a modeled pre-trade bound including estimated fees/slippage. It is not a guarantee against gaps, stop execution slippage, liquidation, exchange outages, or other extreme conditions.

7. Portfolio Margin is account-level. The internal per-trade allocation is a risk ledger, not necessarily segregated isolated margin. Validate account mode, supported Binance endpoints, and account-level risk before live execution.

8. Retry policy means at most two retries after the initial attempt, only for transient failures and only after exchange state confirms no order/fill exists. On ambiguous timeout, query by client order ID before retrying.

9. Normal Stop blocks new entries but must keep monitoring and protection for existing positions active.

10. Cleaner cancels only bot-owned residual orders; never indiscriminately cancel manual orders.

11. Aiven is used for production PostgreSQL. App compute must be deployed separately unless using Aiven Runtime. Verify current Aiven Runtime capability and plan before choosing the production topology.

## 4. Required implementation standards

- Python type hints and Pydantic schemas.
- `Decimal` for all financial calculations and exchange values.
- SQLAlchemy models and Alembic migrations.
- SQLite locally; PostgreSQL in production.
- Async network I/O; bounded queues and concurrency.
- Exchange and AI provider adapters behind interfaces.
- Idempotent trade intents and client order IDs.
- Structured, redacted logs and audit events.
- UTC timestamps in persistence.
- Unit, integration, contract, and end-to-end tests.
- Secrets never committed, logged, or exposed to React.
- Use official, current Binance and ThreeRouter documentation; do not invent endpoints, parameters, agent IDs, or response schemas.

## 5. Mandatory safety constraints

- Testnet first; live credentials and environment are separate.
- Binance API key must not have withdrawal permission.
- Prefer IP allowlisting.
- Fail closed when data, AI, account, database, or risk state is uncertain.
- Require daily loss, drawdown, aggregate exposure, and slippage limits before live engine start.
- Verify TP/SL on Binance after entry fills.
- If protection cannot be established, follow emergency repair/close policy.
- Reconcile exchange state at startup, reconnect, and periodically.
- One active trading worker until distributed locking/leader election is implemented and tested.
- Emergency stop must immediately block new entries and apply the configured policy to open positions.

## 6. Current project stage

Documentation baseline has been prepared. No application code, exchange connection, ThreeRouter integration, credentials, database, or live trading behavior is implied to exist yet.

Next recommended implementation task:
1. Create the repository skeleton.
2. Set up Windows development environment.
3. Implement config, logging, database models, and migrations.
4. Implement read-only Binance metadata/account connectivity.
5. Add market data and trigger tests before any order execution.

## 7. AI coding agent operating instructions

When asked to implement a feature:

1. Read this file and the relevant detailed specification first.
2. Inspect the existing repository before editing; preserve established conventions.
3. State a concise plan for multi-file or high-risk changes.
4. Implement the smallest complete vertical slice.
5. Add or update tests for normal, failure, retry, restart, and idempotency behavior.
6. Run relevant tests, type checks, linting, and migrations.
7. Report exactly what changed, what tests ran, and what remains unverified.
8. Never claim testnet/live success without actual exchange evidence.
9. Never request or print API secrets in chat or source code.
10. If a specification conflicts with exchange behavior or API documentation, stop and explain the conflict; do not silently guess.

## 8. Change management

- Update all affected docs when a product decision changes.
- Record architectural decisions in an ADR (Architecture Decision Record).
- Treat risk and execution changes as high-risk: require tests and explicit review.
- Keep provider prompt/schema versions traceable.
- Do not silently change defaults or remove safety gates.
- Do not add new markets, exchanges, or multi-user support without explicit scope approval.

## 9. Key formulas

### Trigger
`movement_pct = ((P_now - P_180s_ago) / P_180s_ago) * 100`

### Gross stop loss approximation for linear USDT-M contract
`gross_loss = abs(entry_price - stop_price) * quantity`

### Modeled risk
`modeled_total_loss = gross_loss + entry_fee_estimate + exit_fee_estimate + slippage_allowance + applicable_costs`

Approval condition:
`modeled_total_loss <= allocated_margin`

### Margin after a win
`next_margin = base_margin + (realized_net_profit * profit_reinvestment_pct / 100)`

### Margin after a loss
`next_margin = base_margin`

## 10. Open decisions that must be verified, not guessed

- Exact ThreeRouter API base URL, authentication, endpoint paths, agent identifiers, request/response formats, rate limits, and timeout guidance.
- Whether Binance Portfolio Margin supports the exact USDⓈ-M order and risk endpoints selected.
- Exact conditional order types and trigger semantics currently supported for the account.
- Which data feed/provider supplies the required footprint and smart-money evidence.
- Global risk limit values (daily loss, drawdown, aggregate exposure, max consecutive losses).
- Production app compute target: Aiven Runtime or separate VPS/container host.
- Alert delivery channel and retention periods.

Until these are verified, implement interfaces, mocks, and tests—not guessed production integrations.
