# AlphaLoop

> Autonomous AI trading agent for BNB/USDT on BSC — built for the **BNB HACK × CoinMarketCap × Trust Wallet $36,000 hackathon**.

AlphaLoop uses Claude AI to generate, backtest, and autonomously execute crypto trading strategies on BSC mainnet via PancakeSwap V2. Execution is handled by the Trust Wallet Agent Kit (TWAK) — the agent holds its own keys and signs every transaction locally.

**Hackathon:** [dorahacks.io/hackathon/bnbhack-twt-cmc](https://dorahacks.io/hackathon/bnbhack-twt-cmc)
**Live trading window:** June 22–28, 2026 UTC

---

## Wallet Addresses

| Wallet | Address | Purpose |
|--------|---------|---------|
| **TWAK (active)** | `0x73Fb7fA92979dCc7E537Fe4159114f5F70727C7B` | Competition trading wallet — fund this one |
| web3.py (fallback) | `0x9FF88b9333C161c8542Bd817C1FF422f89210866` | Used only if TWAK_REST_URL is not set |

**Send BNB to: `0x73Fb7fA92979dCc7E537Fe4159114f5F70727C7B`**
Network: BSC / BEP-20 (NOT BEP-2, NOT ERC-20)
Minimum: 0.02 BNB (~$12) | Recommended: 0.05 BNB (~$30)

---

## Competition Launch Checklist

### Before June 22 — required

- [ ] Fund TWAK wallet with ≥ 0.02 BNB on BSC mainnet
- [ ] Set `.env` for mainnet (see section below)
- [ ] Start TWAK server: `twak serve --rest --port 7777`
- [ ] Register on-chain: `twak compete register`
- [ ] Verify registration on BscScan: `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`
- [ ] Submit project on DoraHacks (early draft is fine)
- [ ] Start agent: `docker compose up -d`

### June 22–28 — do not touch

- Keep `twak serve --rest --port 7777` running
- Keep `docker compose up -d` running (`restart: unless-stopped` handles crashes)
- Do NOT change `.env` or restart containers unless the agent is down

---

## .env for Mainnet (June 22)

```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-...
CMC_API_KEY=...

# Wallet
AGENT_PRIVATE_KEY=0x...        # fallback only — TWAK is the primary signer
AGENT_WALLET_ADDRESS=0x9FF88b9333C161c8542Bd817C1FF422f89210866

# Network — MAINNET
ENVIRONMENT=mainnet
BSC_RPC_URL=https://bsc-dataseed.binance.org/
DRY_RUN=false

# TWAK
TWAK_REST_URL=http://localhost:7777
TWAK_WALLET_NAME=alphaloop
TWAK_HMAC_SECRET=dfa9b43bb162b52dd440ff83dc86d31b78b496a87ddf68461d81dc9121aa98dc

# Trading
TRADING_PAIR=BNB/USDT
MAX_POSITION_SIZE_USD=10
MIN_CONFIDENCE=0.6
CYCLE_INTERVAL_MINUTES=30
MAX_DAILY_LOSS_USD=50
STOP_LOSS_PERCENT=5

# Competition
COMPETITION_MODE=true
INITIAL_PORTFOLIO_USD=1000
MAX_DRAWDOWN_PCT=25
MAX_POSITION_HOLD_HOURS=20
TOKEN_SCAN_TOP_N=3

# Database
DATABASE_URL=sqlite+aiosqlite:///./storage/alphaloop.db
```

---

## Prize Targets

| Prize | Value | Requirement |
|-------|-------|-------------|
| Track 1 Top 5 (best PnL) | $2,000–$10,000 | Live trades, no DQ |
| Best Use of TWAK | $2,000 | TWAK-only execution + x402 |
| Best Use of CMC Agent Hub | $2,000 | CMC data + x402 payments |
| Best Use of BNB AI Agent SDK | $2,000 | EVMWalletProvider + ERC-8004 |

### DQ Rules — must not happen

- Miss on-chain registration before June 22
- Portfolio drawdown > 30% (circuit breaker fires at 25%)
- Zero trades on any day (daily trade guarantee built in)
- Trade a token not on the eligible list
- Private key committed to public repo
- Agent stays down during the trading window

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       AlphaLoop Agent                           │
│                                                                 │
│  APScheduler (every 30 min)                                     │
│       │                                                         │
│       ▼                                                         │
│  TokenScanner ──▶ picks best token from 30 eligible tokens      │
│       │                                                         │
│       ▼                                                         │
│  CMC Client ──▶ quote + OHLCV (daily + 4h)                      │
│       │                                                         │
│       ▼                                                         │
│  Indicators ──▶ RSI, MACD, Bollinger Bands, SMA 20/50           │
│       │                                                         │
│       ▼                                                         │
│  Claude AI ──▶ BUY / SELL / HOLD + confidence + reasoning       │
│       │                                                         │
│       ├─▶ HOLD or confidence < 0.6 → skip                       │
│       │                                                         │
│       ▼                                                         │
│  Backtester ──▶ 45-day IS + 15-day OOS walk-forward             │
│       │                                                         │
│       ├─▶ fail → skip                                           │
│       │                                                         │
│       ▼                                                         │
│  TWAKExecutor ──▶ POST /actions/swap → BSC mainnet              │
│  (fallback: PancakeSwap V2 via web3.py)                         │
│       │                                                         │
│       ▼                                                         │
│  SQLite ──▶ trade + strategy + run saved                        │
│                                                                 │
│  Competition guards (every cycle):                              │
│    - Drawdown check: halt if ≥ 25%                              │
│    - Stale position force-close: close if open > 20h            │
│    - Daily trade guarantee: force BUY at 22:00 UTC if 0 trades  │
│    - Position guard: max 1 open trade at a time                 │
│    - Daily loss limit: pause if loss > $50/day                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack

| Layer | Library | Purpose |
|-------|---------|---------|
| API server | FastAPI + uvicorn | REST endpoints, lifespan hooks |
| Scheduler | APScheduler | 30-min agent cycle + 5-min trade monitor |
| Market data | httpx + CMC API | Quotes and OHLCV candles |
| Token scanner | Binance public API | RSI + momentum score across 30 tokens |
| Strategy | Anthropic Claude | LLM reasoning over indicators |
| Indicators | pandas + numpy | RSI, MACD, Bollinger Bands, SMA |
| Backtesting | Pure Python | Walk-forward IS/OOS simulation |
| Execution | TWAK REST API | Self-custody swap via Trust Wallet Agent Kit |
| Fallback | web3.py + PancakeSwap V2 | Used if TWAK_REST_URL not set |
| Database | SQLAlchemy + aiosqlite | Async SQLite ORM |
| Dashboard | Next.js | Live chart, equity curve, competition panel |

---

## Quick Start (local)

```bash
git clone <repo>
cd alphaloop

cp .env.example .env
# fill in your keys

pip install -r requirements.txt

# Install TWAK
curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash
twak setup
twak wallet create --name alphaloop
twak serve --rest --port 7777   # keep this running

# Start the agent
uvicorn agent.main:app --reload

# Manually trigger one cycle
curl -X POST http://localhost:8000/run
```

---

## Docker (competition deployment)

```bash
# Start TWAK on the HOST first (not inside Docker)
twak serve --rest --port 7777

# Then launch the agent + dashboard
./scripts/start_competition.sh
# or manually:
docker compose up -d --build
```

TWAK runs on the host. The container reaches it via `host.docker.internal:7777`.
`restart: unless-stopped` ensures the agent auto-recovers from crashes during the 6-day window.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check + live BNB price |
| GET | `/status` | Last run, open positions, signing backend |
| GET | `/trades` | Executed trades (newest first) |
| GET | `/strategies` | Generated strategies |
| GET | `/runs` | Agent run history |
| POST | `/run` | Manually trigger one cycle |
| POST | `/monitor` | Check TP/SL on open positions |
| GET | `/competition/status` | Drawdown, daily trades, stale positions |
| POST | `/competition/register` | Trigger on-chain competition registration |
| GET | `/competition/scan` | Token scanner results right now |
| GET | `/twak/status` | TWAK wallet address, balance, registration |

---

## Project Layout

```
alphaloop/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── scripts/
│   ├── start_competition.sh   — launch script for June 22
│   ├── reset_db.sh            — wipe DB for clean start
│   ├── check_ready.py         — pre-competition readiness checker
│   └── test_mainnet_swaps.py  — verify PancakeSwap V2 paths for top 8 tokens
│
├── agent/
│   ├── config.py              — typed env-var config singleton
│   ├── main.py                — FastAPI app + all endpoints
│   ├── scheduler.py           — run_agent_cycle() + APScheduler
│   └── competition.py         — drawdown, stale close, daily guarantee
│
├── data/
│   ├── cmc_client.py          — async CoinMarketCap client (+ Agent Hub)
│   ├── indicators.py          — RSI, MACD, Bollinger Bands, SMA, ATR
│   └── token_scanner.py       — ranks 30 tokens by momentum score
│
├── strategy/
│   ├── generator.py           — Claude strategy generation (structured JSON)
│   └── backtester.py          — walk-forward IS/OOS backtester
│
├── execution/
│   ├── twak_executor.py       — TWAK REST swap executor (primary)
│   ├── wallet.py              — WalletAgent via web3.py (fallback)
│   ├── pancakeswap.py         — PancakeSwap V2 (fallback)
│   ├── twak_client.py         — TWAK CLI wrapper (registration)
│   └── bnb_wallet.py          — BNB Agent SDK EVMWalletProvider + x402
│
├── db/
│   └── models.py              — SQLAlchemy async ORM + CRUD helpers
│
├── dashboard/                 — Next.js dashboard
│
└── tests/
    └── test_pipeline.py       — 20 smoke tests (no transactions)
```

---

## DoraHacks Submission Summary

> Use this text in the DoraHacks project description.

**What it does**

AlphaLoop is a fully autonomous AI trading agent for BSC. Every 30 minutes it:
1. Scans 30 eligible tokens via a momentum scorer (RSI + 24h change + volume)
2. Fetches market data from CoinMarketCap and technical indicators via Binance OHLCV
3. Asks Claude AI (claude-sonnet-4-5) to generate a BUY / SELL / HOLD strategy with entry, stop-loss, and take-profit levels plus reasoning
4. Walk-forward backtests the strategy (45-day in-sample + 15-day out-of-sample) and rejects it if it fails
5. Executes the approved swap via the Trust Wallet Agent Kit (TWAK) REST API — self-custody, no CEX
6. Monitors open positions every 5 minutes for TP/SL hits and force-closes stale trades

**Why AlphaLoop beats manual trading**

- Removes emotion and FOMO — Claude AI decides with data, not fear or greed
- 24/7 autonomous — runs during Asia hours when most retail traders are asleep
- Built-in risk management: 25% drawdown circuit breaker, daily loss cap, confidence-based position sizing
- Self-custody: private keys never leave the TWAK wallet — no exchange counterparty risk

**Trust Wallet Agent Kit (TWAK) integration**

- All swaps go through `TWAKExecutor` → TWAK REST `POST /actions/swap`
- On-chain registration via `twak compete register` on the competition contract
- x402 micropayment support for CMC Agent Hub paid API calls
- TWAK autonomous mode allowlist restricts execution to 30 competition-eligible tokens only

**CoinMarketCap Agent Hub integration**

- `CMCClient` dynamically switches between the standard Pro API and the Agent Hub MCP endpoint (set `CMC_AGENT_HUB_URL`)
- x402 payment header (`X-Payment`) is attached to Agent Hub requests when `X402_ENABLED=true`
- Supports `get_quote` and `get_market_metrics` via the Agent Hub MCP path

**BNB AI Agent SDK integration**

- `BNBWallet` wraps `EVMWalletProvider` — AES-256 encrypted local keystore, keys never in env vars at runtime
- `X402Signer` for EIP-712 typed-data micropayment signing
- `ERC8004Agent.register_agent(endpoint)` called on startup in mainnet + competition mode

---

## Safety Notes

- `DRY_RUN=true` by default — no real transactions until explicitly disabled
- `MAX_POSITION_SIZE_USD=10` caps every trade
- 25% drawdown circuit breaker halts all trading automatically
- Private key is loaded from `.env` only — never logged or stored in DB
- `.env` is in `.gitignore` — never commit it
