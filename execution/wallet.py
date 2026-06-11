"""BSC wallet — signing and broadcasting via web3.py.

For token swaps, use TWAKExecutor (execution/twak_executor.py) when
TWAK_REST_URL is configured. This class handles BNB transfers and
balance queries using the local private key.

DRY_RUN mode (default when ENVIRONMENT=testnet):
  sign_transaction  — runs normally (pure crypto, no network cost)
  send_transaction  — logs but does NOT broadcast; returns a simulated hash
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time

from dotenv import load_dotenv
from web3 import AsyncWeb3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_account.signers.local import LocalAccount
from execution._compat import PoAMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

BSC_TESTNET_CHAIN_ID = 97
BSC_MAINNET_CHAIN_ID = 56

_TESTNET_TOKENS: dict[str, str] = {
    "USDT": "0x337610D27C682E347C9cd60bD4b3b107c9d34ddE",
    "BUSD": "0xeD24FC36d5Ee211Ea25A80239Fb8C4Cfd80f12Ee",
    "USDC": "0x64544969ed7EBf5f083679233325356EbE738930",
}
_MAINNET_TOKENS: dict[str, str] = {
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
}

_BALANCE_OF_SELECTOR = "0x70a08231"


class WalletError(Exception):
    pass


class InsufficientBalanceError(WalletError):
    pass


# ---------------------------------------------------------------------------
# web3.py backend (local key)
# ---------------------------------------------------------------------------

class _Web3Backend:
    def __init__(self, private_key: str, w3: AsyncWeb3, address: str) -> None:
        self._account: LocalAccount = Account.from_key(private_key)
        self._w3 = w3
        self._address = address

    async def sign_transaction(self, tx: dict) -> str:
        signed = self._account.sign_transaction(tx)
        return signed.raw_transaction.hex()

    async def broadcast(self, signed_hex: str) -> str:
        raw = bytes.fromhex(signed_hex.removeprefix("0x"))
        tx_hash = await self._w3.eth.send_raw_transaction(raw)
        return tx_hash.hex()


# ---------------------------------------------------------------------------
# WalletAgent — public interface (unchanged surface for callers)
# ---------------------------------------------------------------------------

class WalletAgent:
    """Async BSC wallet using web3.py for signing and broadcasting.

    When TWAK_REST_URL is configured, use TWAKExecutor instead for swaps —
    this class handles BNB transfers and balance queries only.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        private_key: str | None = None,
        max_position_usd: float | None = None,
        dry_run: bool | None = None,
    ) -> None:
        from agent.config import config

        environment = os.getenv("ENVIRONMENT", "testnet")
        self._chain_id = BSC_MAINNET_CHAIN_ID if environment == "mainnet" else BSC_TESTNET_CHAIN_ID
        self._token_map = _MAINNET_TOKENS if environment == "mainnet" else _TESTNET_TOKENS

        rpc = rpc_url or os.getenv(
            "BSC_RPC_URL",
            "https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3"
            if environment == "mainnet"
            else "https://bsc-testnet-rpc.publicnode.com",
        )

        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
        self._w3.middleware_onion.inject(PoAMiddleware, layer=0)
        self._max_position_usd: float = max_position_usd or config.MAX_POSITION_SIZE_USD
        self.dry_run: bool = config.DRY_RUN if dry_run is None else dry_run

        key = private_key or os.getenv("AGENT_PRIVATE_KEY", "")
        if not key:
            raise WalletError("AGENT_PRIVATE_KEY is not set")
        if not key.startswith("0x"):
            key = "0x" + key
        account: LocalAccount = Account.from_key(key)
        self._address = account.address
        self._backend = _Web3Backend(key, self._w3, self._address)
        logger.info(
            "WalletAgent[web3]  chain=%d  address=%s  dry_run=%s",
            self._chain_id, self._address, self.dry_run,
        )

    @property
    def address(self) -> str:
        return self._address

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_balance(self, token: str = "BNB") -> float:
        token = token.upper()
        if token == "BNB":
            wei = await self._w3.eth.get_balance(self.address)
            balance = float(self._w3.from_wei(wei, "ether"))
        else:
            contract_addr = self._token_map.get(token)
            if not contract_addr:
                logger.warning("Unknown token '%s' for balance check — returning 0", token)
                return 0.0
            balance = await self._bep20_balance(contract_addr)
        logger.info("Balance %s: %.6f %s", self.address, balance, token)
        return balance

    async def sign_transaction(self, tx_data: dict) -> str:
        tx = await self._fill_defaults(tx_data)
        hex_tx = await self._backend.sign_transaction(tx)
        logger.info(
            "Signed tx  from=%s  to=%s  value=%s  gas=%s  nonce=%s",
            tx.get("from"), tx.get("to"),
            tx.get("value"), tx.get("gas"), tx.get("nonce"),
        )
        return hex_tx

    async def send_transaction(self, signed_tx: str) -> str:
        if self.dry_run:
            sim_hash = (
                "0xDRY"
                + hashlib.sha256(f"{signed_tx}{time.time()}".encode()).hexdigest()[:60]
            )
            logger.warning(
                "[DRY-RUN] Transaction NOT broadcast. Simulated hash: %s  bytes=%d",
                sim_hash, len(signed_tx) // 2,
            )
            return sim_hash

        tx_hash = await self._backend.broadcast(signed_tx)
        logger.info("Broadcast tx_hash=%s", tx_hash)
        return tx_hash

    async def get_transaction_status(self, tx_hash: str) -> str:
        if tx_hash.startswith("0xDRY"):
            return "dry_run"
        try:
            receipt = await self._w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return "pending"
        if receipt is None:
            return "pending"
        status = "success" if receipt["status"] == 1 else "failed"
        logger.info("tx=%s  status=%s  block=%s", tx_hash, status, receipt["blockNumber"])
        return status

    async def send_bnb(self, to: str, amount_bnb: float, bnb_price_usd: float | None = None) -> str:
        if bnb_price_usd is not None:
            self._assert_within_position_limit(amount_bnb * bnb_price_usd)
        balance = await self.get_balance("BNB")
        if balance < amount_bnb and not self.dry_run:
            raise InsufficientBalanceError(
                f"Wallet has {balance:.6f} BNB, need {amount_bnb:.6f} BNB"
            )
        tx_data = {
            "to":    self._w3.to_checksum_address(to),
            "value": self._w3.to_wei(amount_bnb, "ether"),
            "gas":   21_000,
        }
        signed = await self.sign_transaction(tx_data)
        return await self.send_transaction(signed)

    async def test_connection(self) -> dict:
        chain_id = await self._w3.eth.chain_id
        if chain_id != self._chain_id:
            raise WalletError(
                f"Connected to chain_id={chain_id}, expected {self._chain_id}. "
                "Check BSC_RPC_URL."
            )
        balance = await self.get_balance("BNB")
        if self.dry_run:
            return {
                "chain_id": chain_id, "address": self.address,
                "balance": balance, "mode": "dry_run", "tx_hash": None,
                "status": "dry_run — no transaction sent",
            }
        amount = 0.001
        if balance < amount + 0.0005:
            raise InsufficientBalanceError(
                f"Need {amount + 0.0005:.4f} BNB (have {balance:.6f})."
            )
        tx_hash = await self.send_bnb(self.address, amount)
        status = "pending"
        for _ in range(15):
            await asyncio.sleep(2)
            status = await self.get_transaction_status(tx_hash)
            if status != "pending":
                break
        balance_after = await self.get_balance("BNB")
        return {
            "chain_id": chain_id, "address": self.address, "mode": "live",
            "tx_hash": tx_hash, "status": status,
            "balance_before": balance, "balance_after": balance_after,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fill_defaults(self, tx: dict) -> dict:
        tx = dict(tx)
        tx.setdefault("chainId", self._chain_id)
        tx.setdefault("from", self.address)
        if "nonce" not in tx:
            tx["nonce"] = await self._w3.eth.get_transaction_count(self.address, "pending")
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = await self._w3.eth.gas_price
        if "gas" not in tx:
            try:
                tx["gas"] = await self._w3.eth.estimate_gas(tx)
            except Exception:
                tx["gas"] = 200_000
        return tx

    async def _bep20_balance(self, contract_address: str) -> float:
        padded = self.address.lower().removeprefix("0x").zfill(64)
        call_data = _BALANCE_OF_SELECTOR + padded
        result = await self._w3.eth.call(
            {"to": self._w3.to_checksum_address(contract_address), "data": call_data}
        )
        return int(result.hex(), 16) / 10**18

    def _assert_within_position_limit(self, amount_usd: float) -> None:
        if amount_usd > self._max_position_usd:
            raise WalletError(
                f"${amount_usd:.2f} exceeds MAX_POSITION_SIZE_USD=${self._max_position_usd:.2f}"
            )


# ---------------------------------------------------------------------------
# Smoke-test: python -m execution.wallet
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    wallet = WalletAgent()
    print(f"\nAddress  : {wallet.address}")
    print(f"Chain ID : {wallet._chain_id}")
    print(f"Mode     : {'DRY-RUN' if wallet.dry_run else 'LIVE'}")
    print(f"Backend  : web3.py")
    print(f"Max pos  : ${wallet._max_position_usd}")
    print("\n--- get_balance(BNB) ---")
    bnb = await wallet.get_balance("BNB")
    print(f"  {bnb:.6f} BNB")


if __name__ == "__main__":
    asyncio.run(_main())
