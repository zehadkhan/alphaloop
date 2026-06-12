"""Agent orchestration: one cycle + APScheduler wiring."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import config
from data.cmc_client import CMCClient
from data.indicators import compute_indicators, extract_last_row, extract_4h_context
from strategy.generator import StrategyGenerator
from strategy.backtester import Backtester
from execution.wallet import WalletAgent
from execution.pancakeswap import PancakeSwapExecutor
from agent.competition import check_drawdown, force_close_stale_positions
from data.token_scanner import TokenScanner
from db.models import (
    create_agent_run,
    complete_agent_run,
    create_strategy,
    update_strategy_backtest,
    create_trade,
    close_trade,
    list_open_buy_trades,
    get_today_pnl,
    get_daily_trade_count,
    get_last_trade_time,
    get_bot_config,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# Prevents a second cycle from firing while one is still running.
_cycle_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Trade lifecycle monitor
# ---------------------------------------------------------------------------

async def _get_token_price(symbol: str) -> float | None:
    """Fetch the current {symbol}/USDT spot price from Binance (no auth required)."""
    pair = symbol.upper() + "USDT"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": pair},
            )
        if resp.status_code == 200:
            return float(resp.json()["price"])
        logger.warning("[Monitor] Binance %s price returned HTTP %d", pair, resp.status_code)
    except Exception as exc:
        logger.error("[Monitor] %s price fetch failed: %s", symbol, exc)
    return None


async def _get_bnb_price() -> float | None:
    return await _get_token_price("BNB")


async def monitor_open_trades() -> dict:
    """Check every open BUY position against its TP/SL and close if triggered.

    Runs on its own 5-minute schedule AND at the start of each agent cycle so
    PnL is updated before the position guard decides whether to open a new trade.
    """
    trades = await list_open_buy_trades()
    if not trades:
        return {"checked": 0, "closed": 0}

    # Fetch price once per unique symbol (token scanner may trade non-BNB tokens)
    symbols = {t.symbol for t in trades}
    prices: dict[str, float] = {}
    for sym in symbols:
        p = await _get_token_price(sym)
        if p is not None:
            prices[sym] = p

    if not prices:
        logger.warning("[Monitor] Cannot fetch any token prices — skipping trade check")
        return {"checked": len(trades), "closed": 0, "error": "price_unavailable"}

    closed_count = 0
    for trade in trades:
        current_price = prices.get(trade.symbol)
        if current_price is None:
            logger.warning("[Monitor] No price for %s — skipping trade %d", trade.symbol, trade.id)
            continue

        strategy = trade.strategy
        if strategy is None:
            continue

        tp = strategy.take_profit
        sl = strategy.stop_loss

        exit_price: float | None = None
        reason = ""
        if current_price >= tp:
            exit_price = tp
            reason = "take_profit"
        elif current_price <= sl:
            exit_price = sl
            reason = "stop_loss"

        if exit_price is not None:
            await close_trade(trade.id, exit_price=round(exit_price, 4))
            pnl_pct = (exit_price / trade.entry_price - 1) * 100
            logger.info(
                "[Monitor] Closed trade id=%d  %s  entry=%.4f → exit=%.4f  pnl=%+.2f%%",
                trade.id, reason, trade.entry_price, exit_price, pnl_pct,
            )
            closed_count += 1

    price_summary = {s: round(p, 4) for s, p in prices.items()}
    logger.info("[Monitor] Checked %d open trade(s), closed %d  prices=%s",
                len(trades), closed_count, price_summary)
    return {
        "checked": len(trades),
        "closed": closed_count,
        "prices": price_summary,
    }


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
    quote = "USDT"

    # ── Read runtime admin config overrides ───────────────────────────────
    bot_cfg = await get_bot_config()
    if bot_cfg.paused:
        logger.info("Bot is PAUSED by admin — skipping cycle")
        return {"status": "skipped", "reason": "admin_paused"}

    _pos_size_usd = bot_cfg.position_size_usd or config.MAX_POSITION_SIZE_USD
    _min_conf     = bot_cfg.min_confidence    or config.MIN_CONFIDENCE
    _claude_instr = bot_cfg.claude_instruction or None

    # ── Token selection: scan eligible tokens and pick best momentum ──────
    if config.COMPETITION_MODE and len(config.ELIGIBLE_TOKENS) > 1:
        try:
            scanner = TokenScanner(config.ELIGIBLE_TOKENS)
            top_tokens = await scanner.scan(top_n=config.TOKEN_SCAN_TOP_N)
            symbol = top_tokens[0]["symbol"]
            logger.info("[Scanner] Selected token: %s  score=%.3f", symbol, top_tokens[0]["score"])
        except Exception as exc:
            logger.warning("[Scanner] Token scan failed (%s) — falling back to default", exc)
            symbol = config.TRADING_PAIR.split("/")[0].upper()
    else:
        symbol = config.TRADING_PAIR.split("/")[0].upper()

    base = symbol

    # ── Pre-cycle: close any TP/SL hits from open trades ─────────────────
    try:
        await monitor_open_trades()
    except Exception as _mon_exc:
        logger.error("[Cycle] Pre-cycle monitor error (non-fatal): %s", _mon_exc)

    # ── Competition: force-close stale positions (ensures daily trade) ────
    if config.COMPETITION_MODE:
        stale_closed = await force_close_stale_positions()
        if stale_closed:
            logger.info("[Competition] Force-closed %d stale position(s)", stale_closed)

    # ── Competition: drawdown circuit breaker ─────────────────────────────
    if config.COMPETITION_MODE:
        drawdown = await check_drawdown()
        if drawdown["halt"]:
            logger.critical(
                "[Competition] Trading HALTED: drawdown=%.1f%% ≥ %.1f%%",
                drawdown["drawdown_pct"], drawdown["limit_pct"],
            )
            return _result("skipped", 0, reason="drawdown_halt",
                           drawdown_pct=drawdown["drawdown_pct"])

    # ── Competition: daily trade guarantee (override confidence if needed) ─
    _force_execute = False
    if config.COMPETITION_MODE:
        trades_today = await get_daily_trade_count()
        utc_hour = datetime.now(timezone.utc).hour
        if trades_today == 0 and utc_hour >= 22:
            _force_execute = True
            logger.warning(
                "[Competition] No trades today and hour=%d UTC — forcing execution this cycle",
                utc_hour,
            )

    # ── Position guard: one open BUY at a time ────────────────────────────
    open_buys = await list_open_buy_trades()
    if open_buys:
        logger.info(
            "Position guard: %d open BUY trade(s) — skipping new entry",
            len(open_buys),
        )
        return _result("skipped", 0, reason="open_position", open_trades=len(open_buys))

    # ── Daily loss guard ──────────────────────────────────────────────────
    today_pnl = await get_today_pnl()
    if today_pnl < -config.MAX_DAILY_LOSS_USD:
        logger.warning(
            "Daily loss limit breached: today_pnl=%.2f  limit=-%.2f — pausing trading",
            today_pnl, config.MAX_DAILY_LOSS_USD,
        )
        return _result("skipped", 0, reason="daily_loss_limit",
                       today_pnl=today_pnl, limit=-config.MAX_DAILY_LOSS_USD)

    run = await create_agent_run()
    strategies_generated = 0
    trades_executed = 0
    total_pnl = 0.0
    error_message: str | None = None

    try:
        logger.info("=== AlphaLoop cycle starting  run_id=%d  symbol=%s ===", run.id, symbol)

        # ── 1. Fetch market data ──────────────────────────────────────────
        logger.info("[1/6] Fetching market data (daily + 4h)…")
        async with CMCClient() as cmc:
            market_data = await cmc.get_quote(symbol)
            # 60 daily candles: 50+ for SMA-50; backtester uses IS=45 + OOS=15
            ohlcv_data  = await cmc.get_ohlcv(symbol, time_period="daily", count=60)
            # 100 × 4h candles ≈ last 17 days of intraday context
            try:
                ohlcv_4h = await cmc.get_ohlcv(symbol, time_period="4h", count=100)
            except Exception as exc:
                logger.warning("4h data fetch failed (%s) — continuing without it", exc)
                ohlcv_4h = []

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

        indicators_4h: dict | None = None
        if ohlcv_4h:
            df_4h = _ohlcv_to_dataframe(ohlcv_4h)
            df_4h = compute_indicators(df_4h)
            indicators_4h = extract_4h_context(df_4h)
            logger.info(
                "4h context: RSI=%.2f (%s)  trend=%s  MACD_hist=%.6f",
                indicators_4h["rsi"], indicators_4h["rsi_state"],
                indicators_4h["trend"], indicators_4h["macd_hist"],
            )

        logger.info(
            "Daily indicators: RSI=%.2f  MACD=%.6f  BB=[%.2f / %.2f / %.2f]  SMA20=%.2f  SMA50=%.2f",
            indicators["rsi"],
            indicators["macd"],
            indicators["bb_lower"],
            indicators["bb_middle"],
            indicators["bb_upper"],
            indicators["sma_20"],
            indicators["sma_50"],
        )

        # ── 3. Generate strategy via LLM ──────────────────────────────────
        logger.info("[3/6] Generating strategy via Claude (Anthropic)…")
        async with StrategyGenerator() as gen:
            strategy = await gen.generate(symbol, market_data, indicators, indicators_4h, _claude_instr)

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
        if strategy["action"] == "HOLD" and not _force_execute:
            logger.info("Action=HOLD — no trade this cycle")
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="HOLD")

        if strategy["action"] == "HOLD" and _force_execute:
            strategy["action"] = "BUY"
            logger.warning("[Competition] Overriding HOLD → BUY to guarantee daily trade")

        min_confidence = 0.3 if _force_execute else _min_conf
        if strategy["confidence"] < min_confidence:
            logger.info(
                "Confidence %.2f < %.2f threshold — skipping",
                strategy["confidence"], min_confidence,
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
        if config.TWAK_REST_URL:
            from execution.twak_executor import TWAKExecutor
            executor = TWAKExecutor()
            logger.info("[5/6] Executing swap via TWAK REST (%s)…", config.TWAK_REST_URL)
        else:
            wallet   = WalletAgent()
            executor = PancakeSwapExecutor(wallet)
            logger.info("[5/6] Executing swap on PancakeSwap V2 (BSC)…")

        # BUY  = spend quote (USDT) to get base (BNB)
        # SELL = spend base (BNB) to get quote (USDT)
        if strategy["action"] == "BUY":
            token_in, token_out = quote, base
        else:
            token_in, token_out = base, quote

        # Scale position by confidence: 50–100% of MAX_POSITION_SIZE_USD
        position_usd = round(
            _pos_size_usd * max(0.5, min(1.0, strategy["confidence"])), 2
        )
        logger.info(
            "Position sizing: confidence=%.2f → $%.2f (max $%.2f)",
            strategy["confidence"], position_usd, _pos_size_usd,
        )

        swap = await executor.swap(token_in, token_out, position_usd)
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

        # ── 8. Compute PnL (SELL only — BUY PnL realised on future close) ─
        pnl_usd, pnl_pct = _compute_pnl(strategy["action"], swap, position_usd)
        total_pnl = pnl_usd

        # ── 9. Save trade ─────────────────────────────────────────────────
        trade_status = "executed" if swap["status"] == "success" else swap["status"]

        logger.info("[6/6] Saving trade to database…")
        trade = await create_trade({
            "strategy_id": db_strategy.id,
            "symbol":      symbol,
            "action":      strategy["action"],
            "amount_usd":  position_usd,
            "entry_price": strategy["entry_price"],
            "exit_price":  swap["amount_out"] / swap["amount_in"] if strategy["action"] == "SELL" and swap["amount_in"] else None,
            "pnl_usd":     pnl_usd  if strategy["action"] == "SELL" else None,
            "pnl_percent": pnl_pct  if strategy["action"] == "SELL" else None,
            "tx_hash":     swap["tx_hash"],
            "status":      trade_status,
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
        max_instances=1,
    )
    scheduler.add_job(
        monitor_open_trades,
        trigger=IntervalTrigger(minutes=2),
        id="trade_monitor",
        replace_existing=True,
        max_instances=1,
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
