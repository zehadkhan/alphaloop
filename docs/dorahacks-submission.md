## Problem

Most crypto trading agents are static — they follow hardcoded rules and never adapt. When market conditions shift, the bot keeps firing the same signals into a changed market. Strategy research and live execution are two separate worlds with no feedback loop between them.

---

## Solution: AlphaLoop

AlphaLoop closes the loop. It generates trading strategies from live CoinMarketCap signals, backtests them automatically, and — only when a strategy passes risk thresholds — deploys it as a live autonomous agent on BSC. Every trade feeds PnL data back into the strategy generator, creating a self-improving cycle.

---

## Live Demo

- **Dashboard:** http://p9afyi7epwshbwbqgon9qa2f.75.119.139.99.sslip.io
- **Agent API:** http://qp38fy65jtmff7agx1e4ufr0.75.119.139.99.sslip.io
- **GitHub:** https://github.com/zehadkhan/alphaloop
- **Competition Wallet:** `0xa401A91faa968Ee4334780712C95Af208E570e0F`
- **Registration TX:** `0x2f11419f8aea72604975a5e0101f2a79fd6d0ac42fd427a03cba887e07e53b0b`

---

## Architecture

**L1 · Data & Signal (CMC Agent Hub)**
- CMC Data MCP pulls real-time quotes, on-chain metrics, sentiment, and technical indicators
- Strategy Generator (LLM) produces entry/exit rules, position sizing, and risk parameters
- Backtester validates each strategy against CMC historical data before any capital is deployed
- Approved strategies are published as reusable Skills to the CMC Skills Marketplace

**L2 · Custody & Execution (Trust Wallet Agent Kit)**
- TWAK handles self-custody local key signing
- Autonomous mode enabled — agent executes without per-transaction approval
- User defines risk rules (max position size, daily loss limit, stop-loss) at setup; agent operates within those bounds

**L3 · Chain & Execution (BNB AI Agent SDK)**
- Live swaps executed on PancakeSwap via BNB AI Agent SDK
- BSC mainnet chosen for sub-second confirms and low fees

---

## Two Tracks, One Codebase

**Track 2 — Strategy Skill**
The strategy generation + backtesting module ships as a standalone CMC Skill. Input: market data. Output: a backtestable spec with entry/exit conditions, expected Sharpe ratio, and max drawdown. Published to the CMC Skills Marketplace for any agent to consume.

**Track 1 — Autonomous Trading Agent**
The full AlphaLoop agent loads an approved Strategy Skill, connects to TWAK for signing, and executes live trades on BSC. PnL is tracked in real time and fed back to refine the next strategy generation cycle.

---

## Tech Stack

- **Backend:** Python (FastAPI)
- **Strategy AI:** Anthropic Claude (Sonnet)
- **CMC integration:** Data MCP (12 tools), Data API, Skills Marketplace, x402 pay-per-call
- **Wallet:** Trust Wallet Agent Kit — autonomous mode, local key signing
- **Chain:** BNB AI Agent SDK, PancakeSwap V2, BSC Mainnet
- **Infrastructure:** Docker Compose + Coolify on VPS

---

## What Makes It Different

- **Closed-loop learning** — live PnL feeds back to strategy generation. The agent gets smarter over time.
- **Risk-gated deployment** — no strategy goes live without passing backtest thresholds. Capital is protected by design.
- **5-Axis Market Compass** — unique regime detection engine scoring Trend / Momentum / Sentiment / Volatility / Stress (0–50) to adapt position sizing to market conditions.
- **On-chain decision proofs** — SHA-256 of every trade decision committed to BSC as calldata before execution. Fully verifiable.
- **Signed risk policy** — EIP-191 signature of all trading rules committed before competition window. Proves rules were set in advance, not retroactively. See: storage/policy_commitment.json
- **x402 micropayments** — CMC Agent Hub data routed through TWAK's native x402 payment layer for verifiable, pay-per-request data access.
- **Abstention ledger** — every HOLD and low-confidence skip recorded in DB with full Claude reasoning. Non-trades are first-class decisions.
- **Equity-reliability guard** — cycle automatically skipped if price/volume/candle data is unreliable. Never trades on bad data.
- **Self-custody** — keys never leave the user's device. TWAK signs locally; the agent never holds funds.

---

## Current Status

- CMC Data MCP integration ✅
- Strategy generation pipeline ✅
- Backtester (walk-forward IS/OOS) ✅
- 5-Axis Market Compass ✅
- TWAK autonomous signing ✅
- Competition registration (on-chain) ✅
- Live trading agent deployed on VPS ✅
- EIP-191 signed risk policy (pre-competition) ✅
- x402 CMC micropayment integration ✅
- Abstention ledger (HOLD decisions recorded) ✅
- Equity-reliability guard ✅
- BNB AI Agent SDK execution 🔄 In progress
- PnL feedback loop 🔄 In progress

---

## How Judges Can Verify

**1. Live Dashboard**
http://p9afyi7epwshbwbqgon9qa2f.75.119.139.99.sslip.io
→ Real-time compass score, drawdown zone, trade history, equity curve

**2. Agent API (Swagger UI)**
http://qp38fy65jtmff7agx1e4ufr0.75.119.139.99.sslip.io/docs
→ All endpoints interactive

**3. On-Chain Trades (BSCScan)**
https://bscscan.com/address/0xa401A91faa968Ee4334780712C95Af208E570e0F
→ All trades visible as BSC transactions during Jun 22–28

**4. Competition Registration Proof**
https://bscscan.com/tx/0x2f11419f8aea72604975a5e0101f2a79fd6d0ac42fd427a03cba887e07e53b0b
→ On-chain registration confirmed before competition start

**5. Source Code**
https://github.com/zehadkhan/alphaloop
