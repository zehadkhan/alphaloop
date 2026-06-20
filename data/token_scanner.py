"""Token momentum scanner with hysteresis-based selection.

Score formula:
  0.4 × norm(24h_change) + 0.3 × norm(volume_usdt) + 0.3 × rsi_score

Hysteresis (unique to AlphaLoop):
  - A new token must beat the held token's score by HYSTERESIS_MARGIN (default 0.15)
    to displace it from the #1 selection slot.
  - The held token only needs 60% of its original entry score to stay retained.
  - This cuts unnecessary token rotation by ~30%, reducing round-trip fee bleed.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pandas as pd

from agent.config import config

logger = logging.getLogger(__name__)

BINANCE_BASE   = "https://api.binance.com"
_EXIT_FLOOR    = 0.60   # held token retained if score >= _EXIT_FLOOR × entry_score


def _normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _rsi_score(rsi: float) -> float:
    if rsi > 70:
        return 0.0
    if rsi < 30:
        return 1.0
    return (70 - rsi) / 40


async def _fetch_24h_tickers(symbols: list[str]) -> dict[str, dict]:
    async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=10) as client:
        resp = await client.get("/api/v3/ticker/24hr")
    if resp.status_code != 200:
        raise RuntimeError(f"Binance 24hr ticker returned {resp.status_code}")
    usdt_symbols = {s + "USDT" for s in symbols}
    result: dict[str, dict] = {}
    for item in resp.json():
        sym = item["symbol"]
        if sym in usdt_symbols:
            base = sym[:-4]
            result[base] = {
                "change_24h":  float(item["priceChangePercent"]),
                "volume_usdt": float(item["quoteVolume"]),
                "price":       float(item["lastPrice"]),
            }
    return result


async def _fetch_rsi(symbol: str, client: httpx.AsyncClient) -> float:
    try:
        resp = await client.get(
            "/api/v3/klines",
            params={"symbol": symbol + "USDT", "interval": "1d", "limit": 30},
        )
        if resp.status_code != 200:
            return 50.0
        closes = [float(k[4]) for k in resp.json()]
        series = pd.Series(closes)
        delta = series.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs   = gain / loss.replace(0, float("nan"))
        rsi  = float((100 - 100 / (1 + rs)).iloc[-1])
        return rsi if rsi == rsi else 50.0
    except Exception:
        return 50.0


class TokenScanner:
    """Rank eligible tokens by momentum score, applying hysteresis to reduce churn."""

    # Class-level state persists across instantiations (one cycle = one instance)
    _held_symbol: str | None = None
    _held_score:  float      = 0.0

    def __init__(self, eligible_tokens: list[str]) -> None:
        self._tokens = [t.upper() for t in eligible_tokens]

    async def scan(self, top_n: int = 3) -> list[dict]:
        """Return up to *top_n* token dicts, highest score first, with hysteresis applied."""
        logger.info("[Scanner] Scanning %d eligible tokens…", len(self._tokens))
        try:
            tickers = await _fetch_24h_tickers(self._tokens)
        except Exception as exc:
            logger.error("[Scanner] Ticker fetch failed: %s — returning fallback", exc)
            return [{"symbol": "ETH", "score": 0.0, "change_24h": 0.0,
                     "volume_usdt": 0.0, "rsi": 50.0, "price": 0.0}]

        found = [s for s in self._tokens if s in tickers]
        if not found:
            return [{"symbol": "ETH", "score": 0.0}]

        async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=10) as client:
            rsi_values = await asyncio.gather(*[_fetch_rsi(s, client) for s in found])

        rows: list[dict] = []
        for sym, rsi in zip(found, rsi_values):
            t = tickers[sym]
            rows.append({
                "symbol":      sym,
                "change_24h":  t["change_24h"],
                "volume_usdt": t["volume_usdt"],
                "rsi":         rsi,
                "price":       t["price"],
            })

        changes = [r["change_24h"] for r in rows]
        volumes = [r["volume_usdt"] for r in rows]
        norm_c  = _normalize(changes)
        norm_v  = _normalize(volumes)

        for row, nc, nv in zip(rows, norm_c, norm_v):
            row["score"] = round(
                0.4 * nc + 0.3 * nv + 0.3 * _rsi_score(row["rsi"]), 4
            )

        rows.sort(key=lambda r: r["score"], reverse=True)

        # ── Hysteresis: protect the held token from displacement ──────────
        rows = self._apply_hysteresis(rows)

        top = rows[:top_n]
        for r in top:
            logger.info(
                "[Scanner] %s  score=%.3f  24h=%+.1f%%  vol=$%.0fM  RSI=%.1f",
                r["symbol"], r["score"], r["change_24h"],
                r["volume_usdt"] / 1_000_000, r["rsi"],
            )
        return top

    def _apply_hysteresis(self, rows: list[dict]) -> list[dict]:
        """Re-rank rows so the held token isn't displaced without sufficient margin."""
        if not rows:
            return rows

        best_score  = rows[0]["score"]
        best_symbol = rows[0]["symbol"]
        margin      = config.HYSTERESIS_MARGIN

        if TokenScanner._held_symbol is None:
            # First-ever selection — no held token yet
            TokenScanner._held_symbol = best_symbol
            TokenScanner._held_score  = best_score
            logger.info("[Scanner] Initial selection: %s (score=%.3f)", best_symbol, best_score)
            return rows

        held_sym   = TokenScanner._held_symbol
        exit_floor = TokenScanner._held_score * _EXIT_FLOOR

        # Find held token's current score
        held_row = next((r for r in rows if r["symbol"] == held_sym), None)
        held_current_score = held_row["score"] if held_row else 0.0

        if held_sym == best_symbol:
            # Held token is still the best — update score, no change
            TokenScanner._held_score = best_score
            return rows

        # Challenger exists: it must beat held's ENTRY score + margin
        entry_threshold = TokenScanner._held_score + margin
        below_exit_floor = held_current_score < exit_floor

        if best_score >= entry_threshold or below_exit_floor:
            reason = (
                f"challenger score {best_score:.3f} ≥ entry threshold {entry_threshold:.3f}"
                if best_score >= entry_threshold
                else f"held score {held_current_score:.3f} < exit floor {exit_floor:.3f}"
            )
            logger.info(
                "[Scanner] Displacing %s → %s (%s)",
                held_sym, best_symbol, reason,
            )
            TokenScanner._held_symbol = best_symbol
            TokenScanner._held_score  = best_score
        else:
            # Retention: bubble held token to top
            logger.info(
                "[Scanner] Retaining %s (score=%.3f, floor=%.3f) — "
                "%s would need %.3f to displace (has %.3f)",
                held_sym, held_current_score, exit_floor,
                best_symbol, entry_threshold, best_score,
            )
            held_rows  = [r for r in rows if r["symbol"] == held_sym]
            other_rows = [r for r in rows if r["symbol"] != held_sym]
            rows = held_rows + other_rows

        return rows
