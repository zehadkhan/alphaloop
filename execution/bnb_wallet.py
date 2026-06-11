"""BNB Agent SDK wallet provider.

Wraps bnbagent.EVMWalletProvider so the rest of the codebase gets the same
interface as the old WalletAgent but with:
  - AES-256 encrypted local keystore (keys never in env vars at runtime)
  - EIP-712 typed-data signing for x402 micropayments
  - Compatible sign_transaction / send_transaction surface
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from web3 import AsyncWeb3

from bnbagent import EVMWalletProvider, X402Signer
from execution._compat import PoAMiddleware

load_dotenv()

logger = logging.getLogger(__name__)

BSC_RPC = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"


class BNBWallet:
    """Self-custody wallet backed by bnbagent EVMWalletProvider.

    On first instantiation the private key is read from AGENT_PRIVATE_KEY,
    encrypted with WALLET_PASSWORD, and stored in ~/.bnbagent/wallets/.
    Subsequent runs load from the encrypted keystore — no plaintext key needed.
    """

    def __init__(self) -> None:
        password = os.getenv("WALLET_PASSWORD", "alphaloop-default-pw-change-me")
        private_key = os.getenv("AGENT_PRIVATE_KEY") or None

        self._provider = EVMWalletProvider(
            password=password,
            private_key=private_key,
            persist=True,
        )
        self.address: str = self._provider.address

        self._x402 = X402Signer(
            self._provider,
            max_value_per_call={"U": 1_000_000},
            session_budget={"U": 50_000_000},
        )

        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(BSC_RPC))
        self._w3.middleware_onion.inject(PoAMiddleware, layer=0)

        self.dry_run: bool = DRY_RUN
        logger.info(
            "BNBWallet ready  address=%s  dry_run=%s  keystore=encrypted",
            self.address, self.dry_run,
        )

    # ------------------------------------------------------------------
    # Signing — used by PancakeSwapExecutor
    # ------------------------------------------------------------------

    async def sign_transaction(self, tx: dict) -> str:
        """Sign *tx* via EVMWalletProvider and return the raw hex string."""
        result = self._provider.sign_transaction(tx)
        raw: bytes = result["rawTransaction"]
        return raw.hex() if isinstance(raw, bytes) else raw

    async def send_transaction(self, raw_hex: str) -> str:
        """Broadcast a signed transaction and return the tx hash."""
        tx_bytes = bytes.fromhex(raw_hex.removeprefix("0x"))
        tx_hash = await self._w3.eth.send_raw_transaction(tx_bytes)
        return tx_hash.hex()

    # ------------------------------------------------------------------
    # Balance helpers
    # ------------------------------------------------------------------

    async def get_balance(self, token: str = "BNB") -> float:
        token = token.upper()
        if token == "BNB":
            wei = await self._w3.eth.get_balance(self.address)
            return float(self._w3.from_wei(wei, "ether"))
        token_map = {
            "USDT": "0x55d398326f99059fF775485246999027B3197955",
            "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
            "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        }
        contract_addr = token_map.get(token)
        if not contract_addr:
            logger.warning("Unknown token '%s' for balance check — returning 0", token)
            return 0.0
        padded = self.address.lower().removeprefix("0x").zfill(64)
        result = await self._w3.eth.call(
            {"to": self._w3.to_checksum_address(contract_addr), "data": "0x70a08231" + padded}
        )
        return int(result.hex(), 16) / 10**18

    # ------------------------------------------------------------------
    # x402 payment signing (for CMC Agent Hub paid requests)
    # ------------------------------------------------------------------

    def sign_x402_payment(
        self,
        domain: dict,
        types: dict,
        message: dict,
        expected_to: str,
    ) -> dict:
        """Sign an x402 payment challenge using the local wallet."""
        return self._x402.sign_payment(
            domain=domain,
            types=types,
            message=message,
            expected_to=expected_to,
        )
