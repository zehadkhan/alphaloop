# AlphaLoop — BNB Hack Hackathon TODO
# Deadline: June 21 (build) · June 22 (live trading starts) · June 28 (trading ends)

## Legend
- [x] Done
- [ ] Pending
- [!] Blocking — must do before June 22 or DQ

---

## ✅ Already Built (Foundation)

- [x] Claude AI strategy generation (claude-sonnet-4-5, structured JSON output)
- [x] Walk-forward backtester — IS/OOS split, tighter gates
- [x] Trade lifecycle monitor — TP/SL hit detection every 5 min
- [x] Position guard — one open trade at a time
- [x] Multi-timeframe data — daily + 4h Binance candles
- [x] Risk management — daily loss limit + confidence-based sizing
- [x] Full Next.js dashboard — live chart, equity curve, open positions panel
- [x] FastAPI backend — /run /monitor /trades /strategies /runs endpoints
- [x] Docker setup — backend + dashboard containerized

---

## 🔴 CRITICAL — Do This Week (June 9–14)

### [!] Step 0 — On-chain Registration (Deadline: before June 22)
- [ ] Install Trust Wallet Agent Kit CLI: `npm install -g @trustwallet/agent-kit`
- [ ] Import competition wallet into TWAK: `twak wallet import`
- [ ] Register agent on-chain: call `POST /competition/register` (or `twak compete register`)
- [ ] Verify registration on contract: `0x212c61b9b72c95d95bf29cf032f5e5635629aed5`
- [ ] Submit project on DoraHacks (early draft submission, update later)
- [ ] Fund mainnet BSC wallet with BNB for gas + trading capital
- [ ] Set `ENVIRONMENT=mainnet` and `BSC_RPC_URL=<mainnet-rpc>` in `.env`

### [!] Step 1 — Replace web3.py Signing with TWAK
- [x] TWAK CLI wrapper created: `execution/twak_client.py`
- [x] BNB Agent SDK wallet: `execution/bnb_wallet.py` (EVMWalletProvider, encrypted keystore)
- [ ] Read TWAK REST API docs at portal.trustwallet.com
- [ ] Rewrite `execution/wallet.py` — replace `sign_transaction()` with TWAK signing endpoint
- [ ] Keep TWAK as sole execution layer (required for Best TWAK prize)
- [ ] Test signing loop end-to-end on BSC mainnet with small amount
- [ ] Confirm tx hash appears on BscScan

### [!] Step 2 — Switch to CMC AI Agent Hub
- [ ] Get access to CMC AI Agent Hub: coinmarketcap.com/api/agent
- [ ] Replace `cmc_client.py` base URL with Agent Hub MCP endpoint
- [ ] Use Agent Hub `get_quote` skill instead of raw `/v1/cryptocurrency/quotes/latest`
- [x] x402 payment signing ready in `BNBWallet.sign_x402_payment()`
- [x] x402 payment header support added to `CMCClient.get_quote()` (opt-in via X402_ENABLED)
- [ ] Test that market data flows correctly through new client

### [!] Step 3 — Fix Minimum Daily Trade Requirement
- [x] `force_close_stale_positions()` — closes positions > MAX_POSITION_HOLD_HOURS (20h)
- [x] `get_last_trade_time()` DB query added
- [x] `get_daily_trade_count()` DB query added
- [x] Daily trade guarantee: if no trade by 22h UTC → lower confidence gate, force BUY
- [x] Stale positions shown in CompetitionPanel dashboard

### [!] Step 4 — Portfolio-level 30% Drawdown Circuit Breaker
- [x] `INITIAL_PORTFOLIO_USD` config (default 1000)
- [x] `check_drawdown()` in `agent/competition.py`
- [x] Hard stop in `_run_cycle_impl()`: drawdown ≥ 25% → halt
- [x] Drawdown % surfaced in `/competition/status` and CompetitionPanel dashboard

---

## 🟡 HIGH — Build June 14–18

### Step 5 — Expand to Eligible Token List (30 tokens)
- [x] 30 eligible tokens added to `agent/config.py` (ELIGIBLE_TOKENS)
- [x] `TokenScanner` built in `data/token_scanner.py` — ranks by RSI + 24h change + volume
- [x] Each cycle: scan top tokens, pick highest-conviction signal (COMPETITION_MODE=true)
- [x] BSC mainnet token addresses for top 25+ tokens added to `execution/pancakeswap.py`
- [x] Router auto-switches mainnet/testnet on `ENVIRONMENT` env var
- [x] `scripts/test_mainnet_swaps.py` — tests getAmountsOut for top 8 tokens on mainnet
- [ ] Run `ENVIRONMENT=mainnet python scripts/test_mainnet_swaps.py` to confirm paths live

### Step 6 — x402 Native Integration (Best TWAK Prize requirement)
- [x] x402 = HTTP payment protocol — pay per API request on-chain
- [x] `X402Signer` integrated in `BNBWallet` (bnbagent SDK)
- [x] `make_x402_payment()` in `execution/twak_client.py`
- [x] x402 payment header support added to `CMCClient` (X402_ENABLED=true)
- [ ] Wire x402 to actual Agent Hub calls (need Agent Hub access first)
- [ ] Log x402 payment tx hashes — need on-chain proof for judges

### Step 7 — TWAK Autonomous Mode + Guardrails
- [x] `execution/twak_client.py` wraps TWAK CLI (register, sign, x402)
- [x] `agent/competition.py` enforces: per-trade limits, daily loss cap, drawdown halt
- [ ] Install TWAK CLI: `curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash`
- [ ] Configure TWAK autonomous mode allowlist (eligible tokens only)
- [ ] Configure TWAK per-trade limit via `twak config`
- [ ] This satisfies "autonomous execution and guardrails" judging criterion (20 pts)

### Step 8 — BNB AI Agent SDK Integration (Best SDK Prize)
- [x] `bnbagent` installed (v0.3.5)
- [x] `execution/bnb_wallet.py` uses `EVMWalletProvider` (AES-256 encrypted keystore)
- [x] `X402Signer` for micropayment channels
- [x] `ERC8004Agent.register_agent(endpoint)` wired in `agent/main.py` lifespan (was missing endpoint arg — fixed)
- [x] `BNBWallet.get_balance()` rewritten to use web3 directly (removed circular import via WalletAgent)
- [ ] Install bnbagent: `pip install bnbagent` — then test registration on mainnet

---

## 🟢 MEDIUM — Polish June 18–21

### Step 9 — Competition Dashboard Panel
- [x] CompetitionPanel component — drawdown bar, trades today, PnL, days remaining
- [x] `/competition/status` API endpoint
- [x] CompetitionPanel auto-fetches and renders above live chart

### Step 10 — Demo Preparation
- [ ] Record 3-minute demo video showing:
  - [ ] CMC Agent Hub data flowing in
  - [ ] Claude generating strategy (show reasoning)
  - [ ] TWAK signing transaction (show self-custody)
  - [ ] Live chart with trade entry/TP/SL lines
  - [ ] x402 payment happening in trade loop
  - [ ] BscScan tx proof
- [ ] Write clear README:
  - [ ] Architecture diagram
  - [ ] "Why AlphaLoop" — removes human emotion, 24/7 autonomous
  - [ ] Strategy explanation (for DoraHacks submission)
- [ ] Clean up DB (remove stale test trades before live window)

### Step 11 — Submission Checklist
- [ ] DoraHacks submission finalized with:
  - [ ] Agent BSC wallet address (on-chain registered)
  - [ ] Public GitHub repo (clean, no .env files)
  - [ ] Demo video link
  - [ ] Strategy explanation written
- [ ] Confirm on-chain registration visible on competition contract
- [ ] Confirm agent is running and will auto-start on June 22

---

## ⚪ LOW — Nice to Have (only if time)

### Step 12 — Multi-agent Coordination
- [ ] Run 2 agents simultaneously on different token pairs
- [ ] Hedging logic — if BNB long open, look for uncorrelated short

### Step 13 — Sentiment Layer
- [ ] Use CMC Fear & Greed index from Agent Hub
- [ ] Use CMC social/KOL data
- [ ] Add to Claude strategy prompt as market sentiment context

### Step 14 — Copy-trading Signal
- [ ] Monitor top BSC whale wallets via on-chain data
- [ ] Mirror trades with risk-adjusted sizing

---

## 📅 Day-by-Day Schedule

| Date | Goal |
|------|------|
| Jun 9 (today) | Read TWAK docs, DoraHacks early submission, fund wallet |
| Jun 10 | TWAK install + wallet import + on-chain registration |
| Jun 11–12 | TWAK signing integration replace web3.py |
| Jun 13–14 | CMC Agent Hub + x402 integration |
| Jun 15 | Test mainnet token swaps (CAKE, LINK, ETH) |
| Jun 16–17 | TWAK autonomous mode guardrails config |
| Jun 18 | ERC-8004 on-chain agent registration + dashboard polish |
| Jun 19–20 | End-to-end testing on BSC mainnet |
| Jun 21 | Record demo, finalize submission, DB reset |
| Jun 22 | 🚀 Live trading begins — agent must be running 24/7 |
| Jun 22–28 | Monitor agent, do NOT touch code (live window) |
| Jun 28 | Trading ends |

---

## 🎯 Prize Targets

| Prize | Value | What it needs |
|-------|-------|---------------|
| Track 1 Top 5 | $2,000–$10,000 | Best live PnL, no DQ |
| Best Use of TWAK | $2,000 | TWAK-only execution + x402 + autonomous mode |
| Best Use of Agent Hub | $2,000 | CMC Agent Hub MCP + x402 data payments |
| Best Use of BNB SDK | $2,000 | EVMWalletProvider + ERC-8004 registration |
| **Total realistic** | **$6,000–$10,000** | Steps 1–8 complete |

---

## ⚠️ DQ Risks — Do NOT Let These Happen

- [ ] Miss on-chain registration before June 22
- [x] Portfolio drawdown > 30% (circuit breaker at 25%)
- [x] Zero trades on any day (force-close stale + daily guarantee)
- [ ] Token not on eligible list gets traded
- [ ] Private key committed to public repo
- [ ] Agent crashes and stays down during trading window
