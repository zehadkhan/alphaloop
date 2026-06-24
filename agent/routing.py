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
    compliance: bool = False,
) -> tuple[str | None, str, list[tuple[str, str]]]:
    """Pick the first eligible candidate.

    TWAK get_swap_quote is unreliable (false negatives on ETH etc.) — the real
    routability check is the swap() call itself.
    """
    if not candidates:
        return None, "no_candidates", []
    sym = candidates[0]
    logger.info(
        "[TokenPick] Using %s (%s) — %d candidate(s)%s",
        sym, action, len(candidates),
        " [compliance]" if compliance else "",
    )
    return sym, "", []
