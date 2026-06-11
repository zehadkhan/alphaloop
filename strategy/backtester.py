from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

TradeOutcome = Literal["WIN", "LOSS", "OPEN"]

# Walk-forward split: IS uses the first N candles, OOS uses the remainder.
_IS_CANDLES = 45
_OOS_MIN    = 5   # require at least this many OOS candles to run OOS gate

# Gate thresholds (applied to the OOS window when trades exist there)
_OOS_MIN_WIN_RATE  = 0.45
_OOS_MIN_RETURN    = -5.0   # percent
_OOS_MIN_SHARPE    = 0.2

# Fallback gate when OOS window has no trades (applied to IS)
_IS_MIN_WIN_RATE   = 0.50
_IS_MIN_RETURN     = 0.0    # percent


class Backtester:
    """Walk-forward backtester for a single strategy signal.

    Splits the available candles into an in-sample (IS) training window and
    an out-of-sample (OOS) validation window.  The gate decision is made on
    OOS performance when the OOS window contains triggered trades; otherwise
    it falls back to stricter IS thresholds.

    Within each window, trades are simulated non-overlapping.  On the entry
    candle only TP is checked — SL is skipped because the fill is assumed to
    have happened at entry_price and the wicks on that candle pre-date entry.
    From subsequent candles SL is checked before TP (conservative worst-case).
    """

    def run(self, ohlcv_data: list[dict], strategy: dict) -> dict:
        if strategy.get("action") == "HOLD":
            return self._empty_result("Strategy action is HOLD — nothing to backtest")

        all_candles = ohlcv_data[-60:]
        if not all_candles:
            return self._empty_result("No OHLCV data supplied")

        entry_price: float = float(strategy["entry_price"])
        stop_loss:   float = float(strategy["stop_loss"])
        take_profit: float = float(strategy["take_profit"])
        action = strategy["action"]

        sl_pct = (stop_loss   - entry_price) / entry_price * 100
        tp_pct = (take_profit - entry_price) / entry_price * 100

        if action == "BUY":
            if stop_loss >= entry_price:
                return self._empty_result(
                    f"BUY invalid: stop_loss {stop_loss:.2f} must be BELOW entry {entry_price:.2f}"
                )
            if take_profit <= entry_price:
                return self._empty_result(
                    f"BUY invalid: take_profit {take_profit:.2f} must be ABOVE entry {entry_price:.2f}"
                )
        elif action == "SELL":
            if stop_loss <= entry_price:
                return self._empty_result(
                    f"SELL invalid: stop_loss {stop_loss:.2f} must be ABOVE entry {entry_price:.2f}"
                )
            if take_profit >= entry_price:
                return self._empty_result(
                    f"SELL invalid: take_profit {take_profit:.2f} must be BELOW entry {entry_price:.2f}"
                )

        logger.info(
            "Backtest levels — action=%s  entry=%.2f  "
            "sl=%.2f (%+.1f%%)  tp=%.2f (%+.1f%%)  candles=%d",
            action, entry_price, stop_loss, sl_pct, take_profit, tp_pct, len(all_candles),
        )

        # ── Walk-forward split ───────────────────────────────────────────
        if len(all_candles) >= _IS_CANDLES + _OOS_MIN:
            is_candles  = all_candles[:_IS_CANDLES]
            oos_candles = all_candles[_IS_CANDLES:]
        else:
            is_candles  = all_candles
            oos_candles = []

        is_trades,  is_equity  = self._simulate(is_candles,  action, entry_price, stop_loss, take_profit)
        oos_trades, oos_equity = (
            self._simulate(oos_candles, action, entry_price, stop_loss, take_profit)
            if oos_candles else ([], [1.0])
        )

        # ── Metrics ──────────────────────────────────────────────────────
        is_wr  = self._win_rate(is_trades)
        is_ret = self._total_return(is_trades)
        oos_wr  = self._win_rate(oos_trades)
        oos_ret = self._total_return(oos_trades)

        # Chain equity curves for overall sharpe / drawdown
        combined_equity = self._chain_equity(is_equity, oos_equity)
        sharpe = self._sharpe_ratio(combined_equity)
        max_dd = self._max_drawdown(combined_equity)

        all_trades = is_trades + oos_trades

        # ── Gate decision ─────────────────────────────────────────────────
        if oos_trades:
            passed = (
                oos_wr  >= _OOS_MIN_WIN_RATE
                and oos_ret >= _OOS_MIN_RETURN
                and sharpe  >= _OOS_MIN_SHARPE
            )
            gate_source = "OOS"
        elif is_trades:
            passed = is_wr >= _IS_MIN_WIN_RATE and is_ret >= _IS_MIN_RETURN
            gate_source = "IS"
        else:
            return self._empty_result("No trades triggered in either window")

        summary = self._build_summary(
            passed, gate_source,
            is_trades, is_wr, is_ret,
            oos_trades, oos_wr, oos_ret,
            max_dd, sharpe,
        )

        result = {
            "passed":              passed,
            "total_return_percent": round(self._total_return(all_trades), 4),
            "win_rate":            round(self._win_rate(all_trades), 4),
            "max_drawdown":        round(max_dd, 4),
            "sharpe_ratio":        round(sharpe, 4),
            "total_trades":        len(all_trades),
            "is_win_rate":         round(is_wr, 4),
            "is_return":           round(is_ret, 4),
            "is_trades":           len(is_trades),
            "oos_win_rate":        round(oos_wr, 4),
            "oos_return":          round(oos_ret, 4),
            "oos_trades":          len(oos_trades),
            "gate_source":         gate_source,
            "summary":             summary,
        }

        logger.info(
            "Backtest — passed=%s gate=%s  IS %dT wr=%.0f%% ret=%.2f%%  "
            "OOS %dT wr=%.0f%% ret=%.2f%%  sharpe=%.2f",
            passed, gate_source,
            len(is_trades), is_wr * 100, is_ret,
            len(oos_trades), oos_wr * 100, oos_ret,
            sharpe,
        )
        return result

    # ------------------------------------------------------------------
    # Simulation core
    # ------------------------------------------------------------------

    def _simulate(
        self,
        candles: list[dict],
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[list[dict], list[float]]:
        trades: list[dict] = []
        equity_curve: list[float] = [1.0]

        i = 0
        while i < len(candles):
            candle = candles[i]
            low  = float(candle["low"])
            high = float(candle["high"])

            if not (low <= entry_price <= high):
                i += 1
                continue

            outcome, exit_price, resolve_idx = self._resolve_trade(
                candles, i, action, entry_price, stop_loss, take_profit
            )

            pnl_pct = self._pnl_percent(action, entry_price, exit_price)
            equity_curve.append(equity_curve[-1] * (1 + pnl_pct))

            logger.debug(
                "  Trade %d: entry=%.2f exit=%.2f pnl=%+.2f%% [%s] candle=%s",
                len(trades) + 1, entry_price, exit_price,
                pnl_pct * 100, outcome,
                candle.get("timestamp", "")[:10],
            )

            trades.append({
                "entry":       entry_price,
                "exit":        exit_price,
                "outcome":     outcome,
                "pnl_pct":     pnl_pct,
                "candle_open": candle.get("timestamp", ""),
            })
            i = resolve_idx + 1

        return trades, equity_curve

    def _resolve_trade(
        self,
        candles: list[dict],
        entry_idx: int,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[TradeOutcome, float, int]:
        for offset, candle in enumerate(candles[entry_idx:]):
            low  = float(candle["low"])
            high = float(candle["high"])
            is_entry_candle = (offset == 0)

            if action == "BUY":
                if not is_entry_candle and low <= stop_loss:
                    return "LOSS", stop_loss, entry_idx + offset
                if high >= take_profit:
                    return "WIN", take_profit, entry_idx + offset
            else:  # SELL
                if not is_entry_candle and high >= stop_loss:
                    return "LOSS", stop_loss, entry_idx + offset
                if low <= take_profit:
                    return "WIN", take_profit, entry_idx + offset

        final_close = float(candles[-1]["close"])
        outcome: TradeOutcome = (
            "WIN"
            if (action == "BUY"  and final_close > entry_price)
            or (action == "SELL" and final_close < entry_price)
            else "LOSS"
        )
        return outcome, final_close, len(candles) - 1

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _pnl_percent(action: str, entry: float, exit_: float) -> float:
        if action == "BUY":
            return (exit_ - entry) / entry
        return (entry - exit_) / entry

    @staticmethod
    def _total_return(trades: list[dict]) -> float:
        compound = 1.0
        for t in trades:
            compound *= 1 + t["pnl_pct"]
        return (compound - 1) * 100

    @staticmethod
    def _win_rate(trades: list[dict]) -> float:
        if not trades:
            return 0.0
        return sum(1 for t in trades if t["outcome"] == "WIN") / len(trades)

    @staticmethod
    def _max_drawdown(equity_curve: list[float]) -> float:
        arr   = np.array(equity_curve)
        peaks = np.maximum.accumulate(arr)
        return float(((arr - peaks) / peaks).min())

    @staticmethod
    def _sharpe_ratio(equity_curve: list[float], risk_free: float = 0.0) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = np.diff(equity_curve) / equity_curve[:-1]
        std = float(np.std(returns, ddof=1))
        if std == 0 or math.isnan(std):
            return 0.0
        return float((np.mean(returns) - risk_free) / std)

    @staticmethod
    def _chain_equity(is_eq: list[float], oos_eq: list[float]) -> list[float]:
        """Scale OOS equity so it continues from where IS ended."""
        if not is_eq:
            return oos_eq
        if len(oos_eq) <= 1:
            return is_eq
        scale = is_eq[-1]
        return is_eq + [v * scale for v in oos_eq[1:]]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(reason: str) -> dict:
        logger.warning("Backtest skipped: %s", reason)
        return {
            "passed": False,
            "total_return_percent": 0.0,
            "win_rate":    0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "is_win_rate":  0.0,
            "is_return":    0.0,
            "is_trades":    0,
            "oos_win_rate": 0.0,
            "oos_return":   0.0,
            "oos_trades":   0,
            "gate_source":  "none",
            "summary":      reason,
        }

    @staticmethod
    def _build_summary(
        passed: bool,
        gate_source: str,
        is_trades: list[dict],
        is_wr: float,
        is_ret: float,
        oos_trades: list[dict],
        oos_wr: float,
        oos_ret: float,
        max_dd: float,
        sharpe: float,
    ) -> str:
        verdict = "PASS" if passed else "FAIL"
        is_wins  = sum(1 for t in is_trades  if t["outcome"] == "WIN")
        oos_wins = sum(1 for t in oos_trades if t["outcome"] == "WIN")
        return (
            f"{verdict}[{gate_source}] | "
            f"IS {len(is_trades)}T {is_wins}W/{len(is_trades)-is_wins}L "
            f"ret={is_ret:+.1f}% wr={is_wr*100:.0f}% | "
            f"OOS {len(oos_trades)}T {oos_wins}W/{len(oos_trades)-oos_wins}L "
            f"ret={oos_ret:+.1f}% wr={oos_wr*100:.0f}% | "
            f"sharpe={sharpe:.2f} dd={max_dd*100:.1f}%"
        )


# ---------------------------------------------------------------------------
# Smoke-test: python -m strategy.backtester
# ---------------------------------------------------------------------------

def _make_sample_ohlcv(base_price: float = 600.0, n: int = 60) -> list[dict]:
    rng = np.random.default_rng(seed=42)
    candles: list[dict] = []
    price = base_price
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)

    for day in range(n):
        change = rng.normal(loc=0.003, scale=0.018)
        open_  = price
        close  = price * (1 + change)
        high   = max(open_, close) * (1 + abs(rng.normal(0, 0.005)))
        low    = min(open_, close) * (1 - abs(rng.normal(0, 0.005)))
        candles.append({
            "timestamp": (start + timedelta(days=day)).isoformat(),
            "open":   round(open_, 4),
            "high":   round(high, 4),
            "low":    round(low,  4),
            "close":  round(close, 4),
            "volume": round(rng.uniform(800_000, 2_000_000), 0),
        })
        price = close

    return candles


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    candles = _make_sample_ohlcv()
    mid = candles[0]["close"]

    strategies = [
        ("BUY", {
            "action": "BUY", "confidence": 0.78,
            "entry_price": mid,
            "stop_loss":   round(mid * 0.96, 4),
            "take_profit": round(mid * 1.08, 4),
            "reasoning": "Bullish MACD crossover",
            "timeframe": "medium", "risk_level": "medium", "should_execute": True,
        }),
        ("SELL", {
            "action": "SELL", "confidence": 0.71,
            "entry_price": mid,
            "stop_loss":   round(mid * 1.04, 4),
            "take_profit": round(mid * 0.93, 4),
            "reasoning": "Overbought RSI",
            "timeframe": "short", "risk_level": "high", "should_execute": True,
        }),
    ]

    bt = Backtester()
    for label, strategy in strategies:
        print(f"\n--- {label} strategy ---")
        result = bt.run(candles, strategy)
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
