"""Trust Wallet Agent Kit (TWAK) CLI wrapper.

Wraps the `twak` CLI for on-chain registration and competition-mode signing.
All calls are fire-and-forget subprocess invocations; the REST path is used
for x402 payment requests during the live trading window.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

TWAK_BIN = os.getenv("TWAK_BIN", "twak")          # path to CLI binary
WALLET_NAME = os.getenv("TWAK_WALLET_NAME", "alphaloop")
COMPETITION_CONTRACT = "0x212c61b9b72c95d95bf29cf032f5e5635629aed5"


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _run(args: list[str], *, timeout: int = 30) -> dict:
    """Run a TWAK CLI command synchronously, return parsed JSON or raw output."""
    cmd = [TWAK_BIN, *args]
    logger.debug("TWAK CLI: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            logger.error("TWAK CLI error (rc=%d): %s", result.returncode, stderr or stdout)
            return {"ok": False, "error": stderr or stdout, "rc": result.returncode}
        try:
            return {"ok": True, **json.loads(stdout)}
        except json.JSONDecodeError:
            return {"ok": True, "output": stdout}
    except FileNotFoundError:
        logger.warning("TWAK CLI not found at %r — is it installed? (npm install -g @trustwallet/agent-kit)", TWAK_BIN)
        return {"ok": False, "error": "twak_not_installed"}
    except subprocess.TimeoutExpired:
        logger.error("TWAK CLI timed out after %ds", timeout)
        return {"ok": False, "error": "timeout"}


async def _run_async(args: list[str], *, timeout: int = 30) -> dict:
    """Async wrapper around _run so it doesn't block the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _run(args, timeout=timeout))


# ---------------------------------------------------------------------------
# On-chain registration
# ---------------------------------------------------------------------------

async def register_agent() -> dict:
    """Register this agent on the competition contract.

    Equivalent to:  twak compete register --wallet <name> --contract <addr>
    """
    logger.info("Registering agent on competition contract %s", COMPETITION_CONTRACT)
    result = await _run_async([
        "compete", "register",
        "--wallet", WALLET_NAME,
        "--contract", COMPETITION_CONTRACT,
    ], timeout=60)
    if result.get("ok"):
        logger.info("Agent registered: %s", result)
    else:
        logger.error("Registration failed: %s", result.get("error"))
    return result


async def check_registration() -> dict:
    """Check whether this wallet is registered on the competition contract."""
    return await _run_async([
        "compete", "status",
        "--wallet", WALLET_NAME,
        "--contract", COMPETITION_CONTRACT,
    ])


# ---------------------------------------------------------------------------
# Wallet / signing
# ---------------------------------------------------------------------------

async def get_balance(token: str = "BNB") -> dict:
    """Return wallet balance for *token* on BSC."""
    return await _run_async(["balance", "--wallet", WALLET_NAME, "--token", token])


async def sign_and_broadcast(tx: dict) -> dict:
    """Sign a raw transaction dict via TWAK and broadcast it.

    TWAK handles key custody; we pass the unsigned tx as JSON on stdin.
    """
    tx_json = json.dumps(tx)
    cmd = [TWAK_BIN, "sign", "--wallet", WALLET_NAME, "--broadcast"]
    logger.debug("TWAK sign+broadcast: tx_json=%s", tx_json)
    try:
        result = subprocess.run(
            cmd,
            input=tx_json,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        stdout = result.stdout.strip()
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or stdout}
        try:
            return {"ok": True, **json.loads(stdout)}
        except json.JSONDecodeError:
            return {"ok": True, "tx_hash": stdout}
    except FileNotFoundError:
        return {"ok": False, "error": "twak_not_installed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}


# ---------------------------------------------------------------------------
# x402 payment request
# ---------------------------------------------------------------------------

async def make_x402_payment(endpoint: str, amount_usd_cents: int = 1) -> dict:
    """Trigger an x402 micropayment for *endpoint* via TWAK.

    Used for paid CMC Agent Hub requests; logs the on-chain tx hash as proof.
    """
    result = await _run_async([
        "x402", "pay",
        "--wallet", WALLET_NAME,
        "--endpoint", endpoint,
        "--amount", str(amount_usd_cents),
    ])
    if result.get("ok"):
        logger.info("x402 payment sent: endpoint=%s tx=%s", endpoint, result.get("tx_hash"))
    else:
        logger.warning("x402 payment failed: %s", result.get("error"))
    return result
