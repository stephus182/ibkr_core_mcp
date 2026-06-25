from __future__ import annotations

import numpy as np
import pandas as pd


def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["close"].rolling(period).mean()


def ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["close"].ewm(span=period, adjust=False).mean()


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "histogram": macd_line - signal_line},
        index=df.index,
    )


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / df["volume"].cumsum()


def bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = df["close"].rolling(period).mean()
    dev = df["close"].rolling(period).std()
    return pd.DataFrame(
        {"bb_upper": mid + std * dev, "bb_mid": mid, "bb_lower": mid - std * dev},
        index=df.index,
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    lo = df["low"].rolling(k).min()
    hi = df["high"].rolling(k).max()
    pct_k = 100 * (df["close"] - lo) / (hi - lo).replace(0, float("nan"))
    return pd.DataFrame({"stoch_k": pct_k, "stoch_d": pct_k.rolling(d).mean()}, index=df.index)


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi = df["high"].rolling(period).max()
    lo = df["low"].rolling(period).min()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, float("nan"))


def keltner_channels(df: pd.DataFrame, period: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    mid = ema(df, period)
    band = atr_mult * atr(df, period)
    return pd.DataFrame(
        {"kc_upper": mid + band, "kc_mid": mid, "kc_lower": mid - band},
        index=df.index,
    )


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["volume"].rolling(period).mean()


def volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    avg = volume_sma(df, period)
    return df["volume"] / avg.replace(0, float("nan"))


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with all indicator columns appended."""
    out = df.copy()
    out["sma_20"] = sma(df, 20)
    out["ema_20"] = ema(df, 20)
    out["rsi"] = rsi(df, 14)
    _macd = macd(df)
    out["macd"] = _macd["macd"]
    out["macd_signal"] = _macd["macd_signal"]
    out["macd_hist"] = _macd["histogram"]
    out["vwap"] = vwap(df)
    _bb = bollinger_bands(df)
    out["bb_upper"] = _bb["bb_upper"]
    out["bb_mid"] = _bb["bb_mid"]
    out["bb_lower"] = _bb["bb_lower"]
    out["atr"] = atr(df, 14)
    _stoch = stochastic(df)
    out["stoch_k"] = _stoch["stoch_k"]
    out["stoch_d"] = _stoch["stoch_d"]
    out["williams_r"] = williams_r(df)
    _kc = keltner_channels(df)
    out["kc_upper"] = _kc["kc_upper"]
    out["kc_mid"] = _kc["kc_mid"]
    out["kc_lower"] = _kc["kc_lower"]
    out["obv"] = obv(df)
    out["volume_sma"] = volume_sma(df)
    out["volume_ratio"] = volume_ratio(df)
    return out
