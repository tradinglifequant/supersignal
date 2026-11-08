# ADRs — Super Signal

## ADR 001: Exchange Adapter Interface
- **Decision:** Keep Binance-specific code behind `ExchangeAdapter` interface.
- **Context:** Portfolio Margin vs One-way, fapi vs papi endpoints evolve.
- **Consequence:** Easy to swap mock/testnet/live, add validation layers.

## ADR 002: Single Process Trading Worker Initially
- **Decision:** One active worker; dashboard/API can scale separately.
- **Context:** SQLite unsafe for multi-instance; PG advisory locks not yet tested.
- **Consequence:** Simplicity, avoids split-brain duplicate orders.

## ADR 003: Decimal for All Financial Calculations
- **Decision:** Python `Decimal` everywhere; API serializes as strings.
- **Context:** Binary float loses precision on tick/qty/min_notional checks.
- **Consequence:** Slight verbosity, but correctness required.

## ADR 004: Fail-Closed AI Pipeline
- **Decision:** Missing/timeout/malformed agent output → final NO, no trade.
- **Context:** AI is advisory, never risk authority.
- **Consequence:** More rejected candidates, safer capital.

## ADR 005: SQLite Local, Aiven PG Production
- **Decision:** SQLAlchemy models + Alembic support both; TLS enforced for PG.
- **Context:** Windows dev vs online production (per specs).
- **Consequence:** Need to test PG-specific constraints.

## ADR 006: ClientOrderId Idempotency
- **Decision:** Deterministic `newClientOrderId` from trade ID; query-before-retry.
- **Context:** Binance ambiguous timeouts can cause duplicate exposure.
- **Consequence:** All orders traceable to internal trade intent.

## ADR 007: Protection Verification via Exchange State
- **Decision:** Never assume REST ack = protection; poll `openOrders`/`positionRisk`.
- **Context:** TP/SL can be rejected after ack due to price/limits.
- **Consequence:** Extra API calls but guarantees verified protection or emergency close.
