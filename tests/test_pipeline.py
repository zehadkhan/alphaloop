#!/usr/bin/env python3
"""AlphaLoop pipeline smoke-tests.

Tests every layer of the pipeline without executing real blockchain transactions.
API-dependent tests are skipped automatically when the required key is absent.

Run from the project root:
    python tests/test_pipeline.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

# Make sure project root is on the path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASS = "\033[92mPASS\033[0m"
_FAIL = "\033[91mFAIL\033[0m"
_SKIP = "\033[93mSKIP\033[0m"

_results: list[tuple[str, str, str]] = []  # (name, verdict, detail)


def record(name: str, verdict: str, detail: str = "") -> None:
    _results.append((name, verdict, detail))
    tag = {"PASS": _PASS, "FAIL": _FAIL, "SKIP": _SKIP}[verdict]
    suffix = f"  — {detail}" if detail else ""
    print(f"  [{tag}]  {name}{suffix}")


def run_test(name: str):
    """Decorator that catches exceptions and records PASS/FAIL."""
    def decorator(fn):
        async def wrapper():
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    result = await result
                # fn returns None on pass, a skip-reason string, or raises on fail
                if isinstance(result, str):
                    record(name, "SKIP", result)
                else:
                    record(name, "PASS")
            except AssertionError as exc:
                record(name, "FAIL", str(exc))
            except Exception as exc:
                record(name, "FAIL", f"{type(exc).__name__}: {exc}")
        return wrapper
    return decorator


def _make_ohlcv(n: int = 60, base_price: float = 600.0) -> list[dict]:
    """Synthetic daily OHLCV candles with a mild uptrend."""
    rng = np.random.default_rng(seed=7)
    candles: list[dict] = []
    price = base_price
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for i in range(n):
        change = rng.normal(0.002, 0.018)
        open_ = price
        close = price * (1 + change)
        high  = max(open_, close) * (1 + abs(rng.normal(0, 0.004)))
        low   = min(open_, close) * (1 - abs(rng.normal(0, 0.004)))
        candles.append({
            "timestamp": (start + timedelta(days=i)).isoformat(),
            "open":   round(open_, 4),
            "high":   round(high,  4),
            "low":    round(low,   4),
            "close":  round(close, 4),
            "volume": round(rng.uniform(800_000, 2_000_000), 0),
        })
        price = close
    return candles


def _ohlcv_to_df(candles: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


# ---------------------------------------------------------------------------
# Test 1 — Indicator calculations (no API)
# ---------------------------------------------------------------------------

@run_test("Indicator calculations")
def test_indicators():
    from data.indicators import compute_indicators, extract_last_row

    candles = _make_ohlcv(60)
    df = _ohlcv_to_df(candles)
    df = compute_indicators(df)

    expected_cols = [
        "ema_fast", "ema_slow", "sma_20", "sma_50",
        "rsi", "macd", "macd_signal", "macd_hist",
        "atr", "bb_upper", "bb_middle", "bb_lower",
    ]
    missing = [c for c in expected_cols if c not in df.columns]
    assert not missing, f"Missing columns: {missing}"

    last = extract_last_row(df)
    assert 0 <= last["rsi"] <= 100, f"RSI out of range: {last['rsi']}"
    assert last["bb_upper"] >= last["bb_middle"] >= last["bb_lower"], \
        "Bollinger Band ordering violated"
    assert last["sma_20"] > 0, "SMA-20 is zero"
    assert last["sma_50"] > 0, "SMA-50 is zero"
    assert isinstance(last["macd_hist"], float), "macd_hist is not float"


# ---------------------------------------------------------------------------
# Test 2 — Backtester (no API)
# ---------------------------------------------------------------------------

@run_test("Backtester — BUY strategy")
def test_backtester_buy():
    from strategy.backtester import Backtester

    candles = _make_ohlcv(60)
    mid = candles[0]["close"]
    strategy = {
        "action":       "BUY",
        "confidence":   0.80,
        "entry_price":  mid,
        "stop_loss":    round(mid * 0.95, 4),
        "take_profit":  round(mid * 1.10, 4),
        "reasoning":    "test",
        "timeframe":    "medium",
        "risk_level":   "low",
        "should_execute": True,
    }
    result = Backtester().run(candles, strategy)

    required = {"passed", "total_return_percent", "win_rate", "max_drawdown",
                "sharpe_ratio", "total_trades", "summary"}
    missing = required - result.keys()
    assert not missing, f"Missing keys: {missing}"
    assert isinstance(result["passed"], bool), "passed must be bool"
    assert 0.0 <= result["win_rate"] <= 1.0, f"win_rate out of range: {result['win_rate']}"
    assert result["summary"], "summary is empty"


@run_test("Backtester — SELL strategy")
def test_backtester_sell():
    from strategy.backtester import Backtester

    candles = _make_ohlcv(60)
    mid = candles[-1]["close"]
    strategy = {
        "action":       "SELL",
        "confidence":   0.72,
        "entry_price":  mid,
        "stop_loss":    round(mid * 1.05, 4),   # SL above entry for short
        "take_profit":  round(mid * 0.92, 4),   # TP below entry for short
        "reasoning":    "test",
        "timeframe":    "short",
        "risk_level":   "high",
        "should_execute": True,
    }
    result = Backtester().run(candles, strategy)
    assert isinstance(result["passed"], bool)
    assert "total_return_percent" in result


@run_test("Backtester — HOLD action returns skipped")
def test_backtester_hold():
    from strategy.backtester import Backtester

    result = Backtester().run(_make_ohlcv(30), {
        "action": "HOLD", "entry_price": 600.0,
        "stop_loss": 570.0, "take_profit": 640.0,
    })
    assert result["passed"] is False
    assert result["total_trades"] == 0


@run_test("Backtester — invalid levels rejected")
def test_backtester_invalid_levels():
    from strategy.backtester import Backtester

    # SL above entry for a BUY is invalid
    result = Backtester().run(_make_ohlcv(30), {
        "action":      "BUY",
        "entry_price": 600.0,
        "stop_loss":   640.0,   # wrong: above entry
        "take_profit": 660.0,
    })
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# Test 3 — Strategy generator (local logic only; LLM call skipped if no key)
# ---------------------------------------------------------------------------

@run_test("StrategyGenerator — prompt builds without error")
def test_strategy_prompt():
    from strategy.generator import StrategyGenerator

    market_data = {
        "symbol": "BNB", "price": 612.5,
        "volume_24h": 1_200_000_000.0, "market_cap": 90_000_000_000.0,
        "percent_change_1h": 0.3, "percent_change_24h": -1.5,
    }
    indicators = {
        "rsi": 52.0, "macd": 0.0005, "macd_signal": 0.0003, "macd_hist": 0.0002,
        "bb_upper": 630.0, "bb_middle": 610.0, "bb_lower": 590.0,
        "sma_20": 610.0, "sma_50": 598.0,
    }
    gen = StrategyGenerator(api_key="dummy")
    prompt = gen._build_prompt("BNB/USDT", market_data, indicators)
    assert "BNB/USDT" in prompt
    assert "RSI" in prompt
    assert "Bollinger" in prompt
    assert "SMA 20" in prompt


@run_test("StrategyGenerator — parse and validate good JSON")
def test_strategy_validate():
    from strategy.generator import StrategyGenerator

    gen = StrategyGenerator(api_key="dummy")
    raw = """{
        "action": "BUY",
        "confidence": 0.82,
        "entry_price": 612.5,
        "stop_loss": 588.0,
        "take_profit": 660.0,
        "reasoning": "Bullish MACD crossover",
        "timeframe": "medium",
        "risk_level": "low"
    }"""
    result = gen._parse_and_validate(raw)
    assert result["action"] == "BUY"
    assert result["confidence"] == 0.82
    assert isinstance(result["stop_loss"], float)


@run_test("StrategyGenerator — strips markdown fences")
def test_strategy_strip_fences():
    from strategy.generator import StrategyGenerator

    gen = StrategyGenerator(api_key="dummy")
    raw = """```json
{
    "action": "HOLD",
    "confidence": 0.45,
    "entry_price": 610.0,
    "stop_loss": 585.0,
    "take_profit": 650.0,
    "reasoning": "Neutral",
    "timeframe": "short",
    "risk_level": "low"
}
```"""
    result = gen._parse_and_validate(raw)
    assert result["action"] == "HOLD"


@run_test("StrategyGenerator — rejects missing fields")
def test_strategy_missing_fields():
    from strategy.generator import StrategyGenerator, StrategyGeneratorError

    gen = StrategyGenerator(api_key="dummy")
    try:
        gen._parse_and_validate('{"action": "BUY"}')
        assert False, "Should have raised"
    except StrategyGeneratorError as exc:
        assert "missing" in str(exc).lower()


@run_test("StrategyGenerator — full LLM call (OpenRouter)")
async def test_strategy_live():
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return "OPENROUTER_API_KEY not set"

    from strategy.generator import StrategyGenerator

    market_data = {
        "symbol": "BNB", "price": 612.5,
        "volume_24h": 1_200_000_000.0, "market_cap": 90_000_000_000.0,
        "percent_change_1h": 0.3, "percent_change_24h": -1.5,
    }
    indicators = {
        "rsi": 52.0, "macd": 0.0005, "macd_signal": 0.0003, "macd_hist": 0.0002,
        "bb_upper": 630.0, "bb_middle": 610.0, "bb_lower": 590.0,
        "sma_20": 610.0, "sma_50": 598.0,
    }
    async with StrategyGenerator() as gen:
        result = await gen.generate("BNB", market_data, indicators)

    assert result["action"] in ("BUY", "SELL", "HOLD"), f"Bad action: {result['action']}"
    assert 0.0 <= result["confidence"] <= 1.0
    assert "should_execute" in result


# ---------------------------------------------------------------------------
# Test 4 — CMC API connection
# ---------------------------------------------------------------------------

@run_test("CMC API — get_quote(BNB)")
async def test_cmc_quote():
    key = os.getenv("CMC_API_KEY", "")
    if not key:
        return "CMC_API_KEY not set"

    from data.cmc_client import CMCClient

    async with CMCClient() as cmc:
        result = await cmc.get_quote("BNB")

    required = {"symbol", "price", "volume_24h", "percent_change_1h",
                "percent_change_24h", "market_cap"}
    missing = required - result.keys()
    assert not missing, f"Missing fields: {missing}"
    assert result["price"] > 0, "Price must be positive"
    assert result["symbol"] == "BNB"


@run_test("Binance — get_ohlcv(BNB, daily, 5)")
async def test_cmc_ohlcv():
    from data.cmc_client import CMCClient

    async with CMCClient() as cmc:
        candles = await cmc.get_ohlcv("BNB", time_period="daily", count=5)

    assert len(candles) == 5, f"Expected 5 candles, got {len(candles)}"
    for c in candles:
        assert c["high"] >= c["low"],   "high < low on a candle"
        assert c["open"] > 0,           "open price is zero"
        assert c["volume"] > 0,         "volume is zero"
        assert "timestamp" in c,        "missing timestamp"
        assert "T" in c["timestamp"],   "timestamp not ISO-8601"


@run_test("CMC API — get_market_metrics")
async def test_cmc_metrics():
    key = os.getenv("CMC_API_KEY", "")
    if not key:
        return "CMC_API_KEY not set"

    from data.cmc_client import CMCClient

    async with CMCClient() as cmc:
        metrics = await cmc.get_market_metrics()

    assert metrics["total_market_cap"] > 0
    assert 0 < metrics["btc_dominance"] < 100
    assert metrics["active_cryptocurrencies"] > 0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\n" + "=" * 60)
    print("  AlphaLoop Pipeline Tests")
    print("=" * 60 + "\n")

    tests = [
        test_indicators,
        test_backtester_buy,
        test_backtester_sell,
        test_backtester_hold,
        test_backtester_invalid_levels,
        test_strategy_prompt,
        test_strategy_validate,
        test_strategy_strip_fences,
        test_strategy_missing_fields,
        test_strategy_live,
        test_cmc_quote,
        test_cmc_ohlcv,
        test_cmc_metrics,
    ]

    for test_fn in tests:
        await test_fn()

    print("\n" + "=" * 60)
    passed = sum(1 for _, v, _ in _results if v == "PASS")
    failed = sum(1 for _, v, _ in _results if v == "FAIL")
    skipped = sum(1 for _, v, _ in _results if v == "SKIP")
    total = len(_results)
    print(f"  Results: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped")
    print("=" * 60 + "\n")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
