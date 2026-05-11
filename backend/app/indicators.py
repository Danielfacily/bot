import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(close, 12) - ema(close, 26)
    signal = ema(macd_line, 9)
    histogram = macd_line - signal
    return macd_line, signal, histogram


def bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = close.rolling(period).mean()
    std = close.rolling(period).std()
    return middle + std_mult * std, middle, middle - std_mult * std


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(period).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / df["volume"].replace(0, np.nan).cumsum()


def volume_profile(df: pd.DataFrame, bins: int = 12) -> dict:
    if df.empty:
        return {"poc": 0, "bins": []}
    prices = (df["high"] + df["low"] + df["close"]) / 3
    grouped = pd.cut(prices, bins=bins)
    profile = df.groupby(grouped, observed=False)["volume"].sum()
    poc_interval = profile.idxmax()
    poc = float((poc_interval.left + poc_interval.right) / 2)
    return {
        "poc": poc,
        "bins": [{"price": float((idx.left + idx.right) / 2), "volume": float(vol)} for idx, vol in profile.items()],
    }


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema_9"] = ema(out["close"], 9)
    out["ema_21"] = ema(out["close"], 21)
    out["ema_50"] = ema(out["close"], 50)
    out["ema_200"] = ema(out["close"], 200)
    out["rsi"] = rsi(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out["close"])
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger_bands(out["close"])
    out["atr"] = atr(out)
    out["vwap"] = vwap(out)
    out["volume_avg_20"] = out["volume"].rolling(20).mean()
    out["relative_volume"] = out["volume"] / out["volume_avg_20"].replace(0, np.nan)
    out["volatility_relative"] = (out["atr"] / out["close"]) * 100
    out["breakout_high"] = out["close"] > out["high"].rolling(20).max().shift(1)
    out["breakdown_low"] = out["close"] < out["low"].rolling(20).min().shift(1)
    body = (out["close"] - out["open"]).abs()
    candle_range = (out["high"] - out["low"]).replace(0, np.nan)
    out["force_candle"] = (body / candle_range) > 0.65
    upper_wick = out["high"] - out[["open", "close"]].max(axis=1)
    lower_wick = out[["open", "close"]].min(axis=1) - out["low"]
    out["rejection_candle"] = ((upper_wick / candle_range) > 0.45) | ((lower_wick / candle_range) > 0.45)
    return out
