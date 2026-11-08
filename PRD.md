# Super Signal 🎯 — Product Requirements Document

**Status:** Draft baseline for implementation  
**Product:** AI-powered Binance USDT-M Futures trading system  
**Primary operator:** Single-user installation, initially on Windows, later migrated to an online deployment  
**Document role:** Product scope, requirements, acceptance criteria, and non-functional requirements

## 1. Product vision

Super Signal is an automated trading application that scans Binance USDⓈ-M Futures markets for rapid price movements, evaluates each candidate through a six-agent AI verification pipeline, and—when the final decision is affirmative—calculates and executes a risk-bounded trade. It continuously verifies protective orders, monitors positions, and cleans up residual orders after closure.

The application includes a React dashboard backed by FastAPI. It is developed and tested on a Windows PC, then deployed to an online application runtime/server with Aiven-managed PostgreSQL for production persistence.

## 2. Goals

1. Monitor all eligible, actively trading Binance USDⓈ-M perpetual symbols using live market data.
2. Detect a configurable absolute price change, default **1.5% over a rolling 3-minute window**, using last-traded price.
3. Avoid duplicate or stale signals and enforce configurable concurrency limits.
4. Run Agents 1–5 as parallel analytical tasks after initial candidate validation; Agent 6 aggregates their results and returns a strict `YES` or `NO`.
5. Calculate position quantity, entry reference, take-profit, and stop-loss with explicit risk checks.
6. Execute market entries and protective exit orders through Binance Futures APIs.
7. Monitor exchange state as the source of truth, recover from transient failures, and enter a safe state when protection cannot be verified.
8. Provide live configuration, controls, positions, history, logs, and performance metrics.
9. Keep credentials out of source code, logs, browser storage, and version control.
10. Support local Windows development and a controlled production migration.

## 3. Non-goals

- No guarantee of profitability or prediction accuracy.
- No autonomous withdrawal, transfer, or asset-management functionality.
- No support for COIN-M Futures in the initial release.
- No copy trading, social trading, or public multi-tenant user accounts in the initial release.
- No AI authority to bypass deterministic risk rules or exchange constraints.
- No claim that a model-generated entry/TP/SL is safe without deterministic validation.

## 4. Users and operating model

The initial product is a single-operator application. The operator configures credentials and risk settings, verifies account mode and permissions, then starts the engine. Fully automated live trading is the requested operating mode after configuration; nevertheless, first-run readiness checks, explicit live-mode activation, emergency stop, and hard risk gates are mandatory safeguards.

## 5. Fixed baseline decisions

| Area | Decision |
|---|---|
| Exchange market | Binance USDⓈ-M Futures |
| Account | Portfolio Margin account, subject to endpoint and product eligibility verification |
| Trigger source | Last traded price |
| Trigger threshold | Absolute move of 1.5% by default |
| Trigger window | Rolling 180 seconds |
| Market data | Binance WebSocket streams; 1-minute candles may support context |
| Entry | Market order |
| AI topology | Agents 1–5 in parallel; Agent 6 final aggregation |
| Base margin | 3 USDT default, configurable |
| Leverage | 10x default, configurable |
| Concurrent positions | 3 default, configurable |
| Win scaling | Next margin = base margin + configured percentage of realized net profit |
| Loss scaling | Reset next margin to base margin |
| Risk cap | Worst-case modeled loss must not exceed allocated trade margin, including estimated fees and slippage |
| Dashboard | React + FastAPI |
| Local development | Windows PC |
| Production data | Aiven for PostgreSQL |
| Local data | SQLite |
| Production app runtime | Online server or Aiven Runtime, selected during deployment |
| Live operation | Automated after readiness and risk checks |

## 6. Functional requirements

### FR-01 — Market universe

- Discover eligible USDⓈ-M symbols from exchange metadata.
- Include only symbols that are trading and permitted by the configured product policy (initially USDT-margined perpetual contracts).
- Refresh symbol metadata periodically and on exchange reconnect.
- Exclude delisted, paused, unsupported, or otherwise ineligible contracts.
- Respect exchange rate limits and WebSocket stream limits; shard subscriptions where necessary.

**Acceptance:** The scanner lists the current eligible symbol universe and records why a symbol is excluded.

### FR-02 — Price movement trigger

For symbol `s`, define:

`change_pct = ((last_price_now - last_price_180s_ago) / last_price_180s_ago) * 100`

- If `change_pct >= trigger_percentage`, generate a LONG candidate.
- If `change_pct <= -trigger_percentage`, generate a SHORT candidate.
- Use exchange event timestamps and monotonic local receipt times to detect stale data.
- Require a valid historical sample at or before the rolling-window boundary; define and test interpolation/nearest-sample behavior.
- Trigger threshold and window are configurable, with defaults of 1.5% and 180 seconds.
- Apply cooldown/deduplication per symbol and direction; do not generate a new trade while an equivalent candidate is already processing or an open position exists unless explicitly configured.
- Do not infer a signal from missing, stale, out-of-order, or malformed prices.

**Acceptance:** Unit tests cover positive, negative, exact-threshold, below-threshold, zero/invalid price, stale data, out-of-order ticks, and rolling-window boundaries.

### FR-03 — AI verification

- On a valid trigger, collect a timestamped market snapshot and run Agents 1–5 concurrently.
- Agent 1 checks whether the opportunity is valid and tradable.
- Agent 2 assesses market structure, trend, support, resistance, and invalidation.
- Agent 3 assesses smart-money/volume-derived evidence and explicitly labels unavailable or inferred data.
- Agent 4 assesses order-flow evidence using available trades, book, and/or flow data.
- Agent 5 assesses footprint/volume-at-price evidence. If the required feed is unavailable, it must return `INSUFFICIENT_DATA`, not fabricate footprint data.
- Agent 6 receives the original snapshot and all five results, then returns a strict machine-readable `YES` or `NO`, confidence, rationale, and invalidation conditions.
- Missing, timed-out, malformed, contradictory, or low-quality evidence must fail closed (`NO`).
- AI output is advisory; deterministic eligibility and risk checks always take precedence.

**Acceptance:** Mock tests verify parallel invocation, timeouts, malformed responses, missing data, and Agent 6 rejection.

### FR-04 — Position sizing and risk

- Calculate quantity from allocated margin, leverage, entry reference, contract rules, and exchange precision.
- Treat `margin` as the planned isolated trade allocation only if the selected account/product mode actually supports the intended margin semantics. Portfolio Margin is account-level cross-collateralized; do not assume an isolated per-position liquidation boundary.
- Calculate worst-case loss from entry, stop price, quantity, taker fees, expected slippage, and relevant funding/close costs where applicable.
- Reject any trade whose modeled maximum loss exceeds allocated margin.
- Validate minimum quantity, step size, minimum notional, tick size, leverage brackets, position limits, and available account margin.
- AI may propose TP/SL levels; deterministic code validates direction, distance, tick rounding, reward/risk policy, and loss cap.
- If no valid stop can be placed or risk cannot be bounded, do not enter.

**Acceptance:** Property-based and unit tests prove that accepted trades meet configured risk cap under the documented model; invalid/rounded stop levels are rejected.

### FR-05 — Trade execution

- Place a market entry only after all gates pass.
- Use a unique internal trade ID and deterministic client order IDs for idempotency.
- Retry transient submission failures at most two additional attempts only when order state is known to be absent. If submission outcome is ambiguous, query exchange order/position state before retrying to prevent duplicate exposure.
- Do not retry non-retryable errors (invalid quantity, insufficient margin, permission, symbol status, invalid parameters).
- Reconcile fills and use actual average fill price and executed quantity to recalculate protective orders and risk.
- Skip the candidate after persistent failure and record the reason.

**Acceptance:** Mocked exchange tests prove no duplicate entry is created after timeout/ambiguous response.

### FR-06 — TP/SL protection and monitoring

- Place protective orders immediately after entry fill is confirmed.
- Use exchange-native conditional/algorithmic order mechanisms supported by the account and current Binance API.
- Prefer reduce-only/close-position semantics where supported and appropriate.
- Verify that protective orders are accepted and remain present.
- If a protective order is rejected or missing, retry a safe repair path; if protection cannot be established promptly, reduce or close the position using an emergency policy.
- Never create a reverse/increasing position as a fallback.
- Track partial fills, partial closes, trigger-price type, working type, and order lifecycle.
- The exchange is authoritative; local state is reconciled against exchange positions and open orders.

**Acceptance:** Tests cover missing TP, missing SL, rejected protective order, partial fill, partial close, disconnect, and emergency flatten behavior.

### FR-07 — Dynamic margin scaling

Default formula after a profitable closed trade:

`next_margin = base_margin + (realized_net_profit * profit_reinvestment_pct / 100)`

- Use realized net profit after fees and funding where available.
- After a loss, reset to base margin.
- Clamp to configured maximum per-trade allocation and available account risk budget.
- A win must not increase exposure beyond global risk and concurrency controls.
- Persist the calculation inputs and resulting next margin for auditability.
- Default reinvestment percentage: 25%.

### FR-08 — Concurrency and account guardrails

- Maximum concurrent open positions defaults to 3.
- Enforce the limit atomically across workers using database transactions/locks or a single execution coordinator.
- Count exchange-discovered positions, not only local OPEN rows.
- Enforce configurable maximum total notional, daily loss, drawdown, and consecutive-loss circuit breakers before live operation. Safe defaults must be defined before enabling live mode.
- Prevent simultaneous opposite positions on the same symbol unless hedge mode is deliberately supported and tested. Initial release should use one-way mode unless account configuration requires otherwise.
- Validate account mode, position mode, margin mode, and leverage before start.

### FR-09 — Cleaner and reconciliation

- After a position is confirmed closed, inspect open orders for that symbol and trade's client order IDs.
- Cancel only orders belonging to the bot/trade; do not blindly cancel unrelated manual orders.
- Confirm cancellation and zero residual bot exposure.
- Reconcile local and exchange state on startup, reconnect, and periodically.
- Flag manual trades or unknown orders for dashboard visibility.

### FR-10 — Dashboard

The React dashboard must include:

- Secure configuration form for Binance API credentials and ThreeRouter API key.
- Trigger threshold, window, base margin, leverage, concurrency, reinvestment percentage, and risk limits.
- Start/stop controls and live/testnet environment indicator.
- Readiness checks and clear warnings.
- Starting balance, current equity, realized/unrealized P&L, win rate, trade count, and drawdown.
- Scanned symbol list and trigger events.
- Open positions with side, quantity, entry, mark price, TP, SL, margin allocation, unrealized P&L, and protection status.
- Closed trade history and filters.
- Agent decision trace, exchange errors, system logs, and audit events.
- WebSocket/SSE live updates with reconnect behavior.

### FR-11 — Configuration and secrets

- Never expose API secrets to the browser after save.
- Store secrets using OS-protected local secret storage or authenticated encryption with a key outside the database; in production use the deployment's secret manager/environment injection.
- Mask credentials in UI and logs.
- Require least-privilege Binance API key permissions; withdrawals must be disabled.
- Support IP allowlisting when available.
- Provide secret rotation and connection-test flows.
- Never commit `.env`, database files, private keys, or API tokens.

## 7. Default configuration

| Setting | Default | Validation |
|---|---:|---|
| Trigger threshold | 1.5% | Positive, configurable |
| Trigger window | 180 seconds | Positive integer |
| Base margin | 3 USDT | Above exchange minimum and within account risk budget |
| Leverage | 10x | Must be allowed by symbol/account bracket |
| Max concurrent trades | 3 | Integer >= 1 |
| Profit reinvestment | 25% | 0–100% |
| Execution retries | 2 retries after initial attempt | Only safe transient retry |
| AI parallel timeout | Configurable | Timeout fails closed |
| Environment | Testnet during development | Live requires readiness gate |
| Daily loss limit | Must be configured before live start | Hard stop |
| Max drawdown | Must be configured before live start | Hard stop |

## 8. KPI definitions

- **Starting balance:** account balance snapshot captured at selected reporting-period start.
- **Current equity:** exchange-reported account equity, including unrealized P&L as defined by the account API.
- **Realized P&L:** sum of realized trade P&L net of known fees/funding.
- **Unrealized P&L:** exchange-reported open-position P&L.
- **Win rate:** profitable closed trades / all closed trades × 100; breakeven trades are not wins.
- **Total trades:** count of unique executed trade lifecycles, not order attempts.
- **Drawdown:** decline from the peak equity in the selected measurement period.

## 9. Non-functional requirements

- Async market-data and task processing; no blocking network calls in event loop.
- Structured logs with correlation IDs and redaction.
- Durable state transitions and transactional persistence.
- Reconnect with exponential backoff and jitter.
- API timeouts, bounded retries, circuit breakers, and rate-limit handling.
- Health/readiness endpoints.
- UTC timestamps in storage; localized display in dashboard.
- Database migrations with Alembic.
- Unit, integration, contract, and end-to-end tests.
- Graceful shutdown that stops new entries, persists state, and leaves existing positions protected.
- Performance objective: scanner must process all subscribed symbols without unbounded queue growth; establish measured latency budgets during load testing.

## 10. Release acceptance checklist

- [ ] All eligible symbols are discovered and monitored.
- [ ] Trigger logic passes boundary and stale-data tests.
- [ ] Agents 1–5 execute concurrently and Agent 6 aggregates deterministically.
- [ ] Missing or invalid AI evidence fails closed.
- [ ] Position sizing honors symbol filters and account constraints.
- [ ] Risk calculation includes fees and slippage assumptions.
- [ ] Ambiguous order outcomes cannot create duplicate entries.
- [ ] TP/SL are verified on the exchange after fills.
- [ ] Emergency protection policy is tested.
- [ ] Cleaner does not cancel unrelated manual orders.
- [ ] Reconciliation survives process restart and network interruption.
- [ ] Secrets are encrypted/redacted and never sent to frontend.
- [ ] Testnet end-to-end test passes.
- [ ] Live readiness checks and emergency stop are validated.
- [ ] Local SQLite to Aiven PostgreSQL migration is rehearsed and verified.
