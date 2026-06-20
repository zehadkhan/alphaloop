#!/usr/bin/env python3
"""Verify the on-chain decision proof for any AlphaLoop trade.

Usage:
  python scripts/verify_trade.py --trade-id 42
  python scripts/verify_trade.py --trade-id 42 --check-chain

What it verifies:
  1. DB consistency: sha256(proof_string) == proof_hash stored in DB
  2. [--check-chain] On-chain: calldata of proof_tx_hash starts with "0x" + proof_hash

Exit code 0 = VERIFIED, 1 = MISMATCH or missing proof.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def verify(trade_id: int, check_chain: bool) -> bool:
    from db.models import init_db, get_trade

    await init_db()
    trade = await get_trade(trade_id)

    if trade is None:
        print(f"[ERROR] Trade id={trade_id} not found in database")
        return False

    print(f"\n{'='*60}")
    print(f"  AlphaLoop Trade Proof Verifier — Trade #{trade_id}")
    print(f"{'='*60}")
    print(f"  Symbol     : {trade.symbol}")
    print(f"  Action     : {trade.action}")
    print(f"  Entry      : {trade.entry_price}")
    print(f"  Executed   : {trade.executed_at}")
    print(f"  Status     : {trade.status}")

    if not trade.proof_string or not trade.proof_hash:
        print("\n  [SKIP] No proof stored for this trade (pre-upgrade or compliance trade)")
        return False

    print(f"\n  Proof string:\n  {trade.proof_string}\n")

    # Step 1: recompute hash from stored proof_string
    recomputed = hashlib.sha256(trade.proof_string.encode()).hexdigest()
    stored     = trade.proof_hash

    print(f"  Stored   hash : {stored}")
    print(f"  Computed hash : {recomputed}")

    if recomputed != stored:
        print("\n  [FAIL] Hash MISMATCH — proof_string has been tampered with")
        return False

    print("\n  [PASS] DB proof consistent — sha256(proof_string) matches proof_hash")

    if not check_chain:
        print("  (use --check-chain to also verify BSC calldata)")
        print(f"{'='*60}\n  Result: VERIFIED (DB only)\n{'='*60}")
        return True

    # Step 2: verify BSC calldata
    if not trade.proof_tx_hash:
        print("\n  [SKIP] No on-chain tx recorded for this trade (DRY_RUN or tx failed)")
        print(f"{'='*60}\n  Result: VERIFIED (DB only — no on-chain tx)\n{'='*60}")
        return True

    print(f"\n  Checking BSC tx: {trade.proof_tx_hash}")
    try:
        from web3 import AsyncWeb3
        from agent.config import config

        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(config.BSC_RPC_URL))
        tx = await w3.eth.get_transaction(trade.proof_tx_hash)
        if tx is None:
            print("  [FAIL] Transaction not found on chain")
            return False

        calldata = tx["input"]
        expected = "0x" + stored

        print(f"  On-chain calldata : {calldata}")
        print(f"  Expected calldata : {expected}")

        if str(calldata).lower() == expected.lower():
            print(f"\n  [PASS] On-chain calldata matches proof_hash")
            print(f"{'='*60}\n  Result: FULLY VERIFIED (DB + BSC)\n{'='*60}")
            return True
        else:
            print(f"\n  [FAIL] On-chain calldata MISMATCH")
            return False
    except Exception as exc:
        print(f"  [ERROR] Chain verification failed: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify AlphaLoop on-chain trade proof")
    parser.add_argument("--trade-id", type=int, required=True, help="Trade ID to verify")
    parser.add_argument("--check-chain", action="store_true",
                        help="Also fetch BSC tx calldata and compare")
    args = parser.parse_args()

    ok = asyncio.run(verify(args.trade_id, args.check_chain))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
