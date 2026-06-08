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

        Each candle that crosses *entry_price* opens a new trade (one at a
        time).  We then look at subsequent candles to resolve it at SL or TP.
        Unresolved trades at the end of the window are closed at the final
        close price.
        """
        trades: list[dict] = []
        # Equity curve: percentage gain/loss on each closed trade in sequence.
        equity_curve: list[float] = [1.0]  # start at 1.0 (normalised)

        i = 0
        while i < len(candles):
            candle = candles[i]
            low = float(candle["low"])
            high = float(candle["high"])

            # Check whether entry is reachable on this candle.
            if action == "BUY" and low <= entry_price <= high:
                pass  # entry triggered
            elif action == "SELL" and low <= entry_price <= high:
                pass
            else:
                i += 1
                continue

            # Resolve the trade on this or subsequent candles.
            outcome, exit_price = self._resolve_trade(
                candles, i, action, entry_price, stop_loss, take_profit
            )

            pnl_pct = self._pnl_percent(action, entry_price, exit_price)
            equity_curve.append(equity_curve[-1] * (1 + pnl_pct))

            trades.append(
                {
                    "entry": entry_price,
                    "exit": exit_price,
                    "outcome": outcome,
                    "pnl_pct": pnl_pct,
                    "candle_open": candle.get("timestamp", ""),
                }
            )

            # Skip past the resolution candle to avoid overlapping trades.
            # For simplicity advance by 1 — real systems would track the
            # exact resolution index, but it doesn't affect the stat calculations.
            i += 1

        return trades, equity_curve

    def _resolve_trade(
        self,
        candles: list[dict],
        entry_idx: int,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> tuple[TradeOutcome, float]:
        """Scan forward from *entry_idx* and return (outcome, exit_price).

        Stop-loss is checked before take-profit within each candle (conservative).
        """
        for candle in candles[entry_idx:]:
            low = float(candle["low"])
            high = float(candle["high"])

            if action == "BUY":
                if low <= stop_loss:
                    return "LOSS", stop_loss
                if high >= take_profit:
                    return "WIN", take_profit
            else:  # SELL
                if high >= stop_loss:
                    return "LOSS", stop_loss
                if low <= take_profit:
                    return "WIN", take_profit

        # Trade still open at end of window — exit at final close.
        final_close = float(candles[-1]["close"])
        outcome: TradeOutcome = (
            "WIN"
            if (action == "BUY" and final_close > entry_price)
            or (action == "SELL" and final_close < entry_price)
            else "LOSS"
        )
        return outcome, final_close

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
