from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Literal

import numpy as np

logger = logging.getLogger(__name__)

TradeOutcome = Literal["WIN", "LOSS", "OPEN"]


class Backtester:
    """Simulate a single strategy signal against historical OHLCV candles.

    Each BUY signal from the strategy is replayed on each candle in sequence.
    Within every candle the intra-bar order is: stop-loss check first (worst
    case), then take-profit.  This is conservative — it avoids overstating
    results when both levels are inside the same candle's range.
    """

    def run(self, ohlcv_data: list[dict], strategy: dict) -> dict:
        """Backtest *strategy* against *ohlcv_data*.

        Args:
            ohlcv_data: List of candle dicts with keys open, high, low, close,
                        volume, timestamp.  Oldest candle first.  At most the
                        last 30 entries are used.
            strategy:   Output of StrategyGenerator.generate().  Must contain
                        action, entry_price, stop_loss, take_profit.

        Returns:
            Result dict including a ``passed`` boolean that gates execution.
        """
        candles = ohlcv_data[-30:]

        if not candles:
            return self._empty_result("No OHLCV data supplied")

        if strategy.get("action") == "HOLD":
            return self._empty_result("Strategy action is HOLD — nothing to backtest")

        entry_price: float = float(strategy["entry_price"])
        stop_loss: float = float(strategy["stop_loss"])
        take_profit: float = float(strategy["take_profit"])

        if not self._levels_are_valid(strategy["action"], entry_price, stop_loss, take_profit):
            return self._empty_result(
                f"Invalid levels: entry={entry_price} sl={stop_loss} tp={take_profit}"
            )

        sl_pct = (stop_loss - entry_price) / entry_price * 100
        tp_pct = (take_profit - entry_price) / entry_price * 100
        logger.info(
            "Backtest starting — action=%s  entry=%.2f  sl=%.2f (%+.1f%%)  "
            "tp=%.2f (%+.1f%%)  candles=%d",
            strategy["action"], entry_price,
            stop_loss, sl_pct, take_profit, tp_pct, len(candles),
        )

        trades, equity_curve = self._simulate(
            candles, strategy["action"], entry_price, stop_loss, take_profit
        )

        if not trades:
            return self._empty_result("No trades triggered — entry price never reached")

        total_return = self._total_return(trades)
        win_rate = self._win_rate(trades)
        max_dd = self._max_drawdown(equity_curve)
        sharpe = self._sharpe_ratio(equity_curve)
        passed = total_return > 0 and win_rate > 0.5

        summary = self._build_summary(
            passed, trades, total_return, win_rate, max_dd, sharpe
        )

        result = {
            "passed": passed,
            "total_return_percent": round(total_return, 4),
            "win_rate": round(win_rate, 4),
            "max_drawdown": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 4),
            "total_trades": len(trades),
            "summary": summary,
        }

        logger.info(
            "Backtest — passed=%s trades=%d return=%.2f%% win_rate=%.0f%% "
            "max_dd=%.2f%% sharpe=%.2f",
            passed,
            len(trades),
            total_return,
            win_rate * 100,
            max_dd * 100,
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
        """Walk candles and record trade outcomes.

        One trade at a time: after entering on candle i, the loop resumes at
        the candle AFTER the one that resolved the trade (no overlapping
        positions).  SL is not checked on the entry candle itself — we
        assume the limit order filled at entry_price, so the entry candle's
        wick below that level does not mean SL was hit before entry.
        """
        trades: list[dict] = []
        equity_curve: list[float] = [1.0]

        i = 0
        while i < len(candles):
            candle = candles[i]
            low = float(candle["low"])
            high = float(candle["high"])

            if not (low <= entry_price <= high):
                i += 1
                continue

            # Entry triggered — resolve to SL, TP, or window end.
            outcome, exit_price, resolve_idx = self._resolve_trade(
                candles, i, action, entry_price, stop_loss, take_profit
            )

            pnl_pct = self._pnl_percent(action, entry_price, exit_price)
            equity_curve.append(equity_curve[-1] * (1 + pnl_pct))

            logger.info(
                "  Trade %d: entry=%.2f  sl=%.2f  tp=%.2f  exit=%.2f  "
                "pnl=%+.2f%%  [%s]  candle=%s",
                len(trades) + 1,
                entry_price, stop_loss, take_profit, exit_price,
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

            # Advance past the resolution candle so positions don't overlap.
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
        """Scan forward from *entry_idx* and return (outcome, exit_price, candle_idx).

        On the entry candle, only TP is checked — SL is skipped because the
        fill happened at entry_price and the wick below it predates our entry.
        From the next candle onwards, SL is checked before TP (conservative).
        """
        for offset, candle in enumerate(candles[entry_idx:]):
            low = float(candle["low"])
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

        # Trade still open at end of window — exit at final close.
        final_close = float(candles[-1]["close"])
        outcome: TradeOutcome = (
            "WIN"
            if (action == "BUY" and final_close > entry_price)
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
        return (entry - exit_) / entry  # SELL profits when price falls

    @staticmethod
    def _total_return(trades: list[dict]) -> float:
        """Compound percentage return across all trades, as a percentage."""
        compound = 1.0
        for t in trades:
            compound *= 1 + t["pnl_pct"]
        return (compound - 1) * 100

    @staticmethod
    def _win_rate(trades: list[dict]) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t["outcome"] == "WIN")
        return wins / len(trades)

    @staticmethod
    def _max_drawdown(equity_curve: list[float]) -> float:
        """Largest peak-to-trough decline in the equity curve."""
        arr = np.array(equity_curve)
        peaks = np.maximum.accumulate(arr)
        drawdowns = (arr - peaks) / peaks
        return float(drawdowns.min())  # negative number; caller rounds it

    @staticmethod
    def _sharpe_ratio(equity_curve: list[float], risk_free: float = 0.0) -> float:
        """Simplified Sharpe: mean trade return / std dev of trade returns.

        Uses per-trade returns (not annualised) since we're working on a
        30-candle window with no fixed time unit.
        """
        if len(equity_curve) < 2:
            return 0.0
        returns = np.diff(equity_curve) / equity_curve[:-1]
        std = float(np.std(returns, ddof=1))
        if std == 0 or math.isnan(std):
            return 0.0
        return float((np.mean(returns) - risk_free) / std)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _levels_are_valid(
        action: str, entry: float, stop_loss: float, take_profit: float
    ) -> bool:
        if action == "BUY":
            return stop_loss < entry < take_profit
        if action == "SELL":
            return take_profit < entry < stop_loss
        return False

    @staticmethod
    def _empty_result(reason: str) -> dict:
        logger.warning("Backtest skipped: %s", reason)
        return {
            "passed": False,
            "total_return_percent": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "summary": reason,
        }

    @staticmethod
    def _build_summary(
        passed: bool,
        trades: list[dict],
        total_return: float,
        win_rate: float,
        max_dd: float,
        sharpe: float,
    ) -> str:
        verdict = "PASS" if passed else "FAIL"
        wins = sum(1 for t in trades if t["outcome"] == "WIN")
        losses = len(trades) - wins
        return (
            f"{verdict} | {len(trades)} trades ({wins}W/{losses}L) | "
            f"return={total_return:+.2f}% | win_rate={win_rate*100:.0f}% | "
            f"max_dd={max_dd*100:.2f}% | sharpe={sharpe:.2f}"
        )


# ---------------------------------------------------------------------------
# Smoke-test: python -m strategy.backtester
# ---------------------------------------------------------------------------

def _make_sample_ohlcv(base_price: float = 600.0, n: int = 30) -> list[dict]:
    """Generate 30 synthetic daily BNB candles with a mild uptrend."""
    rng = np.random.default_rng(seed=42)
    candles: list[dict] = []
    price = base_price
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)

    for day in range(n):
        change = rng.normal(loc=0.003, scale=0.018)  # ~+0.3% drift, 1.8% vol
        open_ = price
        close = price * (1 + change)
        high = max(open_, close) * (1 + abs(rng.normal(0, 0.005)))
        low = min(open_, close) * (1 - abs(rng.normal(0, 0.005)))
        candles.append(
            {
                "timestamp": (start + timedelta(days=day)).isoformat(),
                "open": round(open_, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": round(rng.uniform(800_000, 2_000_000), 0),
            }
        )
        price = close

    return candles


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    candles = _make_sample_ohlcv()
    mid = candles[0]["close"]

    strategy_buy = {
        "action": "BUY",
        "confidence": 0.78,
        "entry_price": mid,
        "stop_loss": round(mid * 0.96, 4),   # –4%
        "take_profit": round(mid * 1.08, 4),  # +8%
        "reasoning": "Strong uptrend with bullish MACD crossover",
        "timeframe": "medium",
        "risk_level": "medium",
        "should_execute": True,
    }

    strategy_sell = {
        "action": "SELL",
        "confidence": 0.71,
        "entry_price": mid,
        "stop_loss": round(mid * 1.04, 4),   # +4% (loss for a short)
        "take_profit": round(mid * 0.93, 4),  # –7% (profit for a short)
        "reasoning": "Overbought RSI with bearish divergence",
        "timeframe": "short",
        "risk_level": "high",
        "should_execute": True,
    }

    bt = Backtester()

    for label, strategy in [("BUY strategy", strategy_buy), ("SELL strategy", strategy_sell)]:
        print(f"\n--- {label} ---")
        result = bt.run(candles, strategy)
        for k, v in result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(_main())
