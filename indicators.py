# indicators.py
"""
Technical indicators used by Blueprint Trader AI:
- EMA
- RSI
"""

from typing import List, Optional


def ema(values: List[float], period: int) -> Optional[float]:
    """
    Return the latest EMA value for the given period.
    values: oldest -> newest
    """
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period  # simple MA start
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """
    Classic RSI calculation, returns latest RSI.
    values: oldest -> newest
    """
    if len(values) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)

    # initial averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
