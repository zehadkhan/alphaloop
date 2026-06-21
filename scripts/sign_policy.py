#!/usr/bin/env python3
"""
AlphaLoop Risk Policy Commitment Script
Builds a signed risk policy and commits its hash to BSC mainnet as calldata.
Run ONCE before competition window opens (Jun 22 00:00 UTC).

Usage:
    python scripts/sign_policy.py [--dry-run]
"""
import json
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

POLICY = {
    "agent": "AlphaLoop",
    "version": "1.0",
    "competition": "BNB Hack 2026",
    "window": "2026-06-22T00:00:00Z / 2026-06-28T23:59:59Z",
    "committed_at": datetime.now(timezone.utc).isoformat(),
    "rules": {
        "max_position_usd": 10.0,
        "max_drawdown_pct": 25.0,
        "dq_threshold_pct": 30.0,
        "daily_loss_cap_usd": 50.0,
        "max_position_hold_hours": 20.0,
        "min_confidence": 0.55,
        "edge_gate": "confidence * (momentum/10) - round_trip_cost > 0",
        "round_trip_cost_pct": 0.008,
        "drawdown_zones": {
            "GREEN":  {"max_pct": 8,  "size_mult": 1.00},
            "YELLOW": {"max_pct": 15, "size_mult": 0.70},
            "ORANGE": {"max_pct": 22, "size_mult": 0.40, "min_compass": 15},
            "RED":    {"max_pct": 25, "size_mult": 0.10, "min_compass": 35},
            "HALT":   {"min_pct": 25, "size_mult": 0.00},
        },
        "strategy": "5-Axis Market Compass (Trend/Momentum/Sentiment/Volatility/Stress) + Claude AI + Walk-forward backtest gate",
        "execution": "TWAK (Trust Wallet Agent Kit) — self-custody, BSC mainnet",
        "eligible_tokens": 149,
        "compliance_window": "soft 18h UTC, alert 22h UTC, hard 23h UTC force-trade",
    },
}

def build_policy_hash(policy: dict) -> str:
    canonical = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(canonical.encode()).hexdigest()

def sign_policy_eip191(policy_hash: str) -> dict | None:
    """Sign policy hash locally with EIP-191. No BNB needed. Verifiable off-chain."""
    try:
        from web3 import Web3
        from eth_account.messages import encode_defunct
    except ImportError:
        print("web3 not installed. Run: pip install web3")
        return None

    private_key = os.getenv("AGENT_PRIVATE_KEY", "")
    if not private_key:
        print("ERROR: AGENT_PRIVATE_KEY not set in .env")
        return None

    w3 = Web3()
    account = w3.eth.account.from_key(private_key)
    address = account.address

    # EIP-191 sign the policy hash
    msg = encode_defunct(text=f"AlphaLoop Risk Policy Commitment\n{policy_hash}")
    signed = w3.eth.account.sign_message(msg, private_key=private_key)

    print(f"Signer address: {address}")
    print(f"Policy hash:    {policy_hash}")
    print(f"EIP-191 sig:    {signed.signature.hex()}")

    return {
        "signer": address,
        "policy_hash": policy_hash,
        "signature": signed.signature.hex(),
        "message": f"AlphaLoop Risk Policy Commitment\n{policy_hash}",
        "verify_with": f"web3.eth.account.recover_message(encode_defunct(text=message), signature=sig)",
    }

def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("AlphaLoop Risk Policy Commitment")
    print("=" * 60)

    policy_hash = build_policy_hash(POLICY)
    policy_json = json.dumps(POLICY, indent=2)

    print("\nPolicy:")
    print(policy_json)
    print(f"\nSHA-256 hash: {policy_hash}")

    # Save policy locally
    os.makedirs("storage", exist_ok=True)
    with open("storage/risk_policy.json", "w") as f:
        json.dump({"policy": POLICY, "hash": policy_hash}, f, indent=2)
    print("\nSaved to storage/risk_policy.json")

    # Sign with EIP-191 (no BNB needed, fully verifiable)
    print("\nSigning policy with EIP-191...")
    signed = sign_policy_eip191(policy_hash)

    if signed:
        result = {
            "policy_hash": policy_hash,
            "signed_at": POLICY["committed_at"],
            "signer": signed["signer"],
            "signature": signed["signature"],
            "message": signed["message"],
            "policy": POLICY,
        }
        with open("storage/policy_commitment.json", "w") as f:
            json.dump(result, f, indent=2)
        print("\n✅ Policy signed successfully!")
        print(json.dumps({k: v for k, v in result.items() if k != "policy"}, indent=2))
    else:
        print("\n❌ Signing failed.")

if __name__ == "__main__":
    main()
