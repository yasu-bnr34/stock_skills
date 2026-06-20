"""Technical indicators for pullback-in-uptrend screening (KIK-332).

Indicators based on Monex technical analysis reference (vision/):
- RSI: Wilder's RSI (14-period default)
- Bollinger Bands: ±1σ/2σ/3σ
- Stochastics: Slow%K, Slow%D (oversold<20, overbought>80)
- DMI: +DI, -DI, ADX (trend direction and strength)
- MA Deviation Rate: deviation from MA as % (reversal signal)
"""

import numpy as np
import pandas as pd

from src.core._thresholds import th


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI using Wilder's smoothing method (exponential moving average)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing: alpha = 1/period
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_bollinger_bands(
    close: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (upper, middle, lower) Bollinger Bands."""
    middle = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    return upper, middle, lower


def detect_pullback_in_uptrend(hist: pd.DataFrame) -> dict:
    """Detect pullback buying opportunity in an uptrend.

    Parameters
    ----------
    hist : pd.DataFrame
        DataFrame from yfinance ticker.history() with Close and Volume columns.

    Returns
    -------
    dict
        Pullback analysis results with keys: uptrend, is_pullback, pullback_pct,
        bounce_signal, bounce_score, bounce_details, rsi, volume_ratio, sma50,
        sma200, current_price, recent_high, all_conditions.
    """
    # Default result for insufficient data
    default = {
        "uptrend": False,
        "is_pullback": False,
        "pullback_pct": 0.0,
        "bounce_signal": False,
        "bounce_score": 0.0,
        "bounce_details": {
            "rsi_reversal": False,
            "rsi_depth_bonus": False,
            "bb_proximity": False,
            "volume_surge": False,
            "price_reversal": False,
            "lookback_day": 0,
        },
        "rsi": float("nan"),
        "volume_ratio": float("nan"),
        "sma50": float("nan"),
        "sma200": float("nan"),
        "current_price": float("nan"),
        "recent_high": float("nan"),
        "all_conditions": False,
    }

    close = hist["Close"]
    volume = hist["Volume"]

    # 200-day MA needs ~200 data points
    if len(close) < 200:
        return default

    # Moving averages
    sma50 = close.rolling(window=50).mean()
    sma200 = close.rolling(window=200).mean()

    current_price = float(close.iloc[-1])
    current_sma50 = float(sma50.iloc[-1])
    current_sma200 = float(sma200.iloc[-1])

    # RSI
    rsi_series = compute_rsi(close, period=14)
    current_rsi = float(rsi_series.iloc[-1])
    prev_rsi = float(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else float("nan")

    # Volume ratio: 5-day avg / 20-day avg
    vol_5 = volume.rolling(window=5).mean().iloc[-1]
    vol_20 = volume.rolling(window=20).mean().iloc[-1]
    volume_ratio = float(vol_5 / vol_20) if vol_20 > 0 else float("nan")

    # Recent 60-day high
    recent_high = float(close.iloc[-60:].max())

    # Pullback percentage from recent high
    pullback_pct = (current_price - recent_high) / recent_high if recent_high > 0 else 0.0

    # --- Condition 1: Uptrend ---
    uptrend = (current_price > current_sma200) and (current_sma50 > current_sma200)

    # --- Condition 2: Pullback depth ---
    _pb_min = th("technicals", "pullback_min", -0.20)
    _pb_max = th("technicals", "pullback_max", -0.05)
    is_pullback = (
        (_pb_min <= pullback_pct <= _pb_max)
        and (current_price > current_sma200)
    )

    # --- Condition 3: Bounce signal (score-based with lookback) ---
    _, _, lower_band = compute_bollinger_bands(close, period=20, std_dev=2.0)

    lookback = 5  # Check last 5 trading days for bounce signals
    _rsi_rev_lo = th("technicals", "rsi_reversal_lo", 25.0)
    _rsi_rev_hi = th("technicals", "rsi_reversal_hi", 50.0)
    _rsi_dep_lo = th("technicals", "rsi_depth_lo", 25.0)
    _rsi_dep_hi = th("technicals", "rsi_depth_hi", 35.0)
    _bb_prox = th("technicals", "bb_proximity_mult", 1.02)
    _vol_surge = th("technicals", "volume_surge_ratio", 1.2)
    _sc_rsi_rev = th("technicals", "score_rsi_reversal", 40.0)
    _sc_rsi_dep = th("technicals", "score_rsi_depth", 15.0)
    _sc_bb = th("technicals", "score_bb_proximity", 25.0)
    _sc_vol = th("technicals", "score_volume_surge", 10.0)
    _sc_price = th("technicals", "score_price_reversal", 10.0)
    _bounce_min = th("technicals", "bounce_signal_min", 40.0)

    bounce_score = 0.0
    bounce_details: dict = {
        "rsi_reversal": False,
        "rsi_depth_bonus": False,
        "bb_proximity": False,
        "volume_surge": False,
        "price_reversal": False,
        "lookback_day": 0,
    }

    for offset in range(lookback):
        idx = -1 - offset
        if abs(idx) >= len(close) or abs(idx) >= len(rsi_series):
            break

        day_rsi = float(rsi_series.iloc[idx])
        day_prev_rsi = float(rsi_series.iloc[idx - 1]) if abs(idx - 1) < len(rsi_series) else float("nan")
        day_close = float(close.iloc[idx])
        day_prev_close = float(close.iloc[idx - 1]) if abs(idx - 1) < len(close) else float("nan")
        day_lower = float(lower_band.iloc[idx]) if abs(idx) < len(lower_band) and not np.isnan(lower_band.iloc[idx]) else float("nan")

        # Volume ratio for this specific day
        if abs(idx) < len(volume):
            day_vol_5 = volume.iloc[max(0, len(volume) + idx - 4) : len(volume) + idx + 1].mean()
            day_vol_20 = volume.iloc[max(0, len(volume) + idx - 19) : len(volume) + idx + 1].mean()
            day_volume_ratio = float(day_vol_5 / day_vol_20) if day_vol_20 > 0 else float("nan")
        else:
            day_volume_ratio = float("nan")

        day_score = 0.0
        day_details: dict = {
            "rsi_reversal": False,
            "rsi_depth_bonus": False,
            "bb_proximity": False,
            "volume_surge": False,
            "price_reversal": False,
        }

        # RSI reversal: RSI in reversal zone and turning up
        if (
            _rsi_rev_lo <= day_rsi <= _rsi_rev_hi
            and not np.isnan(day_prev_rsi)
            and day_rsi > day_prev_rsi
        ):
            day_score += _sc_rsi_rev
            day_details["rsi_reversal"] = True

        # RSI depth bonus: deep correction in depth zone
        if _rsi_dep_lo <= day_rsi <= _rsi_dep_hi:
            day_score += _sc_rsi_dep
            day_details["rsi_depth_bonus"] = True

        # BB lower proximity: price within multiplier of lower band
        if not np.isnan(day_lower) and day_lower > 0 and day_close <= day_lower * _bb_prox:
            day_score += _sc_bb
            day_details["bb_proximity"] = True

        # Volume surge bonus
        if not np.isnan(day_volume_ratio) and day_volume_ratio > _vol_surge:
            day_score += _sc_vol
            day_details["volume_surge"] = True

        # Price reversal: close > previous close
        if not np.isnan(day_prev_close) and day_close > day_prev_close:
            day_score += _sc_price
            day_details["price_reversal"] = True

        if day_score > bounce_score:
            bounce_score = day_score
            bounce_details = {**day_details, "lookback_day": offset}

    bounce_signal = bounce_score >= _bounce_min

    all_conditions = uptrend and is_pullback and bounce_signal

    return {
        "uptrend": uptrend,
        "is_pullback": is_pullback,
        "pullback_pct": round(pullback_pct, 4),
        "bounce_signal": bounce_signal,
        "bounce_score": round(bounce_score, 2),
        "bounce_details": bounce_details,
        "rsi": round(current_rsi, 2),
        "volume_ratio": round(volume_ratio, 4) if not np.isnan(volume_ratio) else float("nan"),
        "sma50": round(current_sma50, 2),
        "sma200": round(current_sma200, 2),
        "current_price": round(current_price, 2),
        "recent_high": round(recent_high, 2),
        "all_conditions": all_conditions,
    }


def detect_momentum_surge(
    hist: pd.DataFrame,
    fifty_day_avg_change_pct: float | None = None,
    fifty_two_week_high_change_pct: float | None = None,
) -> dict:
    """Detect momentum surge / breakout signals (KIK-506).

    Parameters
    ----------
    hist : pd.DataFrame
        Price history with Close and Volume columns.
    fifty_day_avg_change_pct : float, optional
        50-day MA deviation (from EquityQuery response). Computed from hist if None.
    fifty_two_week_high_change_pct : float, optional
        52-week high change pct (from EquityQuery response). Computed from hist if None.

    Returns
    -------
    dict with keys:
        ma50_deviation, ma200_deviation, volume_ratio, rsi, surge_level,
        surge_score, near_high, new_high
    """
    default = {
        "ma50_deviation": 0.0,
        "ma200_deviation": 0.0,
        "volume_ratio": float("nan"),
        "rsi": float("nan"),
        "surge_level": "none",
        "surge_score": 0.0,
        "near_high": False,
        "new_high": False,
    }

    close = hist["Close"]
    volume = hist["Volume"]

    if len(close) < 50:
        return default

    # --- 50-day MA deviation ---
    sma50 = close.rolling(window=50).mean()
    current_price = float(close.iloc[-1])
    current_sma50 = float(sma50.iloc[-1])

    if fifty_day_avg_change_pct is not None:
        ma50_deviation = fifty_day_avg_change_pct
    else:
        ma50_deviation = (current_price - current_sma50) / current_sma50 if current_sma50 > 0 else 0.0

    # --- 200-day MA deviation ---
    if len(close) >= 200:
        sma200 = close.rolling(window=200).mean()
        current_sma200 = float(sma200.iloc[-1])
        ma200_deviation = (current_price - current_sma200) / current_sma200 if current_sma200 > 0 else 0.0
        trend_aligned = current_sma50 > current_sma200
    else:
        ma200_deviation = 0.0
        trend_aligned = False

    # --- Volume ratio (5-day / 20-day) ---
    vol_5 = volume.rolling(window=5).mean().iloc[-1]
    vol_20 = volume.rolling(window=20).mean().iloc[-1]
    volume_ratio = float(vol_5 / vol_20) if vol_20 > 0 else float("nan")

    # --- RSI ---
    rsi_series = compute_rsi(close, period=14)
    current_rsi = float(rsi_series.iloc[-1])

    # --- 52-week high proximity ---
    if fifty_two_week_high_change_pct is not None:
        high_change = fifty_two_week_high_change_pct
    else:
        if len(close) >= 252:
            week52_high = float(close.iloc[-252:].max())
        else:
            week52_high = float(close.max())
        high_change = (current_price - week52_high) / week52_high if week52_high > 0 else 0.0

    near_high = high_change >= -0.05  # within 5% of 52-week high
    new_high = high_change >= 0.0     # at or above 52-week high

    # --- Surge score (100pt max) ---
    score = 0.0

    # 50MA deviation: 0-30pt
    abs_dev = abs(ma50_deviation)
    if abs_dev >= 0.30:
        score += 30.0
    elif abs_dev >= 0.20:
        score += 25.0
    elif abs_dev >= 0.10:
        score += 15.0
    elif abs_dev >= 0.05:
        score += 8.0

    # Volume ratio: 0-25pt
    if not np.isnan(volume_ratio):
        if volume_ratio >= 5.0:
            score += 25.0
        elif volume_ratio >= 2.0:
            score += 20.0
        elif volume_ratio >= 1.5:
            score += 10.0

    # 52-week high proximity: 0-20pt
    if new_high:
        score += 20.0
    elif near_high:
        score += 15.0

    # RSI momentum: 0-15pt
    if current_rsi >= 70:
        score += 15.0
    elif current_rsi >= 60:
        score += 10.0

    # Trend alignment (SMA50 > SMA200): 0-10pt
    if trend_aligned:
        score += 10.0

    # --- Surge level classification ---
    if ma50_deviation >= 0.30:
        surge_level = "overheated"
    elif ma50_deviation >= 0.15:
        surge_level = "surging"
    elif ma50_deviation >= 0.10:
        surge_level = "accelerating"
    else:
        surge_level = "none"

    return {
        "ma50_deviation": round(ma50_deviation, 4),
        "ma200_deviation": round(ma200_deviation, 4),
        "volume_ratio": round(volume_ratio, 4) if not np.isnan(volume_ratio) else float("nan"),
        "rsi": round(current_rsi, 2),
        "surge_level": surge_level,
        "surge_score": round(score, 2),
        "near_high": near_high,
        "new_high": new_high,
    }


def compute_stochastics(
    hist: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    slow_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Compute Slow Stochastics (Slow%K, Slow%D).

    Formula (from Monex vision/ reference):
      %K = (Close - Lowest(Low, n)) / (Highest(High, n) - Lowest(Low, n)) × 100
      Fast%D = SMA(d_period) of %K
      Slow%K = Fast%D
      Slow%D = SMA(slow_period) of Slow%K

    Signals:
      Buy  : Slow%D < 20, Slow%K crosses above Slow%D (golden cross)
      Sell : Slow%D > 80, Slow%K crosses below Slow%D (dead cross)

    Parameters
    ----------
    hist : pd.DataFrame
        Price history with High, Low, Close columns.
    k_period : int
        %K lookback period (default 14).
    d_period : int
        Fast%D smoothing (default 3).
    slow_period : int
        Slow%D smoothing (default 3).

    Returns
    -------
    tuple[pd.Series, pd.Series]
        (slow_k, slow_d) — 0-100 range.
    """
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]

    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()

    denom = highest_high - lowest_low
    fast_k = ((close - lowest_low) / denom.where(denom != 0, np.nan)) * 100

    fast_d = fast_k.rolling(window=d_period).mean()
    slow_k = fast_d
    slow_d = slow_k.rolling(window=slow_period).mean()

    return slow_k, slow_d


def compute_dmi(
    hist: pd.DataFrame,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute DMI: +DI, -DI, ADX (Wilder's method).

    Formula (from Monex vision/ reference):
      +DM = max(0, High - prev_High)  when +DM > -DM, else 0
      -DM = max(0, prev_Low - Low)    when -DM > +DM, else 0
      TR  = max(High-Low, |High-prev_Close|, |prev_Close-Low|)
      +DI = EWM(+DM, alpha=1/n) / EWM(TR, alpha=1/n) × 100
      -DI = EWM(-DM, alpha=1/n) / EWM(TR, alpha=1/n) × 100
      DX  = |+DI - -DI| / (+DI + -DI) × 100
      ADX = EWM(DX, alpha=1/n)

    Signals:
      Buy  : +DI crosses above -DI (stronger when ADX is rising)
      Sell : +DI crosses below -DI

    Parameters
    ----------
    hist : pd.DataFrame
        Price history with High, Low, Close columns.
    period : int
        Wilder smoothing period (default 14).

    Returns
    -------
    tuple[pd.Series, pd.Series, pd.Series]
        (plus_di, minus_di, adx)
    """
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (prev_close - low).abs(),
    ], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=close.index)
    minus_dm = pd.Series(0.0, index=close.index)

    cond_plus = (up_move > down_move) & (up_move > 0)
    plus_dm[cond_plus] = up_move[cond_plus]

    cond_minus = (down_move > up_move) & (down_move > 0)
    minus_dm[cond_minus] = down_move[cond_minus]

    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    smooth_plus = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    smooth_minus = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    safe_atr = atr.where(atr != 0, np.nan)
    plus_di = 100.0 * smooth_plus / safe_atr
    minus_di = 100.0 * smooth_minus / safe_atr

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.where(di_sum != 0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return plus_di, minus_di, adx


def detect_short_term_surge(hist: pd.DataFrame) -> dict:
    """Detect short-term price surge for 急騰株 screening.

    Parameters
    ----------
    hist : pd.DataFrame
        Price history with Close and Volume columns (at least 26 rows).

    Returns
    -------
    dict with keys:
        day1_change    : 1-day price change ratio (e.g. 0.05 = +5%)
        day5_change    : 5-day price change ratio
        volume_spike   : today's volume / 20-day average volume
        is_new_52w_high: True if within 1% of 52-week high
        macd_cross     : "golden" / "dead" / "none" (within last 3 days)
        surge_type     : "intraday" / "short_term" / "breakout" / "none"
        short_surge_score: 0-100
    """
    default = {
        "day1_change": 0.0,
        "day5_change": 0.0,
        "volume_spike": float("nan"),
        "is_new_52w_high": False,
        "macd_cross": "none",
        "surge_type": "none",
        "short_surge_score": 0.0,
    }

    close = hist["Close"]
    volume = hist["Volume"]

    if len(close) < 26:
        return default

    current_price = float(close.iloc[-1])

    # 1-day change (ratio)
    prev1 = float(close.iloc[-2]) if len(close) >= 2 else None
    day1_change = (current_price - prev1) / prev1 if prev1 else 0.0

    # 5-day change (ratio)
    prev5 = float(close.iloc[-6]) if len(close) >= 6 else None
    day5_change = (current_price - prev5) / prev5 if prev5 else 0.0

    # Volume spike: today vs 20-day average
    vol_20 = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float("nan")
    today_vol = float(volume.iloc[-1])
    volume_spike = today_vol / vol_20 if not np.isnan(vol_20) and vol_20 > 0 else float("nan")

    # 52-week high proximity
    week52_high = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
    high_change = (current_price - week52_high) / week52_high if week52_high > 0 else 0.0
    is_new_52w_high = high_change >= -0.01

    # MACD cross: check last 3 days for golden/dead cross
    from src.core.screening.momentum import compute_macd
    macd_line, signal_line, _ = compute_macd(close)
    macd_cross = "none"
    for offset in range(1, 4):
        if len(macd_line) < offset + 1:
            break
        curr_m = float(macd_line.iloc[-offset])
        curr_s = float(signal_line.iloc[-offset])
        prev_m = float(macd_line.iloc[-offset - 1])
        prev_s = float(signal_line.iloc[-offset - 1])
        if curr_m > curr_s and prev_m <= prev_s:
            macd_cross = "golden"
            break
        if curr_m < curr_s and prev_m >= prev_s:
            macd_cross = "dead"
            break

    # Surge type classification
    vol_ok = not np.isnan(volume_spike)
    if day1_change >= 0.03 and vol_ok and volume_spike >= 2.0:
        surge_type = "intraday"
    elif day5_change >= 0.08 and vol_ok and volume_spike >= 1.5:
        surge_type = "short_term"
    elif is_new_52w_high and vol_ok and volume_spike >= 1.3:
        surge_type = "breakout"
    else:
        surge_type = "none"

    # Score (0-100): price(40) + volume(30) + 52w high(20) + MACD(10)
    score = 0.0
    if day1_change >= 0.05:
        score += 40.0
    elif day1_change >= 0.03:
        score += 30.0
    elif day1_change >= 0.01:
        score += 15.0

    if vol_ok:
        if volume_spike >= 5.0:
            score += 30.0
        elif volume_spike >= 3.0:
            score += 25.0
        elif volume_spike >= 2.0:
            score += 20.0
        elif volume_spike >= 1.5:
            score += 10.0

    if is_new_52w_high:
        score += 20.0
    elif high_change >= -0.05:
        score += 10.0

    if macd_cross == "golden":
        score += 10.0

    return {
        "day1_change": round(day1_change, 4),
        "day5_change": round(day5_change, 4),
        "volume_spike": round(volume_spike, 2) if not np.isnan(volume_spike) else float("nan"),
        "is_new_52w_high": is_new_52w_high,
        "macd_cross": macd_cross,
        "surge_type": surge_type,
        "short_surge_score": round(score, 2),
    }


def compute_ma_deviation(
    close: pd.Series,
    period: int = 25,
) -> pd.Series:
    """Compute MA Deviation Rate / 移動平均乖離率.

    Formula (from Monex vision/ reference):
      deviation = (Close - MA(n)) / MA(n) × 100

    Signals:
      Sell : large positive deviation (overbought, price too far above MA)
      Buy  : large negative deviation (oversold, price too far below MA)

    Typical thresholds depend on the MA period and instrument:
      25-day MA: sell ~+5-6%, buy ~-8%

    Parameters
    ----------
    close : pd.Series
        Close prices.
    period : int
        MA period. Common values: 5, 25, 75, 100, 200 (daily).

    Returns
    -------
    pd.Series
        Deviation rate as percentage.
    """
    ma = close.rolling(window=period).mean()
    deviation = ((close - ma) / ma.where(ma != 0, np.nan)) * 100
    return deviation
