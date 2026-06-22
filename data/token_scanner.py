"""Token momentum scanner — dual-source (Binance + DexScreener), 5-factor scoring.

Score formula (per token):
  30% × norm(1h_change)        — short-term momentum
  20% × norm(4h_change)        — medium-term trend
  25% × norm(volume_spike)     — volume vs 24h avg hourly (spike detection)
  15% × rsi_score(rsi_1h)      — not overbought/oversold (ideal 40–65)
  10% × norm(sma20_distance)   — price above/below 20-period SMA (trend direction)

Data sources:
  Binance — bulk 24h ticker + per-token 1h klines (fast, covers ~90% of competition tokens)
  DexScreener — fallback for BSC-only tokens not listed on Binance
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pandas as pd

from agent.config import config

logger = logging.getLogger(__name__)

BINANCE_BASE     = "https://api.binance.com"
DEXSCREENER_BASE = "https://api.dexscreener.com"

# Minimum 24h USD volume to be considered tradeable
_MIN_VOLUME_USD = 20_000

# Stablecoins — excluded (no directional signal)
_STABLECOINS = {
    "USDT", "USDC", "DAI", "FDUSD", "FRAX", "TUSD", "USD1", "USDE", "USDD",
    "DUSD", "FRXUSD", "USDF", "LISUSDT", "XUSD", "BUSD", "USDP", "GUSD",
    "EURI", "STABLE", "LISUSD",
}

# BSC-only tokens (not on Binance) — scraped from competition list
# These will be tried via DexScreener if Binance returns nothing
_BSC_ONLY_TOKENS = {
    "PIEVERSE", "SIREN", "KITE", "BEAT", "EDGE", "NIGHT", "GWEI", "GENIUS",
    "SKYAI", "TAG", "NXPC", "SAHARA", "RIVER", "MYX", "RAVE", "BILL",
    "KOGE", "ALE", "GOMINING", "VCNT", "GUA", "SMILEK", "BSB", "TOSHI",
    "BAS", "LUR", "BARD", "COAI", "BDCA", "XAUM", "WFI", "AB",
}


def _normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _rsi_score_1h(rsi: float) -> float:
    """Score 1.0 in the ideal scalp zone (45–60), 0.0 at extremes."""
    if rsi >= 70:
        return 0.0
    if rsi <= 30:
        return 0.3   # oversold is a BUY setup, still worth considering
    if 45 <= rsi <= 65:
        return 1.0   # sweet spot for scalping
    if rsi < 45:
        return (rsi - 30) / 15  # 30→45 linearly 0→1
    return (70 - rsi) / 5       # 65→70 linearly 1→0


async def _fetch_binance_24h(symbols: list[str]) -> dict[str, dict]:
    """Bulk-fetch 24h tickers from Binance for all symbols at once."""
    async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=12) as client:
        resp = await client.get("/api/v3/ticker/24hr")
    if resp.status_code != 200:
        raise RuntimeError(f"Binance 24hr ticker returned {resp.status_code}")
    usdt_map = {s + "USDT": s for s in symbols}
    result: dict[str, dict] = {}
    for item in resp.json():
        sym = item["symbol"]
        if sym in usdt_map:
            base = usdt_map[sym]
            vol = float(item["quoteVolume"])
            if vol < _MIN_VOLUME_USD:
                continue
            result[base] = {
                "change_24h":  float(item["priceChangePercent"]),
                "volume_usdt": vol,
                "price":       float(item["lastPrice"]),
            }
    return result


async def _fetch_1h_klines(symbol: str, client: httpx.AsyncClient) -> dict | None:
    """Fetch last 30 hourly candles for a symbol and compute all derived indicators."""
    try:
        resp = await client.get(
            "/api/v3/klines",
            params={"symbol": symbol + "USDT", "interval": "1h", "limit": 30},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        klines = resp.json()
        if len(klines) < 6:
            return None

        closes  = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        # 1h change: last closed candle vs one before it
        change_1h = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0.0

        # 4h change: last close vs close 4 periods ago
        change_4h = (closes[-1] - closes[-5]) / closes[-5] * 100 if closes[-5] else 0.0

        # Volume spike: last candle volume vs 24h average hourly
        avg_vol_1h = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
        volume_spike = volumes[-1] / avg_vol_1h if avg_vol_1h > 0 else 1.0

        # SMA20 distance (how far price is above/below 20-period SMA)
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sum(closes) / len(closes)
        sma20_distance = (closes[-1] - sma20) / sma20 * 100

        # RSI 14 on hourly closes
        series = pd.Series(closes)
        delta  = series.diff()
        gain   = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss   = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs     = gain / loss.replace(0, float("nan"))
        rsi_series = 100 - 100 / (1 + rs)
        rsi_1h = float(rsi_series.iloc[-1]) if rsi_series.iloc[-1] == rsi_series.iloc[-1] else 50.0

        return {
            "change_1h":     round(change_1h, 3),
            "change_4h":     round(change_4h, 3),
            "volume_spike":  round(volume_spike, 3),
            "rsi_1h":        round(rsi_1h, 2),
            "sma20_distance": round(sma20_distance, 3),
        }
    except Exception as exc:
        logger.debug("[Scanner] klines failed for %s: %s", symbol, exc)
        return None


async def _fetch_dexscreener_token(symbol: str, client: httpx.AsyncClient) -> dict | None:
    """Try DexScreener search for a BSC token not listed on Binance."""
    try:
        resp = await client.get(
            f"/latest/dex/search",
            params={"q": symbol},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        pairs = resp.json().get("pairs") or []
        # Filter to BSC pairs with sufficient liquidity
        bsc_pairs = [
            p for p in pairs
            if p.get("chainId") == "bsc"
            and float(p.get("liquidity", {}).get("usd", 0) or 0) >= 20_000
            and p.get("quoteToken", {}).get("symbol", "").upper() in ("USDT", "BUSD", "USDC")
        ]
        if not bsc_pairs:
            return None
        # Take highest-liquidity pair
        best = max(bsc_pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
        pc = best.get("priceChange", {})
        vol = best.get("volume", {})
        liq = float(best.get("liquidity", {}).get("usd", 0) or 0)
        vol_24h = float(vol.get("h24", 0) or 0)
        if vol_24h < _MIN_VOLUME_USD:
            return None
        change_1h  = float(pc.get("h1", 0) or 0)
        change_4h  = float(pc.get("h6", 0) or 0) * (4 / 6)  # approximate from 6h
        change_24h = float(pc.get("h24", 0) or 0)
        price      = float(best.get("priceUsd", 0) or 0)
        avg_vol_1h = vol_24h / 24
        vol_1h     = float(vol.get("h1", 0) or 0)
        volume_spike = vol_1h / avg_vol_1h if avg_vol_1h > 0 else 1.0
        return {
            "change_1h":     round(change_1h, 3),
            "change_4h":     round(change_4h, 3),
            "change_24h":    round(change_24h, 3),
            "volume_usdt":   round(vol_24h, 0),
            "volume_spike":  round(volume_spike, 3),
            "rsi_1h":        50.0,          # DexScreener doesn't provide RSI
            "sma20_distance": 0.0,
            "price":         round(price, 8),
            "data_source":   "dexscreener",
        }
    except Exception as exc:
        logger.debug("[Scanner] DexScreener failed for %s: %s", symbol, exc)
        return None


class TokenScanner:
    """Rank eligible competition tokens by scalping momentum score."""

    def __init__(self, eligible_tokens: list[str] | None = None) -> None:
        tokens = eligible_tokens or config.ELIGIBLE_TOKENS
        self._tokens = [t.upper() for t in tokens if t.upper() not in _STABLECOINS]

    async def scan(self, top_n: int = 10) -> list[dict]:
        """Score all eligible tokens and return top_n highest-scoring."""
        logger.info("[Scanner] Scanning %d tokens (stablecoins excluded)…", len(self._tokens))

        # ── Phase 1: Binance bulk 24h fetch ──────────────────────────────
        try:
            base_data = await _fetch_binance_24h(self._tokens)
        except Exception as exc:
            logger.error("[Scanner] Binance bulk fetch failed: %s — returning ETH fallback", exc)
            return [{"symbol": "ETH", "score": 0.5, "change_1h": 0.0, "change_4h": 0.0,
                     "change_24h": 0.0, "volume_usdt": 0.0, "volume_spike": 1.0,
                     "rsi_1h": 50.0, "price": 0.0, "sma20_distance": 0.0,
                     "data_source": "fallback", "rank": 1}]

        found_on_binance = list(base_data.keys())
        logger.info("[Scanner] Found %d/%d tokens on Binance", len(found_on_binance), len(self._tokens))

        # ── Phase 2: 1h klines for top-50 by volume ──────────────────────
        by_volume = sorted(found_on_binance, key=lambda s: base_data[s]["volume_usdt"], reverse=True)
        kline_candidates = by_volume[:50]

        async with httpx.AsyncClient(base_url=BINANCE_BASE, timeout=12) as client:
            kline_results = await asyncio.gather(
                *[_fetch_1h_klines(s, client) for s in kline_candidates],
                return_exceptions=True,
            )

        rows: list[dict] = []
        for sym, kdata in zip(kline_candidates, kline_results):
            if isinstance(kdata, Exception) or kdata is None:
                kdata = {
                    "change_1h": base_data[sym]["change_24h"] / 24,
                    "change_4h": base_data[sym]["change_24h"] / 6,
                    "volume_spike": 1.0,
                    "rsi_1h": 50.0,
                    "sma20_distance": 0.0,
                }
            rows.append({
                "symbol":        sym,
                "change_1h":     kdata["change_1h"],
                "change_4h":     kdata["change_4h"],
                "change_24h":    base_data[sym]["change_24h"],
                "volume_usdt":   base_data[sym]["volume_usdt"],
                "volume_spike":  kdata["volume_spike"],
                "rsi_1h":        kdata["rsi_1h"],
                "price":         base_data[sym]["price"],
                "sma20_distance": kdata["sma20_distance"],
                "data_source":   "binance",
            })

        # ── Phase 3: DexScreener for BSC-only tokens not on Binance ──────
        missing = [t for t in self._tokens if t not in base_data and t in _BSC_ONLY_TOKENS][:15]
        if missing:
            async with httpx.AsyncClient(base_url=DEXSCREENER_BASE, timeout=15) as dex_client:
                dex_results = await asyncio.gather(
                    *[_fetch_dexscreener_token(s, dex_client) for s in missing],
                    return_exceptions=True,
                )
            for sym, ddata in zip(missing, dex_results):
                if isinstance(ddata, Exception) or ddata is None:
                    continue
                rows.append({"symbol": sym, **ddata})
            logger.info("[Scanner] DexScreener added %d BSC-only tokens",
                        sum(1 for r in dex_results if r and not isinstance(r, Exception)))

        if not rows:
            return [{"symbol": "ETH", "score": 0.5, "change_1h": 0.0, "change_4h": 0.0,
                     "change_24h": 0.0, "volume_usdt": 0.0, "volume_spike": 1.0,
                     "rsi_1h": 50.0, "price": 0.0, "sma20_distance": 0.0,
                     "data_source": "fallback", "rank": 1}]

        # ── Phase 4: Score and rank ───────────────────────────────────────
        scored = self._score_tokens(rows)
        scored.sort(key=lambda r: r["score"], reverse=True)

        # Assign ranks
        for i, r in enumerate(scored):
            r["rank"] = i + 1

        top = scored[:top_n]
        for r in top:
            logger.info(
                "[Scanner] #%d %s  score=%.3f  1h=%+.1f%%  4h=%+.1f%%  "
                "vol_spike=%.1fx  RSI=%.0f  sma_dist=%+.1f%%  src=%s",
                r["rank"], r["symbol"], r["score"],
                r["change_1h"], r["change_4h"],
                r["volume_spike"], r["rsi_1h"], r["sma20_distance"],
                r["data_source"],
            )

        logger.info("[Scanner] Ranked %d tokens, returning top %d", len(scored), len(top))
        return top

    def _score_tokens(self, rows: list[dict]) -> list[dict]:
        """Apply 5-factor weighted scoring in-place and return rows."""
        # Separate sign-aware fields so absolute momentum counts
        change_1h_abs  = [abs(r["change_1h"]) for r in rows]
        change_4h_abs  = [abs(r["change_4h"]) for r in rows]
        volume_spikes  = [max(0.0, r["volume_spike"]) for r in rows]
        sma_distances  = [r["sma20_distance"] for r in rows]

        n_c1 = _normalize(change_1h_abs)
        n_c4 = _normalize(change_4h_abs)
        n_vs = _normalize(volume_spikes)
        n_sd = _normalize(sma_distances)

        for row, nc1, nc4, nvs, nsd in zip(rows, n_c1, n_c4, n_vs, n_sd):
            rsi_s = _rsi_score_1h(row["rsi_1h"])
            row["score"] = round(
                0.30 * nc1 +
                0.20 * nc4 +
                0.25 * nvs +
                0.15 * rsi_s +
                0.10 * nsd,
                4,
            )

        return rows

    @property
    def token_count(self) -> int:
        return len(self._tokens)
