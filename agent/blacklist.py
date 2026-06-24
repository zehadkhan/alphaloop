"""Runtime token blacklist — persisted across restarts."""
from __future__ import annotations

import json
import logging
import os

from agent.config import config

logger = logging.getLogger(__name__)

_BLACKLIST_PATH = os.path.join(os.path.dirname(__file__), "..", "storage", "token_blacklist.json")

_PERMANENT_SIGNALS = (
    "TOKEN_NOT_FOUND",
    "APPROVAL_SENT_SWAP_FAILED",
    "VALIDATION_ERROR",
    "no route",
    "NO_ROUTE",
    "No route",
    "not routable",
    "quote returned zero",
)


def should_blacklist(symbol: str, reason: str) -> bool:
    """Only blacklist on confirmed routing failures, not transient TWAK errors."""
    sym = symbol.upper()
    if sym in config.COMPLIANCE_PRIORITY_TOKENS:
        return any(sig.lower() in reason.lower() for sig in _PERMANENT_SIGNALS)
    return any(sig.lower() in reason.lower() for sig in _PERMANENT_SIGNALS) or "unroutable" in reason.lower()


def load_persisted_blacklist() -> None:
    try:
        if os.path.exists(_BLACKLIST_PATH):
            extra = json.loads(open(_BLACKLIST_PATH).read())
            if isinstance(extra, list):
                config.TWAK_BLACKLIST.update(extra)
                if extra:
                    logger.info("[Blacklist] Loaded %d persisted tokens", len(extra))
    except Exception as exc:
        logger.warning("[Blacklist] Could not load persisted blacklist: %s", exc)


def auto_blacklist(symbol: str, reason: str) -> None:
    sym = symbol.upper()
    if sym in config.TWAK_BLACKLIST:
        return
    if not should_blacklist(sym, reason):
        logger.info("[Blacklist] Not blacklisting %s (transient/uncertain): %s", sym, reason[:80])
        return
    config.TWAK_BLACKLIST.add(sym)
    logger.warning("[Blacklist] AUTO-BLACKLISTED %s — %s", sym, reason[:120])
    try:
        os.makedirs(os.path.dirname(_BLACKLIST_PATH), exist_ok=True)
        existing: list = json.loads(open(_BLACKLIST_PATH).read()) if os.path.exists(_BLACKLIST_PATH) else []
        if sym not in existing:
            existing.append(sym)
            with open(_BLACKLIST_PATH, "w") as f:
                json.dump(existing, f, indent=2)
    except Exception as exc:
        logger.warning("[Blacklist] Could not persist blacklist: %s", exc)


def reset_persisted_blacklist() -> int:
    """Clear runtime additions from storage; keep static config.TWAK_BLACKLIST."""
    removed = 0
    try:
        if os.path.exists(_BLACKLIST_PATH):
            persisted = json.loads(open(_BLACKLIST_PATH).read())
            if isinstance(persisted, list):
                for sym in persisted:
                    if sym in config.TWAK_BLACKLIST:
                        config.TWAK_BLACKLIST.discard(sym)
                        removed += 1
            os.remove(_BLACKLIST_PATH)
            logger.warning("[Blacklist] Reset — removed %d persisted token(s)", removed)
    except Exception as exc:
        logger.warning("[Blacklist] Reset failed: %s", exc)
    return removed
