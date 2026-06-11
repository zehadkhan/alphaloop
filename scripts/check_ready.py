#!/usr/bin/env python3
"""Pre-competition readiness checker.

Run before June 22 to verify all blockers are resolved.
Usage:  python scripts/check_ready.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

OK  = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"

results: list[tuple[str, bool, str]] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    results.append((label, passed, detail))
    icon = OK if passed else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon}  {label}{suffix}")


async def main() -> None:
    print("\n====== AlphaLoop — Pre-Competition Readiness Check ======\n")

    # ── 1. .env exists ─────────────────────────────────────────────
    print("[ Config ]")
    env_exists = os.path.exists(".env")
    check(".env file present", env_exists)

    environment = os.getenv("ENVIRONMENT", "testnet")
    check("ENVIRONMENT=mainnet", environment == "mainnet",
          f"currently '{environment}' — change before June 22")

    dry_run = os.getenv("DRY_RUN", "true").lower()
    check("DRY_RUN=false", dry_run == "false",
          f"currently '{dry_run}' — set to false for live trading")

    competition_mode = os.getenv("COMPETITION_MODE", "false").lower()
    check("COMPETITION_MODE=true", competition_mode == "true",
          f"currently '{competition_mode}'")

    check("ANTHROPIC_API_KEY set", bool(os.getenv("ANTHROPIC_API_KEY")))
    check("CMC_API_KEY set",       bool(os.getenv("CMC_API_KEY")))
    check("AGENT_PRIVATE_KEY set", bool(os.getenv("AGENT_PRIVATE_KEY")))
    check("TWAK_HMAC_SECRET set",  bool(os.getenv("TWAK_HMAC_SECRET")))
    check("AGENT_PUBLIC_URL set",  bool(os.getenv("AGENT_PUBLIC_URL")))

    # ── 2. TWAK CLI ─────────────────────────────────────────────────
    print("\n[ TWAK CLI ]")
    twak_bin = shutil.which("twak")
    check("TWAK CLI installed", bool(twak_bin), twak_bin or "run: curl -fsSL https://agent-kit.trustwallet.com/install.sh | bash")

    if twak_bin:
        res = subprocess.run(["twak", "version"], capture_output=True, text=True, timeout=10)
        check("twak version OK", res.returncode == 0, res.stdout.strip() or res.stderr.strip())

    # ── 3. TWAK REST server ─────────────────────────────────────────
    print("\n[ TWAK REST Server ]")
    twak_url = os.getenv("TWAK_REST_URL", "http://localhost:7777")
    twak_online = False
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{twak_url}/health")
        twak_online = r.status_code == 200
    except Exception:
        pass
    check(f"TWAK server online at {twak_url}", twak_online,
          "run: twak serve --rest --port 7777" if not twak_online else "")

    # ── 4. Wallet balance ───────────────────────────────────────────
    print("\n[ Wallet ]")
    rpc = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
    wallet_addr = os.getenv("AGENT_WALLET_ADDRESS", "")
    check("AGENT_WALLET_ADDRESS set", bool(wallet_addr))

    if wallet_addr:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.post(rpc, json={
                    "jsonrpc": "2.0", "method": "eth_getBalance",
                    "params": [wallet_addr, "latest"], "id": 1,
                })
            wei = int(r.json()["result"], 16)
            bnb = wei / 10**18
            funded = bnb >= 0.02
            check(f"Wallet funded (≥ 0.02 BNB)", funded, f"{bnb:.4f} BNB")
        except Exception as exc:
            check("Wallet balance query", False, str(exc))

    # ── 5. Competition contract registration ────────────────────────
    print("\n[ Competition Registration ]")
    if twak_online:
        try:
            twak_secret = os.getenv("TWAK_HMAC_SECRET", "")
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{twak_url}/actions/competition_status",
                    json={},
                    headers={"Authorization": f"Bearer {twak_secret}",
                             "Content-Type": "application/json"},
                )
            reg = r.json()
            registered = reg.get("registered", False) or reg.get("ok", False)
            check("Agent registered on competition contract", registered,
                  json.dumps(reg) if not registered else "")
        except Exception as exc:
            check("Competition status query", False, str(exc))
    else:
        print(f"  {WARN}  Competition registration check skipped (TWAK server offline)")

    # ── 6. Backend health ───────────────────────────────────────────
    print("\n[ Agent Backend ]")
    backend_url = "http://localhost:8000"
    backend_online = False
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{backend_url}/health")
        backend_online = r.status_code == 200
        if backend_online:
            data = r.json()
            check("Backend /health OK", True, f"BNB=${data.get('bnb_price', '?')}")
    except Exception:
        pass
    if not backend_online:
        check("Backend running", False, "start: uvicorn agent.main:app  or  docker compose up -d")

    # ── 7. Token scanner ────────────────────────────────────────────
    print("\n[ Token Scanner ]")
    if backend_online:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(f"{backend_url}/competition/scan")
            top = r.json().get("top_tokens", [])
            check("Token scanner returns results", len(top) > 0,
                  ", ".join(t["symbol"] for t in top[:3]))
        except Exception as exc:
            check("Token scanner", False, str(exc))
    else:
        print(f"  {WARN}  Token scanner check skipped (backend offline)")

    # ── 8. DoraHacks submission ─────────────────────────────────────
    print("\n[ DoraHacks ]")
    print(f"  {WARN}  Manual check required:")
    print("       https://dorahacks.io/hackathon/bnbhack-twt-cmc")
    print("       - Early draft submission done?")
    print("       - On-chain BSC wallet address filled in?")
    print("       - GitHub repo URL added (public, no .env)?")

    # ── Summary ────────────────────────────────────────────────────
    print("\n====== Summary ======")
    passed  = [r for r in results if r[1]]
    failed  = [r for r in results if not r[1]]
    print(f"  {OK} {len(passed)} checks passed")
    if failed:
        print(f"  {FAIL} {len(failed)} checks FAILED:")
        for label, _, detail in failed:
            print(f"      - {label}" + (f": {detail}" if detail else ""))
        print()
        sys.exit(1)
    else:
        print("\n  All checks passed — agent is ready for June 22!\n")


if __name__ == "__main__":
    asyncio.run(main())
