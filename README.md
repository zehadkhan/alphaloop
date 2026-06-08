# AlphaLoop

> Autonomous AI trading agent for BNB/USDT on PancakeSwap — BSC testnet.

AlphaLoop combines a large language model (Claude via OpenRouter) with quantitative
technical analysis to generate, backtest, and execute crypto trading strategies
fully autonomously. Every cycle it fetches live market data, computes indicators,
asks an LLM to reason about the setup, validates the strategy against 30 days of
historical data, and only then submits a swap on PancakeSwap V2.

Built for the **DoraHacks BNB Chain AI Agent Hackathon**.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        AlphaLoop Agent                           │
│                                                                  │
│   ┌─────────────┐    every 30 min    ┌──────────────────────┐   │
│   │ APScheduler │──────────────────▶ │   run_agent_cycle()  │   │
│   └─────────────┘                    └──────────┬───────────┘   │
│                                                 │               │
│              ┌──────────────────────────────────┤               │
│              │              │                   │               │
│              ▼              ▼                   ▼               │
│   ┌──────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│   │ CoinMarketCap│  │  OpenRouter │  │   BSC Testnet RPC   │   │
│   │  (quotes +   │  │ Claude 3.5  │  │   PancakeSwap V2    │   │
│   │   OHLCV)     │  │  Sonnet     │  │   web3.py / eth_acc │   │
│   └──────┬───────┘  └──────┬──────┘  └─────────┬───────────┘   │
│          │                 │                    │               │
│          ▼                 ▼                    ▼               │
│   ┌──────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│   │  Indicators  │  │  Backtester │  │    WalletAgent      │   │
│   │  RSI / MACD  │  │ 30-day sim  │  │  sign + broadcast   │   │
│   │  BB / SMA    │  │ pass gate   │  │                     │   │
│   └──────────────┘  └─────────────┘  └─────────────────────┘   │
│                                                                  │
│                    ┌───────────────────┐                        │
│                    │  SQLite (aiosqlite)│                        │
│                    │  strategies        │                        │
│                    │  trades            │                        │
│                    │  agent_runs        │                        │
│                    └───────────────────┘                        │
│                                                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  FastAPI  GET /health  /status  /trades  /strategies     │  │
│   │           POST /run  (manual trigger)                    │  │
│   └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Cycle flow

```
Fetch quote + OHLCV (CMC)
         │
         ▼
Compute indicators (RSI, MACD, BB, SMA)
         │
         ▼
Generate strategy (LLM via OpenRouter)
         │
    action == HOLD ──▶ skip
    confidence < 0.6 ─▶ skip
         │
         ▼
Backtest on last 30 daily candles
         │
    passed == False ──▶ skip
         │
         ▼
Save strategy → DB (status: approved)
         │
         ▼
Execute swap on PancakeSwap V2
         │
         ▼
Save trade → DB  |  Log PnL
         │
         ▼
Save agent_run record → DB
```

---

## Stack

| Layer | Library | Purpose |
|---|---|---|
| API server | FastAPI + uvicorn | REST endpoints, lifespan hooks |
| Scheduler | APScheduler | 30-minute periodic agent cycle |
| Market data | httpx + CMC API | Quotes and OHLCV candles |
| Strategy | OpenRouter (Claude) | LLM reasoning over indicators |
| Indicators | pandas + numpy | RSI, MACD, Bollinger Bands, SMA |
| Backtesting | Pure Python | 30-day historical simulation |
| Execution | web3.py + eth_account | BSC signing and broadcasting |
| DEX | PancakeSwap V2 | BNB ↔ USDT swaps on testnet |
| Database | SQLAlchemy + aiosqlite | Async SQLite ORM |
| Config | python-dotenv | Environment variable loading |

---

## Environment variables

Copy `.env.example` to `.env` and fill in every value before running.

| Variable | Required | Description |
|---|---|---|
| `CMC_API_KEY` | Yes | CoinMarketCap API key — get one free at coinmarketcap.com/api |
| `OPENROUTER_API_KEY` | Yes | OpenRouter key — get one at openrouter.ai |
| `BSC_RPC_URL` | Yes | BSC testnet JSON-RPC endpoint (default provided) |
| `AGENT_WALLET_ADDRESS` | Yes | Your BSC testnet wallet address (0x…) |
| `AGENT_PRIVATE_KEY` | Yes | Private key for the wallet — **never commit this** |
| `TRADING_PAIR` | No | Default `BNB/USDT` |
| `MAX_POSITION_SIZE_USD` | No | Maximum USD per trade. Default `10` |
| `STOP_LOSS_PERCENT` | No | Stop-loss % for the backtester gate. Default `5` |
| `MIN_CONFIDENCE` | No | Minimum LLM confidence to proceed. Default `0.6` |
| `CYCLE_INTERVAL_MINUTES` | No | How often the agent runs. Default `30` |
| `ENVIRONMENT` | No | `testnet` or `mainnet`. Default `testnet` |

> **Security**: `AGENT_PRIVATE_KEY` is loaded from `.env` and never logged or
> stored in the database. Add `.env` to `.gitignore` before committing.

---

## Local setup

### Prerequisites

- Python 3.11+
- A funded BSC testnet wallet
  (faucet: https://testnet.bnbchain.org/faucet-smart)
- CoinMarketCap API key (free tier works)
- OpenRouter API key

### Install and run

```bash
git clone <repo>
cd alphaloop

cp .env.example .env
# Open .env and fill in your keys

pip install -r requirements.txt

# Start the agent (scheduler fires every 30 min)
uvicorn agent.main:app --reload

# Manually trigger one cycle right now
curl -X POST http://localhost:8000/run
```

### Run the test suite (no transactions)

```bash
python tests/test_pipeline.py
```

Tests that require API keys are automatically skipped when the key is absent.
No blockchain transactions are ever sent by the test suite.

---

## Docker

```bash
cp .env.example .env
# fill in .env

docker compose up --build
```

The SQLite database is persisted on the host at `./alphaloop.db` via a named
volume mount, so data survives container restarts.

---

## VPS deployment

Tested on Ubuntu 22.04 LTS with Docker + Docker Compose V2.

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone the repo and configure
git clone <repo>
cd alphaloop
cp .env.example .env
nano .env           # fill in your keys

# 3. Start in detached mode
docker compose up -d --build

# 4. Follow logs
docker compose logs -f

# 5. Check health
curl http://localhost:8000/health

# 6. Restart / update
docker compose pull && docker compose up -d --build
```

To expose port 8000 publicly, place nginx or Caddy in front and proxy to
`localhost:8000`. Add a firewall rule to block direct access to :8000.

---

## API endpoints

All endpoints return JSON.

### `GET /health`

Liveness check. Always returns 200 if the process is up.

```json
{"status": "ok", "environment": "testnet"}
```

### `GET /status`

Last agent run summary and next scheduled run time.

```json
{
  "environment": "testnet",
  "trading_pair": "BNB/USDT",
  "last_run": {
    "id": 12,
    "started_at": "2026-06-09T14:00:00+00:00",
    "completed_at": "2026-06-09T14:00:45+00:00",
    "strategies_generated": 1,
    "trades_executed": 1,
    "total_pnl": 0.12,
    "error_message": null
  },
  "scheduled_jobs": [
    {"id": "agent_cycle", "next_run": "2026-06-09T14:30:00+00:00"}
  ]
}
```

### `GET /trades?symbol=BNB&limit=50`

List of executed trades, newest first.

```json
{
  "count": 3,
  "trades": [
    {
      "id": 5,
      "strategy_id": 8,
      "symbol": "BNB",
      "action": "BUY",
      "amount_usd": 10.0,
      "entry_price": 612.5,
      "exit_price": null,
      "pnl_usd": null,
      "pnl_percent": null,
      "tx_hash": "0xabc…",
      "status": "executed",
      "executed_at": "2026-06-09T14:00:42+00:00",
      "closed_at": null
    }
  ]
}
```

### `GET /strategies?symbol=BNB&status=approved&limit=50`

List of generated strategies. `status` is one of `pending`, `approved`, `rejected`.

### `POST /run`

Manually trigger one agent cycle. Waits for completion and returns the full
cycle summary. Returns `200` on success/skip, `500` on error.

```json
{
  "status": "executed",
  "run_id": 13,
  "strategy_id": 9,
  "trade_id": 6,
  "action": "BUY",
  "tx_hash": "0xdef…",
  "pnl_usd": 0.0,
  "backtest": "PASS | 7 trades (5W/2L) | return=+3.12% | win_rate=71% | …"
}
```

Possible `status` values: `executed`, `skipped`, `error`.

---

## Project layout

```
alphaloop/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
│
├── agent/
│   ├── config.py        — typed env-var config singleton
│   ├── main.py          — FastAPI app + endpoints + lifespan
│   └── scheduler.py     — run_agent_cycle() + APScheduler wiring
│
├── data/
│   ├── cmc_client.py    — async CoinMarketCap client
│   └── indicators.py    — RSI, MACD, Bollinger Bands, SMA, ATR
│
├── strategy/
│   ├── generator.py     — LLM strategy generation via OpenRouter
│   └── backtester.py    — 30-day historical simulation + pass gate
│
├── execution/
│   ├── wallet.py        — WalletAgent: sign + broadcast on BSC
│   └── pancakeswap.py   — PancakeSwap V2 swap executor
│
├── db/
│   └── models.py        — SQLAlchemy async ORM + CRUD helpers
│
└── tests/
    └── test_pipeline.py — end-to-end smoke tests (no transactions)
```

---

## Hackathon tracks

### BNB Chain AI Agent track

AlphaLoop is a fully autonomous on-chain AI agent. It perceives market state,
reasons about it using a frontier LLM, decides whether and how to act, and
executes a real DeFi transaction on BSC — all without human intervention.
The agent loop runs indefinitely, learning the rhythm of the market across
every 30-minute cycle.

### DeFi / DEX integration track

The execution layer integrates directly with PancakeSwap V2 on BSC testnet via
its router ABI. Swap calldata is built with web3.py, signed locally with
eth_account, and broadcast through the public BSC testnet RPC. Slippage
tolerance, deadline, and spend approval are all handled programmatically.

### AI + Quantitative Finance track

Strategy generation is a two-stage pipeline: a deterministic quantitative layer
(RSI, MACD, Bollinger Bands, SMA crossovers) produces structured indicator
snapshots, which are then reasoned over by Claude (via OpenRouter). The LLM
output is validated against a strict JSON schema and gated by a 30-day backtest
before any capital is committed — combining the interpretability of classical
quant with the reasoning flexibility of LLMs.

---

## Safety notes

- This project targets **BSC testnet only** by default (`ENVIRONMENT=testnet`).
  `MAX_POSITION_SIZE_USD=10` caps every trade at $10 USD equivalent.
- The private key is loaded from `.env` at startup and never stored in the DB
  or written to any log line.
- The backtester acts as a mandatory quality gate: strategies that do not show
  positive return and >50% win rate on recent history are silently dropped.
- No mainnet deployment is recommended without additional risk controls
  (position sizing, drawdown limits, circuit breakers).
