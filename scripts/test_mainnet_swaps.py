#!/usr/bin/env python3
"""Test that PancakeSwap V2 swap paths exist for the top competition tokens.

Only fetches quotes — does NOT execute any transactions.
Usage:  ENVIRONMENT=mainnet python scripts/test_mainnet_swaps.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

TOKENS_TO_TEST = ["BNB", "CAKE", "LINK", "ETH", "BTC", "SOL", "ADA", "DOT"]


async def test_quotes_via_twak() -> None:
    """Test swap quotes through the TWAK REST server."""
    from execution.twak_executor import TWAKExecutor, TWAKExecutorError
    executor = TWAKExecutor()
    print(f"\n[TWAK] Testing swap quotes on {executor._base_url}")
    addr = await executor.init_address()
    print(f"  Wallet: {addr or 'not fetched'}\n")

    passed = failed = 0
    for sym in TOKENS_TO_TEST:
        if sym == "USDT":
            continue
        try:
            price = await executor.get_price(sym, "USDT")
            if price > 0:
                print(f"  \033[92m✓\033[0m  {sym}/USDT = ${price:,.4f}")
                passed += 1
            else:
                print(f"  \033[91m✗\033[0m  {sym}/USDT = 0 (no liquidity?)")
                failed += 1
        except TWAKExecutorError as exc:
            print(f"  \033[91m✗\033[0m  {sym}/USDT error: {exc}")
            failed += 1

    print(f"\n  {passed} passed, {failed} failed")
    return passed, failed


async def test_quotes_via_pancakeswap() -> None:
    """Test swap quotes directly via PancakeSwap V2 on BSC mainnet."""
    from web3 import AsyncWeb3
    from execution._compat import PoAMiddleware
    from execution.pancakeswap import _MAINNET_TOKENS, ROUTER_ADDRESS_MAINNET, WBNB_ADDRESS_MAINNET

    ROUTER_ABI_FRAGMENT = [{
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    }]

    rpc = os.getenv("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
    w3.middleware_onion.inject(PoAMiddleware, layer=0)

    router = w3.eth.contract(
        address=w3.to_checksum_address(ROUTER_ADDRESS_MAINNET),
        abi=ROUTER_ABI_FRAGMENT,
    )
    usdt = _MAINNET_TOKENS.get("USDT", "0x55d398326f99059fF775485246999027B3197955")

    print(f"\n[PancakeSwap V2] Testing getAmountsOut on mainnet\n")
    passed = failed = 0

    for sym in TOKENS_TO_TEST:
        token_addr = _MAINNET_TOKENS.get(sym)
        if not token_addr:
            print(f"  \033[93m!\033[0m  {sym}: not in token map, skipping")
            continue

        # Quote: 1 token → USDT (or 1 USDT → token for USDT itself)
        try:
            if sym == "BNB":
                path = [w3.to_checksum_address(WBNB_ADDRESS_MAINNET),
                        w3.to_checksum_address(usdt)]
                amount_in = w3.to_wei(1, "ether")
            else:
                path = [w3.to_checksum_address(token_addr),
                        w3.to_checksum_address(WBNB_ADDRESS_MAINNET),
                        w3.to_checksum_address(usdt)]
                amount_in = 10**18  # 1 token (18 decimals)

            amounts = await router.functions.getAmountsOut(amount_in, path).call()
            price_usdt = amounts[-1] / 10**18
            print(f"  \033[92m✓\033[0m  {sym}/USDT = ${price_usdt:,.4f}  (path len={len(path)})")
            passed += 1
        except Exception as exc:
            print(f"  \033[91m✗\033[0m  {sym}: {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n  {passed} passed, {failed} failed")
    return passed, failed


async def main() -> None:
    env = os.getenv("ENVIRONMENT", "testnet")
    twak_url = os.getenv("TWAK_REST_URL", "")

    print("====== AlphaLoop — Mainnet Swap Path Test ======")
    print(f"  ENVIRONMENT = {env}")
    print(f"  TWAK_REST_URL = {twak_url or '(not set)'}")

    if env != "mainnet":
        print("\n  WARNING: ENVIRONMENT is not 'mainnet' — set ENVIRONMENT=mainnet in .env")

    total_passed = total_failed = 0

    if twak_url:
        p, f = await test_quotes_via_twak()
        total_passed += p
        total_failed += f
    else:
        print("\n  TWAK_REST_URL not configured — testing via PancakeSwap V2 directly")

    p, f = await test_quotes_via_pancakeswap()
    total_passed += p
    total_failed += f

    print("\n====== Result ======")
    if total_failed == 0:
        print(f"  \033[92mAll {total_passed} swap paths OK\033[0m")
    else:
        print(f"  \033[91m{total_failed} path(s) FAILED — check token addresses in execution/pancakeswap.py\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
