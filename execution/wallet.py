"""BSC wallet — signing and broadcasting via web3.py.

DRY_RUN mode (default when ENVIRONMENT=testnet):
  sign_transaction  — builds and signs normally (pure crypto, no network cost)
  send_transaction  — logs the signed tx but does NOT broadcast; returns a
                      simulated hash so the rest of the pipeline stays intact
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from web3 import AsyncWeb3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from eth_account.signers.local import LocalAccount
from execution._compat import PoAMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

BSC_TESTNET_CHAIN_ID = 97

_BALANCE_OF_SELECTOR = "0x70a08231"

_TESTNET_TOKENS: dict[str, str] = {
    "USDT": "0x337610D27C682E347C9cd60bD4b3b107c9d34ddE",
    "BUSD": "0xeD24FC36d5Ee211Ea25A80239Fb8C4Cfd80f12Ee",
    "USDC": "0x64544969ed7EBf5f083679233325356EbE738930",
}


class WalletError(Exception):
    pass


class InsufficientBalanceError(WalletError):
    pass


class WalletAgent:
    """Async BSC wallet backed by a local private key.

    When *dry_run* is True (default on testnet), send_transaction logs the
    signed payload and returns a deterministic simulated hash without
    broadcasting anything to the network.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        private_key: str | None = None,
        max_position_usd: float | None = None,
        dry_run: bool | None = None,
    ) -> None:
        from agent.config import config  # local import to avoid circular

        rpc = rpc_url or os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
        key = private_key or os.getenv("AGENT_PRIVATE_KEY", "")

        if not key:
            raise WalletError("AGENT_PRIVATE_KEY is not set")
        if not key.startswith("0x"):
            key = "0x" + key

        self._account: LocalAccount = Account.from_key(key)
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
        self._w3.middleware_onion.inject(PoAMiddleware, layer=0)
        self._max_position_usd: float = max_position_usd or config.MAX_POSITION_SIZE_USD
        self.dry_run: bool = config.DRY_RUN if dry_run is None else dry_run

        mode = "DRY-RUN" if self.dry_run else "LIVE"
        logger.info("WalletAgent ready  address=%s  mode=%s", self.address, mode)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def address(self) -> str:
        return self._account.address

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_balance(self, token: str = "BNB") -> float:
        """Return wallet balance in human units (not Wei)."""
        token = token.upper()
        if token == "BNB":
            wei = await self._w3.eth.get_balance(self.address)
            balance = float(self._w3.from_wei(wei, "ether"))
        else:
            contract_addr = _TESTNET_TOKENS.get(token)
            if not contract_addr:
                raise WalletError(f"Unknown token '{token}'. Add to _TESTNET_TOKENS.")
            balance = await self._bep20_balance(contract_addr)

        logger.info("Balance %s: %.6f %s", self.address, balance, token)
        return balance

    async def sign_transaction(self, tx_data: dict) -> str:
        """Fill defaults, sign with private key, return 0x-prefixed hex.

        Always runs — signing is pure crypto with no network cost.
        """
        tx = await self._fill_defaults(tx_data)
        signed = self._account.sign_transaction(tx)
        hex_tx = signed.raw_transaction.hex()
        logger.info(
            "Signed tx  from=%s  to=%s  value=%s  gas=%s  nonce=%s",
            tx.get("from"), tx.get("to"),
            tx.get("value"), tx.get("gas"), tx.get("nonce"),
        )
        return hex_tx

    async def send_transaction(self, signed_tx: str) -> str:
        """Broadcast signed tx and return tx_hash.

        DRY_RUN=true: logs details and returns a simulated hash (0xDRY…).
        DRY_RUN=false: broadcasts to the network and returns the real hash.
        """
        if self.dry_run:
            sim_hash = (
                "0xDRY"
                + hashlib.sha256(f"{signed_tx}{time.time()}".encode()).hexdigest()[:60]
            )
            logger.warning(
                "[DRY-RUN] Transaction NOT broadcast.  "
                "Set DRY_RUN=false to enable live execution.  "
                "Simulated hash: %s  payload_bytes=%d",
                sim_hash,
                len(signed_tx) // 2,
            )
            return sim_hash

        raw = bytes.fromhex(signed_tx.removeprefix("0x"))
        tx_hash = await self._w3.eth.send_raw_transaction(raw)
        hash_hex = tx_hash.hex()
        logger.info("Broadcast tx_hash=%s", hash_hex)
        return hash_hex

    async def get_transaction_status(self, tx_hash: str) -> str:
        """Return 'pending', 'success', or 'failed'.

        Simulated hashes (0xDRY…) always resolve to 'dry_run' immediately.
        """
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

    async def send_bnb(
        self,
        to: str,
        amount_bnb: float,
        bnb_price_usd: float | None = None,
    ) -> str:
        """Build, sign and send (or simulate) a native BNB transfer."""
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
        """Verify RPC connectivity and key derivation.

        DRY_RUN: checks chain_id and balance but does not send.
        LIVE:    sends 0.001 BNB to self and waits for confirmation.
        """
        chain_id = await self._w3.eth.chain_id
        if chain_id != BSC_TESTNET_CHAIN_ID:
            raise WalletError(
                f"Connected to chain_id={chain_id}, expected {BSC_TESTNET_CHAIN_ID}. "
                "Check BSC_RPC_URL."
            )

        balance = await self.get_balance("BNB")

        if self.dry_run:
            result = {
                "chain_id":   chain_id,
                "address":    self.address,
                "balance":    balance,
                "mode":       "dry_run",
                "tx_hash":    None,
                "status":     "dry_run — no transaction sent",
            }
            logger.info("[DRY-RUN] Connection test: chain_id=%d  balance=%.6f BNB", chain_id, balance)
            return result

        amount = 0.001
        if balance < amount + 0.0005:
            raise InsufficientBalanceError(
                f"Need {amount + 0.0005:.4f} BNB (have {balance:.6f}). "
                "Fund at https://testnet.bnbchain.org/faucet-smart"
            )

        tx_hash = await self.send_bnb(self.address, amount)

        status = "pending"
        for _ in range(15):
            await asyncio.sleep(2)
            status = await self.get_transaction_status(tx_hash)
            if status != "pending":
                break

        balance_after = await self.get_balance("BNB")
        result = {
            "chain_id":      chain_id,
            "address":       self.address,
            "mode":          "live",
            "tx_hash":       tx_hash,
            "status":        status,
            "balance_before": balance,
            "balance_after":  balance_after,
        }
        logger.info("Connection test result: %s", result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fill_defaults(self, tx: dict) -> dict:
        tx = dict(tx)
        tx.setdefault("chainId", BSC_TESTNET_CHAIN_ID)
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
    print(f"Mode     : {'DRY-RUN' if wallet.dry_run else 'LIVE'}")
    print(f"Max pos  : ${wallet._max_position_usd}")

    print("\n--- get_balance(BNB) ---")
    bnb = await wallet.get_balance("BNB")
    print(f"  {bnb:.6f} BNB")

    print("\n--- test_connection ---")
    result = await wallet.test_connection()
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
