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
    high = df["high"]
    low = df["low"]
    n = len(df)
    sh = pd.Series(False, index=df.index)
    sl = pd.Series(False, index=df.index)
    if n < (2 * lookback + 1):
        return sh, sl
    for i in range(lookback, n - lookback):
        window_h = high.iloc[i - lookback : i + lookback + 1]
        window_l = low.iloc[i - lookback : i + lookback + 1]
        if high.iloc[i] == window_h.max() and (window_h == high.iloc[i]).sum() == 1:
            sh.iloc[i] = True
        if low.iloc[i] == window_l.min() and (window_l == low.iloc[i]).sum() == 1:
            sl.iloc[i] = True
    return sh, sl


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """Supertrend. Retorna (linha, direção). direction=1 alta, -1 baixa."""
    hl2 = (df["high"] + df["low"]) / 2
    atr_val = atr(df, period)
    upper_band = (hl2 + multiplier * atr_val).copy()
    lower_band = (hl2 - multiplier * atr_val).copy()
    supertrend_line = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)
    if len(df) == 0:
        return supertrend_line, direction
    supertrend_line.iloc[0] = float(upper_band.iloc[0]) if not pd.isna(upper_band.iloc[0]) else float(df["close"].iloc[0])
    direction.iloc[0] = -1
    for i in range(1, len(df)):
        ub_prev = upper_band.iloc[i - 1]
        lb_prev = lower_band.iloc[i - 1]
        ub_cur = upper_band.iloc[i]
        lb_cur = lower_band.iloc[i]
        prev_close = df["close"].iloc[i - 1]
        curr_close = df["close"].iloc[i]
        if not pd.isna(ub_prev) and not pd.isna(ub_cur):
            upper_band.iloc[i] = ub_cur if (ub_cur < ub_prev or prev_close > ub_prev) else ub_prev
        if not pd.isna(lb_prev) and not pd.isna(lb_cur):
            lower_band.iloc[i] = lb_cur if (lb_cur > lb_prev or prev_close < lb_prev) else lb_prev
        prev_st = supertrend_line.iloc[i - 1]
        if pd.isna(prev_st) or pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
            supertrend_line.iloc[i] = upper_band.iloc[i] if not pd.isna(upper_band.iloc[i]) else curr_close
            direction.iloc[i] = -1
            continue
        if prev_st == ub_prev:
            supertrend_line.iloc[i] = upper_band.iloc[i] if curr_close <= upper_band.iloc[i] else lower_band.iloc[i]
        else:
            supertrend_line.iloc[i] = lower_band.iloc[i] if curr_close >= lower_band.iloc[i] else upper_band.iloc[i]
        direction.iloc[i] = 1 if curr_close > supertrend_line.iloc[i] else -1
    return supertrend_line, direction.astype(int)


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
