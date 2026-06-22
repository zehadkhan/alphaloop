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

# Module-level cache: symbol → BSC contract address (persists across executor instances per process)
_bsc_address_cache: dict[str, str] = {}

# Tokens TWAK recognises by symbol without needing a contract address
_TWAK_KNOWN_SYMBOLS = {"BNB", "ETH", "USDT", "USDC", "BUSD", "WBTC", "BTC", "CAKE"}


async def _resolve_bsc_token(symbol: str) -> str:
    """Return the best identifier for *symbol* that TWAK's swap endpoint accepts.

    Returns the symbol as-is for well-known tokens. For others, queries CMC to get
    the BEP-20 contract address (cached per process). Falls back to the symbol if
    the lookup fails so the caller can still attempt the swap.
    """
    sym = symbol.upper()
    if sym in _TWAK_KNOWN_SYMBOLS:
        return sym
    if sym in _bsc_address_cache:
        return _bsc_address_cache[sym]

    cmc_key = os.getenv("CMC_API_KEY", "")
    if not cmc_key:
        logger.warning("[TWAK] CMC_API_KEY not set — cannot resolve BSC address for %s", sym)
        return sym

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://pro-api.coinmarketcap.com/v1/cryptocurrency/info",
                params={"symbol": sym},
                headers={"X-CMC_PRO_API_KEY": cmc_key, "Accept": "application/json"},
            )
        token_data = resp.json().get("data", {}).get(sym, {})
        if isinstance(token_data, list):
            token_data = token_data[0]

        for ca in token_data.get("contract_address", []):
            platform_name = ca.get("platform", {}).get("name", "").lower()
            if "bnb smart chain" in platform_name or "bep20" in platform_name:
                addr = ca["contract_address"]
                _bsc_address_cache[sym] = addr
                logger.info("[TWAK] Resolved %s → BSC address %s", sym, addr)
                return addr
    except Exception as exc:
        logger.warning("[TWAK] BSC address lookup failed for %s: %s", sym, exc)

    return sym

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
        self._wallet_mode_set: bool = False

    @property
    def address(self) -> str:
        return self._address

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._secret}",
            "Content-Type": "application/json",
        }

    async def _ensure_local_wallet(self) -> None:
        """Set TWAK to local wallet mode once per executor instance."""
        if self._wallet_mode_set:
            return
        try:
            url = f"{self._base_url}/actions/switch_wallet_mode"
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(url, json={"mode": "local"}, headers=self._headers())
            logger.info("TWAK wallet mode → local")
        except Exception as exc:
            logger.debug("switch_wallet_mode skipped: %s", exc)
        self._wallet_mode_set = True

    async def _call(self, action: str, params: dict) -> dict:
        if action != "switch_wallet_mode":
            await self._ensure_local_wallet()
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
        # TWAK returns HTTP 200 even for logical errors — check the success flag
        if data.get("success") is False:
            code = data.get("code", "UNKNOWN")
            msg  = data.get("message", str(data))
            raise TWAKExecutorError(f"TWAK {action} error [{code}]: {msg}")
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

    async def _binance_spot_price(self, token_in: str, token_out: str = "USDT") -> float:
        """Fallback spot price via Binance public API (token_in per 1 unit in token_out)."""
        pair = f"{token_in.upper()}{token_out.upper()}"
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": pair},
            )
        if resp.status_code != 200:
            raise TWAKExecutorError(f"Binance price unavailable for {pair} (HTTP {resp.status_code})")
        price = float(resp.json()["price"])
        if price <= 0:
            raise TWAKExecutorError(f"Binance returned invalid price for {pair}")
        return price

    async def get_price(self, token_in: str, token_out: str) -> float:
        """Return current price of token_in in token_out units.

        Tries TWAK get_swap_quote first; falls back to Binance if TWAK fails or
        returns zero (common when quote routing is unavailable).
        """
        token_in  = token_in.upper()
        token_out = token_out.upper()
        try:
            data = await self._call("get_swap_quote", {
                "fromChain": _get_chain(),
                "fromToken": token_in,
                "toChain":   _get_chain(),
                "toToken":   token_out,
                "amount":    "1",
            })
            out = data.get("toAmount") or data.get("estimatedOutput") or "0"
            price = float(out)
            if price > 0:
                logger.info("Price %s/%s via TWAK: %.6f", token_in, token_out, price)
                return price
            logger.warning("TWAK quote returned 0 for %s/%s — trying Binance", token_in, token_out)
        except Exception as exc:
            logger.warning(
                "TWAK get_swap_quote failed for %s/%s (%s) — trying Binance",
                token_in, token_out, exc,
            )

        if token_out in ("USDT", "USDC", "BUSD"):
            price = await self._binance_spot_price(token_in, token_out)
            logger.info("Price %s/%s via Binance fallback: %.6f", token_in, token_out, price)
            return price
        raise TWAKExecutorError(f"Cannot price {token_in}/{token_out} — TWAK failed and no fallback")

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
            try:
                price = await self.get_price(token_in, "USDT")
                token_amount = amount_usd / price if price else 0
            except Exception as exc:
                logger.error("Price lookup failed for %s: %s", token_in, exc)
                raise TWAKExecutorError(
                    f"Cannot determine {token_in} amount from ${amount_usd}: {exc}"
                ) from exc
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

        # Resolve token symbols to BSC contract addresses where needed.
        # TWAK only recognises major symbols (ETH, BNB, USDT…); altcoins require
        # the BEP-20 contract address so the router can find the liquidity pool.
        from_resolved = await _resolve_bsc_token(token_in)
        to_resolved   = await _resolve_bsc_token(token_out)
        logger.info(
            "[TWAK] Token resolution: %s→%s  %s→%s",
            token_in, from_resolved, token_out, to_resolved,
        )

        data = await self._call("swap", {
            "fromChain": _get_chain(),
            "fromToken": from_resolved,
            "toChain":   _get_chain(),
            "toToken":   to_resolved,
            "amount":    amount_str,
        })

        logger.info("TWAK swap raw response: %s", data)
        tx_hash   = (data.get("txHash") or data.get("tx_hash") or data.get("hash")
                     or data.get("transactionHash") or data.get("receipt", {}).get("transactionHash"))
        amount_out = float(data.get("toAmount") or data.get("receivedAmount")
                          or data.get("amountOut") or 0)
        # TWAK response includes a human-readable summary: "0.001 BNB -> 0.0354 DEXE"
        if not amount_out and data.get("summary"):
            try:
                amount_out = float(data["summary"].split("->")[1].strip().split()[0])
            except Exception:
                pass
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
