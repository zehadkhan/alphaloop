"""AlphaLoop FastAPI application."""
from __future__ import annotations

import logging
import logging.config
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

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
from pydantic import BaseModel

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
    get_latest_token_scans,
    get_performance_history,
    get_trade_stats,
    get_trade,
    close_trade,
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
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


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
    duration_hours = None
    if t.executed_at and t.closed_at:
        ea = t.executed_at if t.executed_at.tzinfo else t.executed_at.replace(tzinfo=timezone.utc)
        ca = t.closed_at  if t.closed_at.tzinfo  else t.closed_at.replace(tzinfo=timezone.utc)
        duration_hours = round((ca - ea).total_seconds() / 3600, 2)
    return {
        "id":             t.id,
        "strategy_id":    t.strategy_id,
        "symbol":         t.symbol,
        "action":         t.action,
        "amount_usd":     t.amount_usd,
        "entry_price":    t.entry_price,
        "exit_price":     t.exit_price,
        "pnl_usd":        t.pnl_usd,
        "pnl_percent":    t.pnl_percent,
        "close_reason":   getattr(t, "close_reason", None),
        "duration_hours": duration_hours,
        "tx_hash":        t.tx_hash,
        "status":         t.status,
        "executed_at":    _fmt_dt(t.executed_at),
        "closed_at":      _fmt_dt(t.closed_at),
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

@app.api_route("/health", methods=["GET", "HEAD"], tags=["system"])
async def health() -> dict:
    """Liveness check — also returns live BNB price and x402 integration status."""
    from agent.scheduler import _get_bnb_price
    from data.cmc_client import _X402_ENABLED, _TWAK_X402_MODE, _USE_AGENT_HUB
    bnb_price = await _get_bnb_price()
    return {
        "status": "ok",
        "environment": config.ENVIRONMENT,
        "bnb_price": bnb_price,
        "x402": {
            "enabled": _X402_ENABLED,
            "twak_x402_mode": _TWAK_X402_MODE,
            "agent_hub_mode": _USE_AGENT_HUB,
        },
    }


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

    if run.error_message and run.error_message.startswith("skip:"):
        parts = run.error_message.split(":")
        skip_reason = parts[1] if len(parts) > 1 else "unknown"
        skip_titles = {
            "extreme_fear":     ("Market caution — Extreme Fear",
                                 f"Fear & Greed = {parts[2] if len(parts) > 2 else '?'}/100. "
                                 "In competition mode the bot continues with 50% position size."),
            "extreme_greed":    ("Gate blocked — Extreme Greed",
                                 f"Fear & Greed = {parts[2] if len(parts) > 2 else '?'}/100. "
                                 "Market overheated — high risk of sharp reversal."),
            "btc_downtrend":    ("Gate blocked — BTC Downtrend",
                                 f"BTC 80h change: {parts[2] if len(parts) > 2 else '?'}%. "
                                 "When BTC falls, altcoins follow — bot waited for recovery."),
            "token_weak_7d":    ("Gate blocked — Token Weak (7-day)",
                                 f"{parts[2] if len(parts) > 2 else 'Token'} down {abs(float(parts[3])) if len(parts) > 3 else '?'}% "
                                 "in 7 days — falling knife, not a safe entry."),
            "unroutable_token": ("Skipped — Token Cannot Be Traded",
                                 f"{parts[2] if len(parts) > 2 else 'Token'} has no swap route on TWAK/BSC. "
                                 "Added to blacklist automatically."),
        }
        title, detail = skip_titles.get(skip_reason, (
            f"Skipped — {skip_reason.replace('_', ' ').title()}",
            "Market quality gate prevented trade this cycle."
        ))
        return {**base, "type": "skipped", "color": "orange",
                "title": title, "detail": detail, "reasoning": None}

    if run.error_message:
        return {**base, "type": "error", "color": "red",
                "title": "System error — the cycle could not complete",
                "detail": run.error_message[:300], "reasoning": None}

    if not run.completed_at:
        return {**base, "type": "running", "color": "blue",
                "title": "Cycle in progress…", "detail": None, "reasoning": None}

    if not strategies and not trades:
        return {**base, "type": "skipped", "color": "gray",
                "title": "Skipped — max positions held or token already open",
                "detail": "The bot only opens one trade per token at a time. It waited for conditions to improve.",
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
            "title": f"AlphaLoop bought ${t.amount_usd:.2f} of {s.symbol} at ${s.entry_price:,.2f}",
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
        reasoning = s.reasoning or ""
        if "compass" in reasoning.lower() or "defensive" in reasoning.lower():
            detail = (
                f"Market compass score too low for a safe entry "
                f"(confidence {conf_pct}% — regime blocked BUY)"
            )
        else:
            detail = (
                f"Confidence {conf_pct}% — regime gates or market structure "
                f"did not justify a trade this cycle"
            )
        return {
            **base,
            "type": "hold",
            "color": "yellow",
            "title": f"AlphaLoop analyzed {s.symbol} and decided to wait — no clear signal yet",
            "detail": detail,
            "reasoning": reasoning[:500] if reasoning else None,
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
            "title": f"AlphaLoop's {s.symbol} signal was tested and rejected — historical results too weak",
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


@app.post("/admin/reset-blacklist", tags=["admin"])
async def admin_reset_blacklist(x_admin_password: str = Header(default="")) -> dict:
    """Clear persisted token blacklist so routable tokens can be retried."""
    _check_admin_password(x_admin_password)
    from agent.blacklist import reset_persisted_blacklist
    removed = reset_persisted_blacklist()
    return {
        "ok": True,
        "removed": removed,
        "blacklist_size": len(config.TWAK_BLACKLIST),
        "blacklist": sorted(config.TWAK_BLACKLIST),
    }


class SellOneRequest(BaseModel):
    symbol: str
    contract: str = ""
    usd_value: float


@app.post("/admin/sell-one", tags=["admin"])
async def admin_sell_one(body: SellOneRequest,
                         x_admin_password: str = Header(default="")) -> dict:
    """Sell a specific token by symbol (or contract address) for a given USD value."""
    _check_admin_password(x_admin_password)
    if not config.TWAK_REST_URL:
        raise HTTPException(status_code=503, detail="TWAK not configured")
    from execution.twak_executor import TWAKExecutor
    executor = TWAKExecutor()
    token_id = body.symbol if body.symbol else body.contract
    swap = await executor.swap(token_id, "BNB", body.usd_value)
    return {
        "symbol": body.symbol,
        "contract": body.contract,
        "usd_value": body.usd_value,
        "bnb_received": swap.get("amount_out", 0.0),
        "tx_hash": swap.get("tx_hash"),
    }


@app.post("/admin/sell-tokens", tags=["admin"])
async def admin_sell_tokens(x_admin_password: str = Header(default="")) -> dict:
    """Sell ALL non-BNB token balances in the TWAK wallet back to BNB.

    Discovers every token the wallet holds via BSCScan tokentx + the full
    competition eligible list, checks on-chain balance (with correct decimals),
    gets price, computes USD value, then sells anything above $0.10.
    """
    _check_admin_password(x_admin_password)
    if not config.TWAK_REST_URL:
        raise HTTPException(status_code=503, detail="TWAK not configured")

    from execution.twak_executor import TWAKExecutor
    import httpx as _httpx

    wallet = "0xa401A91faa968Ee4334780712C95Af208E570e0F"
    rpc    = "https://bsc-dataseed.binance.org/"

    SKIP_CONTRACTS = {
        "0x55d398326f99059ff775485246999027b3197955",  # USDT
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
        "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
    }

    async def _rpc_call(client: _httpx.AsyncClient, method: str, params: list) -> str:
        r = await client.post(rpc, json={"jsonrpc": "2.0", "method": method,
                                         "params": params, "id": 1}, timeout=8)
        return r.json().get("result", "0x0")

    async def _fetch_decimals(contract: str) -> int:
        try:
            async with _httpx.AsyncClient(timeout=8) as c:
                result = await _rpc_call(c, "eth_call",
                                         [{"to": contract, "data": "0x313ce567"}, "latest"])
            val = int(result, 16)
            return val if 0 < val <= 18 else 18
        except Exception:
            return 18

    async def _bsc_balance(contract: str) -> float:
        """Return token balance with correct on-chain decimals."""
        data = "0x70a08231" + "000000000000000000000000" + wallet[2:].lower()
        try:
            decimals = await _fetch_decimals(contract)
            async with _httpx.AsyncClient(timeout=8) as c:
                result = await _rpc_call(c, "eth_call", [{"to": contract, "data": data}, "latest"])
            return int(result, 16) / 10**decimals
        except Exception:
            return 0.0

    # --- Discover all token contracts ---
    # contract_addr (lower) -> symbol string
    # Seed with TWAK_KNOWN_SYMBOLS that resolve to symbols (not addresses) — must be hardcoded
    discovered: dict[str, str] = {
        "0x2170ed0880ac9a755fd29b2688956bd959f933f8": "ETH",   # Binance-Peg ETH
        "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": "BTC",   # Binance-Peg BTC (BTCB)
    }

    # 1) Moralis Web3 API — free token balances endpoint (no deprecated V1 issue)
    moralis_key = os.getenv("MORALIS_API_KEY", "")
    if moralis_key:
        try:
            async with _httpx.AsyncClient(timeout=20) as c:
                r = await c.get(
                    f"https://deep-index.moralis.io/api/v2.2/{wallet}/erc20",
                    params={"chain": "bsc"},
                    headers={"X-API-Key": moralis_key},
                )
            tokens_data = r.json()
            if isinstance(tokens_data, list):
                for t in tokens_data:
                    addr = t.get("token_address", "").lower()
                    sym  = t.get("symbol", "").upper()
                    if addr and addr not in SKIP_CONTRACTS:
                        discovered[addr] = sym or ""
                logger.info("[SellAll] Moralis returned %d tokens", len(tokens_data))
        except Exception as exc:
            logger.warning("[SellAll] Moralis discovery failed: %s", exc)

    # 2) All 149 competition tokens — catches anything we bought but BSCScan missed
    from execution.twak_executor import _resolve_bsc_token
    all_trades = await list_open_buy_trades()
    eligible_syms = set(config.ELIGIBLE_TOKENS) | {t.symbol for t in all_trades}
    eligible_syms -= {"BNB", "USDT", "USDC", "BUSD", "WBNB"}

    for sym in eligible_syms:
        contract = await _resolve_bsc_token(sym)
        if contract and contract != sym:  # got a real address
            addr = contract.lower()
            if addr not in SKIP_CONTRACTS:
                discovered.setdefault(addr, sym.upper())

    logger.info("[SellAll] Total contracts to check: %d", len(discovered))

    executor = TWAKExecutor()
    sold     = []
    errors   = []
    skipped  = 0

    for contract, sym in discovered.items():
        try:
            bal = await _bsc_balance(contract)
            if bal < 1e-6:
                skipped += 1
                continue

            # Get USD value: balance_tokens * price_per_token
            label = sym if sym else contract[:10]
            try:
                price_usd = await executor.get_price(sym if sym else contract, "USDT")
            except Exception:
                price_usd = 0.0

            usd_value = bal * price_usd
            if usd_value < 0.10:
                skipped += 1
                logger.debug("[SellAll] %s bal=%.4f price=%.6f usd=%.4f — dust, skip",
                             label, bal, price_usd, usd_value)
                continue

            logger.info("[SellAll] %s bal=%.4f @ $%.4f = $%.2f — selling",
                        label, bal, price_usd, usd_value)
            swap = await executor.swap(sym if sym else contract, "BNB", usd_value * 0.999)
            bnb  = swap.get("amount_out", 0.0)
            sold.append({
                "symbol": label,
                "contract": contract,
                "amount_tokens": round(bal, 6),
                "usd_value": round(usd_value, 2),
                "bnb_received": round(bnb, 6),
                "tx_hash": swap.get("tx_hash"),
            })
        except Exception as exc:
            errors.append({"symbol": sym or contract[:10], "contract": contract, "error": str(exc)})
            logger.warning("[SellAll] %s: %s", sym or contract[:10], exc)

    total_bnb = sum(s["bnb_received"] for s in sold)
    bnb_price = 550.0
    return {
        "sold": sold,
        "skipped_dust": skipped,
        "total_bnb": round(total_bnb, 6),
        "total_usd": round(total_bnb * bnb_price, 2),
        "errors": errors,
    }


@app.post("/competition/scan", tags=["competition"])
async def competition_scan() -> dict:
    """Run the full 149-token scanner and return ranked results."""
    from data.token_scanner import TokenScanner
    from db.models import save_token_scans as _save_scans
    try:
        scanner = TokenScanner(config.ELIGIBLE_TOKENS)
        results = await scanner.scan(top_n=10)
        try:
            await _save_scans(None, results)
        except Exception:
            pass
        return {
            "scanned":    scanner.token_count,
            "top_tokens": results,
        }
    except Exception as exc:
        return JSONResponse(content={"error": str(exc)}, status_code=500)


@app.get("/scanner/latest", tags=["data"])
async def scanner_latest() -> dict:
    """Return the most recent token scanner cycle results."""
    rows = await get_latest_token_scans(limit=150)
    return {"count": len(rows), "tokens": rows}


@app.get("/performance", tags=["data"])
async def get_performance() -> dict:
    """Return equity curve data (hourly snapshots, last 7 days)."""
    history = await get_performance_history(limit=168)
    return {"count": len(history), "history": history}


@app.get("/stats", tags=["data"])
async def get_stats() -> dict:
    """Return aggregate trading statistics: win rate, avg profit, best/worst trade."""
    stats = await get_trade_stats()
    return stats


@app.get("/gates", tags=["data"])
async def get_gates() -> dict:
    """Return live market gate status: Fear & Greed, BTC trend, blacklist."""
    from data.sentiment import get_fear_greed, get_btc_4h_trend
    from agent.scheduler import _last_compass
    import asyncio as _aio

    fg, btc = await _aio.gather(get_fear_greed(), get_btc_4h_trend())

    gate1_pass = 25 <= fg["value"] <= 85
    gate2_pass = btc["uptrend"]

    return {
        "gates": {
            "fear_greed": {
                "value":       fg["value"],
                "label":       fg["label"],
                "pass":        gate1_pass,
                "reason":      None if gate1_pass else (
                    "Extreme Fear — market panic" if fg["value"] < 25 else "Extreme Greed — bubble risk"
                ),
            },
            "btc_trend": {
                "change_80h":  btc["change_pct"],
                "above_sma10": btc["above_sma10"],
                "uptrend":     btc["uptrend"],
                "pass":        gate2_pass,
                "reason":      None if gate2_pass else f"BTC 80h downtrend ({btc['change_pct']:+.1f}%)",
            },
            "token_7d": {
                "note": "Checked per-token at cycle time",
                "threshold": -20,
            },
        },
        "all_pass":  gate1_pass and gate2_pass,
        "blacklist": sorted(config.TWAK_BLACKLIST),
        "compass":   _last_compass["regime"] if _last_compass else None,
    }


@app.post("/admin/close/{trade_id}", tags=["admin"])
async def admin_close_trade(trade_id: int, x_admin_password: str = Header(default="")) -> dict:
    """Close a specific open trade by ID at current market price."""
    _check_admin_password(x_admin_password)
    from agent.scheduler import _get_token_price
    trade = await get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    if trade.closed_at is not None:
        raise HTTPException(status_code=400, detail="Trade already closed")
    price = await _get_token_price(trade.symbol)
    if price is None:
        raise HTTPException(status_code=503, detail=f"Cannot fetch price for {trade.symbol}")
    await close_trade(trade_id, exit_price=round(price, 4), close_reason="manual")
    pnl_pct = (price / trade.entry_price - 1) * 100
    logger.info("Admin closed trade %d  %s  pnl=%+.2f%%", trade_id, trade.symbol, pnl_pct)
    return {"trade_id": trade_id, "symbol": trade.symbol, "exit_price": price,
            "pnl_pct": round(pnl_pct, 3), "close_reason": "manual"}


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


@app.post("/twak/x402-test", tags=["competition"])
async def twak_x402_test() -> dict:
    """Test TWAK x402 micropayment for CMC Agent Hub data.

    Routes a CMC quote request through TWAK's native x402_request action.
    TWAK handles payment signing — no manual key management needed.
    """
    from data.cmc_client import _X402_ENABLED, _TWAK_X402_MODE, CMC_BASE
    from execution.twak_executor import TWAKExecutor, TWAKExecutorError

    if not config.TWAK_REST_URL:
        return {"ok": False, "reason": "TWAK not configured"}

    test_url = f"{CMC_BASE}/v1/cryptocurrency/quotes/latest?symbol=BNB&convert=USD"
    try:
        executor = TWAKExecutor()
        result = await executor.x402_request(test_url, method="GET", max_payment_atomic="1000")
        return {
            "ok": True,
            "x402_enabled": _X402_ENABLED,
            "twak_x402_mode": _TWAK_X402_MODE,
            "test_url": test_url,
            "response_keys": list(result.keys()) if isinstance(result, dict) else str(type(result)),
        }
    except TWAKExecutorError as exc:
        return {"ok": False, "x402_enabled": _X402_ENABLED, "twak_x402_mode": _TWAK_X402_MODE, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
