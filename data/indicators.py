import math

import numpy as np
import pandas as pd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Trend
    df["ema_fast"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=21, adjust=False).mean()
    df["sma_20"]   = df["close"].rolling(window=20).mean()
    df["sma_50"]   = df["close"].rolling(window=50).mean()

    # Momentum
    df["rsi"]  = _rsi(df["close"], period=14)
    df["macd"], df["macd_signal"] = _macd(df["close"])
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Volatility
    df["atr"] = _atr(df, period=14)
    bb_mid = df["close"].rolling(window=20).mean()
    bb_std = df["close"].rolling(window=20).std(ddof=0)
    df["bb_middle"] = bb_mid
    df["bb_upper"]  = bb_mid + 2 * bb_std
    df["bb_lower"]  = bb_mid - 2 * bb_std

    return df


def extract_last_row(df: pd.DataFrame) -> dict:
    """Return the most recent indicator values as a plain float dict.

    NaN values (from insufficient history for SMA 50, etc.) fall back to the
    current close price so downstream callers never receive NaN.
    """
    last = df.iloc[-1]
    close = float(last["close"])

    def _f(col: str, fallback: float = 0.0) -> float:
        try:
            v = float(last[col])
            return v if not math.isnan(v) else fallback
        except (KeyError, TypeError, ValueError):
            return fallback

    return {
        "rsi":         _f("rsi",         50.0),
        "macd":        _f("macd",         0.0),
        "macd_signal": _f("macd_signal",  0.0),
        "macd_hist":   _f("macd_hist",    0.0),
        "bb_upper":    _f("bb_upper",    close),
        "bb_middle":   _f("bb_middle",   close),
        "bb_lower":    _f("bb_lower",    close),
        "sma_20":      _f("sma_20",      close),
        "sma_50":      _f("sma_50",      close),
        "atr":         _f("atr",          0.0),
        "ema_fast":    _f("ema_fast",    close),
        "ema_slow":    _f("ema_slow",    close),
    }


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"]  - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    ema_fast    = series.ewm(span=fast,   adjust=False).mean()
    ema_slow    = series.ewm(span=slow,   adjust=False).mean()
    macd        = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    return macd, macd_signal
