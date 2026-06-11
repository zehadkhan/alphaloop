"""AlphaLoop FastAPI application."""
from __future__ import annotations

import logging
import logging.config
import os
from contextlib import asynccontextmanager
from datetime import datetime

# ── SSL fallback: if certifi's CA file is unreadable (e.g., Docker overlay on a
#    full disk returns EIO), patch it to use the system CA bundle instead.
#    This must run before any network imports (httpx, requests, etc.).
def _patch_ssl_if_needed() -> None:
    _sys_ca = "/etc/ssl/certs/ca-certificates.crt"
    try:
        import certifi
        with open(certifi.where(), "rb") as _f:
            _f.read(1)
        return  # certifi is fine
    except OSError:
        pass
    if os.path.exists(_sys_ca):
        os.environ.setdefault("SSL_CERT_FILE", _sys_ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _sys_ca)
        try:
            import certifi
            certifi.where = lambda: _sys_ca  # type: ignore[method-assign]
        except Exception:
            pass

_patch_ssl_if_needed()

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from agent.competition import get_competition_status
from agent.config import config
from agent.scheduler import run_agent_cycle, monitor_open_trades, start_scheduler, stop_scheduler
from db.models import (
    AgentRun,
    Strategy,
    Trade,
    init_db,
    list_agent_runs,
    list_strategies,
    list_trades,
    list_open_buy_trades,
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

async def _register_erc8004() -> None:
    """Register this agent on-chain via BNB Agent SDK ERC-8004.

    Only runs on mainnet in competition mode. Skipped silently on testnet.
    """
    if config.ENVIRONMENT != "mainnet" or not config.COMPETITION_MODE:
        return
    try:
        from bnbagent import ERC8004Agent, EVMWalletProvider, AgentEndpoint
        import os
        password = os.getenv("WALLET_PASSWORD", "alphaloop-default-pw-change-me")
        private_key = os.getenv("AGENT_PRIVATE_KEY") or None
        provider = EVMWalletProvider(password=password, private_key=private_key, persist=True)
        agent = ERC8004Agent(provider, network="bsc-mainnet")
        endpoint = AgentEndpoint(
            name="AlphaLoop",
            endpoint=os.getenv("AGENT_PUBLIC_URL", "https://alphaloop.local/erc8183"),
            version="1.0.0",
            capabilities=["trading", "strategy", "x402"],
        )
        logger.info("Registering agent on-chain (ERC-8004) …")
        result = await agent.register_agent(endpoint)
        logger.info("ERC-8004 registration: %s", result)
    except Exception as exc:
        logger.warning("ERC-8004 registration skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_scheduler(interval_minutes=config.CYCLE_INTERVAL_MINUTES)
    await _register_erc8004()
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
    """Liveness check — also returns live BNB price."""
    from agent.scheduler import _get_bnb_price
    bnb_price = await _get_bnb_price()
    return {"status": "ok", "environment": config.ENVIRONMENT, "bnb_price": bnb_price}


@app.get("/status", tags=["system"])
async def status() -> dict:
    """Return the last completed agent run and next scheduled run."""
    from agent.scheduler import scheduler

    runs = await list_agent_runs(limit=1)
    last_run = _run_dict(runs[0]) if runs else None

    open_positions = await list_open_buy_trades()

    jobs = [
        {
            "id":       j.id,
            "next_run": str(j.next_run_time),
        }
        for j in scheduler.get_jobs()
    ]

    return {
        "environment":       config.ENVIRONMENT,
        "trading_pair":      config.TRADING_PAIR,
        "dry_run":           config.DRY_RUN,
        "max_position_usd":  config.MAX_POSITION_SIZE_USD,
        "open_positions":    len(open_positions),
        "competition_mode":  config.COMPETITION_MODE,
        "signing_backend":   "twak" if config.TWAK_REST_URL else "web3",
        "last_run":          last_run,
        "scheduled_jobs":    jobs,
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


@app.post("/monitor", tags=["control"])
async def manual_monitor() -> dict:
    """Manually trigger the trade lifecycle monitor.

    Checks all open BUY positions against their TP/SL using the current
    market price and closes any that have been triggered.
    """
    logger.info("Manual /monitor triggered")
    result = await monitor_open_trades()
    return JSONResponse(content=result, status_code=200)


@app.get("/competition/status", tags=["competition"])
async def competition_status() -> dict:
    """Return competition guardrail status: drawdown, daily trade count, stale positions."""
    from agent.scheduler import _get_bnb_price
    price = await _get_bnb_price()
    result = await get_competition_status(current_price=price)
    return JSONResponse(content=result, status_code=200)


@app.post("/competition/register", tags=["competition"])
async def competition_register() -> dict:
    """Trigger on-chain registration via TWAK CLI.

    Must be run once before the live trading window (before June 22).
    """
    from execution.twak_executor import TWAKExecutor
    logger.info("On-chain competition registration triggered")
    executor = TWAKExecutor()
    try:
        result = await executor.competition_register()
        return JSONResponse(content=result, status_code=200)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)


@app.get("/twak/status", tags=["competition"])
async def twak_status() -> dict:
    """TWAK signing backend status and autonomous mode guardrail config."""
    from execution.twak_executor import TWAKExecutor, TWAKExecutorError
    online = bool(config.TWAK_REST_URL)
    reg = {}
    balance = {}
    wallet_address = None
    if online:
        try:
            executor = TWAKExecutor()
            wallet_address = await executor.init_address()
            reg = await executor.competition_status()
        except TWAKExecutorError as exc:
            reg = {"ok": False, "error": str(exc)}
        except Exception:
            reg = {"ok": False, "error": "twak_not_reachable"}
        try:
            price = await executor.get_price("BNB", "USDT") if online else 0
            balance = {"BNB": {"price_usdt": round(price, 2)}}
        except Exception:
            balance = {}
    return {
        "twak_configured":  online,
        "twak_url":         config.TWAK_REST_URL or None,
        "wallet_name":      config.TWAK_WALLET_NAME,
        "wallet_address":   wallet_address,
        "registration":     reg,
        "balance":          balance,
        "guardrails": {
            "max_position_usd":       config.MAX_POSITION_SIZE_USD,
            "max_daily_loss_usd":     config.MAX_DAILY_LOSS_USD,
            "max_drawdown_pct":       config.MAX_DRAWDOWN_PCT,
            "max_position_hold_hours": config.MAX_POSITION_HOLD_HOURS,
            "eligible_tokens":        config.ELIGIBLE_TOKENS,
        },
    }


@app.post("/competition/scan", tags=["competition"])
async def token_scan() -> dict:
    """Run the token scanner and return top momentum tokens right now."""
    from data.token_scanner import TokenScanner
    scanner = TokenScanner(config.ELIGIBLE_TOKENS)
    top = await scanner.scan(top_n=config.TOKEN_SCAN_TOP_N)
    return {"top_tokens": top, "scanned": len(config.ELIGIBLE_TOKENS)}
