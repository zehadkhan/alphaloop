from dotenv import load_dotenv
import os

load_dotenv()


class Config:
    CMC_API_KEY: str = os.getenv("CMC_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    BSC_RPC_URL: str = os.getenv("BSC_RPC_URL", "https://bsc-testnet-rpc.publicnode.com")
    AGENT_WALLET_ADDRESS: str = os.getenv("AGENT_WALLET_ADDRESS", "")
    AGENT_PRIVATE_KEY: str = os.getenv("AGENT_PRIVATE_KEY", "")
    TRADING_PAIR: str = os.getenv("TRADING_PAIR", "BNB/USDT")
    MAX_POSITION_SIZE_USD: float = float(os.getenv("MAX_POSITION_SIZE_USD", "10"))
    STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "5"))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "testnet")
    # DRY_RUN defaults True on testnet; set DRY_RUN=false to enable live execution
    DRY_RUN: bool = os.getenv(
        "DRY_RUN",
        "true" if os.getenv("ENVIRONMENT", "testnet") == "testnet" else "false",
    ).lower() == "true"
    MIN_CONFIDENCE: float = float(os.getenv("MIN_CONFIDENCE", "0.6"))
    CYCLE_INTERVAL_MINUTES: int = int(os.getenv("CYCLE_INTERVAL_MINUTES", "30"))

    @property
    def is_testnet(self) -> bool:
        return self.ENVIRONMENT == "testnet"


config = Config()
