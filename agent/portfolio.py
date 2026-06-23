"""Eligible-portfolio sizing for competition mode."""
from __future__ import annotations

import logging

import httpx

from agent.config import config
from data.bsc_token_addresses import get_bsc_address

logger = logging.getLogger(__name__)

_BSC_RPC = "https://bsc-dataseed.binance.org/"
_BALANCE_OF = "0x70a08231"


async def _erc20_balance(wallet: str, contract: str, decimals: int = 18) -> float:
    padded = wallet.lower().removeprefix("0x").zfill(64)
    data = _BALANCE_OF + padded
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                _BSC_RPC,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [{"to": contract, "data": data}, "latest"],
                    "id": 1,
                },
            )
        result = resp.json().get("result", "0x0")
        return int(result, 16) / 10**decimals
    except Exception as exc:
        logger.debug("balance fetch failed for %s: %s", contract, exc)
        return 0.0


async def _token_usd_price(symbol: str) -> float:
    pair = symbol.upper() + "USDT"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": pair},
            )
        if resp.status_code == 200:
            return float(resp.json()["price"])
    except Exception:
        pass
    return 0.0


async def get_eligible_portfolio_usd(wallet: str | None = None) -> float:
    """Sum USD value of eligible tokens held (excludes native BNB)."""
    if wallet is None:
        wallet = config.AGENT_WALLET_ADDRESS
    if not wallet:
        return config.INITIAL_PORTFOLIO_USD

    total = 0.0
    for sym in config.ELIGIBLE_TOKENS:
        contract = get_bsc_address(sym)
        if not contract:
            continue
        bal = await _erc20_balance(wallet, contract)
        if bal <= 0:
            continue
        price = await _token_usd_price(sym)
        if price > 0:
            total += bal * price

    if total <= 0:
        return config.INITIAL_PORTFOLIO_USD
    return round(total, 2)


async def cap_position_usd(requested_usd: float, wallet: str | None = None) -> float:
    """Cap position to a fraction of eligible portfolio value."""
    pct = config.MAX_POSITION_PCT_OF_PORTFOLIO
    if pct <= 0 or pct >= 1:
        return requested_usd

    portfolio = await get_eligible_portfolio_usd(wallet)
    cap = round(portfolio * pct, 2)
    cap = max(cap, config.MIN_SWAP_USD)
    capped = min(requested_usd, cap)
    if capped < requested_usd:
        logger.info(
            "[Sizing] Capped $%.2f → $%.2f (%.0f%% of $%.2f eligible portfolio)",
            requested_usd, capped, pct * 100, portfolio,
        )
    return capped
