"""Market sentiment filters: Fear & Greed, BTC 4h trend, token 7-day performance."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"
FNG_URL      = "https://api.alternative.me/fng/?limit=1"


async def get_fear_greed() -> dict:
    """Fetch Crypto Fear & Greed Index (0 = extreme fear, 100 = extreme greed).

    Returns {"value": int, "label": str}.
    Falls back to neutral 50 on error so one API failure never blocks all trades.
    """
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(FNG_URL)
        item  = resp.json()["data"][0]
        value = int(item["value"])
        label = item["value_classification"]
        logger.info("[FearGreed] %d — %s", value, label)
        return {"value": value, "label": label}
    except Exception as exc:
        logger.warning("[FearGreed] fetch failed (%s) — defaulting neutral 50", exc)
        return {"value": 50, "label": "Neutral"}


async def get_btc_4h_trend() -> dict:
    """Check BTC/USDT 4h trend over last 20 candles (~80 hours).

    Returns:
        uptrend      – True if BTC is above its 10-period SMA and not in heavy drop
        change_pct   – 80h price change %
        above_sma10  – price vs SMA10 of last 10 closes
        btc_price    – current BTC price
    Falls back to uptrend=True on error (fail open).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "4h", "limit": 20},
            )
        candles     = resp.json()
        closes      = [float(c[4]) for c in candles]
        current     = closes[-1]
        sma10       = sum(closes[-10:]) / 10
        change_pct  = (closes[-1] / closes[0] - 1) * 100
        above_sma10 = current > sma10
        uptrend     = above_sma10 and change_pct > -5   # not in heavy 80h downtrend
        logger.info(
            "[BTCTrend] price=%.0f  sma10=%.0f  80h=%+.1f%%  uptrend=%s",
            current, sma10, change_pct, uptrend,
        )
        return {
            "uptrend":     uptrend,
            "change_pct":  round(change_pct, 2),
            "above_sma10": above_sma10,
            "btc_price":   current,
        }
    except Exception as exc:
        logger.warning("[BTCTrend] failed (%s) — defaulting uptrend=True", exc)
        return {"uptrend": True, "change_pct": 0.0, "above_sma10": True, "btc_price": 0}


async def get_token_7d_change(symbol: str) -> float:
    """Return 7-day price change % for symbol/USDT using Binance daily klines.

    Returns 0.0 on error (fail open — don't block trade on data unavailability).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol.upper() + "USDT", "interval": "1d", "limit": 8},
            )
        if resp.status_code != 200:
            return 0.0
        candles = resp.json()
        if len(candles) < 2:
            return 0.0
        open_7d    = float(candles[0][1])   # open of oldest candle
        close_now  = float(candles[-1][4])  # close of latest candle
        change     = (close_now / open_7d - 1) * 100
        logger.info("[7dChange] %s %+.1f%%", symbol, change)
        return round(change, 2)
    except Exception as exc:
        logger.warning("[7dChange] %s failed (%s) — returning 0", symbol, exc)
        return 0.0
