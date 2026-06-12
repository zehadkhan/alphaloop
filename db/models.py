from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./alphaloop.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # aiosqlite needs check_same_thread=False surfaced via connect_args
    connect_args={"check_same_thread": False},
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ORM base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)          # BUY | SELL | HOLD
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)       # short | medium
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)      # low | medium | high

    backtest_passed: Mapped[bool | None] = mapped_column(nullable=True)
    backtest_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    backtest_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # pending | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    trades: Mapped[list[Trade]] = relationship("Trade", back_populates="strategy", lazy="selectin")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)          # BUY | SELL
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # pending | executed | failed
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    strategy: Mapped[Strategy | None] = relationship("Strategy", back_populates="trades")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strategies_generated: Mapped[int] = mapped_column(Integer, default=0)
    trades_executed: Mapped[int] = mapped_column(Integer, default=0)
    total_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    paused: Mapped[bool] = mapped_column(default=False)
    position_size_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    claude_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    eligible_tokens_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    monitor_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready: %s", DATABASE_URL)


# ---------------------------------------------------------------------------
# Strategy CRUD
# ---------------------------------------------------------------------------

async def create_strategy(data: dict) -> Strategy:
    async with SessionLocal() as session:
        row = Strategy(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.debug("Created strategy id=%d symbol=%s action=%s", row.id, row.symbol, row.action)
        return row


async def get_strategy(strategy_id: int) -> Strategy | None:
    async with SessionLocal() as session:
        return await session.get(Strategy, strategy_id)


async def list_strategies(
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> Sequence[Strategy]:
    async with SessionLocal() as session:
        q = select(Strategy).order_by(Strategy.created_at.desc()).limit(limit)
        if symbol:
            q = q.where(Strategy.symbol == symbol.upper())
        if status:
            q = q.where(Strategy.status == status)
        result = await session.execute(q)
        return result.scalars().all()


async def update_strategy_backtest(
    strategy_id: int,
    *,
    passed: bool,
    total_return: float,
    win_rate: float,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Strategy)
            .where(Strategy.id == strategy_id)
            .values(
                backtest_passed=passed,
                backtest_return=total_return,
                backtest_win_rate=win_rate,
                status="approved" if passed else "rejected",
            )
        )
        await session.commit()
        logger.debug(
            "Strategy id=%d backtest passed=%s return=%.2f%% win_rate=%.0f%%",
            strategy_id, passed, total_return, win_rate * 100,
        )


async def approve_strategy(strategy_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Strategy).where(Strategy.id == strategy_id).values(status="approved")
        )
        await session.commit()


async def reject_strategy(strategy_id: int) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Strategy).where(Strategy.id == strategy_id).values(status="rejected")
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Trade CRUD
# ---------------------------------------------------------------------------

async def create_trade(data: dict) -> Trade:
    async with SessionLocal() as session:
        row = Trade(**data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.debug("Created trade id=%d symbol=%s action=%s", row.id, row.symbol, row.action)
        return row


async def get_trade(trade_id: int) -> Trade | None:
    async with SessionLocal() as session:
        return await session.get(Trade, trade_id)


async def list_trades(
    symbol: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> Sequence[Trade]:
    async with SessionLocal() as session:
        q = select(Trade).order_by(Trade.executed_at.desc().nullslast()).limit(limit)
        if symbol:
            q = q.where(Trade.symbol == symbol.upper())
        if status:
            q = q.where(Trade.status == status)
        result = await session.execute(q)
        return result.scalars().all()


async def list_open_buy_trades() -> Sequence[Trade]:
    """Return all BUY trades that have not been closed yet."""
    async with SessionLocal() as session:
        q = (
            select(Trade)
            .options(selectinload(Trade.strategy))
            .where(Trade.action == "BUY")
            .where(Trade.closed_at.is_(None))
            .where(Trade.status.in_(["dry_run", "executed"]))
            .order_by(Trade.executed_at.asc())
        )
        result = await session.execute(q)
        return result.scalars().all()


async def close_trade(
    trade_id: int,
    *,
    exit_price: float,
    pnl_usd: float | None = None,
    pnl_percent: float | None = None,
    tx_hash: str | None = None,
) -> None:
    async with SessionLocal() as session:
        trade = await session.get(Trade, trade_id)
        if trade is None:
            logger.warning("close_trade: trade id=%d not found", trade_id)
            return

        # Always recalculate PnL from prices — never trust caller's value
        # (avoids silent 0.0 bugs when price didn't change or pnl was omitted)
        calc_pnl_usd = round((exit_price / trade.entry_price - 1) * trade.amount_usd, 4)
        calc_pnl_pct = round((exit_price / trade.entry_price - 1) * 100, 4)

        # Preserve dry_run status — close_trade is called for both real and
        # simulated trades; changing "dry_run" to "executed" would misrepresent
        # simulation results in the UI.
        new_status = trade.status if trade.status == "dry_run" else "executed"

        await session.execute(
            update(Trade)
            .where(Trade.id == trade_id)
            .values(
                exit_price=round(exit_price, 4),
                pnl_usd=calc_pnl_usd,
                pnl_percent=calc_pnl_pct,
                tx_hash=tx_hash,
                status=new_status,
                closed_at=_now(),
            )
        )
        await session.commit()
        logger.info("Closed trade id=%d  entry=%.4f exit=%.4f pnl=%+.4f (%.4f%%)",
                    trade_id, trade.entry_price, exit_price, calc_pnl_usd, calc_pnl_pct)


async def get_today_pnl() -> float:
    """Sum of pnl_usd from trades closed since UTC midnight today."""
    from datetime import date
    today_utc = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.sum(Trade.pnl_usd))
            .where(Trade.closed_at >= today_utc)
            .where(Trade.pnl_usd.isnot(None))
        )
        total = result.scalar()
        return float(total) if total is not None else 0.0


async def get_last_trade_time() -> datetime | None:
    """Return the executed_at timestamp of the most recent executed trade."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Trade.executed_at)
            .where(Trade.status.in_(["dry_run", "executed"]))
            .order_by(Trade.executed_at.desc())
            .limit(1)
        )
        row = result.scalar()
        return row


async def get_daily_trade_count() -> int:
    """Number of trades executed (opened) since UTC midnight today."""
    from datetime import date
    today_utc = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.count(Trade.id))
            .where(Trade.executed_at >= today_utc)
            .where(Trade.status.in_(["dry_run", "executed"]))
        )
        count = result.scalar()
        return int(count) if count is not None else 0


async def get_peak_portfolio_value() -> float:
    """Return the highest cumulative pnl seen (used for drawdown calculation)."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.sum(Trade.pnl_usd)).where(Trade.pnl_usd.isnot(None))
        )
        total = result.scalar()
        return float(total) if total is not None else 0.0


async def fail_trade(trade_id: int, *, tx_hash: str | None = None) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(Trade)
            .where(Trade.id == trade_id)
            .values(status="failed", tx_hash=tx_hash, closed_at=_now())
        )
        await session.commit()
        logger.debug("Marked trade id=%d as failed", trade_id)


# ---------------------------------------------------------------------------
# AgentRun CRUD
# ---------------------------------------------------------------------------

async def create_agent_run() -> AgentRun:
    async with SessionLocal() as session:
        row = AgentRun()
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.debug("Started agent_run id=%d", row.id)
        return row


async def get_agent_run(run_id: int) -> AgentRun | None:
    async with SessionLocal() as session:
        return await session.get(AgentRun, run_id)


async def list_agent_runs(limit: int = 20) -> Sequence[AgentRun]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
        )
        return result.scalars().all()


async def complete_agent_run(
    run_id: int,
    *,
    strategies_generated: int,
    trades_executed: int,
    total_pnl: float,
    error_message: str | None = None,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(
                completed_at=_now(),
                strategies_generated=strategies_generated,
                trades_executed=trades_executed,
                total_pnl=total_pnl,
                error_message=error_message,
            )
        )
        await session.commit()
        logger.debug(
            "Completed agent_run id=%d strategies=%d trades=%d pnl=%.2f",
            run_id, strategies_generated, trades_executed, total_pnl,
        )


# ---------------------------------------------------------------------------
# BotConfig CRUD
# ---------------------------------------------------------------------------

async def get_bot_config() -> BotConfig:
    """Return the singleton BotConfig row, creating it with defaults if absent."""
    async with SessionLocal() as session:
        row = await session.get(BotConfig, 1)
        if row is None:
            row = BotConfig(id=1)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row


async def update_bot_config(**kwargs) -> BotConfig:
    """Update one or more fields of the singleton BotConfig row."""
    async with SessionLocal() as session:
        row = await session.get(BotConfig, 1)
        if row is None:
            row = BotConfig(id=1)
            session.add(row)
        for k, v in kwargs.items():
            setattr(row, k, v)
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        return row


# ---------------------------------------------------------------------------
# Smoke-test: python -m db.models
# ---------------------------------------------------------------------------

async def _main() -> None:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    await init_db()

    # --- AgentRun lifecycle ---
    run = await create_agent_run()
    print(f"\nAgentRun created: id={run.id} started_at={run.started_at}")

    # --- Strategy lifecycle ---
    strategy = await create_strategy({
        "symbol": "BNB",
        "action": "BUY",
        "confidence": 0.82,
        "entry_price": 612.5,
        "stop_loss": 588.0,
        "take_profit": 660.0,
        "reasoning": "Bullish MACD crossover with RSI in neutral zone",
        "timeframe": "medium",
        "risk_level": "low",
    })
    print(f"Strategy created: id={strategy.id} status={strategy.status}")

    await update_strategy_backtest(
        strategy.id, passed=True, total_return=4.72, win_rate=0.67
    )
    refreshed = await get_strategy(strategy.id)
    print(f"Strategy after backtest: status={refreshed.status} "
          f"return={refreshed.backtest_return}% passed={refreshed.backtest_passed}")

    # --- Trade lifecycle ---
    trade = await create_trade({
        "strategy_id": strategy.id,
        "symbol": "BNB",
        "action": "BUY",
        "amount_usd": 10.0,
        "entry_price": 612.5,
        "status": "pending",
        "executed_at": _now(),
    })
    print(f"\nTrade created: id={trade.id} status={trade.status}")

    await close_trade(
        trade.id,
        exit_price=648.0,
        pnl_usd=0.58,
        pnl_percent=5.79,
        tx_hash="0xabc123",
    )
    closed = await get_trade(trade.id)
    print(f"Trade closed: pnl_usd={closed.pnl_usd} pnl_pct={closed.pnl_percent}% "
          f"tx={closed.tx_hash}")

    # --- Complete agent run ---
    await complete_agent_run(run.id, strategies_generated=1, trades_executed=1, total_pnl=0.58)
    finished = await get_agent_run(run.id)
    print(f"\nAgentRun completed: id={finished.id} "
          f"completed_at={finished.completed_at} pnl={finished.total_pnl}")

    # --- List queries ---
    strategies = await list_strategies(symbol="BNB", status="approved")
    print(f"\nApproved BNB strategies: {len(strategies)}")

    trades = await list_trades(symbol="BNB", status="executed")
    print(f"Executed BNB trades: {len(trades)}")

    runs = await list_agent_runs(limit=5)
    print(f"Recent agent runs: {len(runs)}")


if __name__ == "__main__":
    asyncio.run(_main())
