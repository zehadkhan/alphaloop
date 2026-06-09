"""BSC testnet wallet — signing and broadcasting via web3.py.

Trust Wallet Agent Kit (TWAK) has no Python pip package; it is a CLI/TypeScript
tool.  For programmatic key management on BSC we use web3.py directly, which
gives us the same primitives (eth_account signing, JSON-RPC broadcasting) that
TWAK wraps under the hood.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from dotenv import load_dotenv
from web3 import AsyncWeb3
from web3.exceptions import TransactionNotFound
from eth_account import Account
from execution._compat import PoAMiddleware
from eth_account.signers.local import LocalAccount

load_dotenv()

logger = logging.getLogger(__name__)

BSC_TESTNET_CHAIN_ID = 97

# BEP-20 balanceOf(address) selector + zero-padded address (padded at call time)
_BALANCE_OF_SELECTOR = "0x70a08231"

# Well-known BEP-20 token addresses on BSC testnet
_TESTNET_TOKENS: dict[str, str] = {
    "USDT": "0x337610d27c682E347C9cD60BD4b3b107C9d34dE",
    "BUSD": "0xeD24FC36d5Ee211Ea25A80239Fb8C4Cfd80f12Ee",
    "USDC": "0x64544969ed7EBf5f083679233325356EbE738930",
}


class WalletError(Exception):
    pass


class InsufficientBalanceError(WalletError):
    pass


class WalletAgent:
    """Async BSC testnet wallet backed by a local private key.

    All public methods are coroutines so they compose naturally with the
    async agent loop without blocking the event loop on RPC calls.
    """

    def __init__(
        self,
        rpc_url: str | None = None,
        private_key: str | None = None,
        max_position_usd: float | None = None,
    ) -> None:
        rpc = rpc_url or os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
        key = private_key or os.getenv("AGENT_PRIVATE_KEY", "")

        if not key:
            raise WalletError("AGENT_PRIVATE_KEY is not set")

        # Normalise key — MetaMask exports without 0x prefix sometimes
        if not key.startswith("0x"):
            key = "0x" + key

        self._account: LocalAccount = Account.from_key(key)
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc))
        # BSC uses Clique PoA; the extra-data field is longer than Ethereum's
        # and web3.py raises if we don't install this middleware.
        self._w3.middleware_onion.inject(PoAMiddleware, layer=0)

        self._max_position_usd: float = max_position_usd or float(
            os.getenv("MAX_POSITION_SIZE_USD", "10")
        )

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
        """Return wallet balance for *token* (native BNB or BEP-20 symbol).

        Returns balance in human-readable units (not Wei).
        """
        token = token.upper()
        if token == "BNB":
            wei = await self._w3.eth.get_balance(self.address)
            balance = float(self._w3.from_wei(wei, "ether"))
        else:
            contract_addr = _TESTNET_TOKENS.get(token)
            if not contract_addr:
                raise WalletError(f"Unknown token: {token}. Add it to _TESTNET_TOKENS.")
            balance = await self._bep20_balance(contract_addr)

        logger.info("Balance %s: %.6f %s", self.address, balance, token)
        return balance

    async def sign_transaction(self, tx_data: dict) -> str:
        """Sign *tx_data* with the agent's private key.

        Fills in chain_id, nonce, and gasPrice if absent.
        Returns the signed transaction as a hex string (0x-prefixed).
        """
        tx = await self._fill_defaults(tx_data)
        signed = self._account.sign_transaction(tx)
        hex_tx = signed.raw_transaction.hex()
        logger.info(
            "Signed tx from=%s to=%s value=%s gas=%s",
            tx.get("from"), tx.get("to"), tx.get("value"), tx.get("gas"),
        )
        return hex_tx

    async def send_transaction(self, signed_tx: str) -> str:
        """Broadcast a signed transaction hex and return the tx hash.

        The hex may be 0x-prefixed or raw.
        """
        raw = bytes.fromhex(signed_tx.removeprefix("0x"))
        tx_hash = await self._w3.eth.send_raw_transaction(raw)
        hash_hex = tx_hash.hex()
        logger.info("Broadcast tx_hash=%s", hash_hex)
        return hash_hex

    async def get_transaction_status(self, tx_hash: str) -> str:
        """Return 'pending', 'success', or 'failed' for *tx_hash*."""
        try:
            receipt = await self._w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            return "pending"

        if receipt is None:
            return "pending"

        status = "success" if receipt["status"] == 1 else "failed"
        logger.info("tx_hash=%s status=%s block=%s", tx_hash, status, receipt["blockNumber"])
        return status

    async def send_bnb(
        self,
        to: str,
        amount_bnb: float,
        bnb_price_usd: float | None = None,
    ) -> str:
        """Build, sign and send a native BNB transfer. Returns tx_hash.

        Args:
            to:             Recipient checksummed address.
            amount_bnb:     Amount in BNB (not Wei).
            bnb_price_usd:  Current BNB price.  When provided, the USD value is
                            checked against MAX_POSITION_SIZE_USD before sending.
        """
        if bnb_price_usd is not None:
            amount_usd = amount_bnb * bnb_price_usd
            self._assert_within_position_limit(amount_usd)

        balance = await self.get_balance("BNB")
        if balance < amount_bnb:
            raise InsufficientBalanceError(
                f"Wallet has {balance:.6f} BNB, need {amount_bnb:.6f} BNB"
            )

        tx_data = {
            "to": self._w3.to_checksum_address(to),
            "value": self._w3.to_wei(amount_bnb, "ether"),
            "gas": 21_000,
        }
        signed = await self.sign_transaction(tx_data)
        return await self.send_transaction(signed)

    async def test_connection(self) -> dict:
        """Send 0.001 BNB to self to verify the key, RPC, and chain are live.

        Safe to call on testnet — sending to yourself costs only gas.
        Returns a summary dict.
        """
        logger.info("Running self-transfer connection test on BSC testnet…")

        chain_id = await self._w3.eth.chain_id
        if chain_id != BSC_TESTNET_CHAIN_ID:
            raise WalletError(
                f"Connected to chain_id={chain_id}, expected BSC testnet ({BSC_TESTNET_CHAIN_ID}). "
                "Check BSC_RPC_URL."
            )

        balance_before = await self.get_balance("BNB")
        amount = 0.001

        if balance_before < amount + 0.0005:  # rough gas buffer
            raise InsufficientBalanceError(
                f"Need at least {amount + 0.0005:.4f} BNB for the test transfer "
                f"(wallet has {balance_before:.6f} BNB). "
                "Fund the testnet wallet at https://testnet.bnbchain.org/faucet-smart"
            )

        tx_hash = await self.send_bnb(self.address, amount)

        # Poll for confirmation (up to ~30 s)
        status = "pending"
        for _ in range(15):
            await asyncio.sleep(2)
            status = await self.get_transaction_status(tx_hash)
            if status != "pending":
                break

        balance_after = await self.get_balance("BNB")
        result = {
            "chain_id": chain_id,
            "address": self.address,
            "tx_hash": tx_hash,
            "status": status,
            "balance_before": balance_before,
            "balance_after": balance_after,
        }
        logger.info("Connection test result: %s", result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fill_defaults(self, tx: dict) -> dict:
        tx = dict(tx)  # don't mutate caller's dict
        tx.setdefault("chainId", BSC_TESTNET_CHAIN_ID)
        tx.setdefault("from", self.address)
        if "nonce" not in tx:
            tx["nonce"] = await self._w3.eth.get_transaction_count(
                self.address, "pending"
            )
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = await self._w3.eth.gas_price
        if "gas" not in tx:
            try:
                tx["gas"] = await self._w3.eth.estimate_gas(tx)
            except Exception:
                tx["gas"] = 200_000  # conservative fallback
        return tx

    async def _bep20_balance(self, contract_address: str) -> float:
        """Call balanceOf(address) on a BEP-20 contract via raw eth_call."""
        # Encode: selector (4 bytes) + address zero-padded to 32 bytes
        padded = self.address.lower().removeprefix("0x").zfill(64)
        call_data = _BALANCE_OF_SELECTOR + padded
        result = await self._w3.eth.call(
            {"to": self._w3.to_checksum_address(contract_address), "data": call_data}
        )
        # BEP-20 tokens typically use 18 decimals; USDT on BSC testnet uses 18
        raw = int(result.hex(), 16)
        return raw / 10**18

    def _assert_within_position_limit(self, amount_usd: float) -> None:
        if amount_usd > self._max_position_usd:
            raise WalletError(
                f"Transaction value ${amount_usd:.2f} exceeds "
                f"MAX_POSITION_SIZE_USD=${self._max_position_usd:.2f}"
            )


# ---------------------------------------------------------------------------
# Smoke-test: python -m execution.wallet
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    wallet = WalletAgent()
    print(f"\nWallet address : {wallet.address}")
    print(f"Max position   : ${wallet._max_position_usd}")

    print("\n--- get_balance(BNB) ---")
    bnb = await wallet.get_balance("BNB")
    print(f"  BNB balance: {bnb:.6f}")

    print("\n--- test_connection (self-transfer 0.001 BNB) ---")
    result = await wallet.test_connection()
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
