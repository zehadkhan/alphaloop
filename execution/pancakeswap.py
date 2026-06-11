"""PancakeSwap V2 executor on BSC testnet.

Router: 0xD99D1c33F9fC3444f8101754aBC46c52416550D1
Pair  : BNB (native) ↔ USDT (BEP-20)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from web3 import AsyncWeb3
from web3.exceptions import ContractLogicError
from execution._compat import PoAMiddleware

from execution.wallet import WalletAgent, WalletError, InsufficientBalanceError

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Network constants (BSC testnet, chain ID 97)
# ---------------------------------------------------------------------------

ROUTER_ADDRESS = (
    "0x10ED43C718714eb63d5aA57B78B54704E256024E"   # mainnet PancakeSwap V2
    if os.getenv("ENVIRONMENT", "testnet") == "mainnet"
    else "0xD99D1c33F9fC3444f8101754aBC46c52416550D1"  # testnet
)

# WBNB is what the router uses internally when you pass native BNB
WBNB_ADDRESS  = "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd"
USDT_ADDRESS  = "0x337610D27C682E347C9cd60bD4b3b107c9d34ddE"

# BSC mainnet router (PancakeSwap V2)
ROUTER_ADDRESS_MAINNET = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
WBNB_ADDRESS_MAINNET   = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT_ADDRESS_MAINNET   = "0x55d398326f99059fF775485246999027B3197955"

# Mainnet BEP-20 addresses for competition-eligible tokens
_MAINNET_TOKENS: dict[str, str] = {
    "BNB":   WBNB_ADDRESS_MAINNET,
    "WBNB":  WBNB_ADDRESS_MAINNET,
    "USDT":  USDT_ADDRESS_MAINNET,
    "USDC":  "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "BTC":   "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",   # BTCB
    "ETH":   "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
    "CAKE":  "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
    "LINK":  "0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD",
    "UNI":   "0xBf5140A22578168FD562DCcF235E5D43A02ce9B1",
    "AAVE":  "0xfb6115445Bff7b52FeB98650C87f44907E58f802",
    "DOT":   "0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402",
    "ADA":   "0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47",
    "SOL":   "0x570A5D26f7765Ecb712C0924E4De545B89fD43dF",
    "AVAX":  "0x1CE0c2827e2eF14D5C4f29a091d735A204794041",
    "MATIC": "0xCC42724C6683B7E57334c4E856f4c9965ED682bD",
    "ATOM":  "0x0Eb3a705fc54725037CC9e008bDede697f62F335",
    "XRP":   "0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
    "LTC":   "0x4338665CBB7B2485A8855A139b75D5e34AB0DB94",
    "NEAR":  "0x1Fa4a73a3F0133f0025378af00236f3aBDEE5D63",
    "FTM":   "0xAD29AbB318791D579433D831ed122aFeAf29dcfe",
    "SAND":  "0x67b725d7e342d7B611fa85e859Df9697D9378B2e",
    "MANA":  "0x26433c8127d9b4e9B71Eaa15111DF99Ea2EeB2f8",
    "CHZ":   "0x79a61D3a28F8c8537A3DF63092927cFa1150Fb38",
    "VET":   "0x6FDcdfef7c496407cCb0cEC90f9C5Aaa1Cc8D888",
    "DOGE":  "0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
    "ALGO":  "0xa767f745331D267c7751297D982b050c93985627",
    "TRX":   "0x85EAC5Ac2F758618dFa09bDbe0cf174e7d574D5B",
    "XLM":   "0x43C934A845205F0b514417d757d7235B8f53f1B9",
    "BCH":   "0x8fF795a6F4D97E7887C79beA79aba5cc76444aDC",
    "ETC":   "0x3d6545b08693daE087E957cb1180ee38B9e3c25E",
}

# Runtime token address table — starts with testnet, switches on mainnet
_ENVIRONMENT = os.getenv("ENVIRONMENT", "testnet")
TOKEN_ADDRESSES: dict[str, str] = (
    _MAINNET_TOKENS if _ENVIRONMENT == "mainnet" else {
        "BNB":  WBNB_ADDRESS,
        "WBNB": WBNB_ADDRESS,
        "USDT": USDT_ADDRESS,
    }
)

SLIPPAGE_BPS = 50          # 0.5 % expressed in basis points
DEADLINE_SECONDS = 20 * 60 # 20 minutes

# ---------------------------------------------------------------------------
# Minimal ABIs (only the selectors we actually call)
# ---------------------------------------------------------------------------

_ROUTER_ABI: list[dict] = [
    # getAmountsOut(uint amountIn, address[] path) -> uint[]
    {
        "name": "getAmountsOut",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "amountIn",  "type": "uint256"},
            {"name": "path",      "type": "address[]"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    # swapExactETHForTokens(uint amountOutMin, address[] path, address to, uint deadline)
    {
        "name": "swapExactETHForTokens",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path",         "type": "address[]"},
            {"name": "to",           "type": "address"},
            {"name": "deadline",     "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
    # swapExactTokensForETH(uint amountIn, uint amountOutMin, address[] path, address to, uint deadline)
    {
        "name": "swapExactTokensForETH",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "amountIn",     "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path",         "type": "address[]"},
            {"name": "to",           "type": "address"},
            {"name": "deadline",     "type": "uint256"},
        ],
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
    },
]

_ERC20_ABI: list[dict] = [
    # approve(address spender, uint256 amount) -> bool
    {
        "name": "approve",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount",  "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # allowance(address owner, address spender) -> uint256
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "owner",   "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    # decimals() -> uint8
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]


class SwapError(Exception):
    pass


class PancakeSwapExecutor:
    """Execute PancakeSwap V2 swaps on BSC testnet.

    Takes a WalletAgent for signing/broadcasting; owns its own web3 instance
    for read-only calls (getAmountsOut, allowance) so it doesn't share state
    with the wallet's web3.

    DRY_RUN mode mirrors wallet.py: read-only calls (getAmountsOut, price
    fetches) still run against the network, but no transactions are broadcast.
    """

    def __init__(self, wallet: WalletAgent, rpc_url: str | None = None) -> None:
        self._wallet = wallet
        self.dry_run: bool = wallet.dry_run
        rpc = rpc_url or os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
        self._w3.middleware_onion.inject(PoAMiddleware, layer=0)
        self._router = self._w3.eth.contract(
            address=self._w3.to_checksum_address(ROUTER_ADDRESS),
            abi=_ROUTER_ABI,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_price(self, token_in: str, token_out: str) -> float:
        """Return the current spot price: how many *token_out* per 1 *token_in*.

        Uses getAmountsOut with a 1-unit probe to avoid large-order price impact.
        """
        path = self._build_path(token_in, token_out)
        decimals_in = await self._token_decimals(token_in)
        one_unit = 10 ** decimals_in

        try:
            amounts = await self._router.functions.getAmountsOut(one_unit, path).call()
        except ContractLogicError as exc:
            raise SwapError(f"getAmountsOut failed for {token_in}→{token_out}: {exc}") from exc

        decimals_out = await self._token_decimals(token_out)
        price = amounts[-1] / 10 ** decimals_out
        logger.info("Price %s/%s: %.6f", token_in, token_out, price)
        return price

    async def swap(
        self,
        token_in: str,
        token_out: str,
        amount_usd: float,
    ) -> dict:
        """Swap *amount_usd* worth of *token_in* for *token_out*.

        Handles BNB→USDT (native ETH path) and USDT→BNB (token→ETH path)
        including the ERC-20 approve step when spending a BEP-20 token.

        Returns a result dict matching the documented schema.
        """
        token_in  = token_in.upper()
        token_out = token_out.upper()

        logger.info(
            "Swap requested: %s → %s  $%.2f  wallet=%s",
            token_in, token_out, amount_usd, self._wallet.address,
        )

        # ── 1. Resolve amount_in from USD ──────────────────────────────
        # BNB input requires a price quote from the chain; use a rough estimate
        # in dry_run to avoid any RPC call before we short-circuit.
        if self.dry_run and token_in == "BNB":
            _bnb_est = 600.0
            amount_in_human = amount_usd / _bnb_est
            amount_in_wei   = self._w3.to_wei(amount_in_human, "ether")
        else:
            amount_in_human, amount_in_wei = await self._usd_to_token_amount(
                token_in, amount_usd
            )

        # ── 2. DRY-RUN: exit before any on-chain calls ────────────────
        if self.dry_run:
            logger.warning(
                "[DRY-RUN] Swap NOT broadcast.  %s %.6f → %s  wallet=%s",
                token_in, amount_in_human, token_out, self._wallet.address,
            )
            return {
                "tx_hash":    None,
                "token_in":   token_in,
                "token_out":  token_out,
                "amount_in":  amount_in_human,
                "amount_out": 0.0,
                "price":      0.0,
                "gas_used":   0,
                "status":     "dry_run",
            }

        # ── 3. Safety: balance check ───────────────────────────────────
        balance = await self._wallet.get_balance(token_in)
        if balance < amount_in_human:
            raise InsufficientBalanceError(
                f"Need {amount_in_human:.6f} {token_in}, wallet has {balance:.6f}"
            )

        # ── 4. Quote expected output with slippage floor ───────────────
        path = self._build_path(token_in, token_out)
        try:
            amounts = await self._router.functions.getAmountsOut(amount_in_wei, path).call()
        except ContractLogicError as exc:
            raise SwapError(f"Quote failed: {exc}") from exc

        decimals_out = await self._token_decimals(token_out)
        expected_out_wei = amounts[-1]
        # amountOutMin applies slippage: floor = expected × (1 - slippage)
        amount_out_min = expected_out_wei * (10_000 - SLIPPAGE_BPS) // 10_000
        deadline = int(time.time()) + DEADLINE_SECONDS

        # ── 5. Approve router when spending a BEP-20 token ────────────
        if token_in != "BNB":
            await self._ensure_allowance(token_in, amount_in_wei)

        # ── 6. Build the swap transaction ─────────────────────────────
        try:
            if token_in == "BNB":
                tx = await self._build_eth_for_tokens(
                    path, amount_in_wei, amount_out_min, deadline
                )
            else:
                tx = await self._build_tokens_for_eth(
                    path, amount_in_wei, amount_out_min, deadline
                )
        except ContractLogicError as exc:
            raise SwapError(f"Transaction build failed: {exc}") from exc

        # ── 7. Sign → broadcast → wait for receipt (live only) ──────────
        signed_hex = await self._wallet.sign_transaction(tx)
        tx_hash = await self._wallet.send_transaction(signed_hex)

        receipt = await self._wait_for_receipt(tx_hash)
        success = receipt["status"] == 1

        # ── 8. Parse actual amounts from receipt logs ─────────────────
        actual_out_wei = self._parse_amount_out(receipt, token_out)
        actual_out = actual_out_wei / 10 ** decimals_out if actual_out_wei else (
            expected_out_wei / 10 ** decimals_out
        )
        price = actual_out / amount_in_human if amount_in_human else 0.0

        result: dict = {
            "tx_hash":    tx_hash,
            "token_in":   token_in,
            "token_out":  token_out,
            "amount_in":  amount_in_human,
            "amount_out": round(actual_out, 8),
            "price":      round(price, 6),
            "gas_used":   receipt.get("gasUsed", 0),
            "status":     "success" if success else "failed",
        }

        if not success:
            logger.error("Swap failed on-chain: tx_hash=%s", tx_hash)
        else:
            logger.info(
                "Swap success: %s %.6f → %s %.6f  price=%.4f  gas=%d",
                token_in, amount_in_human,
                token_out, actual_out,
                price, result["gas_used"],
            )

        return result

    # ------------------------------------------------------------------
    # Internal helpers — transaction builders
    # ------------------------------------------------------------------

    async def _build_eth_for_tokens(
        self,
        path: list[str],
        amount_in_wei: int,
        amount_out_min: int,
        deadline: int,
    ) -> dict:
        fn = self._router.functions.swapExactETHForTokens(
            amount_out_min, path, self._wallet.address, deadline
        )
        return await fn.build_transaction({
            "from":  self._wallet.address,
            "value": amount_in_wei,
        })

    async def _build_tokens_for_eth(
        self,
        path: list[str],
        amount_in_wei: int,
        amount_out_min: int,
        deadline: int,
    ) -> dict:
        fn = self._router.functions.swapExactTokensForETH(
            amount_in_wei, amount_out_min, path, self._wallet.address, deadline
        )
        return await fn.build_transaction({"from": self._wallet.address})

    # ------------------------------------------------------------------
    # Internal helpers — token utilities
    # ------------------------------------------------------------------

    def _build_path(self, token_in: str, token_out: str) -> list[str]:
        for symbol in (token_in, token_out):
            if symbol not in TOKEN_ADDRESSES:
                raise SwapError(
                    f"Unknown token '{symbol}'. Add it to TOKEN_ADDRESSES."
                )
        return [
            self._w3.to_checksum_address(TOKEN_ADDRESSES[token_in]),
            self._w3.to_checksum_address(TOKEN_ADDRESSES[token_out]),
        ]

    # BSC testnet BEP-20 decimals — hardcoded to avoid RPC calls for known tokens.
    _KNOWN_DECIMALS: dict[str, int] = {
        "BNB":  18,
        "WBNB": 18,
        "USDT": 18,   # BSC testnet USDT (BEP-20) uses 18 decimals
        "BUSD": 18,
    }

    async def _token_decimals(self, symbol: str) -> int:
        known = self._KNOWN_DECIMALS.get(symbol.upper())
        if known is not None:
            return known
        addr = TOKEN_ADDRESSES.get(symbol.upper())
        if not addr:
            return 18  # safe default for most BEP-20
        contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(addr), abi=_ERC20_ABI
        )
        return await contract.functions.decimals().call()

    async def _usd_to_token_amount(
        self, token: str, amount_usd: float
    ) -> tuple[float, int]:
        """Return (human_amount, wei_amount) for *amount_usd* worth of *token*."""
        if token == "BNB":
            # BNB price = how much USDT per 1 BNB
            bnb_price = await self.get_price("BNB", "USDT")
            human = amount_usd / bnb_price
            wei   = self._w3.to_wei(human, "ether")
        else:
            # For stablecoins, 1 token ≈ $1, so human ≈ amount_usd
            decimals = await self._token_decimals(token)
            human = amount_usd           # assumes 1:1 USD peg
            wei   = int(human * 10 ** decimals)
        return human, int(wei)

    async def _ensure_allowance(self, token: str, required_wei: int) -> None:
        """Approve the router to spend *required_wei* of *token* if needed.

        Skipped entirely in dry_run — no on-chain state to read or write.
        """
        if self.dry_run:
            logger.info("[DRY-RUN] Skipping allowance check/approval for %s", token)
            return

        addr = self._w3.to_checksum_address(TOKEN_ADDRESSES[token])
        contract = self._w3.eth.contract(address=addr, abi=_ERC20_ABI)
        current = await contract.functions.allowance(
            self._wallet.address,
            self._w3.to_checksum_address(ROUTER_ADDRESS),
        ).call()

        if current >= required_wei:
            return  # already approved

        logger.info("Approving router to spend %s …", token)
        # Approve uint256 max to avoid repeated approval txns
        max_uint256 = 2**256 - 1
        approve_tx = await contract.functions.approve(
            self._w3.to_checksum_address(ROUTER_ADDRESS), max_uint256
        ).build_transaction({"from": self._wallet.address})

        signed = await self._wallet.sign_transaction(approve_tx)
        approve_hash = await self._wallet.send_transaction(signed)
        receipt = await self._wait_for_receipt(approve_hash)
        if receipt["status"] != 1:
            raise SwapError(f"Approval transaction failed: {approve_hash}")
        logger.info("Approval confirmed: tx_hash=%s", approve_hash)

    async def _wait_for_receipt(
        self, tx_hash: str, timeout: int = 120, poll_interval: float = 2.0
    ) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                receipt = await self._w3.eth.get_transaction_receipt(tx_hash)
                if receipt is not None:
                    return dict(receipt)
            except Exception:
                pass
            await asyncio.sleep(poll_interval)
        raise SwapError(f"Transaction {tx_hash} not mined within {timeout}s")

    @staticmethod
    def _parse_amount_out(receipt: dict, token_out: str) -> int | None:
        """Extract the actual output amount from Transfer event logs.

        PancakeSwap always emits an ERC-20 Transfer event for the output token
        as the last log entry.  We read the `data` field (3rd topic is amount).
        Returns Wei amount, or None if logs are unavailable.
        """
        logs = receipt.get("logs", [])
        if not logs:
            return None
        # The last Transfer log is the payout to our wallet
        last_log = logs[-1]
        data = last_log.get("data", "0x")
        try:
            return int(data, 16)
        except (ValueError, TypeError):
            return None


# ---------------------------------------------------------------------------
# Smoke-test: python -m execution.pancakeswap
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    wallet = WalletAgent()
    executor = PancakeSwapExecutor(wallet)

    print("\n--- get_price(BNB → USDT) ---")
    price = await executor.get_price("BNB", "USDT")
    print(f"  1 BNB = {price:.4f} USDT")

    print("\n--- get_price(USDT → BNB) ---")
    inv = await executor.get_price("USDT", "BNB")
    print(f"  1 USDT = {inv:.6f} BNB")

    # Uncomment to execute a live swap (costs gas + tokens):
    # print("\n--- swap BNB → USDT ($5) ---")
    # result = await executor.swap("BNB", "USDT", amount_usd=5.0)
    # for k, v in result.items():
    #     print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
