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
    MIN_SWAP_USD: float = float(os.getenv("MIN_SWAP_USD", "1.0"))
    MAX_POSITION_PCT_OF_PORTFOLIO: float = float(os.getenv("MAX_POSITION_PCT_OF_PORTFOLIO", "0.25"))
    STOP_LOSS_PERCENT: float = float(os.getenv("STOP_LOSS_PERCENT", "5"))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "testnet")
    # DRY_RUN defaults True on testnet; set DRY_RUN=false to enable live execution
    DRY_RUN: bool = os.getenv(
        "DRY_RUN",
        "true" if os.getenv("ENVIRONMENT", "testnet") == "testnet" else "false",
    ).lower() == "true"
    MIN_CONFIDENCE: float = float(os.getenv("MIN_CONFIDENCE", "0.45"))
    CYCLE_INTERVAL_MINUTES: int = int(os.getenv("CYCLE_INTERVAL_MINUTES", "15"))
    MAX_DAILY_LOSS_USD: float = float(os.getenv("MAX_DAILY_LOSS_USD", "50"))

    # Token scanner
    TOKEN_SCAN_TOP_N: int = int(os.getenv("TOKEN_SCAN_TOP_N", "3"))   # scan top N momentum tokens
    # Eligible BSC tokens — full competition allowlist (149 tokens), filtered to those
    # with Binance USDT spot pairs (scanner uses Binance). Stablecoins excluded (no signal).
    # Chinese-character tokens and non-Binance-listed exotics excluded gracefully by scanner.
    # Tokens confirmed unroutable on TWAK/PancakeSwap — do not add back without testing
    TWAK_BLACKLIST: set[str] = {
        "TON",    # KeyError in scanner (not a standard Binance BEP-20 pair)
        "ZRO",    # TOKEN_NOT_FOUND on TWAK — no BSC liquidity pool
        "STG",    # APPROVAL_SENT_SWAP_FAILED — swap reverts on 0x router
        "LAB",    # Binance-invalid, causes scanner 400 errors
        "NFT",    # Binance-invalid pair
        "LUNC",   # 1.2% transfer tax breaks 0x router (APPROVAL_SENT_SWAP_FAILED)
        "PENDLE", # Previously FAILED — unroutable on TWAK
        "FLOKI",  # Non-standard decimals, TWAK can't auto-detect
        "DEXE",   # Repeated swap failures — no reliable TWAK route
    }

    ELIGIBLE_TOKENS: list[str] = [
        # Major L1/L2
        "ETH", "XRP", "ADA", "DOT", "AVAX", "ATOM", "LTC", "BCH", "ETC",
        "TRX", "ZEC", "ZIL", "ROSE", "KAVA", "ELF", "ACH", "AXL",
        # DeFi blue chips
        "LINK", "UNI", "AAVE", "COMP", "SNX", "1INCH", "SUSHI", "YFI",
        "CAKE", "LDO", "PENDLE", "RAY",
        # AI + infra
        "FET", "INJ", "FIL", "PEAQ", "AIOZ",
        # Meme / high-vol
        "DOGE", "SHIB", "FLOKI", "BONK", "APE", "LUNC", "BRETT",
        "BABYDOGE", "CHEEMS",
        # BNB ecosystem
        "TWT", "AXS", "SFP", "BTT",
        # Mid-cap with Binance liquidity
        "BAT", "XCN", "DEXE", "FORM", "HTX", "DUSK",
        "APR", "VELO", "ZETA", "IRYS", "BEAM", "ZIG", "PLUME",
        "HUMA", "OPEN",
    ]

    # TWAK REST server
    TWAK_REST_URL: str = os.getenv("TWAK_REST_URL", "")
    TWAK_WALLET_NAME: str = os.getenv("TWAK_WALLET_NAME", "alphaloop")
    TWAK_HMAC_SECRET: str = os.getenv("TWAK_HMAC_SECRET", "")

    # Admin password (protects POST /admin/* endpoints)
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

    # x402 micropayment integration (CMC Agent Hub via TWAK)
    X402_ENABLED: bool = os.getenv("X402_ENABLED", "true").lower() == "true"
    CMC_AGENT_HUB_URL: str = os.getenv("CMC_AGENT_HUB_URL", "")

    # Competition guards
    COMPETITION_MODE: bool = os.getenv("COMPETITION_MODE", "false").lower() == "true"
    INITIAL_PORTFOLIO_USD: float = float(os.getenv("INITIAL_PORTFOLIO_USD", "1000"))
    MAX_DRAWDOWN_PCT: float = float(os.getenv("MAX_DRAWDOWN_PCT", "25"))        # halt at 25%, DQ at 30%
    MAX_POSITION_HOLD_HOURS: float = float(os.getenv("MAX_POSITION_HOLD_HOURS", "4"))  # auto-close after 4h

    # Multi-position scalping
    MAX_CONCURRENT_POSITIONS: int = int(os.getenv("MAX_CONCURRENT_POSITIONS", "3"))
    SCALPING_MODE: bool = os.getenv("SCALPING_MODE", "true").lower() == "true"

    # Minimum volume spike to consider a trade (scanner filter)
    MIN_VOLUME_SPIKE: float = float(os.getenv("MIN_VOLUME_SPIKE", "1.5"))

    # Edge-Verified Adaptive Trading
    # Hysteresis margin: a new token must beat the held token's score by this much to displace it
    HYSTERESIS_MARGIN: float = float(os.getenv("HYSTERESIS_MARGIN", "0.10"))
    # Round-trip cost estimate: TWAK fee ~0.5% + slippage ~0.3% = 0.8%
    ROUND_TRIP_COST_PCT: float = float(os.getenv("ROUND_TRIP_COST_PCT", "0.008"))

    # Performance snapshot interval
    SNAPSHOT_INTERVAL_MINUTES: int = int(os.getenv("SNAPSHOT_INTERVAL_MINUTES", "60"))

    @property
    def is_testnet(self) -> bool:
        return self.ENVIRONMENT == "testnet"


config = Config()
