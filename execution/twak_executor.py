"""TWAK (Trust Wallet Agent Kit) swap executor.

Replaces PancakeSwapExecutor when TWAK_REST_URL is configured.
Uses POST /actions/swap — TWAK handles routing, signing, and broadcast.
Auth: Authorization: Bearer <hmacSecret>
"""
from __future__ import annotations

import json
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

def _get_chain() -> str:
    """Return the TWAK chain identifier — read at call time so Docker env vars are loaded."""
    return "bsc" if os.getenv("ENVIRONMENT", "testnet") == "mainnet" else "bsc-testnet"


def _load_credentials() -> tuple[str, str]:
    """Return (base_url, bearer_token) from env or ~/.twak/credentials.json."""
    base_url = os.getenv("TWAK_REST_URL", "http://127.0.0.1:7777")
    secret = os.getenv("TWAK_HMAC_SECRET", "")
    if not secret:
        try:
            creds_path = os.path.expanduser("~/.twak/credentials.json")
            with open(creds_path) as f:
                secret = json.load(f).get("hmacSecret", "")
        except Exception:
            pass
    return base_url.rstrip("/"), secret


class TWAKExecutorError(Exception):
    pass


class TWAKExecutor:
    """Execute token swaps through the TWAK REST server.

    Drop-in replacement for PancakeSwapExecutor with the same swap() surface.
    The TWAK wallet address is read from the running server on init.
    """

    def __init__(self) -> None:
        self._base_url, self._secret = _load_credentials()
        self.dry_run: bool = os.getenv("DRY_RUN", "true").lower() == "true"
        self._address: str = ""

    @property
    def address(self) -> str:
        return self._address

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._secret}",
            "Content-Type": "application/json",
        }

    async def _call(self, action: str, params: dict) -> dict:
        url = f"{self._base_url}/actions/{action}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=params, headers=self._headers())
        if resp.status_code == 401:
            raise TWAKExecutorError("TWAK auth failed — check TWAK_HMAC_SECRET")
        data = resp.json()
        if resp.status_code != 200:
            raise TWAKExecutorError(
                f"TWAK {action} failed ({resp.status_code}): "
                f"{data.get('message', data)}"
            )
        return data

    async def init_address(self) -> str:
        """Fetch the TWAK wallet BSC address."""
        try:
            data = await self._call("get_address", {"chain": _get_chain()})
            self._address = data.get("address", "")
            logger.info("TWAK wallet address on %s: %s", _get_chain(), self._address)
        except Exception as exc:
            logger.warning("Could not fetch TWAK address: %s", exc)
        return self._address

    async def get_price(self, token_in: str, token_out: str) -> float:
        """Return current price of token_in in token_out units via get_swap_quote."""
        data = await self._call("get_swap_quote", {
            "fromChain": _get_chain(),
            "fromToken": token_in.upper(),
            "toChain":   _get_chain(),
            "toToken":   token_out.upper(),
            "amount":    "1",
        })
        out = data.get("toAmount") or data.get("estimatedOutput") or "0"
        return float(out)

    async def swap(self, token_in: str, token_out: str, amount_usd: float) -> dict:
        """Execute a swap on BSC via TWAK.

        amount_usd is always denominated in USD.
        For token_in == USDT, amount = amount_usd directly.
        For token_in == BNB (or other), amount = amount_usd / current_price.
        """
        token_in  = token_in.upper()
        token_out = token_out.upper()

        # Convert USD to token_in units
        if token_in in ("USDT", "USDC", "BUSD"):
            amount_str = str(round(amount_usd, 6))
        else:
            # Get price to convert USD → token
            try:
                price = await self.get_price(token_in, "USDT")
                token_amount = amount_usd / price if price else 0
            except Exception:
                token_amount = 0
            if token_amount <= 0:
                raise TWAKExecutorError(f"Cannot determine {token_in} amount from ${amount_usd}")
            amount_str = str(round(token_amount, 8))

        logger.info(
            "TWAK swap: %s %s → %s  dry_run=%s  chain=%s",
            amount_str, token_in, token_out, self.dry_run, _get_chain(),
        )

        if self.dry_run:
            logger.warning("[DRY-RUN] TWAK swap NOT executed")
            return {
                "tx_hash":    None,
                "token_in":   token_in,
                "token_out":  token_out,
                "amount_in":  float(amount_str),
                "amount_out": 0.0,
                "price":      0.0,
                "gas_used":   0,
                "status":     "dry_run",
            }

        data = await self._call("swap", {
            "fromChain": _get_chain(),
            "fromToken": token_in,
            "toChain":   _get_chain(),
            "toToken":   token_out,
            "amount":    amount_str,
        })

        tx_hash   = data.get("txHash") or data.get("tx_hash") or data.get("hash")
        amount_out = float(data.get("toAmount") or data.get("receivedAmount") or 0)
        price      = amount_out / float(amount_str) if float(amount_str) else 0

        logger.info(
            "TWAK swap done: %s %s → %s %.6f  tx=%s",
            amount_str, token_in, token_out, amount_out, tx_hash,
        )

        return {
            "tx_hash":    tx_hash,
            "token_in":   token_in,
            "token_out":  token_out,
            "amount_in":  float(amount_str),
            "amount_out": amount_out,
            "price":      round(price, 6),
            "gas_used":   data.get("gasUsed", 0),
            "status":     "success" if tx_hash else "failed",
        }

    async def competition_register(self) -> dict:
        """Register for BNB HACK via TWAK REST."""
        return await self._call("competition_register", {})

    async def competition_status(self) -> dict:
        """Check competition registration status."""
        return await self._call("competition_status", {})

    async def x402_request(self, url: str, method: str = "GET", max_payment_atomic: str = "1000") -> dict:
        """Make an x402 payment-gated request via TWAK."""
        return await self._call("x402_request", {
            "url":               url,
            "method":            method,
            "maxPaymentAtomic":  max_payment_atomic,
        })
