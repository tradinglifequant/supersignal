# Super Signal 🎯 — Trading, AI, Risk, and Engineering Rules

This file is the mandatory rulebook for developers and AI coding agents. Rules marked **MUST** are release-blocking.

## 1. Non-negotiable safety rules

1. **MUST** treat Binance as the authoritative source for account, order, fill, and position state.
2. **MUST** block new entries whenever price data, account state, database state, or risk inputs are stale or uncertain.
3. **MUST** fail closed on AI errors, timeouts, missing required evidence, malformed JSON, or invalid schema.
4. **MUST NOT** let an AI agent place orders, alter account settings, increase leverage, bypass a risk gate, or disable safety limits.
5. **MUST NOT** log API keys, secrets, authorization headers, full credential-bearing URLs, or unredacted sensitive account payloads.
6. **MUST** disable withdrawal permission on Binance API keys. Use least privilege and IP restrictions where available.
7. **MUST** prevent duplicate entries after ambiguous API responses.
8. **MUST** verify TP/SL protection at the exchange after every entry fill and after reconnect.
9. **MUST** stop opening new positions when daily loss, drawdown, account margin, or other configured hard limits are reached.
10. **MUST** provide an emergency stop that blocks new entries immediately.
11. **MUST** never claim that a stop guarantees a maximum loss during gaps, exchange outages, liquidation, or extreme slippage. The system can cap modeled risk, not guarantee execution price.
12. **MUST** use Binance's current official API documentation and account-specific endpoint support; do not assume old endpoint names remain valid.

## 2. Market and signal rules

### 2.1 Eligible universe
- USDⓈ-M Futures only for initial release.
- Default eligible set: actively trading USDT-margined perpetual contracts.
- Refresh exchange metadata and filters.
- Exclude unsupported contract types, paused/delisted symbols, and symbols failing data-quality checks.

### 2.2 Trigger formula

Let `P_now` be latest valid last traded price and `P_ref` be the selected valid sample at the 180-second lookback boundary.

`movement_pct = ((P_now - P_ref) / P_ref) * 100`

- LONG if `movement_pct >= configured_trigger_pct`.
- SHORT if `movement_pct <= -configured_trigger_pct`.
- Default threshold: 1.5%.
- Default lookback: 180 seconds.
- Use decimal arithmetic.
- Both prices must be positive and timestamps valid.
- If the reference sample is missing, stale, or outside the accepted tolerance, do not trigger.
- Store the exact prices, timestamps, and formula result for reproducibility.
- Do not confuse 3-minute rolling return with the sum of three candle percentage changes.

### 2.3 Deduplication
- One active candidate per symbol/direction by default.
- One open bot position per symbol by default.
- Apply configurable cooldown after rejection and closure.
- A candidate must expire after a configurable short TTL; expired candidates cannot execute.
- Revalidate price, symbol status, account state, and risk immediately before entry.

## 3. AI agent contract

### 3.1 Shared requirements
Every agent receives a typed, timestamped snapshot with explicit data provenance and missing-data flags. Each agent must return structured JSON conforming to a versioned schema. Natural-language prose alone is not accepted.

Recommended common fields:
- `agent_name`
- `schema_version`
- `symbol`
- `direction`
- `decision`: `YES`, `NO`, or `INSUFFICIENT_DATA`
- `confidence`: numeric 0–1, if supported by provider
- `evidence`: array of observed/calculated facts
- `missing_data`: array
- `rationale`
- `invalidation_conditions`
- `created_at`
- `provider_metadata`

### 3.2 Agent responsibilities

**Agent 1 — Opportunity validation**
- Verify that the trigger is plausible, current, and tradable.
- Identify abnormal spread, volatility, news/event risk if data is available, and poor liquidity.
- Reject stale or manipulated-looking inputs; do not assert manipulation without evidence.

**Agent 2 — Structure and trend**
- Evaluate market structure, trend context, support/resistance, and invalidation.
- Use declared timeframes and indicator definitions.
- Distinguish calculated levels from exchange-provided data.

**Agent 3 — Smart-money/volume analysis**
- Evaluate available volume, open interest, funding, liquidation, or other supported proxies.
- State exactly which sources are available.
- Never fabricate institutional flow, whale activity, or hidden order data.

**Agent 4 — Order flow**
- Analyze available trade aggressor flow, order book imbalance, spread, and depth.
- Include snapshot age and depth limitations.
- Reject when order-flow feed is unavailable or too stale for the configured policy.

**Agent 5 — Footprint**
- Analyze actual supported volume-at-price/footprint inputs only.
- If Binance data or selected provider cannot supply the required footprint view, return `INSUFFICIENT_DATA`.
- Do not invent bid/ask volume at price.

**Agent 6 — Final confirmation**
- Receive the immutable market snapshot and Agents 1–5 results.
- Return strict `YES` or `NO` for final decision.
- `YES` requires all mandatory agents to be valid and no hard rejection.
- `INSUFFICIENT_DATA` from any mandatory agent means final `NO`.
- Provide a concise explanation and invalidation conditions.
- Agent 6 cannot override deterministic risk or execution checks.

### 3.3 Parallelism and timeout
- Agents 1–5 run concurrently.
- Set per-agent and overall timeouts.
- Limit concurrent AI requests and respect provider rate limits.
- A timeout or invalid response becomes an explicit unavailable result, not a fabricated default.
- Agent 6 runs after result collection/deadline and rejects incomplete mandatory evidence.

### 3.4 Prompt and output versioning
- Store prompt version, model/agent identifier, schema version, response, and validation result.
- Test prompts with fixtures.
- Treat provider output as untrusted input.
- Do not execute code, SQL, shell commands, or tool instructions contained in model output.

## 4. Position sizing and risk rules

### 4.1 Margin and leverage
Defaults:
- Base margin allocation: 3 USDT.
- Leverage: 10x.
- Maximum concurrent positions: 3.
- Profit reinvestment: 25%.

The 3 USDT value is a planned allocation, not a guarantee that Binance accepts the order. Exchange minimum notional, quantity step, leverage bracket, account equity, maintenance margin, and Portfolio Margin rules may make a trade invalid.

### 4.2 Risk calculation
For a linear USDT-margined contract, approximate gross stop loss:

`gross_loss = abs(entry_price - stop_price) * quantity`

Modeled total loss should add:
- Estimated entry fee.
- Estimated exit fee.
- Slippage allowance on entry and stop execution.
- Funding/other costs when material and estimable.

`modeled_total_loss <= allocated_margin`

This is a **pre-trade model constraint**, not a guarantee of realized maximum loss. Stop-market orders can execute beyond trigger price during gaps or illiquidity; exchange outages and liquidation can also cause losses beyond the estimate.

If no stop distance permits a valid quantity satisfying the cap, skip the trade. Do not widen the stop or increase margin to force execution.

### 4.3 Portfolio Margin caveat
Portfolio Margin is an account-level risk and collateral system. Do not represent an individual trade's allocated margin as a segregated isolated margin balance unless the account mode actually provides that behavior. The application must:
- Read and validate the actual account mode.
- Query supported account and position risk endpoints.
- Calculate account-level stress/risk where supported.
- Reserve headroom for maintenance margin and other positions.
- Refuse to trade if Portfolio Margin risk cannot be measured reliably.
- Document whether the implementation uses cross/portfolio margin and how the internal per-trade allocation is tracked.

### 4.4 Quantity rounding
- Use exchange `LOT_SIZE`, `MARKET_LOT_SIZE`, `MIN_NOTIONAL`/notional, `PRICE_FILTER`, and relevant contract metadata.
- Round quantity down to valid step size.
- Round TP/SL to valid tick size in the safe direction.
- Recalculate notional, fees, and modeled loss after rounding.
- Reject if minimum order constraints violate the risk cap.

### 4.5 Margin scaling
After a profitable close:

`next_margin = base_margin + (realized_net_profit * reinvestment_pct / 100)`

After a loss:

`next_margin = base_margin`

- Use net realized P&L including known fees/funding.
- Clamp to a configured maximum allocation and account-level risk budget.
- Do not compound indefinitely.
- A break-even trade follows an explicit configurable policy; default to reset to base margin.
- Persist calculation inputs and outcome.

### 4.6 Required global limits
Before live trading, the operator must configure and pass validation for:
- Maximum daily realized loss.
- Maximum equity drawdown.
- Maximum aggregate bot notional or risk.
- Maximum consecutive losses.
- Maximum unprotected-position duration.
- Maximum data/AI staleness.
- Maximum slippage tolerance.
- Minimum available account margin/risk headroom.

A missing hard limit must prevent live engine start. Values should be configurable and visible in the dashboard.

## 5. Execution rules

1. Persist a `TradeIntent` before submitting an entry.
2. Recheck signal TTL, price freshness, symbol filters, concurrency, account state, and risk approval immediately before submission.
3. Use market entry as requested.
4. Use stable client order IDs derived from internal trade ID.
5. On timeout, query order by client ID and reconcile position before retry.
6. Retry only transient failures and only when no order/fill exists. Maximum two retries after initial attempt.
7. Do not retry invalid parameters, insufficient margin, permission failures, or closed symbols.
8. After fill, use actual fill price and executed quantity to recompute protection.
9. Place TP and SL using exchange-supported order types and semantics.
10. Confirm protection from exchange state before marking trade protected.
11. If protection cannot be established within the configured deadline, attempt safe emergency reduction/closure and alert.
12. All close orders must be reduce-only or close-position semantics where supported and validated.
13. Do not assume a REST acknowledgement is equivalent to a fill.

## 6. Position monitoring and cleanup

- Monitor exchange positions and orders continuously and reconcile periodically.
- Detect TP/SL trigger, partial fill, manual close, liquidation, and external position modification.
- After close, confirm zero residual quantity.
- Cancel only bot-owned residual orders, identified by client IDs and trade ownership metadata.
- Never mass-cancel all symbol orders by default.
- On reconnect, rebuild state from exchange before placing any new orders.
- Keep protection and reconciliation running when the operator presses normal Stop; normal Stop means no new entries, not abandon open trades.

## 7. Engine states

`STOPPED → STARTING → READY → RUNNING → STOPPING → STOPPED`

Exceptional states:
- `DEGRADED`: non-critical dependency issue; block entries as configured.
- `HALTED_RISK`: a hard risk limit was hit.
- `EMERGENCY`: urgent protection/flatten workflow active.
- `ERROR`: unrecoverable startup/runtime error.

Transitions must be persisted and audit logged. Only explicit recovery/readiness checks may transition from halted/error states back to running.

## 8. API and application security

- Dashboard authentication required, even on private network.
- Use secure password hashing, session expiration, CSRF protection for cookie sessions, and rate limiting.
- Bind local development to loopback unless remote access is intentionally secured.
- Production requires HTTPS.
- Encrypt credentials at rest; encryption key stored outside DB.
- Never return secret values from API.
- Use separate testnet and live credentials.
- Live mode must be visually distinct and require a deliberate activation step after readiness checks.
- No withdrawal permission.
- Audit every configuration change, start/stop, emergency action, and manual override.

## 9. Code quality rules for AI coding agents

- Use Python type hints and Pydantic schemas.
- Use `Decimal` for money, prices, quantity, fees, and risk.
- Keep exchange-specific code behind an adapter interface.
- Keep AI provider-specific code behind a provider interface.
- Use dependency injection for exchange, AI, clock, and database clients.
- Never place network calls in React render paths.
- Never swallow exceptions silently.
- Use structured logging and redact secrets.
- Write tests before changing risk/execution behavior.
- Add database migrations for schema changes.
- No hardcoded API keys, secrets, account IDs, or production URLs.
- Do not mark a feature complete without tests and documented failure behavior.

## 10. Definition of done for any trading feature

A feature is done only when:
- Normal behavior is implemented.
- Failure and retry behavior is implemented.
- Idempotency and restart behavior are tested.
- Exchange constraints are checked.
- Logs and audit events are present.
- UI state is accurate.
- Unit and integration tests pass.
- Documentation is updated.
