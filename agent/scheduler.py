"""Agent orchestration: one cycle + APScheduler wiring."""
from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime, timezone

import httpx
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import config
from data.cmc_client import CMCClient
from data.indicators import compute_indicators, extract_last_row, extract_4h_context
from data.regime import MarketCompass
from strategy.generator import StrategyGenerator
from strategy.backtester import Backtester
from execution.wallet import WalletAgent
from execution.pancakeswap import PancakeSwapExecutor
from agent.competition import (
    COMPETITION_END,
    COMPETITION_START,
    check_drawdown,
    force_close_stale_positions,
)
from agent.proof import build_proof, commit_proof_onchain
from data.token_scanner import TokenScanner
from db.models import (
    create_agent_run,
    complete_agent_run,
    create_strategy,
    update_strategy_backtest,
    create_trade,
    close_trade,
    update_trade_proof,
    list_open_buy_trades,
    get_today_pnl,
    get_daily_trade_count,
    get_last_trade_time,
    get_bot_config,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(
    job_defaults={
        "misfire_grace_time": 600,  # 10-min grace — survives busy event loops
        "coalesce": True,           # collapse multiple misfires into one run
    }
)

_cycle_lock = asyncio.Lock()

# Last computed compass — exposed via /status endpoint
_last_compass: dict | None = None


# ---------------------------------------------------------------------------
# Trade lifecycle monitor
# ---------------------------------------------------------------------------

async def _get_token_price(symbol: str) -> float | None:
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
    """Check every open BUY position against its TP/SL and close if triggered."""
    trades = await list_open_buy_trades()
    if not trades:
        return {"checked": 0, "closed": 0}

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
    return {"checked": len(trades), "closed": closed_count, "prices": price_summary}


# ---------------------------------------------------------------------------
# Main agent cycle
# ---------------------------------------------------------------------------

async def run_agent_cycle() -> dict:
    if _cycle_lock.locked():
        logger.warning("Cycle already running — skipping this tick")
        return {"status": "skipped", "reason": "cycle_already_running"}

    async with _cycle_lock:
        try:
            return await asyncio.wait_for(_run_cycle_impl(), timeout=300)
        except asyncio.TimeoutError:
            logger.error("Cycle timed out after 300s — releasing lock")
            return {"status": "error", "reason": "cycle_timeout"}


async def _run_cycle_impl() -> dict:  # noqa: C901
    global _last_compass
    quote = "BNB"

    # ── Read runtime admin config overrides ───────────────────────────────
    bot_cfg   = await get_bot_config()
    if bot_cfg.paused:
        logger.info("Bot is PAUSED by admin — skipping cycle")
        return {"status": "skipped", "reason": "admin_paused"}

    _pos_size_usd = bot_cfg.position_size_usd or config.MAX_POSITION_SIZE_USD
    _min_conf     = bot_cfg.min_confidence    or config.MIN_CONFIDENCE
    _claude_instr = bot_cfg.claude_instruction or None

    # ── Token selection: scan eligible tokens with hysteresis ─────────────
    if config.COMPETITION_MODE and len(config.ELIGIBLE_TOKENS) > 1:
        try:
            scanner    = TokenScanner(config.ELIGIBLE_TOKENS)
            top_tokens = await scanner.scan(top_n=config.TOKEN_SCAN_TOP_N)
            symbol     = top_tokens[0]["symbol"]
            logger.info("[Scanner] Selected token: %s  score=%.3f", symbol, top_tokens[0]["score"])
        except Exception as exc:
            logger.warning("[Scanner] Token scan failed (%s) — falling back to default", exc)
            symbol = config.TRADING_PAIR.split("/")[0].upper()
    else:
        symbol = config.TRADING_PAIR.split("/")[0].upper()

    base = symbol

    # ── Pre-cycle: close any TP/SL hits ──────────────────────────────────
    try:
        await monitor_open_trades()
    except Exception as _mon_exc:
        logger.error("[Cycle] Pre-cycle monitor error (non-fatal): %s", _mon_exc)

    # ── Competition: force-close stale positions ──────────────────────────
    if config.COMPETITION_MODE:
        stale_closed = await force_close_stale_positions()
        if stale_closed:
            logger.info("[Competition] Force-closed %d stale position(s)", stale_closed)

    # ── Position guard: one open BUY at a time ────────────────────────────
    open_buys = await list_open_buy_trades()
    if open_buys:
        logger.info("Position guard: %d open BUY trade(s) — skipping new entry", len(open_buys))
        return _result("skipped", 0, reason="open_position", open_trades=len(open_buys))

    # ── Daily loss guard ──────────────────────────────────────────────────
    today_pnl = await get_today_pnl()
    if today_pnl < -config.MAX_DAILY_LOSS_USD:
        logger.warning(
            "Daily loss limit breached: today_pnl=%.2f  limit=-%.2f",
            today_pnl, config.MAX_DAILY_LOSS_USD,
        )
        return _result("skipped", 0, reason="daily_loss_limit",
                       today_pnl=today_pnl, limit=-config.MAX_DAILY_LOSS_USD)

    # ── Competition: basic drawdown halt ──────────────────────────────────
    if config.COMPETITION_MODE:
        dd_pre = await check_drawdown()
        if dd_pre["halt"]:
            logger.critical(
                "[Competition] Trading HALTED: drawdown=%.1f%%",
                dd_pre["drawdown_pct"],
            )
            return _result("skipped", 0, reason="drawdown_halt",
                           drawdown_pct=dd_pre["drawdown_pct"])

    # ── Daily trade quota — competition requires ≥1 trade/day ─────────────
    # When trades_today == 0 inside the live window, force a trade immediately:
    # override Claude HOLD, skip edge gate + backtest. Escalate further after 23 UTC.
    _force_execute    = False
    _compliance_mode  = "normal"
    if config.COMPETITION_MODE:
        now          = datetime.now(timezone.utc)
        in_window    = COMPETITION_START <= now <= COMPETITION_END
        trades_today = await get_daily_trade_count()
        utc_hour     = now.hour
        if in_window and trades_today == 0:
            _force_execute   = True
            _compliance_mode = "alert"
            logger.warning(
                "[Compliance] Daily trade quota (0 today) — forcing entry, bypassing gates",
            )
            if utc_hour >= 23:
                _compliance_mode = "hard"
                logger.warning(
                    "[Compliance] HARD window (hour=%d UTC) — last-chance force trade",
                    utc_hour,
                )

    run = await create_agent_run()
    strategies_generated = 0
    trades_executed      = 0
    total_pnl            = 0.0
    error_message: str | None = None

    try:
        logger.info("=== AlphaLoop cycle starting  run_id=%d  symbol=%s ===", run.id, symbol)

        # ── 1. Fetch market data ──────────────────────────────────────────
        logger.info("[1/7] Fetching market data…")
        async with CMCClient() as cmc:
            market_data = await cmc.get_quote(symbol)
            ohlcv_data  = await cmc.get_ohlcv(symbol, time_period="daily", count=60)
            try:
                ohlcv_4h = await cmc.get_ohlcv(symbol, time_period="4h", count=100)
            except Exception as exc:
                logger.warning("4h data fetch failed (%s) — continuing without it", exc)
                ohlcv_4h = []
            try:
                global_metrics = await cmc.get_market_metrics()
                btc_dominance  = float(global_metrics.get("btc_dominance", 48.0))
            except Exception as exc:
                logger.warning("Global metrics fetch failed (%s) — btc_dom=48%%", exc)
                btc_dominance = 48.0

        logger.info(
            "Market data: price=%.4f  vol_24h=%.0f  change_24h=%+.2f%%  btc_dom=%.2f%%",
            market_data["price"], market_data["volume_24h"],
            market_data["percent_change_24h"], btc_dominance,
        )

        # ── Equity-reliability guard — skip on bad RPC/API data ───────────
        price = market_data.get("price", 0)
        volume = market_data.get("volume_24h", 0)
        if not price or price <= 0 or not volume or len(ohlcv_data) < 10:
            logger.warning(
                "[Guard] Unreliable market data (price=%.4f, vol=%.0f, candles=%d) — skipping cycle",
                price, volume, len(ohlcv_data),
            )
            await _finish_run(run.id, 0, 0, 0.0, None)
            return _result("skipped", run.id, reason="unreliable_data",
                           price=price, volume=volume, candles=len(ohlcv_data))

        # ── 2. Compute technical indicators ───────────────────────────────
        logger.info("[2/7] Computing technical indicators…")
        df         = _ohlcv_to_dataframe(ohlcv_data)
        df         = compute_indicators(df)
        indicators = extract_last_row(df)

        indicators_4h: dict | None = None
        if ohlcv_4h:
            df_4h         = _ohlcv_to_dataframe(ohlcv_4h)
            df_4h         = compute_indicators(df_4h)
            indicators_4h = extract_4h_context(df_4h)

        logger.info(
            "Daily: RSI=%.2f  MACD_hist=%.6f  BB=[%.2f/%.2f/%.2f]  SMA20=%.2f  SMA50=%.2f",
            indicators["rsi"], indicators["macd_hist"],
            indicators["bb_lower"], indicators["bb_middle"], indicators["bb_upper"],
            indicators["sma_20"], indicators["sma_50"],
        )

        # ── 3. 5-Axis Market Compass ──────────────────────────────────────
        logger.info("[3/7] Computing 5-Axis Market Compass…")
        compass = await MarketCompass().compute(
            symbol=symbol,
            indicators=indicators,
            market_data=market_data,
            btc_dominance=btc_dominance,
            ohlcv_data=ohlcv_data,
        )
        _last_compass      = compass
        compass_profile    = compass["profile"]
        compass_score      = compass["compass_score"]

        # RISK_OFF blocks all trades except hard compliance
        if compass["regime"] == "RISK_OFF" and not _force_execute:
            logger.warning(
                "[Compass] RISK_OFF (score=%.1f) — skipping cycle", compass_score,
            )
            await _finish_run(run.id, 0, 0, 0.0, None)
            return _result("skipped", run.id, reason="risk_off_regime",
                           compass_score=compass_score)

        # Drawdown zone cascade — compass gates applied here (post-compass)
        drawdown_zone: dict = {"zone": "GREEN", "size_multiplier": 1.0, "compass_min": 0}
        if config.COMPETITION_MODE:
            dd_full       = await check_drawdown()
            drawdown_zone = dd_full["zone"]
            if drawdown_zone["zone"] == "ORANGE" and compass_score < 15:
                logger.warning(
                    "[Drawdown] ORANGE zone: compass_score=%.1f < 15 required — skip",
                    compass_score,
                )
                await _finish_run(run.id, 0, 0, 0.0, None)
                return _result("skipped", run.id, reason="orange_zone_low_compass",
                               compass_score=compass_score)
            if drawdown_zone["zone"] == "RED" and compass_score < 35:
                logger.warning(
                    "[Drawdown] RED zone: compass_score=%.1f < 35 required — skip",
                    compass_score,
                )
                await _finish_run(run.id, 0, 0, 0.0, None)
                return _result("skipped", run.id, reason="red_zone_low_compass",
                               compass_score=compass_score)

        # ── 4. Generate strategy via Claude ───────────────────────────────
        logger.info("[4/7] Generating strategy via Claude…")
        async with StrategyGenerator() as gen:
            strategy = await gen.generate(
                symbol, market_data, indicators, indicators_4h,
                _claude_instr, compass=compass,
            )

        strategies_generated = 1
        logger.info(
            "Strategy: action=%s  confidence=%.2f  entry=%.4f  sl=%.4f  tp=%.4f",
            strategy["action"], strategy["confidence"],
            strategy["entry_price"], strategy["stop_loss"], strategy["take_profit"],
        )

        # ── 5. Gate: compliance mode + confidence ─────────────────────────
        _hold_overridden = False
        if _compliance_mode == "hard" and strategy["action"] == "HOLD":
            strategy["action"] = "BUY"
            _hold_overridden = True
            logger.warning("[Compliance] HARD: overriding HOLD → BUY")
        elif _compliance_mode == "alert" and strategy["action"] == "HOLD":
            strategy["action"] = "BUY"
            _hold_overridden = True
            logger.warning("[Compliance] ALERT: overriding HOLD → BUY")

        if _hold_overridden:
            px = float(market_data.get("price", strategy.get("entry_price", 0)))
            strategy["entry_price"] = round(px * 0.995, 4)
            strategy["stop_loss"]   = round(strategy["entry_price"] * 0.96, 4)
            strategy["take_profit"] = round(strategy["entry_price"] * 1.06, 4)
            strategy["confidence"]  = max(strategy.get("confidence", 0.5), 0.55)
            strategy["reasoning"]   = (
                f"[Compliance override: daily trade quota] {strategy.get('reasoning', '')}"
            )

        if strategy["action"] == "HOLD":
            logger.info("Action=HOLD — no trade this cycle")
            # Save HOLD strategy to DB (abstention ledger — every non-trade is recorded)
            try:
                await create_strategy({
                    "symbol":          symbol,
                    "action":          "HOLD",
                    "confidence":      strategy.get("confidence", 0.0),
                    "entry_price":     strategy.get("entry_price", 0.0),
                    "stop_loss":       strategy.get("stop_loss", 0.0),
                    "take_profit":     strategy.get("take_profit", 0.0),
                    "reasoning":       strategy.get("reasoning", "Market conditions unfavorable"),
                    "timeframe":       strategy.get("timeframe", "short"),
                    "risk_level":      strategy.get("risk_level", "low"),
                    "status":          "rejected",
                    "backtest_passed": False,
                })
            except Exception as exc:
                logger.debug("Could not save HOLD strategy: %s", exc)
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="HOLD")

        # Confidence threshold: compliance mode and compass profile both affect it
        if _compliance_mode == "hard":
            min_confidence = 0.25
        elif _compliance_mode == "alert":
            min_confidence = 0.30
        elif _compliance_mode == "soft":
            min_confidence = min(0.45, compass_profile["min_confidence_override"])
        else:
            min_confidence = max(_min_conf, compass_profile["min_confidence_override"])

        if strategy["confidence"] < min_confidence:
            logger.info(
                "Confidence %.2f < %.2f threshold (%s mode) — skipping",
                strategy["confidence"], min_confidence, _compliance_mode,
            )
            try:
                await create_strategy({
                    "symbol":          symbol,
                    "action":          strategy.get("action", "HOLD"),
                    "confidence":      strategy["confidence"],
                    "entry_price":     strategy.get("entry_price", 0.0),
                    "stop_loss":       strategy.get("stop_loss", 0.0),
                    "take_profit":     strategy.get("take_profit", 0.0),
                    "reasoning":       f"[Low confidence: {strategy['confidence']:.0%} < {min_confidence:.0%} threshold] {strategy.get('reasoning', '')}",
                    "timeframe":       strategy.get("timeframe", "short"),
                    "risk_level":      strategy.get("risk_level", "low"),
                    "status":          "rejected",
                    "backtest_passed": False,
                })
            except Exception as exc:
                logger.debug("Could not save low-confidence strategy: %s", exc)
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="low_confidence",
                           confidence=strategy["confidence"],
                           threshold=min_confidence,
                           compliance_mode=_compliance_mode)

        # ── 6. Expected Edge Gate ─────────────────────────────────────────
        if not _force_execute:
            momentum_axis = compass["axes"].get("momentum", 5.0)
            expected_edge = (
                strategy["confidence"] * (momentum_axis / 10.0)
                - config.ROUND_TRIP_COST_PCT
            )
            if expected_edge <= 0:
                logger.info(
                    "[EdgeGate] conf=%.2f × momentum=%.1f/10 − cost=%.1f%% = %.3f%% → SKIP",
                    strategy["confidence"], momentum_axis,
                    config.ROUND_TRIP_COST_PCT * 100, expected_edge * 100,
                )
                await _finish_run(run.id, strategies_generated, 0, 0.0, None)
                return _result("skipped", run.id, reason="edge_gate_failed",
                               expected_edge_pct=round(expected_edge * 100, 3))
            logger.info(
                "[EdgeGate] Edge = %.3f%% — cleared", expected_edge * 100,
            )

        # ── Build proof BEFORE execution (captures decision state) ────────
        proof_ts = int(_time.time())
        proof_string, proof_hash = build_proof(
            unix_ts=proof_ts,
            symbol=symbol,
            compass=compass,
            confidence=strategy["confidence"],
            action=strategy["action"],
            entry_price=strategy["entry_price"],
        )
        logger.info("[Proof] hash=%s", proof_hash[:16] + "…")

        # ── 5. Backtest ───────────────────────────────────────────────────
        logger.info("[5/7] Running backtest on last 30 daily candles…")
        backtest = Backtester().run(ohlcv_data, strategy)
        logger.info("Backtest: %s", backtest["summary"])

        # ── 6. Persist strategy ───────────────────────────────────────────
        db_strategy = await create_strategy({
            "symbol":      symbol,
            "action":      strategy["action"],
            "confidence":  strategy["confidence"],
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

        if not backtest["passed"] and not _force_execute:
            logger.info("Backtest failed — skipping execution")
            await _finish_run(run.id, strategies_generated, 0, 0.0, None)
            return _result("skipped", run.id, reason="backtest_failed",
                           strategy_id=db_strategy.id, backtest=backtest["summary"])
        if not backtest["passed"] and _force_execute:
            logger.warning("[Compliance] HARD/ALERT: backtest failed but force_execute=True — proceeding")

        # ── 7. Execute swap ───────────────────────────────────────────────
        if config.TWAK_REST_URL:
            from execution.twak_executor import TWAKExecutor
            executor = TWAKExecutor()
            logger.info("[6/7] Executing swap via TWAK REST…")
        else:
            wallet   = WalletAgent()
            executor = PancakeSwapExecutor(wallet)
            logger.info("[6/7] Executing swap on PancakeSwap V2…")

        if strategy["action"] == "BUY":
            token_in, token_out = quote, base
        else:
            token_in, token_out = base, quote

        # Position sizing: confidence × compass regime × drawdown zone
        base_position  = _pos_size_usd * max(0.5, min(1.0, strategy["confidence"]))
        compass_mult   = compass_profile.get("max_position_pct", 1.0)
        zone_mult      = drawdown_zone.get("size_multiplier", 1.0)
        position_usd   = round(base_position * compass_mult * zone_mult, 2)
        position_usd   = max(position_usd, 0.01)

        logger.info(
            "[7/7] Position sizing: base=$%.2f × compass(%.0f%%) × zone(%.0f%%) = $%.2f  "
            "[regime=%s  zone=%s]",
            base_position, compass_mult * 100, zone_mult * 100, position_usd,
            compass["regime"], drawdown_zone["zone"],
        )

        swap = await executor.swap(token_in, token_out, position_usd)
        trades_executed = 1

        logger.info(
            "Swap %s: %s %.6f → %s %.6f  price=%.4f  status=%s  tx=%s",
            strategy["action"],
            token_in,  swap["amount_in"],
            token_out, swap["amount_out"],
            swap["price"], swap["status"], swap["tx_hash"],
        )

        pnl_usd, pnl_pct = _compute_pnl(strategy["action"], swap, position_usd)
        total_pnl        = pnl_usd

        trade_status = "executed" if swap["status"] == "success" else swap["status"]
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
            "proof_hash":  proof_hash,
            "proof_string": proof_string,
        })

        # Commit proof on-chain (non-blocking — never delays trade confirmation)
        proof_tx_hash = await commit_proof_onchain(
            trade.id, proof_hash, dry_run=config.DRY_RUN,
        )
        if proof_tx_hash:
            await update_trade_proof(
                trade.id,
                proof_string=proof_string,
                proof_hash=proof_hash,
                proof_tx_hash=proof_tx_hash,
            )

        logger.info(
            "=== Cycle complete  run_id=%d  trade_id=%d  pnl_usd=%+.4f  proof=%s… ===",
            run.id, trade.id, pnl_usd, proof_hash[:12],
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
            compass_score=compass_score,
            regime=compass["regime"],
            drawdown_zone=drawdown_zone["zone"],
            proof_hash=proof_hash,
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
    from datetime import datetime, timezone, timedelta
    first_run = datetime.now(timezone.utc) + timedelta(seconds=30)

    scheduler.add_job(
        run_agent_cycle,
        trigger=IntervalTrigger(minutes=interval_minutes, start_date=first_run),
        id="agent_cycle",
        replace_existing=True,
        max_instances=1,
        next_run_time=first_run,
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
