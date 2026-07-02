#!/usr/bin/env python3
"""Sell ALL token balances in the TWAK wallet back to BNB.

Calls the live admin endpoint on the VPS — no local TWAK needed.

Run:
    python scripts/sell_all.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

WALLET        = "0xa401A91faa968Ee4334780712C95Af208E570e0F"
BSC_RPC       = "https://bsc-dataseed.binance.org/"
BSCSCAN_URL   = "https://api.bscscan.com/api"
ADMIN_URL     = "http://qp38fy65jtmff7agx1e4ufr0.75.119.139.99.sslip.io"
ADMIN_PASS    = os.getenv("ADMIN_PASSWORD", "MpgTzAJ1rio4i!")
MIN_USD       = 0.10

SKIP_CONTRACTS = {
    "0x55d398326f99059ff775485246999027b3197955",  # USDT
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
    "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
}


async def rpc_call(method: str, params: list) -> str:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(BSC_RPC, json={"jsonrpc": "2.0", "method": method,
                                        "params": params, "id": 1})
        return r.json().get("result", "0x0")


async def get_decimals(contract: str) -> int:
    try:
        result = await rpc_call("eth_call", [{"to": contract, "data": "0x313ce567"}, "latest"])
        val = int(result, 16)
        return val if 0 < val <= 18 else 18
    except Exception:
        return 18


async def get_balance(contract: str) -> tuple[float, int]:
    data = "0x70a08231" + "000000000000000000000000" + WALLET[2:].lower()
    try:
        decimals = await get_decimals(contract)
        result = await rpc_call("eth_call", [{"to": contract, "data": data}, "latest"])
        return int(result, 16) / 10**decimals, decimals
    except Exception:
        return 0.0, 18


async def get_symbol(contract: str) -> str:
    try:
        result = await rpc_call("eth_call", [{"to": contract, "data": "0x95d89b41"}, "latest"])
        hex_data = result[2:]
        if len(hex_data) < 128:
            return ""
        str_len = int(hex_data[64:128], 16)
        str_hex = hex_data[128:128 + str_len * 2]
        return bytes.fromhex(str_hex).decode("utf-8", errors="replace").strip("\x00").strip()
    except Exception:
        return ""


async def get_price_usdt(sym: str) -> float:
    async with httpx.AsyncClient(timeout=8) as c:
        for pair in [f"{sym}USDT", f"{sym}BNB"]:
            try:
                r = await c.get("https://api.binance.com/api/v3/ticker/price",
                                params={"symbol": pair})
                data = r.json()
                if "price" not in data:
                    continue
                price = float(data["price"])
                if "BNB" in pair:
                    bnb_r = await c.get("https://api.binance.com/api/v3/ticker/price",
                                        params={"symbol": "BNBUSDT"})
                    price *= float(bnb_r.json()["price"])
                return price
            except Exception:
                continue
    return 0.0


async def sell_token_via_admin(sym: str, contract: str, usd_value: float) -> dict:
    """POST to /admin/sell-one — a lightweight single-token endpoint."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{ADMIN_URL}/admin/sell-one",
            headers={"x-admin-password": ADMIN_PASS},
            json={"symbol": sym, "contract": contract, "usd_value": round(usd_value, 4)},
        )
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()


async def discover_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}
    print("Querying BSCScan for token history...")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(BSCSCAN_URL, params={
                "module": "account", "action": "tokentx",
                "address": WALLET, "page": 1, "offset": 2000,
                "sort": "desc", "apikey": "YourApiKeyToken",
            })
        txs = r.json().get("result", [])
        if isinstance(txs, list):
            for tx in txs:
                addr = tx.get("contractAddress", "").lower()
                sym  = tx.get("tokenSymbol", "").upper()
                if addr and addr not in SKIP_CONTRACTS:
                    tokens[addr] = sym
        print(f"  Found {len(tokens)} unique contracts\n")
    except Exception as e:
        print(f"  BSCScan error: {e}\n")
    return tokens


async def main():
    print(f"=== SELL ALL | wallet {WALLET} ===\n")

    tokens = await discover_tokens()
    if not tokens:
        print("No tokens discovered. Exiting.")
        return

    to_sell: list[tuple[str, str, float, float]] = []  # (contract, sym, bal, usd)

    print("Checking on-chain balances...")
    for contract, sym in sorted(tokens.items(), key=lambda x: x[1]):
        bal, decimals = await get_balance(contract)
        if bal < 1e-6:
            continue
        label = sym if sym else await get_symbol(contract)
        if not label:
            label = contract[:10]
        price = await get_price_usdt(label)
        usd   = bal * price
        status = f"${usd:.2f}" if usd >= MIN_USD else f"${usd:.4f} DUST"
        print(f"  {label:<12} bal={bal:<14.4f} dec={decimals}  price=${price:.6f}  {status}")
        if usd >= MIN_USD:
            to_sell.append((contract, label, bal, usd))

    print(f"\n{len(to_sell)} tokens to sell (above ${MIN_USD})\n")
    if not to_sell:
        print("Nothing to sell.")
        return

    sold   = []
    errors = []

    for contract, sym, bal, usd in to_sell:
        print(f"  Selling {sym} (${usd:.2f}) ...", end=" ", flush=True)
        try:
            result = await sell_token_via_admin(sym, contract, usd * 0.999)
            bnb = result.get("bnb_received", 0.0)
            tx  = result.get("tx_hash", "")
            print(f"✓  {bnb:.6f} BNB  tx={tx[:20]}...")
            sold.append({"sym": sym, "usd": usd, "bnb": bnb})
        except Exception as e:
            print(f"✗  {e}")
            errors.append({"sym": sym, "error": str(e)})

    total_bnb = sum(s["bnb"] for s in sold)
    print(f"\n=== DONE ===")
    print(f"Sold: {len(sold)}  |  Errors: {len(errors)}")
    print(f"Total: {total_bnb:.6f} BNB  (${total_bnb * 550:.2f})")
    if errors:
        print("\nFailed:")
        for e in errors:
            print(f"  {e['sym']}: {e['error']}")


if __name__ == "__main__":
    asyncio.run(main())
