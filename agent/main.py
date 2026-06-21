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

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse

from agent.competition import get_competition_status
from agent.config import config
from agent.scheduler import run_agent_cycle, monitor_open_trades, start_scheduler, stop_scheduler
from db.models import (
    AgentRun,
    BotConfig,
    Strategy,
    Trade,
    init_db,
    list_agent_runs,
    list_strategies,
    list_trades,
    list_open_buy_trades,
    get_bot_config,
    update_bot_config,
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
        from bnbagent import ERC8004Agent, EVMWalletProvider
        import os
        password   = os.getenv("WALLET_PASSWORD", "alphaloop-default-pw-change-me")
        private_key = os.getenv("AGENT_PRIVATE_KEY") or None
        provider   = EVMWalletProvider(password=password, private_key=private_key, persist=True)
        agent      = ERC8004Agent(provider, network="bsc-mainnet")
        agent_uri  = os.getenv("AGENT_PUBLIC_URL", "https://alphaloop.local/erc8183")
        metadata   = [
            {"name": "AlphaLoop"},
            {"version": "1.0.0"},
            {"capabilities": "trading,strategy,x402"},
        ]
        logger.info("Registering agent on-chain (ERC-8004)  uri=%s …", agent_uri)
        result = await agent.register_agent(agent_uri, metadata)
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


def _config_dict(c: BotConfig) -> dict:
    import json as _json
    tokens = None
    if c.eligible_tokens_json:
        try:
            tokens = _json.loads(c.eligible_tokens_json)
        except Exception:
            tokens = None
    return {
        "paused":                    c.paused,
        "position_size_usd":         c.position_size_usd,
        "min_confidence":            c.min_confidence,
        "claude_instruction":        c.claude_instruction,
        "eligible_tokens":           tokens,
        "monitor_interval_minutes":  c.monitor_interval_minutes,
        "updated_at":                _fmt_dt(c.updated_at),
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

    from agent.scheduler import _last_compass
    compass_summary: dict | None = None
    if _last_compass:
        compass_summary = {
            "compass_score": _last_compass.get("compass_score"),
            "regime":        _last_compass.get("regime"),
            "axes":          _last_compass.get("axes"),
        }

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
        "compass":           compass_summary,
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


# ---------------------------------------------------------------------------
# Activity feed helpers
# ---------------------------------------------------------------------------

def _ensure_aware(dt: datetime | None) -> datetime | None:
    from datetime import timezone as _tz
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)


def _activity_item(run: AgentRun, strategies: list, trades: list) -> dict:
    base: dict = {
        "id": run.id,
        "time": _fmt_dt(run.started_at),
        "duration_s": None,
    }
    if run.started_at and run.completed_at:
        try:
            base["duration_s"] = round(
                (_ensure_aware(run.completed_at) - _ensure_aware(run.started_at)).total_seconds()  # type: ignore[operator]
            )
        except Exception:
            pass

    if run.error_message:
        return {**base, "type": "error", "color": "red",
                "title": "System error — the cycle could not complete",
                "detail": run.error_message[:300], "reasoning": None}

    if not run.completed_at:
        return {**base, "type": "running", "color": "blue",
                "title": "Cycle in progress…", "detail": None, "reasoning": None}

    if not strategies and not trades:
        return {**base, "type": "skipped", "color": "gray",
                "title": "Skipped — already holding an open position",
                "detail": "The bot only opens one trade at a time. It waited for the current position to close before looking for a new one.",
                "reasoning": None}

    buy_strats   = [s for s in strategies if s.action == "BUY"]
    hold_strats  = [s for s in strategies if s.action == "HOLD"]
    approved     = [s for s in buy_strats  if s.status == "approved"]
    rejected_bt  = [s for s in buy_strats  if s.status == "rejected"]

    if trades and approved:
        s = approved[0]
        t = trades[0]
        conf_pct = round(s.confidence * 100)
        return {
            **base,
            "type": "trade",
            "color": "green",
            "title": f"Claude bought ${t.amount_usd:.2f} of {s.symbol} at ${s.entry_price:,.2f}",
            "detail": (
                f"Confidence {conf_pct}% · "
                f"Stop-loss ${s.stop_loss:,.2f} · "
                f"Take-profit ${s.take_profit:,.2f} · "
                f"Risk: {s.risk_level}"
            ),
            "reasoning": s.reasoning[:500] if s.reasoning else None,
            "symbol": s.symbol,
            "entry_price": s.entry_price,
            "take_profit": s.take_profit,
            "stop_loss": s.stop_loss,
            "confidence": s.confidence,
        }

    if hold_strats:
        s = hold_strats[0]
        conf_pct = round(s.confidence * 100)
        return {
            **base,
            "type": "hold",
            "color": "yellow",
            "title": f"Claude analyzed {s.symbol} and decided to wait — no clear signal yet",
            "detail": f"Confidence only {conf_pct}% — needs to be higher before placing a trade",
            "reasoning": s.reasoning[:500] if s.reasoning else None,
            "symbol": s.symbol,
        }

    if rejected_bt:
        s = rejected_bt[0]
        if s.backtest_return is not None and s.backtest_win_rate is not None:
            detail = (
                f"Backtest showed {s.backtest_return:.1f}% return "
                f"with {s.backtest_win_rate * 100:.0f}% win rate — below the required threshold"
            )
        else:
            detail = "The idea did not pass the historical performance test"
        return {
            **base,
            "type": "rejected",
            "color": "orange",
            "title": f"Claude's {s.symbol} idea was tested and rejected — historical results too weak",
            "detail": detail,
            "reasoning": s.reasoning[:500] if s.reasoning else None,
            "symbol": s.symbol,
        }

    return {
        **base,
        "type": "completed",
        "color": "gray",
        "title": f"Cycle completed — {run.strategies_generated} ideas analyzed, {run.trades_executed} trades placed",
        "detail": None,
        "reasoning": None,
    }


@app.get("/activity", tags=["data"])
async def get_activity(limit: int = 20) -> dict:
    """Plain-English summary of recent agent cycles — designed for non-traders."""
    from datetime import timezone as _tz
    from db.models import SessionLocal
    from sqlalchemy import select as _select

    runs = await list_agent_runs(limit=limit)
    if not runs:
        return {"count": 0, "items": []}

    oldest_start = _ensure_aware(runs[-1].started_at)

    async with SessionLocal() as session:
        strat_rows = (await session.execute(
            _select(Strategy)
            .where(Strategy.created_at >= oldest_start)
            .order_by(Strategy.created_at.asc())
        )).scalars().all()

        trade_rows = (await session.execute(
            _select(Trade)
            .where(Trade.executed_at >= oldest_start)
            .order_by(Trade.executed_at.asc())
        )).scalars().all()

    def _aw(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)

    items = []
    for run in runs:
        rs = _aw(run.started_at)
        re = _aw(run.completed_at)

        run_strats = [
            s for s in strat_rows
            if (sc := _aw(s.created_at)) and rs and sc >= rs and (re is None or sc <= re)
        ]
        run_trades = [
            t for t in trade_rows
            if (tc := _aw(t.executed_at)) and rs and tc >= rs and (re is None or tc <= re)
        ]

        items.append(_activity_item(run, run_strats, run_trades))

    return {"count": len(items), "items": items}


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


@app.get("/admin/config", tags=["admin"])
async def admin_get_config() -> dict:
    """Return current runtime bot configuration."""
    cfg = await get_bot_config()
    return _config_dict(cfg)


def _check_admin_password(x_admin_password: str = "") -> None:
    if config.ADMIN_PASSWORD and x_admin_password != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin password")


@app.post("/admin/config", tags=["admin"])
async def admin_update_config(body: dict, x_admin_password: str = Header(default="")) -> dict:
    _check_admin_password(x_admin_password)
    """Update runtime bot configuration. Send only the fields you want to change.

    Accepted fields: paused, position_size_usd, min_confidence,
    claude_instruction, eligible_tokens (list of strings).
    """
    import json as _json
    updates: dict = {}

    if "paused" in body:
        updates["paused"] = bool(body["paused"])
    if "position_size_usd" in body:
        v = body["position_size_usd"]
        updates["position_size_usd"] = float(v) if v is not None else None
    if "min_confidence" in body:
        v = body["min_confidence"]
        updates["min_confidence"] = float(v) if v is not None else None
    if "claude_instruction" in body:
        v = body["claude_instruction"]
        updates["claude_instruction"] = str(v).strip() if v else None
    if "eligible_tokens" in body:
        v = body["eligible_tokens"]
        updates["eligible_tokens_json"] = _json.dumps(v) if v else None
    if "monitor_interval_minutes" in body:
        v = body["monitor_interval_minutes"]
        updates["monitor_interval_minutes"] = int(v) if v is not None else None

    cfg = await update_bot_config(**updates)
    logger.info("Admin config updated: %s", updates)

    # Reschedule the trade monitor job if interval changed
    if "monitor_interval_minutes" in updates:
        from agent.scheduler import scheduler
        from apscheduler.triggers.interval import IntervalTrigger
        new_mins = updates["monitor_interval_minutes"] or 2
        scheduler.reschedule_job(
            "trade_monitor",
            trigger=IntervalTrigger(minutes=new_mins),
        )
        logger.info("Trade monitor rescheduled to every %d min", new_mins)

    return _config_dict(cfg)


@app.post("/admin/pause", tags=["admin"])
async def admin_toggle_pause(x_admin_password: str = Header(default="")) -> dict:
    _check_admin_password(x_admin_password)
    """Toggle the bot pause state."""
    cfg = await get_bot_config()
    new_state = not cfg.paused
    cfg = await update_bot_config(paused=new_state)
    logger.info("Admin: bot %s", "PAUSED" if new_state else "RESUMED")
    return {"paused": new_state, "message": "Bot paused" if new_state else "Bot resumed"}


@app.post("/admin/close-all", tags=["admin"])
async def admin_close_all(x_admin_password: str = Header(default="")) -> dict:
    _check_admin_password(x_admin_password)
    """Emergency: close all open positions at current market price."""
    from agent.scheduler import _get_token_price
    open_trades = await list_open_buy_trades()
    if not open_trades:
        return {"closed": 0, "message": "No open positions"}

    closed = 0
    errors = []
    for trade in open_trades:
        try:
            price = await _get_token_price(trade.symbol)
            if price is None:
                errors.append(f"trade {trade.id}: price unavailable")
                continue
            from db.models import close_trade as _close_trade
            await _close_trade(trade.id, exit_price=round(price, 4))
            pnl_pct = (price / trade.entry_price - 1) * 100
            closed += 1
            logger.info("Admin close-all: closed trade %d %s pnl=%+.2f%%",
                        trade.id, trade.symbol, pnl_pct)
        except Exception as exc:
            errors.append(f"trade {trade.id}: {exc}")

    return {"closed": closed, "total": len(open_trades), "errors": errors}


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
