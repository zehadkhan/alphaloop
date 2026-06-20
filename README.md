# AlphaLoop

> Autonomous AI trading agent for BSC — built for the **BNB HACK × CoinMarketCap × Trust Wallet $36,000 hackathon**.

AlphaLoop uses Claude AI to generate, backtest, and autonomously execute crypto trading strategies on BSC mainnet via PancakeSwap V2 / TWAK. It is unique in using a **5-Axis Market Compass** and **on-chain decision proofs** to verify every trade decision before execution.

**Hackathon:** [dorahacks.io/hackathon/bnbhack-twt-cmc](https://dorahacks.io/hackathon/bnbhack-twt-cmc)
**Live trading window:** June 22–28, 2026 UTC

---

## Quick Start

```bash
# 1. Start TWAK (keep this terminal open)
twak serve

# 2. Start agent + dashboard (new terminal)
bash scripts/start_competition.sh

# 3. Stop everything
bash scripts/stop.sh
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3001 |
| Agent API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

---

## Daily Commands

```bash
# Live logs
tail -f storage/uvicorn.log

# Competition status
curl http://localhost:8000/competition/status | python3 -m json.tool

# Trigger a manual cycle right now
curl -X POST http://localhost:8000/run

# See what token scanner picked
curl -X POST http://localhost:8000/competition/scan | python3 -m json.tool

# Emergency close all positions
curl -X POST http://localhost:8000/admin/close-all

# Verify a trade's on-chain proof
python scripts/verify_trade.py --trade-id N --check-chain
```

---

## What the Agent Does Every 30 Minutes

1. **Scans eligible tokens** — momentum scorer with hysteresis (avoids churn)
2. **Computes 5-Axis Market Compass** — Trend / Momentum / Sentiment / Volatility / Stress (0–50 score)
3. **Generates strategy via Claude** — compass state included in prompt, Claude knows the regime
4. **Checks Edge Gate** — `confidence × (momentum/10) − 0.8% > 0` (skips low-value trades)
5. **Runs backtest** — 45-day IS + 15-day OOS walk-forward, rejects if it fails
6. **Executes swap via TWAK** — size scaled by compass regime × drawdown zone
7. **Commits proof to BSC** — SHA-256 of compass state + decision stored as calldata

---

## Safety Zones (Drawdown Cascade)

| Zone | Drawdown | Position Size | Extra Gate |
|---|---|---|---|
| GREEN | < 8% | 100% | — |
| YELLOW | 8–15% | 70% | — |
| ORANGE | 15–22% | 40% | Compass score ≥ 15 |
| RED | 22–25% | 10% | Compass score ≥ 35 |
| HALT | ≥ 25% | 0% | No new trades |

Additional guards every cycle:
- **Daily loss cap** — pause if loss > $50/day
- **Stale position force-close** — close if open > 20h
- **Smart compliance window** — soft hunt 18h UTC, alert 22h, force 23h
- **Position guard** — max 1 open trade at a time

---

## Wallet Addresses

| Wallet | Address | Purpose |
|---|---|---|
| **TWAK (active)** | `0x73Fb7fA92979dCc7E537Fe4159114f5F70727C7B` | Competition trading wallet — fund this |
| web3.py (fallback) | `0x9FF88b9333C161c8542Bd817C1FF422f89210866` | Used only if TWAK not configured |

**Send BNB to: `0x73Fb7fA92979dCc7E537Fe4159114f5F70727C7B`**
Network: BSC / BEP-20. Minimum: 0.02 BNB. Recommended: 0.05 BNB.

---

## Architecture

```
APScheduler (every 30 min)
       │
       ▼
TokenScanner ──▶ hysteresis-ranked BEP-20 tokens (30 eligible)
       │
       ▼
CMC Client ──▶ quote + OHLCV + global metrics (btc_dominance, F&G)
       │
       ▼
Indicators ──▶ RSI, MACD, BB, SMA20/50, EMA9/21, ATR
       │
       ▼
5-Axis Market Compass ──▶ Trend / Momentum / Sentiment / Volatility / Stress
       │                   score 0–50 → regime profile → position sizing
       ▼
Claude AI ──▶ BUY / SELL / HOLD + confidence + entry/SL/TP + reasoning
       │       (receives full compass state in prompt)
       │
       ├── HOLD or confidence < threshold → skip
       ├── Edge gate: conf × momentum − cost ≤ 0 → skip
       │
       ▼
Backtester ──▶ walk-forward IS/OOS → fail → skip
       │
       ▼
Build Proof ──▶ sha256(compass_state + decision) = proof_hash
       │
       ▼
TWAKExecutor ──▶ POST /actions/swap → BSC mainnet
(fallback: PancakeSwap V2 via web3.py)
       │
       ▼
Commit Proof ──▶ self-transfer BNB tx with proof_hash as calldata
       │
       ▼
SQLite ──▶ trade + strategy + proof_string + proof_hash + run saved
```

---

## 5-Axis Market Compass

AlphaLoop's unique regime detection engine. Each axis scored 0–10 independently:

| Axis | Inputs | Source |
|---|---|---|
| Trend | EMA9/21 cross + price vs SMA20/50 | Binance OHLCV |
| Momentum | RSI + MACD histogram + 24h change | Binance OHLCV + CMC |
| Sentiment | Fear & Greed index + BTC dominance level | alternative.me + CMC |
| Volatility | ATR percentile + BB-width percentile (moderate = best) | Binance OHLCV |
| Stress | Perp funding rate z-score + price stretch from SMA50 (inverted) | Binance FAPI |

**Compass Score = sum of 5 axes (0–50)**

| Score | Regime | Position Size |
|---|---|---|
| 35–50 | MOMENTUM_RIDE | 100% |
| 25–35 | TREND_CONFIRM | 85% |
| 15–25 | NEUTRAL_CAUTIOUS | 60% |
| 8–15 | DEFENSIVE | 30% |
| < 8 | RISK_OFF | Skip |

---

## On-Chain Decision Proof

Every executed trade produces a verifiable proof:

```
ALPHALOOP_PROOF_v1|{timestamp}|{symbol}|{compass_score}|{axes}|{confidence}|{action}|{entry_price}
```

SHA-256 of this string is committed to BSC as calldata in a self-transfer BNB tx — before the trade executes. Anyone can verify:

```bash
python scripts/verify_trade.py --trade-id 42 --check-chain
```

---

## Stack

| Layer | Library | Purpose |
|---|---|---|
| API server | FastAPI + uvicorn | REST endpoints, lifespan hooks |
| Scheduler | APScheduler | 30-min cycle + 2-min trade monitor |
| Regime engine | custom (data/regime.py) | 5-axis compass, F&G, perp funding |
| Market data | httpx + CMC API | Quotes, OHLCV, global metrics |
| Token scanner | Binance public API | Hysteresis-aware momentum ranking |
| Strategy | Anthropic Claude (sonnet-4-5) | LLM reasoning with compass context |
| Indicators | pandas + numpy | RSI, MACD, BB, SMA, EMA, ATR |
| Backtesting | Pure Python | Walk-forward IS/OOS |
| Execution | TWAK REST API | Self-custody swap via Trust Wallet Agent Kit |
| Fallback | web3.py + PancakeSwap V2 | If TWAK not available |
| Database | SQLAlchemy 2.0 + aiosqlite | Async SQLite ORM + proof columns |
| Dashboard | Next.js 14 | Live chart, compass bar, zone badge, equity curve |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check + live BNB price |
| GET | `/status` | Last run, compass, open positions |
| GET | `/trades` | Executed trades |
| GET | `/strategies` | Generated strategies |
| GET | `/runs` | Agent run history |
| GET | `/activity` | Plain-English cycle summaries |
| POST | `/run` | Trigger one cycle manually |
| POST | `/monitor` | Check TP/SL on open positions |
| GET | `/competition/status` | Drawdown zone, daily trades, stale positions |
| POST | `/competition/register` | On-chain competition registration |
| POST | `/competition/scan` | Token scanner results right now |
| GET | `/twak/status` | TWAK wallet, balance, registration |
| GET | `/admin/config` | Runtime config |
| POST | `/admin/config` | Update config (paused, position size, etc.) |
| POST | `/admin/close-all` | Emergency close all positions |

---

## Project Layout

```
alphaloop/
├── agent/
│   ├── config.py              — env-var config singleton
│   ├── main.py                — FastAPI app + all endpoints
│   ├── scheduler.py           — run_agent_cycle() + APScheduler
│   ├── competition.py         — drawdown cascade, stale close, compliance window
│   └── proof.py               — on-chain decision proof builder
│
├── data/
│   ├── cmc_client.py          — async CMC client (Pro API + Agent Hub + x402)
│   ├── indicators.py          — RSI, MACD, BB, SMA, EMA, ATR
│   ├── token_scanner.py       — hysteresis-aware momentum token ranking
│   └── regime.py              — 5-Axis Market Compass engine
│
├── strategy/
│   ├── generator.py           — Claude strategy generation with compass context
│   └── backtester.py          — walk-forward IS/OOS backtester
│
├── execution/
│   ├── twak_executor.py       — TWAK REST swap executor (primary)
│   ├── pancakeswap.py         — PancakeSwap V2 (fallback)
│   ├── bnb_wallet.py          — BNB Agent SDK EVMWalletProvider + x402
│   └── wallet.py              — WalletAgent via web3.py
│
├── db/
│   └── models.py              — SQLAlchemy ORM + proof columns on Trade
│
├── dashboard/                 — Next.js dashboard
│   └── components/
│       └── CompetitionPanel.tsx — zone badge + compass bar
│
├── scripts/
│   ├── start_competition.sh   — one-command launch (terminal or --docker)
│   ├── stop.sh                — stop all processes
│   ├── reset_db.sh            — wipe DB for clean start
│   ├── verify_trade.py        — verify on-chain proof for any trade
│   └── check_ready.py         — pre-competition readiness checker
│
└── ref-projects/              — competitor repos for research (git-ignored)
    └── REPO_LIST.md
```

---

## Docker (optional)

Terminal mode is the default. Use Docker only for VPS/server deployment:

```bash
# Start TWAK on host first
twak serve

# Docker mode
bash scripts/start_competition.sh --docker
# or:
docker compose up -d --build
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `testnet` | Set to `mainnet` for competition |
| `DRY_RUN` | `true` | Set to `false` for live trades |
| `COMPETITION_MODE` | `false` | Set to `true` to enable all guardrails |
| `CMC_API_KEY` | — | CoinMarketCap Pro API key |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude API key |
| `AGENT_PRIVATE_KEY` | — | BSC wallet private key |
| `AGENT_WALLET_ADDRESS` | — | BSC wallet address |
| `BSC_RPC_URL` | testnet RPC | Use `https://bsc-dataseed.binance.org/` for mainnet |
| `TWAK_REST_URL` | — | TWAK server URL e.g. `http://localhost:1337` |
| `TWAK_WALLET_NAME` | `alphaloop` | TWAK wallet name |
| `MAX_POSITION_SIZE_USD` | `10` | Max USD per trade |
| `INITIAL_PORTFOLIO_USD` | `1000` | Starting portfolio (for drawdown calc) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./storage/alphaloop.db` | DB path |
| `HYSTERESIS_MARGIN` | `0.15` | Token scanner displacement threshold |
| `ROUND_TRIP_COST_PCT` | `0.008` | Edge gate cost estimate (0.8%) |

---

## Safety Notes

- `DRY_RUN=true` by default — no real transactions until explicitly disabled
- `MAX_POSITION_SIZE_USD=10` caps every trade
- 25% drawdown circuit breaker halts all trading automatically
- Private key loaded from `.env` only — never logged or stored in DB
- `.env` is in `.gitignore` — never commit it
- `ref-projects/` is in `.gitignore` — competitor code never committed
