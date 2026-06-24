"""Agent orchestration: one cycle + APScheduler wiring."""
from __future__ import annotations

import asyncio
import json
import logging
import os
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
from agent.portfolio import cap_position_usd
from agent.pricing import round_price
from agent.routing import build_candidate_symbols, pick_routable_symbol
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
    list_open_trades,
    get_today_pnl,
    get_daily_trade_count,
    get_last_trade_time,
    get_bot_config,
    save_token_scans,
    save_performance_snapshot,
    get_trade_stats,
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

from agent.blacklist import auto_blacklist, load_persisted_blacklist
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
    """Check every open position against TP/SL and 4h timeout, close if triggered."""
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

    now = datetime.now(timezone.utc)
    closed_count = 0
    close_details = []

    for trade in trades:
        current_price = prices.get(trade.symbol)
        if current_price is None:
            logger.warning("[Monitor] No price for %s — skipping trade %d", trade.symbol, trade.id)
            continue

        strategy = trade.strategy

        exit_price: float | None = None
        close_reason: str | None = None

        # ── TP/SL check ───────────────────────────────────────────────
        if strategy is not None:
            tp = strategy.take_profit
            sl = strategy.stop_loss
            if trade.action == "BUY":
                if current_price >= tp:
                    exit_price, close_reason = tp, "TP"
                elif current_price <= sl:
                    exit_price, close_reason = sl, "SL"
            else:  # SELL position
                if current_price <= tp:
                    exit_price, close_reason = tp, "TP"
                elif current_price >= sl:
                    exit_price, close_reason = sl, "SL"

        # ── Timeout check (4-hour auto-close) ─────────────────────────
        if exit_price is None and trade.executed_at:
            ea = trade.executed_at if trade.executed_at.tzinfo else trade.executed_at.replace(tzinfo=timezone.utc)
            age_hours = (now - ea).total_seconds() / 3600
            if age_hours >= config.MAX_POSITION_HOLD_HOURS:
                exit_price  = current_price
                close_reason = "timeout"
                logger.info(
                    "[Monitor] Timeout: trade id=%d  %s  age=%.1fh  exit=%.4f",
                    trade.id, trade.symbol, age_hours, exit_price,
                )

        if exit_price is not None:
            # Execute real on-chain SELL for executed BUY positions
            actual_exit_price = exit_price
            sell_tx_hash: str | None = None
            if (
                trade.action == "BUY"
                and trade.status == "executed"
                and not config.DRY_RUN
                and config.TWAK_REST_URL
            ):
                try:
                    from execution.twak_executor import TWAKExecutor
                    sell_executor = TWAKExecutor()
                    # Estimate current token value in USD
                    sell_value_usd = (
                        round(current_price * (trade.amount_usd / trade.entry_price), 4)
                        if trade.entry_price and trade.entry_price > 0
                        else round(trade.amount_usd, 4)
                    )
                    sell_value_usd = max(sell_value_usd, 0.01)
                    logger.info(
                        "[Monitor] Executing SELL swap: %s → BNB  ~$%.2f  reason=%s",
                        trade.symbol, sell_value_usd, close_reason,
                    )
                    sell_swap = await sell_executor.swap(trade.symbol, "BNB", sell_value_usd)
                    sell_tx_hash = sell_swap.get("tx_hash")
                    if sell_swap.get("price") and sell_swap["price"] > 0:
                        actual_exit_price = sell_swap["price"]
                    logger.info(
                        "[Monitor] SELL executed: tx=%s  exit_price=%.8f",
                        sell_tx_hash, actual_exit_price,
                    )
                except Exception as sell_exc:
                    logger.error(
                        "[Monitor] SELL swap failed for trade %d (%s): %s — closing DB only",
                        trade.id, trade.symbol, sell_exc,
                    )

            await close_trade(
                trade.id,
                exit_price=round_price(actual_exit_price),
                tx_hash=sell_tx_hash,
                close_reason=close_reason,
            )
            pnl_pct = 0.0
            if trade.entry_price and trade.entry_price > 0:
                pnl_pct = (actual_exit_price / trade.entry_price - 1) * 100
                if trade.action == "SELL":
                    pnl_pct = -pnl_pct
            logger.info(
                "[Monitor] Closed trade id=%d  reason=%s  entry=%.4f → exit=%.4f  pnl=%+.2f%%",
                trade.id, close_reason, trade.entry_price, actual_exit_price, pnl_pct,
            )
            closed_count += 1
            close_details.append({"trade_id": trade.id, "reason": close_reason, "pnl_pct": round(pnl_pct, 3)})

    price_summary = {s: round(p, 4) for s, p in prices.items()}
    logger.info("[Monitor] Checked %d open trade(s), closed %d  prices=%s",
                len(trades), closed_count, price_summary)
    return {"checked": len(trades), "closed": closed_count, "prices": price_summary,
            "close_details": close_details}


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
    quote = "BNB"   # wallet holds BNB; PancakeSwap routes BNB↔token on BSC

    # ── Read runtime admin config overrides ───────────────────────────────
    bot_cfg   = await get_bot_config()
    if bot_cfg.paused:
        logger.info("Bot is PAUSED by admin — skipping cycle")
        return {"status": "skipped", "reason": "admin_paused"}

    _pos_size_usd = bot_cfg.position_size_usd or config.MAX_POSITION_SIZE_USD
    _min_conf     = bot_cfg.min_confidence    or config.MIN_CONFIDENCE
    _claude_instr = bot_cfg.claude_instruction or None

    # ── Token selection: scan all eligible tokens, pick top 3 ────────────
    top_tokens: list[dict] = []
    scanner_data_by_symbol: dict[str, dict] = {}
    if config.COMPETITION_MODE and len(config.ELIGIBLE_TOKENS) > 1:
        try:
            scanner    = TokenScanner(config.ELIGIBLE_TOKENS)
            top_tokens = await scanner.scan(top_n=10)
            # Remove blacklisted tokens before selection
            top_tokens = [t for t in top_tokens if t["symbol"] not in config.TWAK_BLACKLIST]
            for t in top_tokens:
                scanner_data_by_symbol[t["symbol"]] = t
            # Scan results saved to DB after agent_run is created below
            logger.info(
                "[Scanner] Top 3: %s",
                ", ".join(f"{t['symbol']}({t['score']:.2f})" for t in top_tokens[:3]),
            )
        except Exception as exc:
            logger.warning("[Scanner] Token scan failed (%s) — falling back to default", exc)
    if not top_tokens:
        default = config.TRADING_PAIR.split("/")[0].upper()
        top_tokens = [{"symbol": default, "score": 0.5}]

    # Determine which tokens we can trade this cycle
    open_trades = await list_open_trades()
    open_symbols = {t.symbol for t in open_trades}
    open_count   = len(open_trades)

    # Daily trade quota — checked early so symbol selection can prioritize routable staples
    _force_execute    = False
    _compliance_mode  = "normal"
    _fear_size_mult   = 1.0
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

    candidates = build_candidate_symbols(
        top_tokens, open_symbols, compliance=_force_execute,
    )
    if not candidates:
        logger.info("No trade candidates after blacklist/open-position filter — skipping")
        return _result("skipped", 0, reason="no_available_token")

    symbol, route_reason, route_failures = await pick_routable_symbol(candidates, action="BUY")
    for sym, err in route_failures:
        auto_blacklist(sym, err)
    if not symbol:
        logger.warning("[RouteCheck] No routable token in %d candidates — skipping", len(candidates))
        return _result("skipped", 0, reason="unroutable_token", error=route_reason)

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

    # ── Position guard: max MAX_CONCURRENT_POSITIONS open at once ────────
    if open_count >= config.MAX_CONCURRENT_POSITIONS:
        logger.info(
            "Position guard: %d/%d positions full — skipping new entry",
            open_count, config.MAX_CONCURRENT_POSITIONS,
        )
        return _result("skipped", 0, reason="max_positions_reached",
                       open_trades=open_count, max=config.MAX_CONCURRENT_POSITIONS)

    if symbol in open_symbols:
        logger.info("Position guard: already holding %s — skipping", symbol)
        return _result("skipped", 0, reason="token_already_held", symbol=symbol)

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

    # ── Daily trade quota flags set above (before routable symbol pick) ───

    run = await create_agent_run()
    strategies_generated = 0
    trades_executed      = 0
    total_pnl            = 0.0
    error_message: str | None = None

    # Persist scanner results to DB now that we have a run_id
    if top_tokens:
        try:
            await save_token_scans(run.id, top_tokens)
        except Exception as _scan_save_exc:
            logger.debug("[Scanner] Failed to save scan results: %s", _scan_save_exc)

    try:
        logger.info("=== AlphaLoop cycle starting  run_id=%d  symbol=%s ===", run.id, symbol)

        # ── 0. Market quality gates (skip expensive API calls if market bad) ──
        if not _force_execute:
            from data.sentiment import get_fear_greed, get_btc_4h_trend, get_token_7d_change
            fg, btc, token_7d = await asyncio.gather(
                get_fear_greed(),
                get_btc_4h_trend(),
                get_token_7d_change(symbol),
            )

            # Gate 1: Fear & Greed — extreme fear or extreme greed
            if fg["value"] < 25:
                if config.COMPETITION_MODE:
                    _fear_size_mult = 0.5
                    logger.info(
                        "[Gate1] Fear&Greed=%d (Extreme Fear) — competition mode: "
                        "reducing size to 50%%, continuing",
                        fg["value"],
                    )
                else:
                    logger.info("[Gate1] Fear&Greed=%d (Extreme Fear) — market panic, skip", fg["value"])
                    await _finish_run(run.id, 0, 0, 0.0, f"skip:extreme_fear:{fg['value']}")
                    return _result("skipped", run.id, reason="extreme_fear", fear_greed=fg["value"])
            if fg["value"] > 85:
                if config.COMPETITION_MODE:
                    _fear_size_mult = 0.5
                    logger.info(
                        "[Gate1] Fear&Greed=%d (Extreme Greed) — competition mode: "
                        "reducing size to 50%%, continuing",
                        fg["value"],
                    )
                else:
                    logger.info("[Gate1] Fear&Greed=%d (Extreme Greed) — bubble risk, skip", fg["value"])
                    await _finish_run(run.id, 0, 0, 0.0, f"skip:extreme_greed:{fg['value']}")
                    return _result("skipped", run.id, reason="extreme_greed", fear_greed=fg["value"])

            # Gate 2: BTC 4h trend — if BTC in heavy downtrend, everything follows
            if not btc["uptrend"]:
                logger.info(
                    "[Gate2] BTC 4h downtrend (80h=%+.1f%%, above_sma10=%s) — skip",
                    btc["change_pct"], btc["above_sma10"],
                )
                await _finish_run(run.id, 0, 0, 0.0, f"skip:btc_downtrend:{btc['change_pct']:.1f}")
                return _result("skipped", run.id, reason="btc_downtrend",
                               btc_change_pct=btc["change_pct"])

            # Gate 3: Token 7-day performance — heavily falling token → skip
            if token_7d < -20:
                logger.info("[Gate3] %s down %.1f%% in 7d — weak token, skip", symbol, token_7d)
                await _finish_run(run.id, 0, 0, 0.0, f"skip:token_weak_7d:{symbol}:{token_7d:.1f}")
                return _result("skipped", run.id, reason="token_weak_7d",
                               symbol=symbol, change_7d=token_7d)

            logger.info(
                "[Gates] PASS — F&G=%d (%s)  BTC_80h=%+.1f%%  %s_7d=%+.1f%%",
                fg["value"], fg["label"], btc["change_pct"], symbol, token_7d,
            )
        else:
            fg = {"value": 50, "label": "Neutral"}
            btc = {"uptrend": True, "change_pct": 0.0}
            token_7d = 0.0

        # ── 1. Fetch market data ──────────────────────────────────────────
        logger.info("[1/7] Fetching market data…")
        async with CMCClient() as cmc:
            market_data = await cmc.get_quote(symbol)
            try:
                ohlcv_data = await cmc.get_ohlcv(symbol, time_period="daily", count=60)
            except RuntimeError as exc:
                logger.warning("[Data] Daily OHLCV failed for %s (%s) — skipping token", symbol, exc)
                await _finish_run(run.id, 0, 0, 0.0, f"ohlcv_failed:{symbol}")
                return _result("skipped", run.id, reason="ohlcv_unavailable", symbol=symbol)
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

        # RISK_OFF blocks all trades in scalping mode too (extreme stress)
        if compass["regime"] == "RISK_OFF" and not _force_execute:
            logger.warning(
                "[Compass] RISK_OFF (score=%.1f) — skipping cycle", compass_score,
            )
            await _finish_run(run.id, 0, 0, 0.0, None)
            return _result("skipped", run.id, reason="risk_off_regime",
                           compass_score=compass_score)

        # Drawdown zone cascade — position sizing only, no compass score gate in scalping mode
        drawdown_zone: dict = {"zone": "GREEN", "size_multiplier": 1.0, "compass_min": 0}
        if config.COMPETITION_MODE:
            dd_full       = await check_drawdown()
            drawdown_zone = dd_full["zone"]
            # Halt at HALT zone only — removed per-zone compass score gates for scalping

        # ── 4. Generate strategy via Claude ───────────────────────────────
        logger.info("[4/7] Generating strategy via Claude…")
        scanner_ctx = scanner_data_by_symbol.get(symbol)
        # Attach sentiment data so Claude factors it into confidence
        sentiment_ctx = {
            "fear_greed_value": fg["value"],
            "fear_greed_label": fg["label"],
            "btc_80h_change":   btc["change_pct"],
            "btc_uptrend":      btc["uptrend"],
            "token_7d_change":  token_7d,
        }
        async with StrategyGenerator() as gen:
            strategy = await gen.generate(
                symbol, market_data, indicators, indicators_4h,
                _claude_instr, compass=compass, scanner_data=scanner_ctx,
                sentiment=sentiment_ctx,
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
            strategy["entry_price"] = round(px * 0.999, 4)
            strategy["stop_loss"]   = round(strategy["entry_price"] * 0.990, 4)
            strategy["take_profit"] = round(strategy["entry_price"] * 1.020, 4)
            strategy["confidence"]  = max(strategy.get("confidence", 0.5), 0.50)
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

        # Scalping mode: lower confidence floor, no compass profile override
        if _compliance_mode == "hard":
            min_confidence = 0.25
        elif _compliance_mode in ("alert", "soft"):
            min_confidence = 0.30
        else:
            min_confidence = _min_conf  # uses config.MIN_CONFIDENCE = 0.45

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
            await executor.init_address()
            logger.info("[6/7] Executing swap via TWAK REST…")
        else:
            wallet   = WalletAgent()
            executor = PancakeSwapExecutor(wallet)
            logger.info("[6/7] Executing swap on PancakeSwap V2…")

        if strategy["action"] == "BUY":
            token_in, token_out = quote, base
        else:
            # SELL on a DEX = closing an existing long position.
            # If we have no open BUY position for this token, we can't short it.
            has_long = any(t.symbol == symbol and t.action == "BUY" for t in open_trades)
            if not has_long:
                logger.info(
                    "SELL signal for %s but no open long position — cannot short on DEX, skipping",
                    symbol,
                )
                await _finish_run(run.id, strategies_generated, 0, 0.0, None)
                return _result("skipped", run.id, reason="no_long_to_sell", symbol=symbol)
            token_in, token_out = base, quote

        # Position sizing: confidence × compass regime × drawdown zone × fear multiplier
        base_position  = _pos_size_usd * max(0.5, min(1.0, strategy["confidence"]))
        compass_mult   = compass_profile.get("max_position_pct", 1.0)
        zone_mult      = drawdown_zone.get("size_multiplier", 1.0)
        position_usd   = round(base_position * compass_mult * zone_mult * _fear_size_mult, 2)
        position_usd   = max(position_usd, config.MIN_SWAP_USD)

        if config.COMPETITION_MODE and config.TWAK_REST_URL:
            try:
                position_usd = await cap_position_usd(
                    position_usd, executor.address or config.AGENT_WALLET_ADDRESS or None,
                )
            except Exception as cap_exc:
                logger.debug("[Sizing] Portfolio cap skipped: %s", cap_exc)

        position_usd = max(position_usd, config.MIN_SWAP_USD)

        logger.info(
            "[7/7] Position sizing: base=$%.2f × compass(%.0f%%) × zone(%.0f%%) = $%.2f  "
            "[regime=%s  zone=%s]",
            base_position, compass_mult * 100, zone_mult * 100, position_usd,
            compass["regime"], drawdown_zone["zone"],
        )

        # Route already verified at cycle start; re-check only if executor was recreated
        if config.TWAK_REST_URL and hasattr(executor, "test_route"):
            route_ok, route_err = await executor.test_route(base, action=strategy["action"])
            if not route_ok:
                auto_blacklist(symbol, route_err)
                logger.warning("[RouteCheck] %s unroutable at execution — blacklisted.", symbol)
                await _finish_run(run.id, strategies_generated, 0, 0.0, f"skip:unroutable_token:{symbol}")
                return _result("skipped", run.id, reason="unroutable_token",
                               symbol=symbol, error=route_err)
            logger.info("[RouteCheck] %s route OK (%s)", symbol, strategy["action"])

        try:
            swap = await executor.swap(token_in, token_out, position_usd)
        except Exception as swap_exc:
            err_msg = f"{type(swap_exc).__name__}: {swap_exc}"
            logger.error("[Swap] Failed for %s: %s", symbol, err_msg)
            # Auto-blacklist tokens with routing errors so we never retry them
            unroutable_signals = (
                "TOKEN_NOT_FOUND", "APPROVAL_SENT_SWAP_FAILED",
                "VALIDATION_ERROR", "400 Bad Request",
                "no route", "NO_ROUTE", "No route",
            )
            if any(sig in err_msg for sig in unroutable_signals):
                auto_blacklist(symbol, err_msg[:120])
            await create_trade({
                "strategy_id": db_strategy.id,
                "symbol":      symbol,
                "action":      strategy["action"],
                "amount_usd":  position_usd,
                "entry_price": strategy["entry_price"],
                "tx_hash":     None,
                "status":      "failed",
                "executed_at": datetime.now(timezone.utc),
                "proof_hash":  proof_hash,
                "proof_string": proof_string,
            })
            await _finish_run(run.id, strategies_generated, 0, 0.0, err_msg)
            return _result("skipped", run.id, reason="swap_failed", error=err_msg,
                           symbol=symbol, action=strategy["action"])

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

async def _take_performance_snapshot() -> None:
    """Hourly snapshot of portfolio state for equity curve."""
    try:
        from db.models import get_today_pnl as _get_pnl, get_trade_stats as _get_stats
        open_trades = await list_open_buy_trades()
        realized    = await _get_pnl()
        stats       = await _get_stats()
        await save_performance_snapshot(
            portfolio_value_usd=config.INITIAL_PORTFOLIO_USD + realized,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=0.0,
            open_positions=len(open_trades),
            total_trades=stats["total_trades"],
            win_count=stats["win_count"],
            loss_count=stats["loss_count"],
        )
        logger.info("[Snapshot] Portfolio=%.2f  realized=%+.2f  open=%d",
                    config.INITIAL_PORTFOLIO_USD + realized, realized, len(open_trades))
    except Exception as exc:
        logger.error("[Snapshot] Failed: %s", exc)


def start_scheduler(interval_minutes: int = 15) -> None:
    from datetime import datetime, timezone, timedelta
    load_persisted_blacklist()
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
    scheduler.add_job(
        _take_performance_snapshot,
        trigger=IntervalTrigger(minutes=config.SNAPSHOT_INTERVAL_MINUTES),
        id="performance_snapshot",
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
