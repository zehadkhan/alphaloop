"""On-chain decision proof — AlphaLoop's verifiability layer.

For every executed trade we:
  1. Build a canonical proof string encoding the full compass state + decision
  2. SHA-256 hash it → proof_hash
  3. In COMPETITION_MODE + mainnet: commit proof_hash as calldata in a
     self-transfer BNB tx (costs only gas ~21k + calldata)
  4. Store proof_string, proof_hash, proof_tx_hash in the Trade record

Verification (scripts/verify_trade.py):
  - Load proof_string from DB
  - Recompute sha256(proof_string) → must match proof_hash
  - Fetch BSC tx calldata → must match "0x" + proof_hash

The proof captures the MARKET STATE at decision time, not just the trade intent.
This is unique among competition entries — the regime axes are part of the record.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

_PREFIX = "ALPHALOOP_PROOF_v1"


def build_proof(
    unix_ts: int,
    symbol: str,
    compass: dict,
    confidence: float,
    action: str,
    entry_price: float,
) -> tuple[str, str]:
    """Build proof string and hash.

    Returns:
        (proof_string, proof_hash)

    Format (pipe-delimited, human-readable, reproducible):
      ALPHALOOP_PROOF_v1|{ts}|{symbol}|{score}|momentum:{m},sentiment:{s},
      stress:{st},trend:{tr},volatility:{v}|{confidence}|{action}|{entry_price}
    """
    axes = compass.get("axes", {})
    axes_str = ",".join(f"{k}:{v:.1f}" for k, v in sorted(axes.items()))
    proof_string = (
        f"{_PREFIX}"
        f"|{unix_ts}"
        f"|{symbol.upper()}"
        f"|{compass.get('compass_score', 0.0):.1f}"
        f"|{axes_str}"
        f"|{confidence:.2f}"
        f"|{action.upper()}"
        f"|{entry_price:.4f}"
    )
    proof_hash = hashlib.sha256(proof_string.encode()).hexdigest()
    return proof_string, proof_hash


async def commit_proof_onchain(
    trade_id: int,
    proof_hash: str,
    dry_run: bool = True,
) -> str | None:
    """Send a self-transfer BNB tx with proof_hash as calldata.

    In DRY_RUN mode: logs only, no tx.
    Returns the tx_hash on success, None if skipped or failed.
    This is non-blocking — trade execution never waits for BSC confirmation.
    """
    logger.info("[Proof] trade_id=%d  hash=%s…  dry_run=%s",
                trade_id, proof_hash[:16], dry_run)

    if dry_run:
        logger.info("[Proof] DRY_RUN — on-chain commit skipped (hash computed and stored)")
        return None

    try:
        from agent.config import config
        from execution.bnb_wallet import BNBWallet

        wallet = BNBWallet()
        w3      = wallet.w3
        account = wallet.account

        calldata = "0x" + proof_hash  # 32 bytes of hash as hex = 66 chars

        nonce = await w3.eth.get_transaction_count(account.address)
        gas_price = await w3.eth.gas_price
        chain_id = 56 if config.ENVIRONMENT == "mainnet" else 97

        tx = {
            "from":     account.address,
            "to":       account.address,
            "value":    0,
            "data":     calldata,
            "nonce":    nonce,
            "chainId":  chain_id,
            "gas":      50_000,
            "gasPrice": gas_price,
        }
        signed   = account.sign_transaction(tx)
        tx_bytes = signed.rawTransaction
        tx_hash  = (await w3.eth.send_raw_transaction(tx_bytes)).hex()
        logger.info("[Proof] Committed on-chain: tx=%s", tx_hash)
        return tx_hash
    except Exception as exc:
        logger.error("[Proof] On-chain commit failed (non-fatal, hash still stored): %s", exc)
        return None
