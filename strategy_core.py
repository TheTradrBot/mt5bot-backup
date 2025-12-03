"""
Strategy Core Module for Blueprint Trader AI.

This module provides the single source of truth for trading rules,
used by both backtests and live scanning/Discord outputs.

The strategy is parameterized to allow optimization while staying
faithful to the Blueprint confluence-based approach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any


@dataclass
class StrategyParams:
    """
    Strategy parameters that can be optimized.
    
    These control confluence thresholds, SL/TP ratios, filters, etc.
    """
    min_confluence: int = 2
    min_quality_factors: int = 1
    
    atr_sl_multiplier: float = 1.5
    atr_tp1_multiplier: float = 0.6
    atr_tp2_multiplier: float = 1.1
    atr_tp3_multiplier: float = 1.8
    
    fib_low: float = 0.382
    fib_high: float = 0.886
    
    structure_sl_lookback: int = 35
    liquidity_sweep_lookback: int = 12
    
    use_htf_filter: bool = True
    use_structure_filter: bool = True
    use_liquidity_filter: bool = True
    use_fib_filter: bool = True
    use_confirmation_filter: bool = True
    
    require_htf_alignment: bool = False
    require_confirmation_for_active: bool = True
    require_rr_for_active: bool = True
    
    min_rr_ratio: float = 1.0
    risk_per_trade_pct: float = 1.0
    
    cooldown_bars: int = 0
    max_open_trades: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert parameters to dictionary."""
        return {
            "min_confluence": self.min_confluence,
            "min_quality_factors": self.min_quality_factors,
            "atr_sl_multiplier": self.atr_sl_multiplier,
            "atr_tp1_multiplier": self.atr_tp1_multiplier,
            "atr_tp2_multiplier": self.atr_tp2_multiplier,
            "atr_tp3_multiplier": self.atr_tp3_multiplier,
            "fib_low": self.fib_low,
            "fib_high": self.fib_high,
            "structure_sl_lookback": self.structure_sl_lookback,
            "liquidity_sweep_lookback": self.liquidity_sweep_lookback,
            "use_htf_filter": self.use_htf_filter,
            "use_structure_filter": self.use_structure_filter,
            "use_liquidity_filter": self.use_liquidity_filter,
            "use_fib_filter": self.use_fib_filter,
            "use_confirmation_filter": self.use_confirmation_filter,
            "require_htf_alignment": self.require_htf_alignment,
            "require_confirmation_for_active": self.require_confirmation_for_active,
            "require_rr_for_active": self.require_rr_for_active,
            "min_rr_ratio": self.min_rr_ratio,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "cooldown_bars": self.cooldown_bars,
            "max_open_trades": self.max_open_trades,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StrategyParams":
        """Create parameters from dictionary."""
        return cls(**{k: v for k, v in d.items() if hasattr(cls, k)})


@dataclass
class Signal:
    """Represents a trading signal/setup."""
    symbol: str
    direction: str
    bar_index: int
    timestamp: Any
    
    confluence_score: int = 0
    quality_factors: int = 0
    
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    
    is_active: bool = False
    is_watching: bool = False
    
    flags: Dict[str, bool] = field(default_factory=dict)
    notes: Dict[str, str] = field(default_factory=dict)


@dataclass
class Trade:
    """Represents a completed trade for backtest analysis."""
    symbol: str
    direction: str
    entry_date: Any
    exit_date: Any
    entry_price: float
    exit_price: float
    stop_loss: float
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    
    risk: float = 0.0
    reward: float = 0.0
    rr: float = 0.0
    
    is_winner: bool = False
    exit_reason: str = ""
    
    confluence_score: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert trade to dictionary."""
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_date": str(self.entry_date),
            "exit_date": str(self.exit_date),
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "risk": self.risk,
            "reward": self.reward,
            "rr": self.rr,
            "is_winner": self.is_winner,
            "exit_reason": self.exit_reason,
            "confluence_score": self.confluence_score,
        }


def _atr(candles: List[Dict], period: int = 14) -> float:
    """
    Calculate Average True Range (ATR).
    
    Args:
        candles: List of OHLCV candle dictionaries
        period: ATR period (default 14)
    
    Returns:
        ATR value or 0 if insufficient data
    """
    if len(candles) < period + 1:
        return 0.0
    
    tr_values = []
    for i in range(1, len(candles)):
        high = candles[i].get("high")
        low = candles[i].get("low")
        prev_close = candles[i - 1].get("close")
        
        if high is None or low is None or prev_close is None:
            continue
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_values.append(tr)
    
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values) if tr_values else 0.0
    
    atr_val = sum(tr_values[:period]) / period
    for tr in tr_values[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    
    return atr_val


def _find_pivots(candles: List[Dict], lookback: int = 5) -> Tuple[List[float], List[float]]:
    """
    Find swing highs and swing lows in candle data.
    
    Args:
        candles: List of OHLCV candle dictionaries
        lookback: Number of bars to look back/forward for pivot identification
    
    Returns:
        Tuple of (swing_highs, swing_lows) as lists of price levels
    """
    if len(candles) < lookback * 2 + 1:
        return [], []
    
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]
        
        is_swing_high = True
        is_swing_low = True
        
        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if candles[j]["high"] > high:
                is_swing_high = False
            if candles[j]["low"] < low:
                is_swing_low = False
        
        if is_swing_high:
            swing_highs.append(high)
        if is_swing_low:
            swing_lows.append(low)
    
    return swing_highs, swing_lows


def _infer_trend(candles: List[Dict], ema_short: int = 8, ema_long: int = 21) -> str:
    """
    Infer trend direction from candle data using EMA crossover and price action.
    
    Args:
        candles: List of OHLCV candle dictionaries
        ema_short: Short EMA period
        ema_long: Long EMA period
    
    Returns:
        "bullish", "bearish", or "mixed"
    """
    if not candles or len(candles) < ema_long + 5:
        return "mixed"
    
    closes = [c["close"] for c in candles if c.get("close") is not None]
    
    if len(closes) < ema_long + 5:
        return "mixed"
    
    def calc_ema(values: List[float], period: int) -> float:
        if len(values) < period:
            valid_values = [v for v in values if v is not None and v == v]
            return sum(valid_values) / len(valid_values) if valid_values else 0
        k = 2 / (period + 1)
        initial_values = [v for v in values[:period] if v is not None and v == v]
        if not initial_values:
            return 0
        ema = sum(initial_values) / len(initial_values)
        for price in values[period:]:
            if price is not None and price == price:
                ema = price * k + ema * (1 - k)
        return ema
    
    ema_s = calc_ema(closes, ema_short)
    ema_l = calc_ema(closes, ema_long)
    
    current_price = closes[-1]
    recent_high = max(c["high"] for c in candles[-10:])
    recent_low = min(c["low"] for c in candles[-10:])
    
    bullish_signals = 0
    bearish_signals = 0
    
    if ema_s > ema_l:
        bullish_signals += 1
    else:
        bearish_signals += 1
    
    if current_price > ema_l:
        bullish_signals += 1
    else:
        bearish_signals += 1
    
    if len(closes) >= 20:
        higher_highs = closes[-1] > max(closes[-10:-1]) if len(closes) > 10 else False
        lower_lows = closes[-1] < min(closes[-10:-1]) if len(closes) > 10 else False
        
        if higher_highs:
            bullish_signals += 1
        if lower_lows:
            bearish_signals += 1
    
    if bullish_signals > bearish_signals:
        return "bullish"
    elif bearish_signals > bullish_signals:
        return "bearish"
    else:
        return "mixed"


def _pick_direction_from_bias(
    mn_trend: str,
    wk_trend: str,
    d_trend: str
) -> Tuple[str, str, bool]:
    """
    Determine trade direction based on multi-timeframe bias.
    
    Args:
        mn_trend: Monthly trend
        wk_trend: Weekly trend
        d_trend: Daily trend
    
    Returns:
        Tuple of (direction, note, htf_aligned)
    """
    trends = [mn_trend, wk_trend, d_trend]
    bullish_count = sum(1 for t in trends if t == "bullish")
    bearish_count = sum(1 for t in trends if t == "bearish")
    
    if bullish_count >= 2:
        direction = "bullish"
        htf_aligned = mn_trend == "bullish" or wk_trend == "bullish"
        note = f"HTF bias: {mn_trend.upper()[0]}/{wk_trend.upper()[0]}/{d_trend.upper()[0]} -> Bullish"
    elif bearish_count >= 2:
        direction = "bearish"
        htf_aligned = mn_trend == "bearish" or wk_trend == "bearish"
        note = f"HTF bias: {mn_trend.upper()[0]}/{wk_trend.upper()[0]}/{d_trend.upper()[0]} -> Bearish"
    else:
        direction = d_trend if d_trend != "mixed" else "bullish"
        htf_aligned = False
        note = f"HTF bias: Mixed ({mn_trend[0].upper()}/{wk_trend[0].upper()}/{d_trend[0].upper()})"
    
    return direction, note, htf_aligned


def _location_context(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    price: float,
    direction: str,
) -> Tuple[str, bool]:
    """
    Check if price is at a key location (support/resistance zone).
    
    Returns:
        Tuple of (note, is_valid_location)
    """
    if not daily_candles or len(daily_candles) < 20:
        return "Location: Insufficient data", False
    
    highs = [c["high"] for c in daily_candles[-50:]] if len(daily_candles) >= 50 else [c["high"] for c in daily_candles]
    lows = [c["low"] for c in daily_candles[-50:]] if len(daily_candles) >= 50 else [c["low"] for c in daily_candles]
    
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    range_size = recent_high - recent_low
    
    if range_size <= 0:
        return "Location: No range", False
    
    swing_highs, swing_lows = _find_pivots(daily_candles[-50:] if len(daily_candles) >= 50 else daily_candles, lookback=3)
    
    atr = _atr(daily_candles, 14)
    zone_tolerance = atr * 0.5 if atr > 0 else range_size * 0.05
    
    if direction == "bullish":
        near_support = any(abs(price - sl) < zone_tolerance for sl in swing_lows[-5:]) if swing_lows else False
        near_range_low = (price - recent_low) < range_size * 0.3
        
        if near_support or near_range_low:
            return "Location: Near support zone", True
        else:
            return "Location: Not at key support", False
    else:
        near_resistance = any(abs(price - sh) < zone_tolerance for sh in swing_highs[-5:]) if swing_highs else False
        near_range_high = (recent_high - price) < range_size * 0.3
        
        if near_resistance or near_range_high:
            return "Location: Near resistance zone", True
        else:
            return "Location: Not at key resistance", False


def _fib_context(
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
    price: float,
    fib_low: float = 0.382,
    fib_high: float = 0.886,
) -> Tuple[str, bool]:
    """
    Check if price is within a Fibonacci retracement zone.
    
    Returns:
        Tuple of (note, is_in_fib_zone)
    """
    try:
        candles = daily_candles if daily_candles and len(daily_candles) >= 30 else weekly_candles
        
        if not candles or len(candles) < 20:
            return "Fib: Insufficient data", False
        
        leg = _find_last_swing_leg_for_fib(candles, direction)
        
        if not leg:
            return "Fib: No clear swing leg found", False
        
        lo, hi = leg
        span = hi - lo
        
        if span <= 0:
            return "Fib: Invalid swing range", False
        
        if direction == "bullish":
            fib_382 = hi - span * 0.382
            fib_500 = hi - span * 0.5
            fib_618 = hi - span * 0.618
            fib_786 = hi - span * 0.786
            
            if fib_786 <= price <= fib_382:
                level = round((hi - price) / span, 3)
                return f"Fib: Price at {level:.1%} retracement (Golden Pocket zone)", True
            elif fib_618 <= price <= fib_500:
                return "Fib: Price at 50-61.8% zone", True
            else:
                return "Fib: Price outside retracement zone", False
        else:
            fib_382 = lo + span * 0.382
            fib_500 = lo + span * 0.5
            fib_618 = lo + span * 0.618
            fib_786 = lo + span * 0.786
            
            if fib_382 <= price <= fib_786:
                level = round((price - lo) / span, 3)
                return f"Fib: Price at {level:.1%} retracement (Golden Pocket zone)", True
            elif fib_500 <= price <= fib_618:
                return "Fib: Price at 50-61.8% zone", True
            else:
                return "Fib: Price outside retracement zone", False
    except Exception as e:
        return f"Fib: Error calculating ({type(e).__name__})", False


def _find_last_swing_leg_for_fib(candles: List[Dict], direction: str) -> Optional[Tuple[float, float]]:
    """
    Find the last swing leg for Fibonacci calculation.
    
    Returns:
        Tuple of (swing_low, swing_high) or None
    """
    if not candles or len(candles) < 20:
        return None
    
    try:
        swing_highs, swing_lows = _find_pivots(candles, lookback=3)
    except Exception:
        swing_highs, swing_lows = [], []
    
    if not swing_highs or not swing_lows:
        try:
            highs = [c["high"] for c in candles[-30:] if "high" in c]
            lows = [c["low"] for c in candles[-30:] if "low" in c]
            if highs and lows:
                return (min(lows), max(highs))
        except Exception:
            pass
        return None
    
    try:
        recent_highs = swing_highs[-3:] if len(swing_highs) >= 3 else swing_highs
        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows
        
        if recent_highs and recent_lows:
            hi = max(recent_highs)
            lo = min(recent_lows)
            return (lo, hi)
    except Exception:
        pass
    
    return None


def _daily_liquidity_context(candles: List[Dict], price: float) -> Tuple[str, bool]:
    """
    Check for liquidity sweep or proximity to liquidity pools.
    
    Returns:
        Tuple of (note, is_near_liquidity)
    """
    try:
        if not candles or len(candles) < 10:
            return "Liquidity: Insufficient data", False
        
        lookback = min(20, len(candles))
        recent = candles[-lookback:]
        
        recent_highs = [c["high"] for c in recent if "high" in c]
        recent_lows = [c["low"] for c in recent if "low" in c]
        
        if not recent_highs or not recent_lows:
            return "Liquidity: Invalid data", False
        
        equal_highs = []
        equal_lows = []
        
        atr = _atr(candles, 14)
        tolerance = atr * 0.2 if atr > 0 else (max(recent_highs) - min(recent_lows)) * 0.02
        
        for i, h in enumerate(recent_highs):
            for j, h2 in enumerate(recent_highs):
                if i != j and abs(h - h2) < tolerance:
                    equal_highs.append(h)
                    break
        
        for i, l in enumerate(recent_lows):
            for j, l2 in enumerate(recent_lows):
                if i != j and abs(l - l2) < tolerance:
                    equal_lows.append(l)
                    break
        
        near_equal_high = any(abs(price - h) < tolerance * 2 for h in equal_highs)
        near_equal_low = any(abs(price - l) < tolerance * 2 for l in equal_lows)
        
        current = candles[-1]
        prev = candles[-2] if len(candles) >= 2 else None
        
        swept_high = False
        swept_low = False
        
        if prev:
            prev_high = max(c["high"] for c in candles[-10:-1] if "high" in c)
            prev_low = min(c["low"] for c in candles[-10:-1] if "low" in c)
            
            if current.get("high", 0) > prev_high and current.get("close", 0) < prev_high:
                swept_high = True
            if current.get("low", float("inf")) < prev_low and current.get("close", float("inf")) > prev_low:
                swept_low = True
        
        if swept_high or swept_low:
            return "Liquidity: Sweep detected", True
        elif near_equal_high or near_equal_low:
            return "Liquidity: Near equal highs/lows", True
        else:
            return "Liquidity: No clear liquidity zone", False
    except Exception as e:
        return f"Liquidity: Error ({type(e).__name__})", False


def _structure_context(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[bool, str]:
    """
    Check market structure alignment (BOS/CHoCH).
    
    Returns:
        Tuple of (is_aligned, note)
    """
    if not daily_candles or len(daily_candles) < 10:
        return False, "Structure: Insufficient data"
    
    swing_highs, swing_lows = _find_pivots(daily_candles[-30:], lookback=3)
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False, "Structure: Not enough swing points"
    
    if direction == "bullish":
        higher_low = swing_lows[-1] > swing_lows[-2] if len(swing_lows) >= 2 else False
        higher_high = swing_highs[-1] > swing_highs[-2] if len(swing_highs) >= 2 else False
        
        bos_up = daily_candles[-1]["close"] > max(swing_highs[-3:]) if swing_highs else False
        
        if bos_up:
            return True, "Structure: BOS up confirmed"
        elif higher_low and higher_high:
            return True, "Structure: HH/HL pattern (bullish)"
        elif higher_low:
            return True, "Structure: Higher low formed"
        else:
            return False, "Structure: No bullish structure"
    else:
        lower_high = swing_highs[-1] < swing_highs[-2] if len(swing_highs) >= 2 else False
        lower_low = swing_lows[-1] < swing_lows[-2] if len(swing_lows) >= 2 else False
        
        bos_down = daily_candles[-1]["close"] < min(swing_lows[-3:]) if swing_lows else False
        
        if bos_down:
            return True, "Structure: BOS down confirmed"
        elif lower_high and lower_low:
            return True, "Structure: LH/LL pattern (bearish)"
        elif lower_high:
            return True, "Structure: Lower high formed"
        else:
            return False, "Structure: No bearish structure"


def _h4_confirmation(
    h4_candles: List[Dict],
    direction: str,
    daily_candles: List[Dict],
) -> Tuple[str, bool]:
    """
    Check for 4H timeframe confirmation (entry trigger).
    
    Returns:
        Tuple of (note, is_confirmed)
    """
    candles = h4_candles if h4_candles and len(h4_candles) >= 5 else daily_candles[-10:]
    
    if not candles or len(candles) < 3:
        return "4H: Insufficient data", False
    
    last = candles[-1]
    prev = candles[-2]
    
    body_last = abs(last["close"] - last["open"])
    range_last = last["high"] - last["low"]
    body_ratio = body_last / range_last if range_last > 0 else 0
    
    if direction == "bullish":
        bullish_candle = last["close"] > last["open"]
        engulfing = (
            last["close"] > last["open"] and
            prev["close"] < prev["open"] and
            last["close"] > prev["open"] and
            last["open"] < prev["close"]
        )
        
        lower_wick = last["open"] - last["low"] if last["close"] > last["open"] else last["close"] - last["low"]
        upper_wick = last["high"] - last["close"] if last["close"] > last["open"] else last["high"] - last["open"]
        pin_bar = lower_wick > body_last * 2 and upper_wick < body_last * 0.5
        
        bos_check = last["high"] > max(c["high"] for c in candles[-5:-1]) if len(candles) >= 5 else False
        
        if engulfing:
            return "4H: Bullish engulfing confirmed", True
        elif pin_bar:
            return "4H: Bullish pin bar (rejection)", True
        elif bos_check and bullish_candle:
            return "4H: Break of structure up", True
        elif bullish_candle and body_ratio > 0.6:
            return "4H: Strong bullish candle", True
        else:
            return "4H: Awaiting bullish confirmation", False
    else:
        bearish_candle = last["close"] < last["open"]
        engulfing = (
            last["close"] < last["open"] and
            prev["close"] > prev["open"] and
            last["close"] < prev["open"] and
            last["open"] > prev["close"]
        )
        
        upper_wick = last["high"] - last["open"] if last["close"] < last["open"] else last["high"] - last["close"]
        lower_wick = last["close"] - last["low"] if last["close"] < last["open"] else last["open"] - last["low"]
        pin_bar = upper_wick > body_last * 2 and lower_wick < body_last * 0.5
        
        bos_check = last["low"] < min(c["low"] for c in candles[-5:-1]) if len(candles) >= 5 else False
        
        if engulfing:
            return "4H: Bearish engulfing confirmed", True
        elif pin_bar:
            return "4H: Bearish pin bar (rejection)", True
        elif bos_check and bearish_candle:
            return "4H: Break of structure down", True
        elif bearish_candle and body_ratio > 0.6:
            return "4H: Strong bearish candle", True
        else:
            return "4H: Awaiting bearish confirmation", False


def _find_structure_sl(candles: List[Dict], direction: str, lookback: int = 35) -> Optional[float]:
    """
    Find structure-based stop loss level.
    
    Returns:
        Stop loss price level or None
    """
    if not candles or len(candles) < 5:
        return None
    
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    swing_highs, swing_lows = _find_pivots(recent, lookback=3)
    
    if direction == "bullish":
        if swing_lows:
            return min(swing_lows[-3:]) if len(swing_lows) >= 3 else min(swing_lows)
        else:
            return min(c["low"] for c in recent[-10:])
    else:
        if swing_highs:
            return max(swing_highs[-3:]) if len(swing_highs) >= 3 else max(swing_highs)
        else:
            return max(c["high"] for c in recent[-10:])


def _compute_confluence_flags(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    direction: str,
    params: Optional[StrategyParams] = None,
) -> Tuple[Dict[str, bool], Dict[str, str], Tuple]:
    """
    Compute all confluence flags for a trading setup.
    
    This is the main entry point for confluence calculation,
    used by both backtests and live scanning.
    
    Returns:
        Tuple of (flags dict, notes dict, trade_levels tuple)
    """
    return compute_confluence(
        monthly_candles, weekly_candles, daily_candles, h4_candles, direction, params
    )


def compute_confluence(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    direction: str,
    params: Optional[StrategyParams] = None,
) -> Tuple[Dict[str, bool], Dict[str, str], Tuple]:
    """
    Compute confluence flags for a given setup.
    
    Uses the same core logic as strategy.py but with parameterization.
    
    Args:
        monthly_candles: Monthly OHLCV data
        weekly_candles: Weekly OHLCV data
        daily_candles: Daily OHLCV data
        h4_candles: 4H OHLCV data
        direction: Trade direction ("bullish" or "bearish")
        params: Strategy parameters (uses defaults if None)
    
    Returns:
        Tuple of (flags dict, notes dict, trade_levels tuple)
    """
    if params is None:
        params = StrategyParams()
    
    price = daily_candles[-1]["close"] if daily_candles else float("nan")
    
    mn_trend = _infer_trend(monthly_candles) if monthly_candles else "mixed"
    wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
    d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"
    _, htf_note_text, htf_ok = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)
    
    if params.use_htf_filter:
        loc_note, loc_ok = _location_context(
            monthly_candles, weekly_candles, daily_candles, price, direction
        )
    else:
        loc_note, loc_ok = "Location filter disabled", True
    
    if params.use_fib_filter:
        fib_note, fib_ok = _fib_context(weekly_candles, daily_candles, direction, price)
    else:
        fib_note, fib_ok = "Fib filter disabled", True
    
    if params.use_liquidity_filter:
        liq_note, liq_ok = _daily_liquidity_context(daily_candles, price)
    else:
        liq_note, liq_ok = "Liquidity filter disabled", True
    
    if params.use_structure_filter:
        struct_ok, struct_note = _structure_context(
            monthly_candles, weekly_candles, daily_candles, direction
        )
    else:
        struct_ok, struct_note = True, "Structure filter disabled"
    
    if params.use_confirmation_filter:
        conf_note, conf_ok = _h4_confirmation(h4_candles, direction, daily_candles)
    else:
        conf_note, conf_ok = "Confirmation filter disabled", True
    
    rr_note, rr_ok, entry, sl, tp1, tp2, tp3, tp4, tp5 = compute_trade_levels(
        daily_candles, direction, params
    )
    
    flags = {
        "htf_bias": htf_ok,
        "location": loc_ok,
        "fib": fib_ok,
        "liquidity": liq_ok,
        "structure": struct_ok,
        "confirmation": conf_ok,
        "rr": rr_ok,
    }
    
    notes = {
        "htf_bias": htf_note_text,
        "location": loc_note,
        "fib": fib_note,
        "liquidity": liq_note,
        "structure": struct_note,
        "confirmation": conf_note,
        "rr": rr_note,
    }
    
    trade_levels = (entry, sl, tp1, tp2, tp3, tp4, tp5)
    return flags, notes, trade_levels


def compute_trade_levels(
    daily_candles: List[Dict],
    direction: str,
    params: Optional[StrategyParams] = None,
) -> Tuple[str, bool, Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Compute entry, SL, and TP levels using parameterized logic.
    
    Args:
        daily_candles: Daily OHLCV data
        direction: Trade direction
        params: Strategy parameters
    
    Returns:
        Tuple of (note, is_valid, entry, sl, tp1, tp2, tp3, tp4, tp5)
    """
    if params is None:
        params = StrategyParams()
    
    if not daily_candles:
        return "R/R: no data.", False, None, None, None, None, None, None, None
    
    current = daily_candles[-1]["close"]
    atr = _atr(daily_candles, 14)
    
    if atr <= 0:
        return "R/R: ATR too small.", False, None, None, None, None, None, None, None
    
    leg = _find_last_swing_leg_for_fib(daily_candles, direction)
    structure_sl = _find_structure_sl(daily_candles, direction, lookback=params.structure_sl_lookback)
    
    if leg:
        lo, hi = leg
        span = hi - lo
        if span > 0:
            if direction == "bullish":
                gp_mid = hi - span * 0.618
                entry = current if abs(current - gp_mid) < atr * 0.3 else gp_mid
                
                base_sl = lo - atr * 0.5
                if structure_sl is not None:
                    sl = min(base_sl, structure_sl - atr * 0.4)
                else:
                    sl = base_sl
                
                risk = entry - sl
                
                if risk > 0:
                    tp1 = entry + risk * params.atr_tp1_multiplier
                    tp2 = entry + risk * params.atr_tp2_multiplier
                    tp3 = entry + risk * params.atr_tp3_multiplier
                    tp4 = entry + risk * 2.5
                    tp5 = entry + risk * 3.5
                    
                    note = f"R/R: Entry near {entry:.5f}, SL at {sl:.5f}"
                    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5
            else:
                gp_mid = lo + span * 0.618
                entry = current if abs(current - gp_mid) < atr * 0.3 else gp_mid
                
                base_sl = hi + atr * 0.5
                if structure_sl is not None:
                    sl = max(base_sl, structure_sl + atr * 0.4)
                else:
                    sl = base_sl
                
                risk = sl - entry
                
                if risk > 0:
                    tp1 = entry - risk * params.atr_tp1_multiplier
                    tp2 = entry - risk * params.atr_tp2_multiplier
                    tp3 = entry - risk * params.atr_tp3_multiplier
                    tp4 = entry - risk * 2.5
                    tp5 = entry - risk * 3.5
                    
                    note = f"R/R: Entry near {entry:.5f}, SL at {sl:.5f}"
                    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5
    
    entry = current
    sl_mult = params.atr_sl_multiplier
    
    if direction == "bullish":
        if structure_sl is not None:
            sl = min(entry - atr * sl_mult, structure_sl - atr * 0.4)
        else:
            sl = entry - atr * sl_mult
        risk = entry - sl
        tp1 = entry + risk * params.atr_tp1_multiplier
        tp2 = entry + risk * params.atr_tp2_multiplier
        tp3 = entry + risk * params.atr_tp3_multiplier
        tp4 = entry + risk * 2.5
        tp5 = entry + risk * 3.5
    else:
        if structure_sl is not None:
            sl = max(entry + atr * sl_mult, structure_sl + atr * 0.4)
        else:
            sl = entry + atr * sl_mult
        risk = sl - entry
        tp1 = entry - risk * params.atr_tp1_multiplier
        tp2 = entry - risk * params.atr_tp2_multiplier
        tp3 = entry - risk * params.atr_tp3_multiplier
        tp4 = entry - risk * 2.5
        tp5 = entry - risk * 3.5
    
    note = f"R/R: ATR+structure levels"
    return note, True, entry, sl, tp1, tp2, tp3, tp4, tp5


def generate_signals(
    candles: List[Dict],
    symbol: str = "UNKNOWN",
    params: Optional[StrategyParams] = None,
    monthly_candles: Optional[List[Dict]] = None,
    weekly_candles: Optional[List[Dict]] = None,
    h4_candles: Optional[List[Dict]] = None,
) -> List[Signal]:
    """
    Generate trading signals from historical candles.
    
    This function walks through candles sequentially (no look-ahead bias)
    and generates signals based on the Blueprint strategy rules.
    
    Args:
        candles: Daily OHLCV candles (oldest to newest)
        symbol: Asset symbol
        params: Strategy parameters
        monthly_candles: Optional monthly data (derived from daily if not provided)
        weekly_candles: Optional weekly data (derived from daily if not provided)
        h4_candles: Optional 4H data (uses daily for confirmation if not provided)
    
    Returns:
        List of Signal objects
    """
    if params is None:
        params = StrategyParams()
    
    if len(candles) < 50:
        return []
    
    signals = []
    
    for i in range(50, len(candles)):
        try:
            daily_slice = candles[:i+1]
            
            weekly_slice = weekly_candles[:i//5+1] if weekly_candles else None
            monthly_slice = monthly_candles[:i//20+1] if monthly_candles else None
            h4_slice = h4_candles[:i*6+1] if h4_candles else None
            
            mn_trend = _infer_trend(monthly_slice) if monthly_slice else _infer_trend(daily_slice[-60:])
            wk_trend = _infer_trend(weekly_slice) if weekly_slice else _infer_trend(daily_slice[-20:])
            d_trend = _infer_trend(daily_slice[-10:])
            
            direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)
            
            flags, notes, trade_levels = compute_confluence(
                monthly_slice or [],
                weekly_slice or [],
                daily_slice,
                h4_slice or daily_slice[-20:],
                direction,
                params,
            )
        except Exception:
            continue
        
        entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels
        
        confluence_score = sum(1 for v in flags.values() if v)
        
        quality_factors = sum([
            flags.get("location", False),
            flags.get("fib", False),
            flags.get("liquidity", False),
            flags.get("structure", False),
            flags.get("htf_bias", False),
        ])
        
        has_rr = flags.get("rr", False)
        has_confirmation = flags.get("confirmation", False)
        
        is_active = False
        is_watching = False
        
        if confluence_score >= params.min_confluence and quality_factors >= params.min_quality_factors:
            if params.require_rr_for_active and not has_rr:
                is_watching = True
            elif params.require_confirmation_for_active and not has_confirmation:
                is_watching = True
            else:
                is_active = True
        elif confluence_score >= params.min_confluence - 1:
            is_watching = True
        
        if is_active or is_watching:
            candle = candles[i]
            timestamp = candle.get("time") or candle.get("timestamp") or candle.get("date")
            
            signal = Signal(
                symbol=symbol,
                direction=direction,
                bar_index=i,
                timestamp=timestamp,
                confluence_score=confluence_score,
                quality_factors=quality_factors,
                entry=entry,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                is_active=is_active,
                is_watching=is_watching,
                flags=flags,
                notes=notes,
            )
            signals.append(signal)
    
    return signals


def simulate_trades(
    candles: List[Dict],
    symbol: str = "UNKNOWN",
    params: Optional[StrategyParams] = None,
    monthly_candles: Optional[List[Dict]] = None,
    weekly_candles: Optional[List[Dict]] = None,
    h4_candles: Optional[List[Dict]] = None,
) -> List[Trade]:
    """
    Simulate trades through historical candles using the Blueprint strategy.
    
    This is a walk-forward simulation with no look-ahead bias.
    Uses the same logic as live trading but runs through historical data.
    
    Args:
        candles: Daily OHLCV candles (oldest to newest)
        symbol: Asset symbol
        params: Strategy parameters
        monthly_candles: Optional monthly data
        weekly_candles: Optional weekly data
        h4_candles: Optional 4H data
    
    Returns:
        List of completed Trade objects
    """
    if params is None:
        params = StrategyParams()
    
    signals = generate_signals(
        candles, symbol, params,
        monthly_candles, weekly_candles, h4_candles
    )
    
    active_signals = [s for s in signals if s.is_active]
    
    trades = []
    open_trade = None
    last_trade_bar = -params.cooldown_bars - 1
    
    for signal in active_signals:
        if signal.bar_index <= last_trade_bar + params.cooldown_bars:
            continue
        
        if signal.entry is None or signal.stop_loss is None or signal.tp1 is None:
            continue
        
        if open_trade is not None:
            continue
        
        entry_bar = signal.bar_index
        entry_price = signal.entry
        sl = signal.stop_loss
        tp1 = signal.tp1
        tp2 = signal.tp2
        tp3 = signal.tp3
        direction = signal.direction
        
        risk = abs(entry_price - sl)
        if risk <= 0:
            continue
        
        trade_closed = False
        tp1_hit = False
        trailing_sl = sl
        
        reward = 0.0
        rr = 0.0
        is_winner = False
        exit_reason = ""
        
        for exit_bar in range(entry_bar + 1, len(candles)):
            c = candles[exit_bar]
            high = c["high"]
            low = c["low"]
            exit_timestamp = c.get("time") or c.get("timestamp") or c.get("date")
            
            if direction == "bullish":
                if low <= trailing_sl:
                    if tp1_hit:
                        reward = trailing_sl - entry_price
                        rr = reward / risk
                        exit_reason = "TP1+Trail"
                        is_winner = rr >= 0
                    else:
                        reward = trailing_sl - entry_price
                        rr = -1.0
                        exit_reason = "SL"
                        is_winner = False
                    
                    trade_closed = True
                elif tp1 is not None and high >= tp1 and not tp1_hit:
                    tp1_hit = True
                    trailing_sl = entry_price
                    
                    if low <= trailing_sl:
                        reward = 0
                        rr = 0.0
                        exit_reason = "TP1+Trail"
                        is_winner = True
                        trade_closed = True
                
                if not trade_closed and tp1_hit:
                    if tp3 is not None and high >= tp3:
                        reward = tp3 - entry_price
                        rr = reward / risk
                        exit_reason = "TP3"
                        is_winner = True
                        trade_closed = True
                    elif tp2 is not None and high >= tp2:
                        reward = tp2 - entry_price
                        rr = reward / risk
                        exit_reason = "TP2"
                        is_winner = True
                        trade_closed = True
            else:
                if high >= trailing_sl:
                    if tp1_hit:
                        reward = entry_price - trailing_sl
                        rr = reward / risk
                        exit_reason = "TP1+Trail"
                        is_winner = rr >= 0
                    else:
                        reward = entry_price - trailing_sl
                        rr = -1.0
                        exit_reason = "SL"
                        is_winner = False
                    
                    trade_closed = True
                elif tp1 is not None and low <= tp1 and not tp1_hit:
                    tp1_hit = True
                    trailing_sl = entry_price
                    
                    if high >= trailing_sl:
                        reward = 0
                        rr = 0.0
                        exit_reason = "TP1+Trail"
                        is_winner = True
                        trade_closed = True
                
                if not trade_closed and tp1_hit:
                    if tp3 is not None and low <= tp3:
                        reward = entry_price - tp3
                        rr = reward / risk
                        exit_reason = "TP3"
                        is_winner = True
                        trade_closed = True
                    elif tp2 is not None and low <= tp2:
                        reward = entry_price - tp2
                        rr = reward / risk
                        exit_reason = "TP2"
                        is_winner = True
                        trade_closed = True
            
            if trade_closed:
                entry_timestamp = signal.timestamp
                
                trade = Trade(
                    symbol=symbol,
                    direction=direction,
                    entry_date=entry_timestamp,
                    exit_date=exit_timestamp,
                    entry_price=entry_price,
                    exit_price=entry_price + reward if direction == "bullish" else entry_price - reward,
                    stop_loss=sl,
                    tp1=tp1,
                    tp2=tp2,
                    tp3=tp3,
                    risk=risk,
                    reward=reward,
                    rr=rr,
                    is_winner=is_winner,
                    exit_reason=exit_reason,
                    confluence_score=signal.confluence_score,
                )
                trades.append(trade)
                last_trade_bar = exit_bar
                break
        
        if not trade_closed:
            pass
    
    return trades


def get_default_params() -> StrategyParams:
    """Get default strategy parameters."""
    return StrategyParams()


def get_aggressive_params() -> StrategyParams:
    """Get aggressive (more trades) strategy parameters."""
    return StrategyParams(
        min_confluence=1,
        min_quality_factors=0,
        require_confirmation_for_active=False,
        require_rr_for_active=False,
        atr_sl_multiplier=1.2,
        atr_tp1_multiplier=0.5,
        atr_tp2_multiplier=1.0,
        atr_tp3_multiplier=1.5,
    )


def get_conservative_params() -> StrategyParams:
    """Get conservative (higher quality) strategy parameters."""
    return StrategyParams(
        min_confluence=4,
        min_quality_factors=2,
        require_htf_alignment=True,
        require_confirmation_for_active=True,
        require_rr_for_active=True,
        atr_sl_multiplier=1.8,
        atr_tp1_multiplier=0.8,
        atr_tp2_multiplier=1.5,
        atr_tp3_multiplier=2.5,
    )
