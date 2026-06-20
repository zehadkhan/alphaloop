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
    TRADING_PAIR: str = os.getenv("TRADING_PAIR", "ETH/USDT")
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
    MAX_DAILY_LOSS_USD: float = float(os.getenv("MAX_DAILY_LOSS_USD", "50"))

    # Token scanner
    TOKEN_SCAN_TOP_N: int = int(os.getenv("TOKEN_SCAN_TOP_N", "3"))   # scan top N momentum tokens
    # Eligible BSC tokens — sourced directly from the BNB HACK competition allowlist.
    # BNB is excluded (not in competition's BEP-20 eligible list).
    # Stablecoins excluded (no price movement = no signal).
    ELIGIBLE_TOKENS: list[str] = [
        # High-liquidity DeFi
        "ETH", "CAKE", "LINK", "UNI", "AAVE", "COMP", "SNX", "1INCH", "SUSHI",
        # Layer-1s with good BSC bridge liquidity
        "ADA", "DOT", "AVAX", "ATOM", "XRP", "TRX", "LTC", "BCH", "ETC",
        # Meme / high-volatility (more trading signals)
        "DOGE", "SHIB", "FLOKI", "BONK", "APE",
        # AI + trending DeFi
        "FET", "INJ", "LDO", "PENDLE",
        # Others with solid BSC presence
        "AXS", "YFI", "FIL",
    ]

    # TWAK REST server
    TWAK_REST_URL: str = os.getenv("TWAK_REST_URL", "")
    TWAK_WALLET_NAME: str = os.getenv("TWAK_WALLET_NAME", "alphaloop")
    TWAK_HMAC_SECRET: str = os.getenv("TWAK_HMAC_SECRET", "")

    # Competition guards
    COMPETITION_MODE: bool = os.getenv("COMPETITION_MODE", "false").lower() == "true"
    INITIAL_PORTFOLIO_USD: float = float(os.getenv("INITIAL_PORTFOLIO_USD", "1000"))
    MAX_DRAWDOWN_PCT: float = float(os.getenv("MAX_DRAWDOWN_PCT", "25"))        # halt at 25%, DQ at 30%
    MAX_POSITION_HOLD_HOURS: float = float(os.getenv("MAX_POSITION_HOLD_HOURS", "20"))  # force-close stale

    # Edge-Verified Adaptive Trading — new knobs
    # Hysteresis margin: a new token must beat the held token's score by this much to displace it
    HYSTERESIS_MARGIN: float = float(os.getenv("HYSTERESIS_MARGIN", "0.15"))
    # Round-trip cost estimate: TWAK fee ~0.5% + slippage ~0.3% = 0.8%
    ROUND_TRIP_COST_PCT: float = float(os.getenv("ROUND_TRIP_COST_PCT", "0.008"))

    @property
    def is_testnet(self) -> bool:
        return self.ENVIRONMENT == "testnet"


config = Config()
