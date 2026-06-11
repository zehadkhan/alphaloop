# ✅ June 22 এর আগে যা করতে হবে

Competition window: **June 22–28, 2026**

---

## Prize Targets

| Prize | Value | Requirement |
|-------|-------|-------------|
| Track 1 Top 5 (best PnL) | $2,000–$10,000 | Live trades, no DQ |
| Best Use of TWAK | $2,000 | TWAK-only execution + x402 |
| Best Use of CMC Agent Hub | $2,000 | CMC data + x402 payments |
| Best Use of BNB AI Agent SDK | $2,000 | EVMWalletProvider + ERC-8004 |

## DQ Rules — must not happen

- [ ] Miss on-chain registration before June 22
- [ ] Portfolio drawdown > 30% (circuit breaker fires at 25% ✅)
- [ ] Zero trades on any day (daily trade guarantee built in ✅)
- [ ] Trade a token not on the eligible list ⚠️ update ELIGIBLE_TOKENS
- [ ] Private key committed to public repo ✅ .gitignore covers .env
- [ ] Agent stays down during the trading window

---

## 1. Real Wallet তৈরি ও Fund করা
- [ ] TWAK CLI install করো: `npm install -g @trustwallet/twak-cli`
- [ ] Wallet তৈরি করো: `twak wallet import --name alphaloop`
- [ ] Wallet address বের করো: `twak wallet show alphaloop`
- [ ] সেই address এ **real BNB পাঠাও** (minimum ~$50 worth)
  - Gas fee এর জন্য BNB লাগবে
  - Trade এর জন্য BNB লাগবে

---

## 2. On-Chain Registration (একবারই করতে হবে)
- [ ] Competition এ register করো: `twak compete register`
- [ ] অথবা Dashboard থেকে: `POST /competition/register` বাটন চাপো
- [ ] Confirm করো: `GET /twak/status` — `registration.ok = true` দেখালে হয়েছে

---

## 3. `.env` Production এ Set করো
```env
ENVIRONMENT=mainnet
DRY_RUN=false
COMPETITION_MODE=true
TWAK_REST_URL=http://localhost:7777
TWAK_WALLET_NAME=alphaloop
```
- [ ] `.env` এ উপরের values set করো
- [ ] Restart: `uvicorn agent.main:app --host 0.0.0.0 --port 8000`

---

## 4. Mainnet Test করো (real trade আগে)
- [ ] Swap path test: `python scripts/test_mainnet_swaps.py`
  - PancakeSwap এ BNB/USDT কাজ করছে কিনা দেখবে
- [ ] Readiness check: `python scripts/check_ready.py`
  - সব green হলে ready

---

## 5. Docker Fix করো (optional কিন্তু ভালো)
- [ ] Docker daemon ঠিক হলে rebuild করো:
  ```
  docker compose up -d --build
  ```
- [ ] তারপর `dashboard/.env.local` ফাইলটা delete করো
- [ ] Dashboard restart করো port override ছাড়া

---

## 6. DoraHacks Submission
- [ ] **June 21 এর মধ্যে** DoraHacks এ draft submit করো
- [ ] Demo video record করো (2–3 মিনিট):
  - Dashboard দেখাও
  - "Run Now" চাপো, cycle দেখাও
  - Activity Feed এ Claude এর reasoning দেখাও
- [ ] Video upload করো DoraHacks এ

---

## 7. June 22 এর দিন (Competition শুরুর আগে)
- [ ] `python scripts/check_ready.py` — সব ✅ কিনা দেখো
- [ ] Dashboard open রাখো: `http://localhost:3001`
- [ ] Backend চলছে কিনা চেক করো: `http://localhost:8000/health`
- [ ] Wallet এ BNB আছে কিনা দেখো: `/twak/status`

---

## মনে রাখো
- বট **নিজেই** trade করবে — তোমাকে কিছু করতে হবে না
- শুধু নিশ্চিত করো server বন্ধ না হয় (June 22–28)
- Maximum drawdown 30% — বট নিজেই থামবে যদি বেশি লস হয়
- প্রতিদিন কমপক্ষে ১টা trade হওয়া দরকার competition rule অনুযায়ী
