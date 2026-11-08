# Super Signal 🎯 — Technical and UI Design

## 1. Design direction

Build a professional trading operations dashboard: information-dense but calm, with strong visual hierarchy, clear risk states, and no decorative elements that obscure execution health. The UI is an operational control surface, not a marketing page.

**Frontend:** React + TypeScript  
**Backend:** FastAPI + Python asyncio  
**Local database:** SQLite  
**Production database:** Aiven PostgreSQL  
**API contract:** OpenAPI-generated types or a shared, versioned schema package

## 2. Navigation and page structure

Primary navigation:
1. Overview
2. Live Scanner
3. Positions
4. Trade History
5. AI Analysis
6. Configuration
7. System Logs

Persistent top bar:
- Product name/logo.
- Environment chip: `TESTNET` or `LIVE`.
- Engine state.
- Binance connection state.
- AI provider state.
- Database state.
- User menu / sign out.

The LIVE indicator must be unmistakable and must never be inferred from color alone; include text.

## 3. Overview page

### KPI cards
- Starting balance.
- Current equity.
- Realized P&L.
- Unrealized P&L.
- Win rate.
- Total executed trades.
- Current open positions / maximum.
- Current drawdown.

Each KPI includes a definition tooltip and reporting time range. Do not combine realized and unrealized P&L without labeling.

### Operational status
- Engine state and last state transition.
- Market data freshness and symbol coverage.
- AI pipeline health and recent latency.
- Exchange account mode and margin headroom.
- Protection health: number of open positions with verified TP/SL.
- Recent risk blocks and circuit-breaker status.

### Charts
- Equity curve.
- Realized P&L over time.
- Trade outcomes.
- Optional per-symbol performance.

Charts must use persisted, reconciled data and disclose selected time range.

## 4. Live Scanner page

Table columns:
- Symbol.
- Last price.
- 3-minute change.
- Direction candidate.
- Data freshness.
- Spread/liquidity indicator when available.
- Candidate status.
- AI pipeline status.
- Last update.

Filters:
- All / triggered / processing / rejected / approved.
- Long / short.
- Symbol search.

Candidate detail drawer:
- Current and reference prices.
- Exact timestamps and formula.
- Market snapshot freshness.
- Agents 1–5 results.
- Agent 6 decision.
- Risk gate result.
- Rejection reason.

## 5. Positions page

Open positions table:
- Symbol and side.
- Quantity.
- Average entry.
- Mark price.
- Notional.
- Internal margin allocation.
- Leverage.
- TP and SL trigger values.
- Unrealized P&L.
- Protection status.
- Exchange update time.

Position detail:
- Entry order and fills.
- Protective order IDs and status.
- Modeled risk at entry.
- Current exchange-reported liquidation/risk metrics if available.
- Timeline of position events.
- Manual intervention indicator.

Protection state must be textual: `VERIFIED`, `REPAIRING`, `UNPROTECTED`, `CLOSING`, or `UNKNOWN`.

## 6. Trade History page

Columns:
- Trade ID.
- Symbol.
- Direction.
- Entry/exit time.
- Average entry/exit.
- Quantity.
- Margin allocation.
- TP/SL.
- Net realized P&L.
- Fees/funding.
- Close reason.
- Agent decision summary.

Filters:
- Date range.
- Symbol.
- Side.
- TP / SL / manual / emergency / other.
- Profitable / losing.
- Environment.

Export CSV only for authorized users; redact account identifiers and secrets.

## 7. AI Analysis page

Display:
- Trigger snapshot and data-quality flags.
- Agent 1–5 execution timing and structured outputs.
- Agent 6 final decision.
- Prompt/model/schema versions.
- Provider latency and error state.
- Missing evidence and rejection reasons.

Show AI outputs as untrusted analysis. Do not render arbitrary HTML or markdown from provider responses without sanitization.

## 8. Configuration page

Sections:

### Exchange
- Environment selector: Testnet / Live.
- API key input.
- API secret input.
- Credential test button.
- Masked saved status.
- Account mode and permissions readout.

### ThreeRouter
- API key input.
- Connection test.
- Agent mapping/IDs if configured.
- Timeout and concurrency settings.

### Signal
- Trigger percentage (default 1.5).
- Lookback seconds (default 180).
- Candidate TTL.
- Cooldown.
- Eligible symbol policy.

### Position and risk
- Base margin (default 3 USDT).
- Leverage (default 10x).
- Maximum concurrent positions (default 3).
- Profit reinvestment percentage (default 25%).
- Maximum per-trade allocation.
- Daily loss limit.
- Maximum drawdown.
- Aggregate exposure/risk limit.
- Slippage and fee assumptions.
- Emergency protection deadline.

Every field includes validation, unit, range, and help text. Changing risk settings while running must either be blocked or applied only to future trades with an audit event.

## 9. Control panel

Buttons:
- Start engine.
- Stop new entries.
- Emergency stop.

Start flow:
1. Confirm environment.
2. Run readiness checks.
3. Display account mode, risk limits, API permission status, data/AI/database health, and unknown positions/orders.
4. Start only if all hard gates pass.

Normal Stop:
- Blocks new candidates/entries.
- Keeps position monitor, protective order verification, reconciliation, and cleanup active.

Emergency Stop:
- Blocks all new entries immediately.
- Applies the configured emergency policy to existing positions (protect/flatten behavior must be explicit).
- Requires confirmation and records audit event.
- UI must show progress and final exchange-reconciled outcome.

## 10. Visual system

- Dark-first optional theme with high-contrast text.
- Neutral surfaces and restrained accent colors.
- Green/red only for positive/negative financial direction, never as the sole signal.
- Amber for warning/degraded; red for critical risk/emergency.
- Monospaced numerals for prices, quantities, percentages, and IDs.
- Consistent decimal precision based on symbol filters.
- Responsive layout: desktop-first; mobile supports monitoring and emergency controls, with careful confirmation for destructive actions.
- Accessibility: keyboard navigation, visible focus, semantic tables, labels, and non-color status text.

## 11. Frontend state and data flow

- Initial REST snapshot on page load.
- Authenticated WebSocket stream for live updates.
- Reconnect with exponential backoff.
- After reconnect, request a fresh snapshot before applying deltas.
- Track event sequence or timestamps to avoid stale updates overwriting newer state.
- Use query/cache layer for server state; local component state only for transient UI state.
- Never store API secrets in localStorage, sessionStorage, URL parameters, or client logs.

## 12. Backend design standards

- Pydantic schemas at API and provider boundaries.
- SQLAlchemy ORM models and Alembic migrations.
- Decimal serialization as strings in APIs to avoid binary floating-point loss.
- UTC ISO-8601 timestamps.
- Pagination and filtering for history/log endpoints.
- Structured error envelope with stable error codes.
- Authentication and authorization dependency on all private routes.
- WebSocket authentication and origin validation.
- Separate read-only dashboard service access from trading execution privileges where practical.

## 13. Database model

### `app_config`
- `id`
- `environment`
- `trigger_percentage`
- `trigger_window_seconds`
- `base_margin`
- `leverage`
- `max_concurrent_trades`
- `profit_reinvestment_pct`
- `max_trade_allocation`
- `daily_loss_limit`
- `max_drawdown_pct`
- `max_aggregate_exposure`
- `max_slippage_bps`
- `updated_at`

Secrets should be stored separately in encrypted credential records or an external secret manager, not as plaintext config columns.

### `exchange_credentials`
- `id`
- `exchange`
- `environment`
- `api_key_ciphertext`
- `api_secret_ciphertext`
- `encryption_key_version`
- `created_at`
- `rotated_at`
- `last_tested_at`

### `signal_candidates`
- `id`
- `event_key` (unique)
- `symbol`
- `direction`
- `current_price`
- `reference_price`
- `change_pct`
- `window_seconds`
- `detected_at`
- `expires_at`
- `status`
- `rejection_reason`

### `trades`
- `id`
- `candidate_id`
- `symbol`
- `side`
- `entry_order_client_id`
- `entry_order_id`
- `entry_price`
- `exit_price`
- `position_size`
- `notional`
- `margin_allocation`
- `leverage`
- `take_profit`
- `stop_loss`
- `modeled_max_loss`
- `realized_pnl`
- `fees`
- `funding`
- `status`
- `created_at`
- `closed_at`

### `orders`
- `id`
- `trade_id`
- `client_order_id` (unique)
- `exchange_order_id`
- `order_type`
- `side`
- `reduce_only`
- `quantity`
- `trigger_price`
- `status`
- `submitted_at`
- `updated_at`

### `agent_logs`
- `id`
- `candidate_id`
- `trade_id` nullable
- `agent_name`
- `provider`
- `model_or_agent_id`
- `prompt_version`
- `schema_version`
- `request_hash`
- `response_json`
- `validation_status`
- `latency_ms`
- `created_at`

### `system_logs`
- `id`
- `level`
- `event_code`
- `message_redacted`
- `correlation_id`
- `trade_id` nullable
- `created_at`

### `engine_state`
- `id`
- `state`
- `environment`
- `changed_at`
- `reason`

### `audit_events`
- `id`
- `actor`
- `action`
- `before_json`
- `after_json`
- `correlation_id`
- `created_at`

### `equity_snapshots`
- `id`
- `wallet_balance`
- `account_equity`
- `available_balance`
- `unrealized_pnl`
- `captured_at`

### `margin_scaling_events`
- `id`
- `closed_trade_id`
- `base_margin`
- `realized_net_profit`
- `reinvestment_pct`
- `next_margin`
- `created_at`

## 14. Data integrity and indexes

- Unique index on `orders.client_order_id`.
- Unique index on `signal_candidates.event_key`.
- Index trades by `(status, created_at)` and `(symbol, created_at)`.
- Index agent logs by `(candidate_id, created_at)`.
- Foreign keys enforced.
- Use database transactions for trade intent and state changes.
- Use PostgreSQL row/advisory locks for singleton execution and concurrency in production.
- Store raw provider/exchange payloads only when necessary, with redaction and retention policy.

## 15. Migration and backup

- SQLite and PostgreSQL share SQLAlchemy models, but schema differences must be tested.
- Use Alembic migrations as the only schema-change mechanism.
- Export/import through a controlled migration script; verify row counts, key relationships, timestamps, and financial totals.
- Aiven PostgreSQL connection must use TLS and certificate verification.
- Test backup restoration before live production use.
