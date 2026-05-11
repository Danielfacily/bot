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


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — força de tendência."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_val = tr.rolling(period).mean().replace(0, np.nan)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr_val)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr_val)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    return dx.rolling(period).mean()


def swing_highs_lows(df: pd.DataFrame, lookback: int = 5) -> tuple[pd.Series, pd.Series]:
    """Identifica swing highs/lows com janela simétrica. Retorna (sh_bool, sl_bool)."""
    high = df["high"].values
    low = df["low"].values
    n = len(high)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    if n < (2 * lookback + 1):
        return pd.Series(sh, index=df.index), pd.Series(sl, index=df.index)
    for i in range(lookback, n - lookback):
        wh = high[i - lookback: i + lookback + 1]
        wl = low[i - lookback: i + lookback + 1]
        if high[i] == wh.max() and (wh == high[i]).sum() == 1:
            sh[i] = True
        if low[i] == wl.min() and (wl == low[i]).sum() == 1:
            sl[i] = True
    return pd.Series(sh, index=df.index), pd.Series(sl, index=df.index)


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Supertrend. Retorna (linha, direção). direction=1 alta, -1 baixa."""
    hl2 = ((df["high"] + df["low"]) / 2).values
    atr_vals = atr(df, period).values
    close = df["close"].values
    n = len(close)

    upper = hl2 + multiplier * atr_vals
    lower = hl2 - multiplier * atr_vals
    st = np.full(n, np.nan)
    direction = np.full(n, -1, dtype=int)

    if n == 0:
        return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)

    st[0] = upper[0] if not np.isnan(upper[0]) else close[0]

    for i in range(1, n):
        if np.isnan(atr_vals[i]):
            st[i] = upper[i] if not np.isnan(upper[i]) else close[i]
            direction[i] = -1
            continue
        # Adjust bands (Wilder's method)
        if not np.isnan(upper[i - 1]):
            upper[i] = upper[i] if (upper[i] < upper[i - 1] or close[i - 1] > upper[i - 1]) else upper[i - 1]
        if not np.isnan(lower[i - 1]):
            lower[i] = lower[i] if (lower[i] > lower[i - 1] or close[i - 1] < lower[i - 1]) else lower[i - 1]
        prev_st = st[i - 1]
        if np.isnan(prev_st):
            st[i] = upper[i]
            direction[i] = -1
        elif prev_st == upper[i - 1]:
            st[i] = upper[i] if close[i] <= upper[i] else lower[i]
        else:
            st[i] = lower[i] if close[i] >= lower[i] else upper[i]
        direction[i] = 1 if close[i] > st[i] else -1

    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def z_score(series: pd.Series, period: int = 20) -> pd.Series:
    """Z-Score: (price - mean) / std."""
    rolling_mean = series.rolling(period).mean()
    rolling_std = series.rolling(period).std()
    return (series - rolling_mean) / rolling_std.replace(0, np.nan)


def market_structure(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Detecta estrutura HH/HL/LH/LL."""
    high = df["high"]
    low = df["low"]
    sh, sl = swing_highs_lows(df, lookback=lookback)
    sh_values = high.where(sh).ffill()
    sl_values = low.where(sl).ffill()
    hh = sh & (high > sh_values.shift(1))
    hl = sl & (low > sl_values.shift(1))
    lh = sh & (high < sh_values.shift(1))
    ll = sl & (low < sl_values.shift(1))
    structure = pd.Series("neutral", index=df.index)
    structure[hh | hl] = "bullish"
    structure[lh | ll] = "bearish"
    # Forward fill structure for continuity
    structure = structure.replace("neutral", np.nan).ffill().fillna("neutral")
    out = pd.DataFrame(index=df.index)
    out["swing_high"] = sh
    out["swing_low"] = sl
    out["hh"] = hh
    out["hl"] = hl
    out["lh"] = lh
    out["ll"] = ll
    out["structure"] = structure
    return out


def volume_spike(volume: pd.Series, period: int = 20, threshold: float = 2.0) -> pd.Series:
    """Spike de volume: > threshold * média(period)."""
    vol_ma = volume.rolling(period).mean()
    return volume > (vol_ma * threshold)


def liquidity_zones(df: pd.DataFrame, lookback: int = 50) -> dict:
    """Top 3 zonas de liquidez acima e abaixo do preço atual."""
    if len(df) == 0:
        return {"liquidity_above": [], "liquidity_below": []}
    tail = df.tail(lookback)
    sh, sl = swing_highs_lows(tail, lookback=3)
    current_price = float(df["close"].iloc[-1])
    sh_prices = tail["high"][sh].values.tolist()
    sl_prices = tail["low"][sl].values.tolist()
    above = sorted([float(p) for p in sh_prices if p > current_price])[:3]
    below = sorted([float(p) for p in sl_prices if p < current_price], reverse=True)[:3]
    return {"liquidity_above": above, "liquidity_below": below}


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
    out["adx"] = adx(out)
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
    # Volume delta proxy: taker buy volume vs sell, if available
    if "taker_buy_base" in out.columns:
        delta = (out["taker_buy_base"] * 2) - out["volume"]
        out["volume_delta_ma"] = delta.rolling(10).mean()
    else:
        signed = np.where(out["close"] > out["open"], out["volume"], -out["volume"])
        out["volume_delta_ma"] = pd.Series(signed, index=out.index).rolling(10).mean()
    # Supertrend
    st_line, st_dir = supertrend(out)
    out["supertrend"] = st_line
    out["supertrend_dir"] = st_dir
    # Z-score
    out["z_score"] = z_score(out["close"])
    # Market structure
    struct = market_structure(out)
    out["hh"] = struct["hh"]
    out["hl"] = struct["hl"]
    out["lh"] = struct["lh"]
    out["ll"] = struct["ll"]
    out["market_structure"] = struct["structure"]
    out["swing_high"] = struct["swing_high"]
    out["swing_low"] = struct["swing_low"]
    # Volume spike
    out["volume_spike"] = volume_spike(out["volume"])
    # Market regime: simple heuristic based on adx
    out["market_regime"] = pd.Series(
        np.where(out["adx"] >= 25, "trending", "ranging"),
        index=out.index,
    )
    return out
