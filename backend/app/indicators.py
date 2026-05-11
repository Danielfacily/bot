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

    return out
