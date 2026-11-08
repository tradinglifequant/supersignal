# Going live: the staged path to real-money execution

This document is the operator runbook for moving Super Signal from mock to real
Portfolio Margin trading. It is deliberately ordered: **each stage must be
completed and observed before the next one is enabled.**

> Nothing in this repository enables real-money trading by default. Four
> independent configuration switches plus a passing exchange preflight are
> required, and any one of them blocks execution on its own.

---

## Stage 0 — Where the system is now (default)

```
TRADING_ENV=none          # no order can reach any exchange
AI_GATE_MODE=threerouter  # fails closed without THREEROUTER_API_KEY
LIVE_TRADING_OPT_IN=false
KILL_SWITCH=false
```

`TRADING_ENV=none` means the trading gate refuses every exposure-increasing
order regardless of any other setting. Reduce-only and close-position orders are
always permitted, because being unable to close a position is worse than being
unable to open one.

---

## Stage 1 — Decide the AI gate

| `AI_GATE_MODE` | Behaviour |
|---|---|
| `threerouter` | Calls the five LLM agents. **Fails closed** (final NO) if `THREEROUTER_API_KEY` is unset. |
| `deterministic` | Local rule engine in `app/ai/deterministic_gate.py`. No network, fully auditable. |
| `reject_all` | Approves nothing. Useful to run the pipeline and inspect signals without trading. |

The deterministic gate is **not a bypass**. It emits the same five per-agent
verdicts and the same fail-closed aggregation, so agent logs and the audit trail
are identical. Its rules reject when:

- any of `candles_1m`, `orderbook`, `funding_rate`, `volume_24h` is unavailable
- the price feed is older than 10 s, or the symbol is not `TRADING`
- 24 h quote volume is under the liquidity floor
- the trigger exceeds the blow-off band
- 1 m structure drifts against the signal direction
- funding is extreme, or already crowded toward the signal direction
- top-10 depth does not favour the direction, or the spread is too wide

Tune the thresholds at the top of `deterministic_gate.py`.

---

## Stage 2 — Real Binance **testnet**

```
BINANCE_API_KEY=<testnet key>
BINANCE_API_SECRET=<testnet secret>
BINANCE_TESTNET=true
TRADING_ENV=testnet
PORTFOLIO_MARGIN=false
```

Testnet keys come from <https://testnet.binancefuture.com>. The engine will now
place real orders against the testnet exchange. **Run it for at least
`REQUIRE_TESTNET_SOAK_HOURS` (default 24) before Stage 3** — the gate enforces
this and will refuse live entries until the soak is recorded.

Verify with `GET /api/engine/preflight?refresh=true`. It must show
`"passed": true` and no blocking reasons.

---

## Stage 3 — Production Portfolio Margin

Portfolio Margin accounts do **not** use the standard futures order endpoint.
With `PORTFOLIO_MARGIN=true` the adapter routes:

| Operation | Endpoint |
|---|---|
| place / query / cancel order | `/papi/v1/um/order` |
| open orders | `/papi/v1/um/openOrders` |
| cancel all | `/papi/v1/um/allOpenOrders` |
| position risk | `/papi/v1/um/positionRisk` |
| account / balance | `/papi/v1/account`, `/papi/v1/balance` |

```
BINANCE_API_KEY=<production key>
BINANCE_API_SECRET=<production secret>
BINANCE_TESTNET=false
PORTFOLIO_MARGIN=true
TRADING_ENV=live
LIVE_TRADING_OPT_IN=true
LIVE_TRADING_ACKNOWLEDGEMENT=I_UNDERSTAND_REAL_MONEY_RISK
KILL_SWITCH=false
```

### API key requirements

Create a dedicated key and grant **only**:

- ✅ Enable Reading
- ✅ Enable Futures
- ❌ **Enable Withdrawals — leave this OFF**

The preflight reads `canWithdraw` from the account and **refuses to trade** if it
is true (`REJECT_KEY_WITHDRAWAL=true` by default). Restrict the key to your
server's IP as well.

### Live will still be refused until preflight passes

The gate additionally checks, against the exchange itself:

- connectivity
- `canTrade` is true
- `canWithdraw` is false
- local clock drift is within `MAX_CLOCK_DRIFT_MS` (default 1000 ms)
- every hard risk limit is configured and positive
- the recorded testnet soak meets `REQUIRE_TESTNET_SOAK_HOURS`

---

## Stage 4 — Set risk ceilings before you arm it

```
MAX_ORDER_NOTIONAL=100      # hard per-order ceiling, quote currency
MAX_AGGREGATE_EXPOSURE=1000
MAX_TRADE_ALLOCATION=100
DAILY_LOSS_LIMIT=50
MAX_DRAWDOWN_PCT=10
MAX_CONCURRENT_TRADES=3
MAX_CONSECUTIVE_LOSSES=5
MAX_SLIPPAGE_BPS=50
```

`MAX_ORDER_NOTIONAL` is enforced by the trading gate itself, independently of the
risk engine, and it is the last thing standing between a sizing bug and a large
order.

---

## Emergency controls

| Action | Effect |
|---|---|
| `KILL_SWITCH=true` + restart | Blocks all new entries immediately; exits still work. |
| `POST /api/engine/stop` | Stops new entries; the position monitor keeps protecting open trades. |
| `POST /api/engine/emergency-stop` | Flattens every open position, then stops. |

---

## What is still unverified

These are genuine gaps, not formalities. Do not treat a green test suite as
covering them.

- **No live or testnet exchange contract has been verified from this
  environment** — there is no network path to Binance here, so every PM endpoint
  in this document is implemented against the published API but has not been
  exercised against a real account.
- Protective (SL/TP) and reducing order paths have not been confirmed on a real
  PM account, including behaviour during partial fills and exchange outages.
- Portfolio Margin specifics that need live verification: `uniMMRSetting` /
  maintenance-margin interaction, position-side mode (`Hedge` vs `One-way`),
  per-symbol leverage application via `/papi/v1/um/leverage`, and auto-exchange
  of collateral.
- No reconnect soak, no 24 h continuous lifecycle run, no PostgreSQL/Windows
  staging rehearsal, no independent security review.

Until those are done, `TRADING_ENV=live` is available but should be treated as
unproven.
