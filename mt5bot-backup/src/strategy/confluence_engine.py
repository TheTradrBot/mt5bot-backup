"""
Blueprint HTF Confluence Strategy Engine - v4 Spec Implementation.

This module implements the confluence scoring system for the Blueprint strategy,
following the v4 specification for The5ers 10K High Stakes challenge.

Confluence Pillars (Max 10 points):
1. HTF Bias (Weekly + Daily alignment): 0-2 points
2. Location (MN/W1 S/R zones): 0-2 points  
3. Daily OB (Supply/Demand zone): 0-2 points
4. Fibonacci (Golden Pocket 0.618-0.796): 0-1 point
5. Structural Framework (N/V/H&S patterns): 0-1 point
6. Liquidity Confluence: 0-1 point
7. H4 Confirmation: 0-1 point

Minimum confluence for trade: 4 points
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime
import numpy as np


@dataclass
class ConfluenceScore:
    """Breakdown of confluence factors for a trade setup."""
    htf_bias: int = 0
    htf_bias_note: str = ""
    
    location: int = 0
    location_note: str = ""
    
    daily_ob: int = 0
    daily_ob_note: str = ""
    
    fibonacci: int = 0
    fibonacci_note: str = ""
    
    structure: int = 0
    structure_note: str = ""
    
    liquidity: int = 0
    liquidity_note: str = ""
    
    h4_confirmation: int = 0
    h4_confirmation_note: str = ""
    
    @property
    def total(self) -> int:
        return (
            self.htf_bias + 
            self.location + 
            self.daily_ob + 
            self.fibonacci + 
            self.structure + 
            self.liquidity + 
            self.h4_confirmation
        )
    
    @property
    def max_possible(self) -> int:
        return 10
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "htf_bias": {"score": self.htf_bias, "note": self.htf_bias_note},
            "location": {"score": self.location, "note": self.location_note},
            "daily_ob": {"score": self.daily_ob, "note": self.daily_ob_note},
            "fibonacci": {"score": self.fibonacci, "note": self.fibonacci_note},
            "structure": {"score": self.structure, "note": self.structure_note},
            "liquidity": {"score": self.liquidity, "note": self.liquidity_note},
            "h4_confirmation": {"score": self.h4_confirmation, "note": self.h4_confirmation_note},
            "total": self.total,
            "max": self.max_possible,
        }
    
    def get_breakdown(self) -> List[str]:
        """Get list of confluence factors that scored."""
        items = []
        if self.htf_bias > 0:
            items.append(f"HTF Bias ({self.htf_bias}/2): {self.htf_bias_note}")
        if self.location > 0:
            items.append(f"Location ({self.location}/2): {self.location_note}")
        if self.daily_ob > 0:
            items.append(f"Daily OB ({self.daily_ob}/2): {self.daily_ob_note}")
        if self.fibonacci > 0:
            items.append(f"Fibonacci ({self.fibonacci}/1): {self.fibonacci_note}")
        if self.structure > 0:
            items.append(f"Structure ({self.structure}/1): {self.structure_note}")
        if self.liquidity > 0:
            items.append(f"Liquidity ({self.liquidity}/1): {self.liquidity_note}")
        if self.h4_confirmation > 0:
            items.append(f"H4 Confirm ({self.h4_confirmation}/1): {self.h4_confirmation_note}")
        return items


@dataclass
class TradeSetup:
    """Represents a potential trade setup with all analysis."""
    symbol: str
    direction: str
    status: str
    
    confluence: ConfluenceScore
    
    entry_zone_high: Optional[float] = None
    entry_zone_low: Optional[float] = None
    entry_price: Optional[float] = None
    
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    
    risk_reward_tp1: Optional[float] = None
    risk_reward_tp2: Optional[float] = None
    risk_reward_tp3: Optional[float] = None
    
    framework_type: str = ""
    impulse_type: str = ""
    
    analysis_time: Optional[datetime] = None
    
    @property
    def is_tradeable(self) -> bool:
        return self.status == "ACTIVE" and self.confluence.total >= 4
    
    @property
    def is_watching(self) -> bool:
        return self.status == "WATCHING" and self.confluence.total >= 3


@dataclass
class StrategyParamsV4:
    """
    Strategy parameters for v4 spec optimization.
    """
    min_confluence_score: int = 4
    
    h4_confirmation_mode: str = "A"
    
    fib_zone_low: float = 0.618
    fib_zone_high: float = 0.796
    fib_tolerance: float = 0.02
    
    sl_buffer_atr_mult: float = 0.3
    
    tp_schema: str = "structural"
    tp1_min_rr: float = 2.0
    
    allow_continuation: bool = True
    allow_reversal: bool = True
    
    skip_friday_entries: bool = True
    
    risk_per_trade_pct: float = 0.75
    max_open_risk_pct: float = 3.0
    internal_daily_loss_cap: float = 4.0
    max_drawdown_threshold: float = 8.0


def calculate_atr(candles: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range."""
    if len(candles) < period + 1:
        return 0.0
    
    tr_values = []
    for i in range(1, len(candles)):
        high = candles[i].get("high", 0)
        low = candles[i].get("low", 0)
        prev_close = candles[i - 1].get("close", 0)
        
        if high and low and prev_close:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
    
    if len(tr_values) < period:
        return sum(tr_values) / len(tr_values) if tr_values else 0.0
    
    return sum(tr_values[-period:]) / period


def infer_trend(candles: List[Dict]) -> str:
    """
    Infer trend direction using HH/HL vs LH/LL structure.
    
    Returns: "bullish", "bearish", or "neutral"
    """
    if not candles or len(candles) < 20:
        return "neutral"
    
    swing_highs = []
    swing_lows = []
    
    for i in range(2, len(candles) - 2):
        if (candles[i]["high"] > candles[i-1]["high"] and 
            candles[i]["high"] > candles[i-2]["high"] and
            candles[i]["high"] > candles[i+1]["high"] and 
            candles[i]["high"] > candles[i+2]["high"]):
            swing_highs.append((i, candles[i]["high"]))
        
        if (candles[i]["low"] < candles[i-1]["low"] and 
            candles[i]["low"] < candles[i-2]["low"] and
            candles[i]["low"] < candles[i+1]["low"] and 
            candles[i]["low"] < candles[i+2]["low"]):
            swing_lows.append((i, candles[i]["low"]))
    
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "neutral"
    
    last_highs = [h[1] for h in swing_highs[-3:]]
    last_lows = [l[1] for l in swing_lows[-3:]]
    
    higher_high = len(last_highs) >= 2 and last_highs[-1] > last_highs[-2]
    higher_low = len(last_lows) >= 2 and last_lows[-1] > last_lows[-2]
    lower_high = len(last_highs) >= 2 and last_highs[-1] < last_highs[-2]
    lower_low = len(last_lows) >= 2 and last_lows[-1] < last_lows[-2]
    
    if higher_high and higher_low:
        return "bullish"
    elif lower_high and lower_low:
        return "bearish"
    else:
        return "neutral"


def evaluate_htf_bias(
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    direction: str,
) -> Tuple[int, str]:
    """
    Evaluate HTF bias alignment (0-2 points).
    
    +1 point if Weekly trend aligns
    +1 point if Daily trend aligns
    """
    score = 0
    notes = []
    
    weekly_trend = infer_trend(weekly_candles) if weekly_candles else "neutral"
    daily_trend = infer_trend(daily_candles) if daily_candles else "neutral"
    
    if weekly_trend == direction:
        score += 1
        notes.append(f"W1 {direction}")
    elif weekly_trend == "neutral":
        notes.append("W1 neutral")
    else:
        notes.append(f"W1 against ({weekly_trend})")
    
    if daily_trend == direction:
        score += 1
        notes.append(f"D1 {direction}")
    elif daily_trend == "neutral":
        notes.append("D1 neutral")
    else:
        notes.append(f"D1 against ({daily_trend})")
    
    return score, ", ".join(notes)


def evaluate_location(
    price: float,
    sr_levels: List[Dict],
    direction: str,
    atr: float,
) -> Tuple[int, str]:
    """
    Evaluate price location relative to S/R zones (0-2 points).
    
    +2 points if at strong MN/W1 S/R
    +1 point if at moderate S/R
    """
    if not sr_levels:
        return 0, "No S/R data"
    
    tolerance = atr * 1.5 if atr > 0 else price * 0.005
    
    for sr in sr_levels:
        if abs(price - sr['level']) < tolerance:
            sr_type = sr['type']
            strength = sr.get('strength', 1)
            
            if direction == "bullish" and sr_type == "support":
                if strength >= 3:
                    return 2, f"Strong support at {sr['level']:.5f}"
                else:
                    return 1, f"Support at {sr['level']:.5f}"
            elif direction == "bearish" and sr_type == "resistance":
                if strength >= 3:
                    return 2, f"Strong resistance at {sr['level']:.5f}"
                else:
                    return 1, f"Resistance at {sr['level']:.5f}"
    
    return 0, "Not at key S/R"


def evaluate_daily_ob(
    price: float,
    ob_zones: List[Dict],
    direction: str,
) -> Tuple[int, str]:
    """
    Evaluate Daily Order Block (Supply/Demand) zones (0-2 points).
    
    +2 points if in fresh OB
    +1 point if in tested OB
    """
    if not ob_zones:
        return 0, "No OB data"
    
    for zone in ob_zones:
        zone_type = zone.get('type', '')
        fresh = zone.get('fresh', False)
        
        if direction == "bullish" and zone_type == "demand":
            if zone['zone_low'] <= price <= zone['zone_high']:
                if fresh:
                    return 2, f"Fresh demand zone {zone['zone_low']:.5f}-{zone['zone_high']:.5f}"
                else:
                    return 1, f"Tested demand zone"
        
        elif direction == "bearish" and zone_type == "supply":
            if zone['zone_low'] <= price <= zone['zone_high']:
                if fresh:
                    return 2, f"Fresh supply zone {zone['zone_low']:.5f}-{zone['zone_high']:.5f}"
                else:
                    return 1, f"Tested supply zone"
    
    return 0, "Not in OB zone"


def find_impulse_for_fib(candles: List[Dict], direction: str) -> Optional[Tuple[float, float]]:
    """
    Find the correct impulse leg for Fibonacci calculation.
    
    For bullish: body low -> wick high of impulse up
    For bearish: body high -> wick low of impulse down
    
    Returns: (swing_low, swing_high) or None
    """
    if not candles or len(candles) < 20:
        return None
    
    avg_range = sum(c["high"] - c["low"] for c in candles[-20:]) / 20
    impulse_threshold = avg_range * 3
    
    for i in range(len(candles) - 5, 4, -1):
        segment = candles[i-5:i+1]
        segment_move = segment[-1]["close"] - segment[0]["open"]
        
        if direction == "bullish" and segment_move > impulse_threshold:
            body_low = min(min(c["open"], c["close"]) for c in segment[:3])
            wick_high = max(c["high"] for c in segment)
            return (body_low, wick_high)
        
        elif direction == "bearish" and segment_move < -impulse_threshold:
            body_high = max(max(c["open"], c["close"]) for c in segment[:3])
            wick_low = min(c["low"] for c in segment)
            return (wick_low, body_high)
    
    highs = [c["high"] for c in candles[-30:]]
    lows = [c["low"] for c in candles[-30:]]
    return (min(lows), max(highs))


def evaluate_fibonacci(
    price: float,
    daily_candles: List[Dict],
    direction: str,
    params: StrategyParamsV4,
) -> Tuple[int, str]:
    """
    Evaluate Fibonacci golden pocket alignment (0-1 point).
    
    +1 point if price is in 0.618-0.796 retracement zone
    """
    impulse = find_impulse_for_fib(daily_candles, direction)
    if not impulse:
        return 0, "No clear impulse"
    
    lo, hi = impulse
    span = hi - lo
    
    if span <= 0:
        return 0, "Invalid impulse range"
    
    if direction == "bullish":
        fib_618 = hi - span * params.fib_zone_low
        fib_796 = hi - span * params.fib_zone_high
        
        zone_high = fib_618 + span * params.fib_tolerance
        zone_low = fib_796 - span * params.fib_tolerance
        
        if zone_low <= price <= zone_high:
            level = (hi - price) / span
            return 1, f"In golden pocket ({level:.1%})"
    else:
        fib_618 = lo + span * params.fib_zone_low
        fib_796 = lo + span * params.fib_zone_high
        
        zone_low = fib_618 - span * params.fib_tolerance
        zone_high = fib_796 + span * params.fib_tolerance
        
        if zone_low <= price <= zone_high:
            level = (price - lo) / span
            return 1, f"In golden pocket ({level:.1%})"
    
    return 0, "Outside golden pocket"


def detect_structural_framework(daily_candles: List[Dict], direction: str) -> Tuple[int, str]:
    """
    Detect structural frameworks like N/V patterns or H&S (0-1 point).
    
    +1 point if clear framework present
    """
    if not daily_candles or len(daily_candles) < 30:
        return 0, "Insufficient data"
    
    swing_highs = []
    swing_lows = []
    
    for i in range(3, len(daily_candles) - 3):
        if (daily_candles[i]["high"] > daily_candles[i-1]["high"] and 
            daily_candles[i]["high"] > daily_candles[i+1]["high"]):
            swing_highs.append((i, daily_candles[i]["high"]))
        
        if (daily_candles[i]["low"] < daily_candles[i-1]["low"] and 
            daily_candles[i]["low"] < daily_candles[i+1]["low"]):
            swing_lows.append((i, daily_candles[i]["low"]))
    
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return 0, "Not enough swings"
    
    if direction == "bullish":
        last_highs = [h[1] for h in swing_highs[-4:]]
        last_lows = [l[1] for l in swing_lows[-4:]]
        
        if len(last_highs) >= 3:
            if last_highs[-1] > last_highs[-2] and last_highs[-2] < last_highs[-3]:
                return 1, "Bullish N pattern"
        
        if len(last_lows) >= 3:
            if last_lows[-2] < last_lows[-3] and last_lows[-2] < last_lows[-1]:
                return 1, "Inverse H&S forming"
    
    else:
        last_highs = [h[1] for h in swing_highs[-4:]]
        last_lows = [l[1] for l in swing_lows[-4:]]
        
        if len(last_lows) >= 3:
            if last_lows[-1] < last_lows[-2] and last_lows[-2] > last_lows[-3]:
                return 1, "Bearish V pattern"
        
        if len(last_highs) >= 3:
            if last_highs[-2] > last_highs[-3] and last_highs[-2] > last_highs[-1]:
                return 1, "H&S forming"
    
    return 0, "No clear framework"


def evaluate_liquidity(
    price: float,
    candles: List[Dict],
    direction: str,
    atr: float,
) -> Tuple[int, str]:
    """
    Evaluate liquidity confluence (0-1 point).
    
    +1 point if near equal highs/lows or recent sweep
    """
    if not candles or len(candles) < 20:
        return 0, "Insufficient data"
    
    tolerance = atr * 0.3 if atr > 0 else price * 0.002
    
    highs = [c["high"] for c in candles[-20:]]
    lows = [c["low"] for c in candles[-20:]]
    
    equal_highs = []
    equal_lows = []
    
    for i, h1 in enumerate(highs):
        for j, h2 in enumerate(highs):
            if i != j and abs(h1 - h2) < tolerance:
                equal_highs.append((h1 + h2) / 2)
                break
    
    for i, l1 in enumerate(lows):
        for j, l2 in enumerate(lows):
            if i != j and abs(l1 - l2) < tolerance:
                equal_lows.append((l1 + l2) / 2)
                break
    
    if direction == "bullish":
        for eq in equal_lows:
            if abs(price - eq) < tolerance * 2:
                return 1, f"Near equal lows at {eq:.5f}"
        
        recent_low = min(lows[-5:])
        prev_low = min(lows[:-5])
        if recent_low < prev_low and price > recent_low:
            return 1, "Liquidity sweep below"
    
    else:
        for eq in equal_highs:
            if abs(price - eq) < tolerance * 2:
                return 1, f"Near equal highs at {eq:.5f}"
        
        recent_high = max(highs[-5:])
        prev_high = max(highs[:-5])
        if recent_high > prev_high and price < recent_high:
            return 1, "Liquidity sweep above"
    
    return 0, "No clear liquidity"


def evaluate_h4_confirmation(
    h4_candles: List[Dict],
    entry_zone_low: float,
    entry_zone_high: float,
    direction: str,
    mode: str = "A",
) -> Tuple[int, str]:
    """
    Evaluate H4 confirmation (0-1 point).
    
    Mode A: 3 consecutive H4 closes inside zone
    Mode B: 2 closes + wick rejection signs
    Mode C: 1-2 closes + minor H4 BOS
    """
    if not h4_candles or len(h4_candles) < 5:
        return 0, "Insufficient H4 data"
    
    closes_inside = 0
    for c in h4_candles[-5:]:
        close = c["close"]
        if entry_zone_low <= close <= entry_zone_high:
            closes_inside += 1
        else:
            closes_inside = 0
    
    if mode == "A":
        if closes_inside >= 3:
            return 1, "3 consecutive H4 closes in zone"
        return 0, f"Only {closes_inside} closes in zone (need 3)"
    
    elif mode == "B":
        if closes_inside >= 2:
            last_candle = h4_candles[-1]
            if direction == "bullish":
                lower_wick = min(last_candle["open"], last_candle["close"]) - last_candle["low"]
                body = abs(last_candle["close"] - last_candle["open"])
                if lower_wick > body:
                    return 1, "2 closes + wick rejection"
            else:
                upper_wick = last_candle["high"] - max(last_candle["open"], last_candle["close"])
                body = abs(last_candle["close"] - last_candle["open"])
                if upper_wick > body:
                    return 1, "2 closes + wick rejection"
        return 0, "No confirmation (mode B)"
    
    elif mode == "C":
        if closes_inside >= 1:
            recent_highs = [c["high"] for c in h4_candles[-6:-1]]
            recent_lows = [c["low"] for c in h4_candles[-6:-1]]
            last = h4_candles[-1]
            
            if direction == "bullish":
                if last["close"] > max(recent_highs):
                    return 1, "Close + H4 BOS up"
            else:
                if last["close"] < min(recent_lows):
                    return 1, "Close + H4 BOS down"
        return 0, "No confirmation (mode C)"
    
    return 0, "Invalid mode"


def calculate_entry_levels(
    direction: str,
    entry_zone_low: float,
    entry_zone_high: float,
    daily_candles: List[Dict],
    params: StrategyParamsV4,
) -> Dict[str, float]:
    """
    Calculate entry, SL, and TP levels following v4 spec.
    
    SL: Below/above entry zone + buffer
    TP1: >=2R at structural level or fib -0.25
    TP2: fib -0.68
    TP3: fib -1.00
    """
    atr = calculate_atr(daily_candles)
    sl_buffer = atr * params.sl_buffer_atr_mult
    
    impulse = find_impulse_for_fib(daily_candles, direction)
    
    if direction == "bullish":
        entry = entry_zone_high
        sl = entry_zone_low - sl_buffer
        risk = entry - sl
        
        if impulse:
            lo, hi = impulse
            span = hi - lo
            tp1_fib = hi + span * 0.25
            tp2_fib = hi + span * 0.68
            tp3_fib = hi + span * 1.00
        else:
            tp1_fib = entry + risk * 2.0
            tp2_fib = entry + risk * 3.0
            tp3_fib = entry + risk * 4.5
        
        tp1 = max(entry + risk * params.tp1_min_rr, tp1_fib)
        tp2 = tp2_fib
        tp3 = tp3_fib
        
    else:
        entry = entry_zone_low
        sl = entry_zone_high + sl_buffer
        risk = sl - entry
        
        if impulse:
            lo, hi = impulse
            span = hi - lo
            tp1_fib = lo - span * 0.25
            tp2_fib = lo - span * 0.68
            tp3_fib = lo - span * 1.00
        else:
            tp1_fib = entry - risk * 2.0
            tp2_fib = entry - risk * 3.0
            tp3_fib = entry - risk * 4.5
        
        tp1 = min(entry - risk * params.tp1_min_rr, tp1_fib)
        tp2 = tp2_fib
        tp3 = tp3_fib
    
    return {
        "entry": entry,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": abs(risk),
    }


def analyze_setup(
    symbol: str,
    current_price: float,
    monthly_candles: List[Dict],
    weekly_candles: List[Dict],
    daily_candles: List[Dict],
    h4_candles: List[Dict],
    sr_levels: List[Dict],
    ob_zones: List[Dict],
    params: StrategyParamsV4 = None,
) -> TradeSetup:
    """
    Analyze a potential trade setup with full confluence scoring.
    
    This is the main entry point for the strategy engine.
    """
    if params is None:
        params = StrategyParamsV4()
    
    atr = calculate_atr(daily_candles)
    
    weekly_trend = infer_trend(weekly_candles)
    daily_trend = infer_trend(daily_candles)
    
    if weekly_trend == "bullish" or (weekly_trend == "neutral" and daily_trend == "bullish"):
        direction = "bullish"
    elif weekly_trend == "bearish" or (weekly_trend == "neutral" and daily_trend == "bearish"):
        direction = "bearish"
    else:
        direction = "bullish" if current_price > weekly_candles[-1]["close"] else "bearish"
    
    confluence = ConfluenceScore()
    
    confluence.htf_bias, confluence.htf_bias_note = evaluate_htf_bias(
        monthly_candles, weekly_candles, daily_candles, direction
    )
    
    confluence.location, confluence.location_note = evaluate_location(
        current_price, sr_levels, direction, atr
    )
    
    confluence.daily_ob, confluence.daily_ob_note = evaluate_daily_ob(
        current_price, ob_zones, direction
    )
    
    confluence.fibonacci, confluence.fibonacci_note = evaluate_fibonacci(
        current_price, daily_candles, direction, params
    )
    
    confluence.structure, confluence.structure_note = detect_structural_framework(
        daily_candles, direction
    )
    
    confluence.liquidity, confluence.liquidity_note = evaluate_liquidity(
        current_price, daily_candles, direction, atr
    )
    
    entry_zone_low = current_price - atr
    entry_zone_high = current_price + atr
    
    for zone in ob_zones:
        if zone.get('type') == ('demand' if direction == 'bullish' else 'supply'):
            if zone['zone_low'] <= current_price <= zone['zone_high']:
                entry_zone_low = zone['zone_low']
                entry_zone_high = zone['zone_high']
                break
    
    confluence.h4_confirmation, confluence.h4_confirmation_note = evaluate_h4_confirmation(
        h4_candles, entry_zone_low, entry_zone_high, direction, params.h4_confirmation_mode
    )
    
    if confluence.total >= params.min_confluence_score and confluence.h4_confirmation > 0:
        status = "ACTIVE"
    elif confluence.total >= params.min_confluence_score - 1:
        status = "WATCHING"
    else:
        status = "SCAN"
    
    levels = calculate_entry_levels(
        direction, entry_zone_low, entry_zone_high, daily_candles, params
    )
    
    setup = TradeSetup(
        symbol=symbol,
        direction=direction,
        status=status,
        confluence=confluence,
        entry_zone_high=entry_zone_high,
        entry_zone_low=entry_zone_low,
        entry_price=levels["entry"],
        stop_loss=levels["stop_loss"],
        tp1=levels["tp1"],
        tp2=levels["tp2"],
        tp3=levels["tp3"],
        analysis_time=datetime.utcnow(),
    )
    
    if levels["risk"] > 0:
        setup.risk_reward_tp1 = abs(levels["tp1"] - levels["entry"]) / levels["risk"]
        setup.risk_reward_tp2 = abs(levels["tp2"] - levels["entry"]) / levels["risk"]
        setup.risk_reward_tp3 = abs(levels["tp3"] - levels["entry"]) / levels["risk"]
    
    return setup
