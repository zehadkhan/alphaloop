"""Token momentum scanner.

Fetches 24h ticker stats for all eligible tokens in a single Binance call,
scores each by a momentum formula, and returns the top-N candidates for the
current cycle.

Score = 0.4 × norm(24h_change) + 0.3 × norm(volume_usdt) + 0.3 × rsi_score
  rsi_score: derived from RSI of last 30 daily closes
             0 if RSI > 70 (overbought), 1 if RSI < 30 (oversold), linear between
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"


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
    return (70 - rsi) / 40   # linear: 70→0, 30→1


async def _fetch_24h_tickers(symbols: list[str]) -> dict[str, dict]:
    """Single Binance call returning 24h stats for all USDT pairs."""
    async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=10) as client:
        resp = await client.get("/api/v3/ticker/24hr")
    if resp.status_code != 200:
        raise RuntimeError(f"Binance 24hr ticker returned {resp.status_code}")

    usdt_symbols = {s + "USDT" for s in symbols}
    result: dict[str, dict] = {}
    for item in resp.json():
        sym = item["symbol"]
        if sym in usdt_symbols:
            base = sym[:-4]   # strip "USDT"
            result[base] = {
                "change_24h":  float(item["priceChangePercent"]),
                "volume_usdt": float(item["quoteVolume"]),
                "price":       float(item["lastPrice"]),
            }
    return result


async def _fetch_rsi(symbol: str, client: httpx.AsyncClient) -> float:
    """Fetch 30 daily closes from Binance and compute RSI(14)."""
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
        rs = gain / loss.replace(0, float("nan"))
        rsi = float((100 - 100 / (1 + rs)).iloc[-1])
        return rsi if rsi == rsi else 50.0   # NaN guard
    except Exception:
        return 50.0


class TokenScanner:
    """Rank eligible tokens by momentum and return the top-N for this cycle."""

    def __init__(self, eligible_tokens: list[str]) -> None:
        self._tokens = [t.upper() for t in eligible_tokens]

    async def scan(self, top_n: int = 3) -> list[dict]:
        """Return up to *top_n* token dicts, highest score first.

        Each dict: {symbol, score, change_24h, volume_usdt, rsi, price}
        """
        logger.info("[Scanner] Fetching 24h tickers for %d eligible tokens…", len(self._tokens))
        try:
            tickers = await _fetch_24h_tickers(self._tokens)
        except Exception as exc:
            logger.error("[Scanner] Ticker fetch failed: %s — returning BNB fallback", exc)
            return [{"symbol": "BNB", "score": 0.0, "change_24h": 0.0,
                     "volume_usdt": 0.0, "rsi": 50.0, "price": 0.0}]

        found = [s for s in self._tokens if s in tickers]
        if not found:
            logger.warning("[Scanner] No eligible tokens found in Binance data")
            return [{"symbol": "BNB", "score": 0.0}]

        # Fetch RSI concurrently
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

        # Normalize and score
        changes = [r["change_24h"] for r in rows]
        volumes = [r["volume_usdt"] for r in rows]
        norm_c = _normalize(changes)
        norm_v = _normalize(volumes)

        for row, nc, nv in zip(rows, norm_c, norm_v):
            row["score"] = round(
                0.4 * nc + 0.3 * nv + 0.3 * _rsi_score(row["rsi"]), 4
            )

        rows.sort(key=lambda r: r["score"], reverse=True)
        top = rows[:top_n]

        for r in top:
            logger.info(
                "[Scanner] %s  score=%.3f  24h=%+.1f%%  vol=$%.0fM  RSI=%.1f",
                r["symbol"], r["score"], r["change_24h"],
                r["volume_usdt"] / 1_000_000, r["rsi"],
            )
        return top
