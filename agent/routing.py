"""TWAK route selection — pick tokens that can actually be swapped."""
from __future__ import annotations

import logging

from agent.config import config

logger = logging.getLogger(__name__)


def build_candidate_symbols(
    top_tokens: list[dict],
    open_symbols: set[str],
    *,
    compliance: bool = False,
) -> list[str]:
    """Ordered token candidates: compliance staples first, then scanner, then default."""
    seen: set[str] = set()
    ordered: list[str] = []

    def add(sym: str) -> None:
        sym = sym.upper()
        if sym in seen or sym in open_symbols or sym in config.TWAK_BLACKLIST:
            return
        seen.add(sym)
        ordered.append(sym)

    if compliance:
        for sym in config.COMPLIANCE_PRIORITY_TOKENS:
            add(sym)

    for t in top_tokens:
        if t.get("data_source", "binance") == "dexscreener":
            continue
        add(t["symbol"])

    default = config.TRADING_PAIR.split("/")[0].upper()
    add(default)
    return ordered


async def pick_routable_symbol(
    candidates: list[str],
    *,
    action: str = "BUY",
) -> tuple[str | None, str, list[tuple[str, str]]]:
    """Return the first routable candidate, overall reason, and failed checks."""
    failed: list[tuple[str, str]] = []
    if not candidates:
        return None, "no_candidates", failed

    if not config.TWAK_REST_URL:
        return candidates[0], "", failed

    from execution.twak_executor import TWAKExecutor

    executor = TWAKExecutor()
    await executor.init_address()

    for sym in candidates:
        ok, err = await executor.test_route(sym, action=action)
        if ok:
            logger.info("[RouteCheck] Selected routable token: %s (%s)", sym, action)
            return sym, "", failed
        logger.warning("[RouteCheck] %s not routable (%s): %s", sym, action, err)
        failed.append((sym, err))

    return None, "no_routable_candidates", failed
