# Super Signal 🎯 — Implementation Phases and Delivery Roadmap

## Delivery approach

Build and validate on a Windows PC first. Keep live trading disabled until testnet, failure-recovery, risk, and security gates pass. Then migrate the same codebase to an online runtime/server with Aiven PostgreSQL.

Each phase has deliverables, tests, and an exit gate. Do not skip phases to reach live trading faster.

## Phase 0 — Scope lock and technical discovery

**Tasks**
- Confirm Binance USDⓈ-M Futures account capabilities and Portfolio Margin endpoint support.
- Verify Binance API key permissions and testnet/live environment separation.
- Obtain ThreeRouter API documentation, authentication method, agent identifiers, request/response schemas, rate limits, and pricing/limits.
- Verify which feeds are available for order flow, smart-money proxies, and footprint.
- Choose Aiven Runtime or separate online compute host for the application.
- Define global loss/drawdown/slippage limits before live mode.

**Deliverables**
- Confirmed API integration contracts.
- Configuration specification.
- Risk policy defaults and account-mode decision record.
- Deployment decision record.

**Exit gate:** No undocumented ThreeRouter endpoint or assumed Binance account capability remains in implementation scope.

## Phase 1 — Windows development foundation

**Tasks**
- Create repository and folder structure.
- Set up Python, FastAPI, asyncio, Pydantic, SQLAlchemy, Alembic, pytest, and structured logging.
- Set up React + TypeScript frontend and test tooling.
- Add `.env.example`, `.gitignore`, local developer scripts, and dependency lock files.
- Implement SQLite local database and initial migrations.
- Add health/readiness endpoints and application settings.

**Deliverables**
- App boots locally on Windows.
- Database initializes and migrations run.
- React dashboard shell communicates with FastAPI.
- Secret redaction and local authentication baseline.

**Tests**
- Backend unit tests.
- API smoke tests.
- Frontend lint/typecheck/tests.
- Migration up/down or forward-migration verification.

**Exit gate:** Clean clone can be configured and started using documented Windows instructions.

## Phase 2 — Binance exchange adapter and market data

**Tasks**
- Implement exchange adapter interface.
- Fetch exchange metadata and eligible USDⓈ-M perpetual symbols.
- Implement async WebSocket listener(s) for last-price data.
- Implement subscription sharding, reconnect, heartbeat, stale detection, and bounded queues.
- Maintain per-symbol rolling 180-second price history.
- Add 1-minute candles and optional order-book/trade feeds required by analysis.
- Implement account-mode, balance, position, order, and exchange-filter readers.
- Add testnet configuration and safe credential validation.

**Tests**
- Recorded fixture replay.
- Reconnect and dropped-message tests.
- Stale/out-of-order event tests.
- Symbol metadata/filter tests.
- Testnet read-only account checks.

**Exit gate:** Scanner covers the eligible symbol universe without unbounded memory/queue growth and can recover after disconnect.

## Phase 3 — Trigger engine and candidate lifecycle

**Tasks**
- Implement rolling percentage formula using last price.
- Add exact threshold boundary handling.
- Add cooldown, deduplication, candidate TTL, and persisted candidate lifecycle.
- Add market snapshot builder with source timestamps and missing-data flags.
- Expose scanner and signal data to dashboard.

**Tests**
- +1.5%, -1.5%, just below threshold, zero/invalid price, missing lookback, stale feed, and event ordering.
- Duplicate trigger and cooldown tests.
- Restart/replay consistency tests.

**Exit gate:** Signal generation is deterministic and reproducible from stored input data.

## Phase 4 — ThreeRouter AI pipeline

**Tasks**
- Implement provider client only after official ThreeRouter API contract is verified.
- Define versioned Pydantic request/response schemas.
- Implement Agents 1–5 concurrently with bounded concurrency and timeouts.
- Implement Agent 6 final aggregation.
- Persist agent logs, prompt versions, latency, and schema-validation status.
- Build dashboard agent trace.

**Tests**
- Mock positive and negative responses.
- Agent timeout and provider outage.
- Invalid JSON/schema.
- Contradictory agent decisions.
- Missing footprint/order-flow evidence.
- Prompt injection/untrusted output handling.
- Parallel execution timing and concurrency limits.

**Exit gate:** No candidate can proceed when required evidence is missing or invalid; Agent 6 returns strict machine-readable decision.

## Phase 5 — Risk engine and position planner

**Tasks**
- Implement Decimal-based position sizing.
- Load and enforce exchange filters and leverage brackets.
- Implement fee/slippage model and stop-loss risk calculation.
- Implement Portfolio Margin account-level checks and internal per-trade allocation ledger.
- Validate TP/SL direction and rounding.
- Add global daily loss, drawdown, notional, consecutive-loss, and account-headroom limits.
- Implement margin scaling and loss reset behavior.

**Tests**
- Property-based risk tests.
- Exchange precision/minimum notional tests.
- Fee/slippage boundary tests.
- Leverage bracket and account headroom tests.
- Verify every approved order remains under modeled margin risk after rounding.

**Exit gate:** Risk engine can independently reject unsafe trades and cannot be bypassed by AI output.

## Phase 6 — Testnet execution and protection

**Tasks**
- Implement durable TradeIntent and idempotent client order IDs.
- Implement market entry, fill reconciliation, and safe retry logic.
- Implement TP/SL placement and verification.
- Implement partial-fill handling and protection repair.
- Implement emergency close policy.
- Implement position monitor and bot-owned order cleaner.
- Implement startup/reconnect reconciliation.

**Tests**
- Successful market order.
- Insufficient margin and invalid quantity.
- Timeout before/after exchange acceptance.
- Duplicate submission prevention.
- TP/SL rejection and missing protection.
- Partial fills, manual close, disconnect, restart.
- Residual order cleanup without canceling manual orders.

**Exit gate:** Full testnet lifecycle passes repeatedly with no duplicate exposure and no unprotected position left unresolved.

## Phase 7 — Dashboard and operator controls

**Tasks**
- Build overview KPIs.
- Build live scanner and signal queue.
- Build open/closed position tables.
- Build configuration and credential management.
- Build engine controls, risk status, connection indicators, and logs.
- Implement authenticated WebSocket updates and reconnect snapshot.
- Add emergency stop and visible live/testnet mode.

**Tests**
- API authorization and validation.
- Secret masking.
- UI behavior on stale/disconnected data.
- Start/stop and emergency action audit tests.
- Responsive layout and accessibility checks.

**Exit gate:** Operator can understand system state and risk without reading raw logs.

## Phase 8 — Full system simulation and security review

**Tasks**
- Run paper trading using recorded/replayed market data.
- Run testnet for an extended observation window.
- Load-test full symbol universe and AI request concurrency.
- Test database interruption, Aiven-like network latency, process kill/restart, and WebSocket outage.
- Review authentication, secret storage, dependency vulnerabilities, API permissions, and logs.
- Test backup/restore and database migration.

**Exit gate:** All release blockers resolved; no known critical/high security issues; measured performance meets documented targets.

## Phase 9 — Production migration to online infrastructure

**Tasks**
- Create Aiven PostgreSQL service and enforce TLS.
- Decide whether app runs on Aiven Runtime or separate VPS/container host.
- Configure production environment variables and secret storage.
- Create production database and run Alembic migrations.
- Export and import required local configuration/history if desired; never copy testnet secrets into production.
- Configure domain/HTTPS, authentication, firewall, monitoring, backups, and alerting.
- Configure Binance API IP allowlist to match production egress where possible.
- Deploy one trading worker only.
- Verify health/readiness, database connection, exchange read-only connection, and reconciliation.

**Tests**
- SQLite-to-PostgreSQL migration rehearsal.
- Connection/TLS verification.
- App restart and worker singleton verification.
- Restore from backup.
- Production secrets and API permission audit.

**Exit gate:** Production deployment is stable in read-only/paper mode before any live entry is enabled.

## Phase 10 — Controlled live activation

**Preconditions**
- Operator has reviewed risk limits and understands stop execution limitations.
- Testnet lifecycle and recovery tests pass.
- API key has no withdrawal permission and is restricted appropriately.
- Portfolio Margin account compatibility is verified.
- Global loss/drawdown and slippage caps are configured.
- Emergency stop has been tested.
- Production reconciliation reports no unknown positions/orders.
- Monitoring and alerts are active.

**Activation**
- Start with the smallest valid allocation and conservative limits.
- Monitor every trade and protection state.
- Do not increase allocation until operational evidence supports it.
- Stop new entries automatically on any risk/data/account uncertainty.
- Keep an incident and rollback procedure.

**Exit gate:** Live operation remains within all configured limits and all protective controls are verified.

## Phase 11 — Operations and improvement

- Review P&L and execution quality without changing rules based on isolated outcomes.
- Track AI agent agreement, rejection reasons, latency, and data quality.
- Version prompts and risk models; run regression fixtures before rollout.
- Rotate credentials and review access periodically.
- Apply dependency/security updates through staged deployments.
- Rehearse database restore and application rollback.
- Add features only with corresponding tests and documentation.

## Project completion checklist

- [ ] Phase 0 integration contracts confirmed.
- [ ] Windows developer setup reproducible.
- [ ] Binance data pipeline stable.
- [ ] Trigger engine deterministic.
- [ ] ThreeRouter agents schema-validated and fail-closed.
- [ ] Risk engine and Portfolio Margin constraints validated.
- [ ] Testnet execution/protection lifecycle reliable.
- [ ] Dashboard and operator controls complete.
- [ ] Security and recovery review passed.
- [ ] Aiven PostgreSQL and online app deployment verified.
- [ ] Controlled live activation checklist signed off.
