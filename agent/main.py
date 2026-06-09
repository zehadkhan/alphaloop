"""AlphaLoop FastAPI application."""
from __future__ import annotations

import logging
import logging.config
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from agent.config import config
from agent.scheduler import run_agent_cycle, start_scheduler, stop_scheduler
from db.models import (
    AgentRun,
    Strategy,
    Trade,
    init_db,
    list_agent_runs,
    list_strategies,
    list_trades,
)

# ---------------------------------------------------------------------------
# Logging — timestamps on every line
# ---------------------------------------------------------------------------

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler(interval_minutes=config.CYCLE_INTERVAL_MINUTES)
    logger.info(
        "AlphaLoop started | env=%s | pair=%s | interval=%d min",
        config.ENVIRONMENT, config.TRADING_PAIR, config.CYCLE_INTERVAL_MINUTES,
    )
    yield
    stop_scheduler()
    logger.info("AlphaLoop stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AlphaLoop",
    description="Autonomous BNB/USDT trading agent on BSC testnet",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Serialisers (ORM → plain dict, no Pydantic dependency)
# ---------------------------------------------------------------------------

def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _strategy_dict(s: Strategy) -> dict:
    return {
        "id":               s.id,
        "symbol":           s.symbol,
        "action":           s.action,
        "confidence":       s.confidence,
        "entry_price":      s.entry_price,
        "stop_loss":        s.stop_loss,
        "take_profit":      s.take_profit,
        "reasoning":        s.reasoning,
        "timeframe":        s.timeframe,
        "risk_level":       s.risk_level,
        "backtest_passed":  s.backtest_passed,
        "backtest_return":  s.backtest_return,
        "backtest_win_rate": s.backtest_win_rate,
        "status":           s.status,
        "created_at":       _fmt_dt(s.created_at),
    }


def _trade_dict(t: Trade) -> dict:
    return {
        "id":           t.id,
        "strategy_id":  t.strategy_id,
        "symbol":       t.symbol,
        "action":       t.action,
        "amount_usd":   t.amount_usd,
        "entry_price":  t.entry_price,
        "exit_price":   t.exit_price,
        "pnl_usd":      t.pnl_usd,
        "pnl_percent":  t.pnl_percent,
        "tx_hash":      t.tx_hash,
        "status":       t.status,
        "executed_at":  _fmt_dt(t.executed_at),
        "closed_at":    _fmt_dt(t.closed_at),
    }


def _run_dict(r: AgentRun) -> dict:
    return {
        "id":                    r.id,
        "started_at":            _fmt_dt(r.started_at),
        "completed_at":          _fmt_dt(r.completed_at),
        "strategies_generated":  r.strategies_generated,
        "trades_executed":       r.trades_executed,
        "total_pnl":             r.total_pnl,
        "error_message":         r.error_message,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"])
async def health() -> dict:
    """Liveness check."""
    return {"status": "ok", "environment": config.ENVIRONMENT}


@app.get("/status", tags=["system"])
async def status() -> dict:
    """Return the last completed agent run and next scheduled run."""
    from agent.scheduler import scheduler

    runs = await list_agent_runs(limit=1)
    last_run = _run_dict(runs[0]) if runs else None

    jobs = [
        {
            "id":       j.id,
            "next_run": str(j.next_run_time),
        }
        for j in scheduler.get_jobs()
    ]

    return {
        "environment":    config.ENVIRONMENT,
        "trading_pair":   config.TRADING_PAIR,
        "dry_run":        config.DRY_RUN,
        "max_position_usd": config.MAX_POSITION_SIZE_USD,
        "last_run":       last_run,
        "scheduled_jobs": jobs,
    }


@app.get("/trades", tags=["data"])
async def get_trades(symbol: str | None = None, limit: int = 50) -> dict:
    """List executed trades, newest first."""
    rows = await list_trades(symbol=symbol, limit=limit)
    return {"count": len(rows), "trades": [_trade_dict(t) for t in rows]}


@app.get("/strategies", tags=["data"])
async def get_strategies(
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict:
    """List generated strategies, newest first."""
    rows = await list_strategies(symbol=symbol, status=status, limit=limit)
    return {"count": len(rows), "strategies": [_strategy_dict(s) for s in rows]}


@app.get("/runs", tags=["data"])
async def get_runs(limit: int = 20) -> dict:
    """List all agent runs, newest first."""
    rows = await list_agent_runs(limit=limit)
    return {"count": len(rows), "runs": [_run_dict(r) for r in rows]}


@app.post("/run", tags=["control"])
async def manual_run() -> dict:
    """Manually trigger one agent cycle and wait for the result.

    Returns the cycle summary.  If a cycle is already running, returns
    immediately with status='skipped'.
    """
    logger.info("Manual /run triggered")
    result = await run_agent_cycle()
    status_code = 200 if result["status"] in ("executed", "skipped") else 500
    return JSONResponse(content=result, status_code=status_code)
