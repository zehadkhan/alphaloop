"""5-Axis Market Compass — AlphaLoop's unique regime detection engine.

Axes (each scored 0–10, sum = Compass Score 0–50):
  1. Trend       — EMA9/21 cross + price vs SMA20/SMA50
  2. Momentum    — RSI position + MACD direction + 24h price change
  3. Sentiment   — Fear & Greed index + BTC dominance level
  4. Volatility  — ATR percentile + BB-width percentile (moderate vol = best)
  5. Stress      — Perp funding rate z-score + price stretch from SMA50 (inverted)

Regime profiles (Compass Score → trading posture):
  MOMENTUM_RIDE     35–50  full size, relaxed confidence
  TREND_CONFIRM     25–35  85% size, normal confidence
  NEUTRAL_CAUTIOUS  15–25  60% size, tighter confidence
  DEFENSIVE          8–15  30% size, high confidence required
  RISK_OFF           <8    skip trade (unless hard compliance)
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_FAPI_BASE  = "https://fapi.binance.com"
_FNG_URL    = "https://api.alternative.me/fng/?limit=1"

_PROFILES: list[dict] = [
    {
        "name":   "MOMENTUM_RIDE",
        "min":    35, "max": 50,
        "max_position_pct":        1.00,
        "min_confidence_override": 0.50,
        "tp_multiplier":           1.15,
        "sl_multiplier":           0.95,
        "label": "Strong bull — riding momentum",
        "guidance": "Confirmed momentum across multiple axes — lean toward full size, allow wider TP.",
    },
    {
        "name":   "TREND_CONFIRM",
        "min":    25, "max": 35,
        "max_position_pct":        0.85,
        "min_confidence_override": 0.55,
        "tp_multiplier":           1.10,
        "sl_multiplier":           0.97,
        "label": "Confirmed trend — standard size",
        "guidance": "Trend intact but not extreme — normal positioning, standard risk/reward.",
    },
    {
        "name":   "NEUTRAL_CAUTIOUS",
        "min":    15, "max": 25,
        "max_position_pct":        0.60,
        "min_confidence_override": 0.62,
        "tp_multiplier":           1.05,
        "sl_multiplier":           1.00,
        "label": "Mixed signals — cautious sizing",
        "guidance": "Signals are mixed — require higher conviction before entering. Prefer tight stops.",
    },
    {
        "name":   "DEFENSIVE",
        "min":    8, "max": 15,
        "max_position_pct":        0.30,
        "min_confidence_override": 0.72,
        "tp_multiplier":           1.00,
        "sl_multiplier":           1.05,
        "label": "Defensive — high bar to trade",
        "guidance": "Weak market structure — only enter with strong multi-indicator alignment. Tight sizing.",
    },
    {
        "name":   "RISK_OFF",
        "min":    0, "max": 8,
        "max_position_pct":        0.00,
        "min_confidence_override": 1.00,
        "tp_multiplier":           1.00,
        "sl_multiplier":           1.10,
        "label": "Risk-off — skip unless forced",
        "guidance": "High risk environment — avoid new entries. Only compliance trade if absolutely required.",
    },
]


def _clamp(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


class MarketCompass:
    """Computes the 5-axis compass score and returns a full regime context dict."""

    async def compute(
        self,
        symbol: str,
        indicators: dict,
        market_data: dict,
        btc_dominance: float = 48.0,
        ohlcv_data: list[dict] | None = None,
    ) -> dict:
        axes: dict[str, float] = {}

        axes["trend"]      = self._axis_trend(indicators, market_data)
        axes["momentum"]   = self._axis_momentum(indicators, market_data)
        axes["sentiment"]  = await self._axis_sentiment(btc_dominance)
        axes["volatility"] = self._axis_volatility(indicators, ohlcv_data or [])
        axes["stress"]     = await self._axis_stress(symbol, indicators, market_data)

        compass_score = round(sum(axes.values()), 2)
        profile = self._resolve_profile(compass_score)

        logger.info(
            "[Compass] %s | trend=%.1f  momentum=%.1f  sentiment=%.1f  "
            "volatility=%.1f  stress=%.1f | TOTAL=%.1f  regime=%s",
            symbol,
            axes["trend"], axes["momentum"], axes["sentiment"],
            axes["volatility"], axes["stress"],
            compass_score, profile["name"],
        )

        return {
            "axes":          {k: round(v, 2) for k, v in axes.items()},
            "compass_score": compass_score,
            "regime":        profile["name"],
            "profile":       profile,
        }

    # ── Axis 1: Trend ───────────────────────────────────────────────────────

    def _axis_trend(self, ind: dict, mkt: dict) -> float:
        price    = mkt.get("price", 0.0)
        ema_fast = ind.get("ema_fast", 0.0)
        ema_slow = ind.get("ema_slow", 0.0)
        sma_20   = ind.get("sma_20",   0.0)
        sma_50   = ind.get("sma_50",   0.0)

        score = 5.0
        if ema_fast > 0 and ema_slow > 0:
            score += 2.0 if ema_fast > ema_slow else -2.0
        if price > 0 and sma_20 > 0:
            score += 1.0 if price > sma_20 else -1.0
        if price > 0 and sma_50 > 0:
            score += 1.5 if price > sma_50 else -1.5
        # Alignment bonus: EMA cross and price-SMA50 agree
        if ema_fast > 0 and ema_slow > 0 and sma_50 > 0:
            ema_bull   = ema_fast > ema_slow
            price_bull = price > sma_50
            score += 0.5 if ema_bull == price_bull else -0.5

        return _clamp(score)

    # ── Axis 2: Momentum ────────────────────────────────────────────────────

    def _axis_momentum(self, ind: dict, mkt: dict) -> float:
        rsi       = ind.get("rsi",        50.0)
        macd_hist = ind.get("macd_hist",   0.0)
        change_24 = mkt.get("percent_change_24h", 0.0)

        # RSI: -1 to +1 signal (50 = neutral)
        rsi_sig = (rsi - 50.0) / 50.0

        # MACD histogram direction
        macd_sig = 1.0 if macd_hist > 0 else -1.0

        # 24h change: clip ±10%
        change_sig = max(-1.0, min(1.0, change_24 / 10.0))

        composite = 0.50 * rsi_sig + 0.30 * macd_sig + 0.20 * change_sig
        return _clamp((composite + 1.0) / 2.0 * 10.0)

    # ── Axis 3: Sentiment ───────────────────────────────────────────────────

    async def _axis_sentiment(self, btc_dominance: float) -> float:
        fg = await self._fetch_fear_greed()

        # F&G 0-100 → 0-7
        fg_score = _clamp(fg / 100.0 * 7.0, 0.0, 7.0)

        # BTC dominance: low = altcoin season = bullish for tokens
        if btc_dominance < 42.0:
            btc_score = 3.0
        elif btc_dominance < 50.0:
            btc_score = 1.5
        else:
            btc_score = 0.0

        return _clamp(fg_score + btc_score)

    # ── Axis 4: Volatility ──────────────────────────────────────────────────

    def _axis_volatility(self, ind: dict, ohlcv: list[dict]) -> float:
        if len(ohlcv) < 15:
            return 5.0

        closes = [float(c["close"]) for c in ohlcv]
        highs  = [float(c["high"])  for c in ohlcv]
        lows   = [float(c["low"])   for c in ohlcv]

        # 14-period simple ATR series
        trs = [
            max(highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i]  - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        window = 14
        atrs = [
            sum(trs[i - window + 1: i + 1]) / window
            for i in range(window - 1, len(trs))
        ]
        if not atrs:
            return 5.0

        atr_min, atr_max = min(atrs), max(atrs)
        atr_pct = (
            (atrs[-1] - atr_min) / (atr_max - atr_min)
            if atr_max > atr_min else 0.5
        )

        # BB width percentile
        bb_upper = ind.get("bb_upper", closes[-1])
        bb_lower = ind.get("bb_lower", closes[-1])
        bb_mid   = ind.get("bb_middle", closes[-1])
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.05
        bb_pct   = min(1.0, bb_width / 0.15)

        def _bell(pct: float) -> float:
            dist = abs(pct - 0.40)
            return max(0.0, 1.0 - dist / 0.40)

        score = (_bell(atr_pct) * 0.55 + _bell(bb_pct) * 0.45) * 10.0
        return _clamp(score)

    # ── Axis 5: Positioning Stress (inverted) ───────────────────────────────

    async def _axis_stress(
        self,
        symbol: str,
        ind: dict,
        mkt: dict,
    ) -> float:
        funding_stress = await self._fetch_funding_stress(symbol)

        price  = mkt.get("price", 0.0)
        sma_50 = ind.get("sma_50", price)
        if sma_50 > 0 and price > 0:
            stretch = abs((price - sma_50) / sma_50)
            stretch_stress = min(1.0, stretch / 0.15)
        else:
            stretch_stress = 0.0

        total_stress = funding_stress * 0.55 + stretch_stress * 0.45
        return _clamp((1.0 - total_stress) * 10.0)

    # ── External data fetchers ──────────────────────────────────────────────

    async def _fetch_fear_greed(self) -> float:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                resp = await c.get(_FNG_URL)
            fg = float(resp.json()["data"][0]["value"])
            logger.debug("[Compass] F&G = %.0f", fg)
            return fg
        except Exception as exc:
            logger.warning("[Compass] F&G fetch failed (%s) — defaulting 50", exc)
            return 50.0

    async def _fetch_funding_stress(self, symbol: str) -> float:
        """Return funding rate stress 0–1. Returns 0.0 for tokens without perp market."""
        perp = symbol.upper() + "USDT"
        try:
            async with httpx.AsyncClient(base_url=_FAPI_BASE, timeout=8) as c:
                resp = await c.get("/fapi/v1/fundingRate", params={"symbol": perp, "limit": 8})
            if resp.status_code != 200:
                return 0.0
            rates = [float(r["fundingRate"]) for r in resp.json()]
            if len(rates) < 2:
                return 0.0
            mean_r = sum(rates) / len(rates)
            std_r  = (sum((r - mean_r) ** 2 for r in rates) / len(rates)) ** 0.5 or 1e-9
            z      = abs((rates[-1] - mean_r) / std_r)
            stress = min(1.0, z / 3.0)
            logger.debug("[Compass] %s funding z=%.2f stress=%.2f", perp, z, stress)
            return stress
        except Exception:
            return 0.0

    # ── Profile resolution ──────────────────────────────────────────────────

    def _resolve_profile(self, score: float) -> dict:
        for p in _PROFILES:
            if p["min"] <= score <= p["max"]:
                return p
        return _PROFILES[-1]
