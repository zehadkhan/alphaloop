"""Agent orchestration: one cycle + APScheduler wiring."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import config
from data.cmc_client import CMCClient
from data.indicators import compute_indicators, extract_last_row
from strategy.generator import StrategyGenerator
from strategy.backtester import Backtester
from execution.wallet import WalletAgent
from execution.pancakeswap import PancakeSwapExecutor
from db.models import (
    create_agent_run,
    complete_agent_run,
    create_strategy,
    update_strategy_backtest,
    create_trade,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Prevents a second cycle from firing while one is still running.
_cycle_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Main agent cycle
# ---------------------------------------------------------------------------

async def run_agent_cycle() -> dict:
    """Execute one full agent cycle end-to-end.

    Returns a summary dict so both the scheduler and the /run endpoint can
    surface the result without duplicating logic.
    """
    if _cycle_lock.locked():
        logger.warning("Cycle already running — skipping this tick")
        return {"status": "skipped", "reason": "cycle_already_running"}

    async with _cycle_lock:
        return await _run_cycle_impl()


async def _run_cycle_impl() -> dict:
    symbol = config.TRADING_PAIR.split("/")[0].upper()   # "BNB" from "BNB/USDT"
    base, quote = config.TRADING_PAIR.split("/")         # "BNB", "USDT"

    run = await create_agent_run()
    strategies_generated = 0
    trades_executed = 0
    total_pnl = 0.0
    error_message: str | None = None

    try:
        logger.info("=== AlphaLoop cycle starting  run_id=%d  symbol=%s ===", run.id, symbol)

        # ── 1. Fetch market data ──────────────────────────────────────────
        logger.info("[1/6] Fetching market data from CoinMarketCap…")
        async with CMCClient() as cmc:
            market_data = await cmc.get_quote(symbol)
            # Fetch 60 candles: 50+ needed for SMA-50, last 30 used by backtester
            ohlcv_data = await cmc.get_ohlcv(symbol, time_period="daily", count=60)

        logger.info(
            "Market data fetched: price=%.4f  vol_24h=%.0f  change_24h=%+.2f%%",
            market_data["price"],
            market_data["volume_24h"],
            market_data["percent_change_24h"],
        )

        # ── 2. Compute technical indicators ───────────────────────────────
        logger.info("[2/6] Computing technical indicators…")
        df = _ohlcv_to_dataframe(ohlcv_data)
        df = compute_indicators(df)
        indicators = extract_last_row(df)

        logger.info(
            "Indicators: RSI=%.2f  MACD=%.6f  BB=[%.2f / %.2f / %.2f]  SMA20=%.2f  SMA50=%.2f",
            indicators["rsi"],
            indicators["macd"],
            indicators["bb_lower"],
            indicators["bb_middle"],
            indicators["bb_upper"],
            indicators["sma_20"],
            indicators["sma_50"],
        )

        # ── 3. Generate strategy via LLM ──────────────────────────────────
        logger.info("[3/6] Generating strategy via OpenRouter…")
        async with StrategyGenerator() as gen:
            strategy = await gen.generate(symbol, market_data, indicators)

        strategies_generated = 1
        logger.info(
            "Strategy: action=%s  confidence=%.2f  entry=%.4f  sl=%.4f  tp=%.4f  execute=%s",
            strategy["action"],
            strategy["confidence"],
            strategy["entry_price"],
            strategy["stop_loss"],
            strategy["take_profit"],
            strategy["should_execute"],
        )

        # ── 4. Gate: HOLD or low confidence ──────────────────────────────
        if strategy["action"] == "HOLD":
            logger.info("Action=HOLD — no trade this cycle")
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="HOLD")

        if strategy["confidence"] < config.MIN_CONFIDENCE:
            logger.info(
                "Confidence %.2f < %.2f threshold — skipping",
                strategy["confidence"], config.MIN_CONFIDENCE,
            )
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="low_confidence",
                           confidence=strategy["confidence"])

        # ── 5. Backtest ───────────────────────────────────────────────────
        logger.info("[4/6] Running backtest on last 30 daily candles…")
        backtest = Backtester().run(ohlcv_data, strategy)
        logger.info("Backtest: %s", backtest["summary"])

        # ── 6. Persist strategy (always, even if rejected) ────────────────
        db_strategy = await create_strategy({
            "symbol":     symbol,
            "action":     strategy["action"],
            "confidence": strategy["confidence"],
            "entry_price": strategy["entry_price"],
            "stop_loss":   strategy["stop_loss"],
            "take_profit": strategy["take_profit"],
            "reasoning":   strategy["reasoning"],
            "timeframe":   strategy["timeframe"],
            "risk_level":  strategy["risk_level"],
            "status":      "pending",
        })
        await update_strategy_backtest(
            db_strategy.id,
            passed=backtest["passed"],
            total_return=backtest["total_return_percent"],
            win_rate=backtest["win_rate"],
        )
        logger.info("Strategy saved: id=%d  status=%s", db_strategy.id,
                    "approved" if backtest["passed"] else "rejected")

        if not backtest["passed"]:
            logger.info("Backtest failed — skipping execution")
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="backtest_failed",
                           strategy_id=db_strategy.id, backtest=backtest["summary"])

        # ── 7. Execute swap ───────────────────────────────────────────────
        logger.info("[5/6] Executing swap on PancakeSwap V2 (BSC testnet)…")
        wallet   = WalletAgent()
        executor = PancakeSwapExecutor(wallet)

        # BUY  = spend quote (USDT) to get base (BNB)
        # SELL = spend base (BNB) to get quote (USDT)
        if strategy["action"] == "BUY":
            token_in, token_out = quote, base
        else:
            token_in, token_out = base, quote

        swap = await executor.swap(token_in, token_out, config.MAX_POSITION_SIZE_USD)
        trades_executed = 1

        logger.info(
            "Swap %s: %s %.6f → %s %.6f  price=%.4f  gas=%d  status=%s  tx=%s",
            strategy["action"],
            token_in,  swap["amount_in"],
            token_out, swap["amount_out"],
            swap["price"],
            swap["gas_used"],
            swap["status"],
            swap["tx_hash"],
        )

        # ── 8. Compute PnL (SELL only — BUY PnL realised on future SELL) ─
        pnl_usd, pnl_pct = _compute_pnl(strategy["action"], swap, config.MAX_POSITION_SIZE_USD)
        total_pnl = pnl_usd

        # ── 9. Save trade ─────────────────────────────────────────────────
        logger.info("[6/6] Saving trade to database…")
        trade = await create_trade({
            "strategy_id": db_strategy.id,
            "symbol":      symbol,
            "action":      strategy["action"],
            "amount_usd":  config.MAX_POSITION_SIZE_USD,
            "entry_price": strategy["entry_price"],
            "exit_price":  swap["amount_out"] / swap["amount_in"] if strategy["action"] == "SELL" and swap["amount_in"] else None,
            "pnl_usd":     pnl_usd  if strategy["action"] == "SELL" else None,
            "pnl_percent": pnl_pct  if strategy["action"] == "SELL" else None,
            "tx_hash":     swap["tx_hash"],
            "status":      swap["status"],
            "executed_at": datetime.now(timezone.utc),
        })

        logger.info(
            "=== Cycle complete  run_id=%d  trade_id=%d  pnl_usd=%+.4f ===",
            run.id, trade.id, pnl_usd,
        )

        await _finish_run(run.id, strategies_generated, trades_executed, total_pnl, None)
        return _result(
            "executed", run.id,
            strategy_id=db_strategy.id,
            trade_id=trade.id,
            action=strategy["action"],
            tx_hash=swap["tx_hash"],
            swap_status=swap["status"],
            pnl_usd=pnl_usd,
            backtest=backtest["summary"],
        )

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        logger.exception("Cycle error (run_id=%d): %s", run.id, exc)
        await _finish_run(run.id, strategies_generated, trades_executed, total_pnl, error_message)
        return _result("error", run.id, error=error_message)


# ---------------------------------------------------------------------------
# Scheduler wiring
# ---------------------------------------------------------------------------

def start_scheduler(interval_minutes: int = 30) -> None:
    scheduler.add_job(
        run_agent_cycle,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="agent_cycle",
        replace_existing=True,
        max_instances=1,    # APScheduler won't queue a second instance
    )
    scheduler.start()
    logger.info("Scheduler started — interval=%d min  next_run=%s",
                interval_minutes,
                scheduler.get_job("agent_cycle").next_run_time)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _ohlcv_to_dataframe(ohlcv_data: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(ohlcv_data)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _compute_pnl(action: str, swap: dict, position_usd: float) -> tuple[float, float]:
    """Return (pnl_usd, pnl_percent) for a completed swap.

    For BUY trades pnl is unrealised and returned as (0.0, 0.0).
    For SELL trades pnl = USDT received − position_usd spent.
    """
    if action != "SELL":
        return 0.0, 0.0
    received_usd = float(swap["amount_out"])
    pnl_usd = received_usd - position_usd
    pnl_pct = (pnl_usd / position_usd) * 100 if position_usd else 0.0
    return round(pnl_usd, 4), round(pnl_pct, 4)


async def _finish_run(
    run_id: int,
    strategies_generated: int,
    trades_executed: int,
    total_pnl: float,
    error_message: str | None,
) -> None:
    await complete_agent_run(
        run_id,
        strategies_generated=strategies_generated,
        trades_executed=trades_executed,
        total_pnl=total_pnl,
        error_message=error_message,
    )


def _result(status: str, run_id: int, **kwargs) -> dict:
    return {"status": status, "run_id": run_id, **kwargs}
