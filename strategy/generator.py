from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-5"

_SYSTEM_PROMPT = (
    "You are a quantitative trading strategy analyst. "
    "Given market data and technical indicators, generate a clear trading strategy. "
    "Always respond in valid JSON only."
)

_USER_PROMPT_TEMPLATE = """\
Analyze the following market data for {pair} and produce a trading strategy.

## Market Data
- Current price : {price}
- 24 h volume   : {volume_24h}
- Market cap    : {market_cap}
- 1 h change    : {percent_change_1h:.2f}%
- 24 h change   : {percent_change_24h:.2f}%

## Technical Indicators
- RSI (14)           : {rsi:.2f}
- MACD               : {macd:.6f}
- MACD signal        : {macd_signal:.6f}
- MACD histogram     : {macd_hist:.6f}
- Bollinger upper    : {bb_upper:.4f}
- Bollinger middle   : {bb_middle:.4f}
- Bollinger lower    : {bb_lower:.4f}
- SMA 20             : {sma_20:.4f}
- SMA 50             : {sma_50:.4f}

## Market Conditions
- Trading pair       : {pair}
- Current conditions : {conditions}

Respond with a single JSON object that strictly matches this schema — no markdown, no extra keys:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": <float 0.0–1.0>,
  "entry_price": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "reasoning": "<string>",
  "timeframe": "short" | "medium",
  "risk_level": "low" | "medium" | "high"
}}

Critical pricing rules — all values must be absolute prices (not percentages):

For BUY action (current price ≈ {price:.2f}):
  entry_price  = 0.5–1.5% BELOW current price  (limit buy on a small pullback)
  stop_loss    = 3–5% BELOW entry_price         (must be strictly less than entry)
  take_profit  = 5–10% ABOVE entry_price        (must be strictly greater than entry)
  Example: price={price:.2f} → entry≈{buy_entry:.2f}, sl≈{buy_sl:.2f}, tp≈{buy_tp:.2f}

For SELL action (current price ≈ {price:.2f}):
  entry_price  = 0.5–1.5% ABOVE current price  (limit sell on a small rally)
  stop_loss    = 3–5% ABOVE entry_price         (must be strictly greater than entry)
  take_profit  = 5–10% BELOW entry_price        (must be strictly less than entry)
  Example: price={price:.2f} → entry≈{sell_entry:.2f}, sl≈{sell_sl:.2f}, tp≈{sell_tp:.2f}

For HOLD action: entry_price, stop_loss, take_profit = current price (placeholder only).
Risk/reward must be ≥ 1.5 (tp_distance / sl_distance ≥ 1.5).
"""

_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "action":       str,
    "confidence":   float,
    "entry_price":  float,
    "stop_loss":    float,
    "take_profit":  float,
    "reasoning":    str,
    "timeframe":    str,
    "risk_level":   str,
}
_VALID_ACTIONS     = {"BUY", "SELL", "HOLD"}
_VALID_TIMEFRAMES  = {"short", "medium"}
_VALID_RISK_LEVELS = {"low", "medium", "high"}

CONFIDENCE_THRESHOLD = 0.6


class StrategyGeneratorError(Exception):
    pass


class StrategyGenerator:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            logger.warning("ANTHROPIC_API_KEY is not set")
        # AsyncAnthropic supports `async with` natively
        self._client = anthropic.AsyncAnthropic(api_key=key)

    async def __aenter__(self) -> "StrategyGenerator":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        symbol: str,
        market_data: dict,
        indicators: dict,
    ) -> dict:
        """Call Claude and return a validated strategy dict.

        Returns:
            Strategy dict with ``should_execute=True`` only when
            action != HOLD and confidence >= CONFIDENCE_THRESHOLD.
        """
        pair   = market_data.get("symbol", symbol) + "/USDT"
        prompt = self._build_prompt(pair, market_data, indicators)
        raw    = await self._call_claude(prompt)
        strategy = self._parse_and_validate(raw)
        strategy["should_execute"] = (
            strategy["action"] != "HOLD"
            and strategy["confidence"] >= CONFIDENCE_THRESHOLD
        )

        logger.info(
            "Strategy for %s — action=%s confidence=%.2f execute=%s | %s",
            pair,
            strategy["action"],
            strategy["confidence"],
            strategy["should_execute"],
            strategy["reasoning"][:120],
        )
        return strategy

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, pair: str, market_data: dict, indicators: dict) -> str:
        price = market_data.get("price", 0.0)

        rsi = indicators.get("rsi", 50.0)
        if rsi > 70:
            conditions = "overbought (RSI > 70)"
        elif rsi < 30:
            conditions = "oversold (RSI < 30)"
        else:
            conditions = "neutral"

        change_24h = market_data.get("percent_change_24h", 0.0)
        if abs(change_24h) > 5:
            conditions += f", high 24 h volatility ({change_24h:+.1f}%)"

        # Pre-compute example price levels so the prompt shows concrete numbers.
        buy_entry = price * 0.99
        buy_sl    = buy_entry * 0.96
        buy_tp    = buy_entry * 1.07
        sell_entry = price * 1.01
        sell_sl    = sell_entry * 1.04
        sell_tp    = sell_entry * 0.93

        return _USER_PROMPT_TEMPLATE.format(
            pair=pair,
            price=price,
            volume_24h=market_data.get("volume_24h", 0.0),
            market_cap=market_data.get("market_cap", 0.0),
            percent_change_1h=market_data.get("percent_change_1h", 0.0),
            percent_change_24h=change_24h,
            rsi=rsi,
            macd=indicators.get("macd", 0.0),
            macd_signal=indicators.get("macd_signal", 0.0),
            macd_hist=indicators.get("macd_hist", 0.0),
            bb_upper=indicators.get("bb_upper", price),
            bb_middle=indicators.get("bb_middle", price),
            bb_lower=indicators.get("bb_lower", price),
            sma_20=indicators.get("sma_20", price),
            sma_50=indicators.get("sma_50", price),
            conditions=conditions,
            buy_entry=buy_entry,
            buy_sl=buy_sl,
            buy_tp=buy_tp,
            sell_entry=sell_entry,
            sell_sl=sell_sl,
            sell_tp=sell_tp,
        )

    async def _call_claude(self, user_prompt: str) -> str:
        try:
            message = await self._client.messages.create(
                model=MODEL,
                max_tokens=512,
                temperature=0.2,   # low temp for deterministic structured output
                # Cache the static system prompt — saves tokens on every cycle
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIStatusError as exc:
            raise StrategyGeneratorError(
                f"Anthropic API error {exc.status_code}: {exc.message}"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise StrategyGeneratorError(f"Network error: {exc}") from exc

        raw = message.content[0].text
        logger.debug(
            "Claude response: input_tokens=%d output_tokens=%d cache_read=%d",
            message.usage.input_tokens,
            message.usage.output_tokens,
            getattr(message.usage, "cache_read_input_tokens", 0),
        )
        return raw

    def _parse_and_validate(self, raw: str) -> dict:
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        try:
            strategy: dict = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise StrategyGeneratorError(
                f"Response is not valid JSON: {exc}\nRaw: {raw[:400]}"
            ) from exc

        # Type-coerce numeric fields — model occasionally returns strings
        for field in ("confidence", "entry_price", "stop_loss", "take_profit"):
            if field in strategy:
                try:
                    strategy[field] = float(strategy[field])
                except (TypeError, ValueError):
                    pass

        missing = [f for f in _REQUIRED_FIELDS if f not in strategy]
        if missing:
            raise StrategyGeneratorError(f"Strategy missing fields: {missing}")

        wrong_type = [
            f for f, t in _REQUIRED_FIELDS.items()
            if not isinstance(strategy[f], t)
        ]
        if wrong_type:
            raise StrategyGeneratorError(
                "Strategy fields have wrong types: "
                + ", ".join(f"{f}={type(strategy[f]).__name__}" for f in wrong_type)
            )

        if strategy["action"]     not in _VALID_ACTIONS:
            raise StrategyGeneratorError(f"Invalid action: {strategy['action']!r}")
        if strategy["timeframe"]  not in _VALID_TIMEFRAMES:
            raise StrategyGeneratorError(f"Invalid timeframe: {strategy['timeframe']!r}")
        if strategy["risk_level"] not in _VALID_RISK_LEVELS:
            raise StrategyGeneratorError(f"Invalid risk_level: {strategy['risk_level']!r}")

        strategy["confidence"] = max(0.0, min(1.0, strategy["confidence"]))
        return strategy


# ---------------------------------------------------------------------------
# Smoke-test: python -m strategy.generator
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    market_data = {
        "symbol": "BNB",
        "price": 612.45,
        "volume_24h": 1_230_000_000.0,
        "market_cap": 89_500_000_000.0,
        "percent_change_1h": 0.42,
        "percent_change_24h": -1.87,
    }
    indicators = {
        "rsi": 54.3,
        "macd": 0.000812,
        "macd_signal": 0.000654,
        "macd_hist": 0.000158,
        "bb_upper": 625.10,
        "bb_middle": 608.75,
        "bb_lower": 592.40,
        "sma_20": 608.75,
        "sma_50": 598.20,
    }

    async with StrategyGenerator() as gen:
        strategy = await gen.generate("BNB", market_data, indicators)

    print("\n--- Strategy ---")
    for k, v in strategy.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
