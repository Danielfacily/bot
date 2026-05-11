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


def volume_delta(df: pd.DataFrame) -> pd.Series:
    """
    Volume Delta estimado: volume de candles de alta é positivo, de baixa é negativo.
    Indica pressão compradora (+) ou vendedora (-) em cada candle.
    """
    delta = df["volume"].copy().astype(float)
    bearish_mask = df["close"] < df["open"]
    delta[bearish_mask] = -delta[bearish_mask]
    return delta


def adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Average Directional Index (ADX) com DI+ e DI-.
    ADX >= 25 indica tendência, < 25 indica lateralização.
    Retorna: (adx, plus_di, minus_di)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    high_low = high - low
    high_close = (high - close.shift()).abs()
    low_close = (low - close.shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # Suavização de Wilder (EWM com alpha = 1/period)
    atr_smooth = true_range.ewm(alpha=1 / period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=1 / period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * (plus_dm_smooth / atr_smooth.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr_smooth.replace(0, np.nan))

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx_series = dx.ewm(alpha=1 / period, adjust=False).mean()

    return adx_series, plus_di, minus_di


def detect_market_regime(adx_series: pd.Series, threshold: float = 25.0) -> pd.Series:
    """
    Classifica o regime de mercado com base no ADX:
    - 'trending'  : ADX >= threshold (tendência definida, operar a favor)
    - 'ranging'   : ADX <  threshold (lateral, evitar scalping de tendência)
    """
    return pd.Series(
        np.where(adx_series >= threshold, "trending", "ranging"),
        index=adx_series.index,
    )


def swing_highs_lows(df: pd.DataFrame, lookback: int = 5) -> tuple[pd.Series, pd.Series]:
    """
    Detecta swing highs e swing lows locais usando janela simétrica.
    swing_high[i] = True se high[i] é a máxima dos lookback candles adjacentes.
    Os últimos lookback candles ficam como False (janela incompleta).
    """
    window = lookback * 2 + 1
    swing_high = (df["high"] == df["high"].rolling(window, center=True, min_periods=lookback + 1).max()).fillna(False)
    swing_low = (df["low"] == df["low"].rolling(window, center=True, min_periods=lookback + 1).min()).fillna(False)
    return swing_high, swing_low


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """
    Supertrend indicator. Returns (supertrend_line, direction).
    direction: 1 = bullish, -1 = bearish.
    """
    if len(df) == 0:
        return pd.Series(dtype=float), pd.Series(dtype=int)

    hl2 = (df["high"] + df["low"]) / 2
    atr_val = atr(df, period)
    upper_band = (hl2 + multiplier * atr_val).copy()
    lower_band = (hl2 - multiplier * atr_val).copy()

    supertrend_line = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype="float")
    direction.iloc[0] = -1.0
    supertrend_line.iloc[0] = upper_band.iloc[0]

    for i in range(1, len(df)):
        curr_close = float(df["close"].iloc[i])
        prev_close = float(df["close"].iloc[i - 1])
        prev_upper = upper_band.iloc[i - 1]
        prev_lower = lower_band.iloc[i - 1]
        ub = upper_band.iloc[i]
        lb = lower_band.iloc[i]
        if pd.notna(prev_upper) and pd.notna(ub):
            if ub < prev_upper or prev_close > prev_upper:
                upper_band.iloc[i] = ub
            else:
                upper_band.iloc[i] = prev_upper
        if pd.notna(prev_lower) and pd.notna(lb):
            if lb > prev_lower or prev_close < prev_lower:
                lower_band.iloc[i] = lb
            else:
                lower_band.iloc[i] = prev_lower

        prev_st = supertrend_line.iloc[i - 1]
        if pd.isna(prev_st):
            prev_st = upper_band.iloc[i]
        if prev_st == upper_band.iloc[i - 1]:
            if curr_close <= upper_band.iloc[i]:
                supertrend_line.iloc[i] = upper_band.iloc[i]
            else:
                supertrend_line.iloc[i] = lower_band.iloc[i]
        else:
            if curr_close >= lower_band.iloc[i]:
                supertrend_line.iloc[i] = lower_band.iloc[i]
            else:
                supertrend_line.iloc[i] = upper_band.iloc[i]

        direction.iloc[i] = 1.0 if curr_close > supertrend_line.iloc[i] else -1.0

    return supertrend_line, direction.astype("Int64")


def z_score(series: pd.Series, period: int = 20) -> pd.Series:
    """Z-Score: (price - mean) / std. > 2 ou < -2 = desvio extremo."""
    rolling_mean = series.rolling(period).mean()
    rolling_std = series.rolling(period).std()
    return (series - rolling_mean) / rolling_std.replace(0, np.nan)


def market_structure(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Estrutura HH/HL/LH/LL. Retorna: swing_high, swing_low, hh, hl, lh, ll, structure.
    """
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
    # Forward-fill estrutura para manter regime entre swings
    structure = structure.replace("neutral", np.nan).ffill().fillna("neutral")

    out = pd.DataFrame(index=df.index)
    out["swing_high"] = sh
    out["swing_low"] = sl
    out["hh"] = hh.fillna(False)
    out["hl"] = hl.fillna(False)
    out["lh"] = lh.fillna(False)
    out["ll"] = ll.fillna(False)
    out["structure"] = structure
    return out


def volume_spike(volume: pd.Series, period: int = 20, threshold: float = 2.0) -> pd.Series:
    """Spike: volume atual > threshold * média dos últimos period candles."""
    vol_ma = volume.rolling(period).mean()
    return volume > (vol_ma * threshold)


def liquidity_zones(df: pd.DataFrame, lookback: int = 50) -> dict:
    """
    Zonas de liquidez: acima de swing highs e abaixo de swing lows.
    Retorna as 3 zonas mais relevantes acima/abaixo do preço atual.
    """
    sh, sl = swing_highs_lows(df.tail(lookback), lookback=3)
    current_price = float(df["close"].iloc[-1])
    sh_prices = df["high"][sh].tail(lookback).values.tolist()
    sl_prices = df["low"][sl].tail(lookback).values.tolist()

    above = sorted([p for p in sh_prices if p > current_price])[:3]
    below = sorted([p for p in sl_prices if p < current_price], reverse=True)[:3]

    return {"liquidity_above": above, "liquidity_below": below}


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula e adiciona todos os indicadores técnicos ao DataFrame de candles.
    Colunas adicionadas:
      ema_9, ema_21, ema_50, ema_200           — médias móveis exponenciais
      rsi                                       — RSI 14 períodos
      macd, macd_signal, macd_hist              — MACD padrão (12/26/9)
      bb_upper, bb_mid, bb_lower                — Bollinger Bands 20/2
      atr                                       — ATR 14 períodos
      vwap                                      — VWAP cumulativo
      volume_avg_20                             — média de volume 20 candles
      relative_volume                           — volume / média 20 candles
      volatility_relative                       — (ATR / close) * 100 em %
      volume_delta                              — pressão compradora/vendedora por candle
      adx, plus_di, minus_di                   — indicadores de tendência (ADX)
      market_regime                             — "trending" ou "ranging"
      breakout_high                             — fechou acima da máxima dos últimos 20 candles
      breakdown_low                             — fechou abaixo da mínima dos últimos 20 candles
      force_candle                              — corpo do candle >= 65% do range
      rejection_candle                          — sombra superior ou inferior >= 45% do range
    """
    out = df.copy()

    # Médias móveis
    out["ema_9"] = ema(out["close"], 9)
    out["ema_21"] = ema(out["close"], 21)
    out["ema_50"] = ema(out["close"], 50)
    out["ema_200"] = ema(out["close"], 200)

    # Osciladores
    out["rsi"] = rsi(out["close"])
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(out["close"])

    # Volatilidade
    out["bb_upper"], out["bb_mid"], out["bb_lower"] = bollinger_bands(out["close"])
    out["atr"] = atr(out)

    # Volume
    out["vwap"] = vwap(out)
    out["volume_avg_20"] = out["volume"].rolling(20).mean()
    out["relative_volume"] = out["volume"] / out["volume_avg_20"].replace(0, np.nan)
    out["volume_delta"] = volume_delta(out)
    out["volume_delta_ma"] = out["volume_delta"].rolling(10).mean()

    # Métricas de volatilidade relativa
    out["volatility_relative"] = (out["atr"] / out["close"]) * 100

    # Força da tendência — ADX
    out["adx"], out["plus_di"], out["minus_di"] = adx(out)
    out["market_regime"] = detect_market_regime(out["adx"])

    # Padrões de preço
    out["breakout_high"] = out["close"] > out["high"].rolling(20).max().shift(1)
    out["breakdown_low"] = out["close"] < out["low"].rolling(20).min().shift(1)

    body = (out["close"] - out["open"]).abs()
    candle_range = (out["high"] - out["low"]).replace(0, np.nan)
    out["force_candle"] = (body / candle_range) > 0.65

    upper_wick = out["high"] - out[["open", "close"]].max(axis=1)
    lower_wick = out[["open", "close"]].min(axis=1) - out["low"]
    out["rejection_candle"] = ((upper_wick / candle_range) > 0.45) | ((lower_wick / candle_range) > 0.45)

    # Supertrend, Z-Score
    try:
        st_line, st_dir = supertrend(out)
        out["supertrend"] = st_line
        out["supertrend_dir"] = st_dir
    except Exception:
        out["supertrend"] = np.nan
        out["supertrend_dir"] = 0

    out["z_score"] = z_score(out["close"])

    # Estrutura de mercado
    try:
        struct = market_structure(out)
        out["hh"] = struct["hh"]
        out["hl"] = struct["hl"]
        out["lh"] = struct["lh"]
        out["ll"] = struct["ll"]
        out["market_structure"] = struct["structure"]
        out["swing_high"] = struct["swing_high"]
        out["swing_low"] = struct["swing_low"]
    except Exception:
        out["market_structure"] = "neutral"

    out["volume_spike"] = volume_spike(out["volume"])

    return out
