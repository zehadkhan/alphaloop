"""Competition-mode guardrails for the BNB Hack hackathon (June 22–28).

Rules enforced here:
  1. Portfolio drawdown ≥ MAX_DRAWDOWN_PCT → halt all trading (DQ threshold is 30%)
  2. Position open > MAX_POSITION_HOLD_HOURS → force-close to ensure daily trade activity
  3. get_competition_status() → full status dict for /competition/status endpoint
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from agent.config import config
from db.models import (
    close_trade,
    get_daily_trade_count,
    get_today_pnl,
    list_open_buy_trades,
)

logger = logging.getLogger(__name__)

COMPETITION_START = datetime(2026, 6, 22, 0, 0, 0, tzinfo=timezone.utc)
COMPETITION_END   = datetime(2026, 6, 28, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Drawdown check
# ---------------------------------------------------------------------------

async def check_drawdown(current_price: float | None = None) -> dict:
    """Return drawdown status. If drawdown ≥ MAX_DRAWDOWN_PCT, halt=True."""
    today_pnl = await get_today_pnl()

    # Unrealized loss from open positions
    unrealized = 0.0
    if current_price is not None:
        open_trades = await list_open_buy_trades()
        for t in open_trades:
            unrealized += (current_price / t.entry_price - 1) * t.amount_usd

    # Realized + unrealized loss as fraction of initial portfolio
    total_loss = min(0.0, today_pnl + unrealized)   # only losses count
    drawdown_pct = abs(total_loss) / config.INITIAL_PORTFOLIO_USD * 100

    halt = drawdown_pct >= config.MAX_DRAWDOWN_PCT
    if halt:
        logger.critical(
            "[Competition] DRAWDOWN HALT: %.1f%% ≥ %.1f%%  (DQ threshold=30%%)",
            drawdown_pct, config.MAX_DRAWDOWN_PCT,
        )
    return {
        "drawdown_pct": round(drawdown_pct, 2),
        "halt": halt,
        "today_pnl": round(today_pnl, 4),
        "unrealized": round(unrealized, 4),
        "limit_pct": config.MAX_DRAWDOWN_PCT,
    }


# ---------------------------------------------------------------------------
# Force-close stale positions
# ---------------------------------------------------------------------------

async def force_close_stale_positions() -> int:
    """Close any BUY position open longer than MAX_POSITION_HOLD_HOURS.

    Returns the number of positions force-closed.
    """
    if not config.COMPETITION_MODE:
        return 0

    open_trades = await list_open_buy_trades()
    if not open_trades:
        return 0

    now = datetime.now(timezone.utc)
    max_age = timedelta(hours=config.MAX_POSITION_HOLD_HOURS)

    # Only fetch prices for stale trades (avoids unnecessary API calls)
    # DB timestamps are naive UTC; add tzinfo before comparing to timezone-aware now
    def _age(t) -> timedelta:
        ts = t.executed_at.replace(tzinfo=timezone.utc) if t.executed_at.tzinfo is None else t.executed_at
        return now - ts

    stale = [t for t in open_trades if t.executed_at and _age(t) >= max_age]
    if not stale:
        return 0

    from agent.scheduler import _get_token_price
    closed = 0
    for trade in stale:
        current_price = await _get_token_price(trade.symbol)
        if current_price is None:
            logger.warning("[Competition] Cannot fetch price for %s — skipping force-close of trade %d",
                           trade.symbol, trade.id)
            continue

        age = _age(trade)
        await close_trade(trade.id, exit_price=round(current_price, 4))
        pnl_pct = (current_price / trade.entry_price - 1) * 100
        logger.info(
            "[Competition] Force-closed stale trade id=%d  symbol=%s  age=%.1fh  pnl=%+.2f%%",
            trade.id, trade.symbol, age.total_seconds() / 3600, pnl_pct,
        )
        closed += 1

    return closed


# ---------------------------------------------------------------------------
# Competition status summary
# ---------------------------------------------------------------------------

async def get_competition_status(current_price: float | None = None) -> dict:
    """Return a comprehensive competition status dict."""
    now = datetime.now(timezone.utc)

    in_window = COMPETITION_START <= now <= COMPETITION_END
    days_remaining = max(0, (COMPETITION_END - now).days) if in_window else 0

    trades_today = await get_daily_trade_count()
    drawdown = await check_drawdown(current_price)

    open_trades = await list_open_buy_trades()
    stale = []
    if open_trades:
        max_age = timedelta(hours=config.MAX_POSITION_HOLD_HOURS)
        for t in open_trades:
            if not t.executed_at:
                continue
            ts = t.executed_at.replace(tzinfo=timezone.utc) if t.executed_at.tzinfo is None else t.executed_at
            if (now - ts) >= max_age:
                stale.append(t.id)

    min_trades_met = trades_today >= 1

    return {
        "competition_mode": config.COMPETITION_MODE,
        "in_trading_window": in_window,
        "days_remaining": days_remaining,
        "trades_today": trades_today,
        "min_trades_met": min_trades_met,
        "drawdown_pct": drawdown["drawdown_pct"],
        "drawdown_halt": drawdown["halt"],
        "today_pnl": drawdown["today_pnl"],
        "open_positions": len(open_trades),
        "stale_positions": stale,
        "initial_portfolio_usd": config.INITIAL_PORTFOLIO_USD,
    }
