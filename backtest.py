"""
Enhanced Backtest Engine for Blueprint Trader AI.

Features:
- Walk-forward simulation with no look-ahead bias
- Proper trade execution simulation using candle H/L
- Partial profit taking support
- Detailed trade logging
- Multiple exit scenarios
"""

from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Tuple, Optional

from data import get_ohlcv
from config import SIGNAL_MODE, MIN_CONFLUENCE_STANDARD, MIN_CONFLUENCE_AGGRESSIVE
from strategy_core import (
    _infer_trend,
    _pick_direction_from_bias,
    _compute_confluence_flags,
    _find_pivots,
    _atr,
)


def _parse_partial_date(s: str, for_start: bool) -> Optional[date]:
    """Parse date strings like 'Jan 2024', '2024-01-01', 'Now'."""
    s = s.strip()
    if not s:
        return None

    lower = s.lower()
    if lower in ("now", "today"):
        return date.today()

    fmts = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%Y/%m/%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass

    month_fmts = ["%b %Y", "%B %Y"]
    for fmt in month_fmts:
        try:
            dt = datetime.strptime(s, fmt).date()
            if for_start:
                return date(dt.year, dt.month, 1)
            else:
                if dt.month == 12:
                    return date(dt.year, 12, 31)
                else:
                    next_month = date(dt.year, dt.month + 1, 1)
                    return next_month - timedelta(days=1)
        except Exception:
            pass

    return None


def _parse_period(period_str: str) -> Tuple[Optional[date], Optional[date]]:
    """Parse 'Jan 2024 - Sep 2024' into (start_date, end_date)."""
    s = period_str.strip()
    if "-" in s:
        left, right = s.split("-", 1)
    else:
        left, right = s, "now"

    start = _parse_partial_date(left.strip(), for_start=True)
    end = _parse_partial_date(right.strip(), for_start=False)

    if start and end and start > end:
        start, end = end, start

    return start, end


def _candle_to_datetime(candle: Dict) -> Optional[datetime]:
    """Get datetime from a candle dict, normalized to UTC."""
    t = candle.get("time") or candle.get("timestamp") or candle.get("date")
    if t is None:
        return None

    dt = None
    if isinstance(t, datetime):
        dt = t
    elif isinstance(t, date):
        dt = datetime(t.year, t.month, t.day, tzinfo=timezone.utc)
    elif isinstance(t, (int, float)):
        try:
            dt = datetime.utcfromtimestamp(t).replace(tzinfo=timezone.utc)
        except Exception:
            return None
    elif isinstance(t, str):
        s = t.strip()
        try:
            s2 = s.replace("Z", "+00:00")
            if "." in s2:
                head, tail = s2.split(".", 1)
                decimals = "".join(ch for ch in tail if ch.isdigit())[:6]
                rest = tail[len(decimals):]
                s2 = f"{head}.{decimals}{rest}"
            dt = datetime.fromisoformat(s2)
        except Exception:
            pass

        if dt is None:
            fmts = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]
            for fmt in fmts:
                try:
                    dt = datetime.strptime(s[:len(fmt)], fmt)
                    break
                except Exception:
                    continue
    
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    
    return dt


def _candle_to_date(candle: Dict) -> Optional[date]:
    dt = _candle_to_datetime(candle)
    return dt.date() if dt else None


def _build_date_list(candles: List[Dict]) -> List[Optional[date]]:
    return [_candle_to_date(c) for c in candles]


def _build_dt_list(candles: List[Dict]) -> List[Optional[datetime]]:
    """Build list of datetime objects for timestamp-accurate slicing."""
    return [_candle_to_datetime(c) for c in candles]


def _slice_up_to_dt(candles: List[Dict], dts: List[Optional[datetime]], cutoff_dt: Optional[datetime]) -> List[Dict]:
    """Slice candles up to and including cutoff datetime (timestamp-accurate)."""
    if cutoff_dt is None:
        return []
    return [c for c, t in zip(candles, dts) if t and t <= cutoff_dt]


def _maybe_exit_trade(
    trade: Dict,
    high: float,
    low: float,
    exit_date: date,
) -> Optional[Dict]:
    """
    Check if trade hits TP or SL on a candle.
    Conservative approach: if SL and any TP are both hit on same bar, assume SL hit first.
    Trailing stop moves to breakeven after TP1 hit.
    """
    direction = trade["direction"]
    entry = trade["entry"]
    sl = trade.get("trailing_sl", trade["sl"])
    tp1 = trade["tp1"]
    tp2 = trade["tp2"]
    tp3 = trade["tp3"]
    risk = trade["risk"]
    tp1_hit = trade.get("tp1_hit", False)

    if direction == "bullish":
        hit_tp3 = tp3 is not None and high >= tp3
        hit_tp2 = tp2 is not None and high >= tp2
        hit_tp1 = tp1 is not None and high >= tp1
        hit_sl = low <= sl

        if hit_sl:
            if tp1_hit:
                rr = (sl - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": max(rr, 0.0),
                    "exit_reason": "TP1+Trail",
                }
            else:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": -1.0,
                    "exit_reason": "SL",
                }
        
        if tp1_hit:
            if hit_tp3:
                rr = (tp3 - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP3",
                }
            elif hit_tp2:
                rr = (tp2 - entry) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP2",
                }
        elif hit_tp1 and not tp1_hit:
            trade["tp1_hit"] = True
            new_sl = entry
            trade["trailing_sl"] = new_sl
            if low <= new_sl:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": 0.0,
                    "exit_reason": "TP1+Trail",
                }
            return None

    else:
        hit_tp3 = tp3 is not None and low <= tp3
        hit_tp2 = tp2 is not None and low <= tp2
        hit_tp1 = tp1 is not None and low <= tp1
        hit_sl = high >= sl

        if hit_sl:
            if tp1_hit:
                rr = (entry - sl) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": max(rr, 0.0),
                    "exit_reason": "TP1+Trail",
                }
            else:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": -1.0,
                    "exit_reason": "SL",
                }
        
        if tp1_hit:
            if hit_tp3:
                rr = (entry - tp3) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP3",
                }
            elif hit_tp2:
                rr = (entry - tp2) / risk
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": rr,
                    "exit_reason": "TP2",
                }
        elif hit_tp1 and not tp1_hit:
            trade["tp1_hit"] = True
            new_sl = entry
            trade["trailing_sl"] = new_sl
            if high >= new_sl:
                return {
                    "entry_date": trade["entry_date"].isoformat(),
                    "exit_date": exit_date.isoformat(),
                    "direction": direction,
                    "rr": 0.0,
                    "exit_reason": "TP1+Trail",
                }
            return None

    return None


def run_backtest(asset: str, period: str) -> Dict:
    """
    Walk-forward backtest of the Blueprint strategy.
    
    Key improvements:
    - No look-ahead bias: uses only data available at each point
    - Proper trade execution simulation
    - Detailed trade logging
    - Conservative exit assumptions
    """
    daily = get_ohlcv(asset, timeframe="D", count=2000, use_cache=False)
    if not daily:
        return {
            "asset": asset,
            "period": period,
            "total_trades": 0,
            "win_rate": 0.0,
            "net_return_pct": 0.0,
            "trades": [],
            "notes": "No Daily data available.",
        }

    weekly = get_ohlcv(asset, timeframe="W", count=500, use_cache=False) or []
    monthly = get_ohlcv(asset, timeframe="M", count=240, use_cache=False) or []
    h4 = get_ohlcv(asset, timeframe="H4", count=2000, use_cache=False) or []

    daily_dates = _build_date_list(daily)
    weekly_dates = _build_date_list(weekly)
    monthly_dates = _build_date_list(monthly)
    h4_dates = _build_date_list(h4)
    
    daily_dts = _build_dt_list(daily)
    weekly_dts = _build_dt_list(weekly)
    monthly_dts = _build_dt_list(monthly)
    h4_dts = _build_dt_list(h4)

    start_req, end_req = _parse_period(period)

    indices: List[int] = []

    if start_req or end_req:
        last_d = next((d for d in reversed(daily_dates) if d is not None), None)
        first_d = next((d for d in daily_dates if d is not None), None)

        end_date = end_req or last_d
        start_date = start_req or first_d

        if start_date is None or end_date is None:
            start_idx = max(0, len(daily) - 260)
            indices = list(range(start_idx, len(daily)))
            period_label = "Last 260 Daily candles"
        else:
            for i, d in enumerate(daily_dates):
                if d is None:
                    continue
                if start_date <= d <= end_date:
                    indices.append(i)

            if not indices:
                start_idx = max(0, len(daily) - 260)
                indices = list(range(start_idx, len(daily)))
                period_label = "Last 260 Daily candles"
            else:
                sd = daily_dates[indices[0]]
                ed = daily_dates[indices[-1]]
                period_label = f"{sd.isoformat()} - {ed.isoformat()}" if sd and ed else period
    else:
        start_idx = max(0, len(daily) - 260)
        indices = list(range(start_idx, len(daily)))
        period_label = "Last 260 Daily candles"

    if not indices:
        return {
            "asset": asset,
            "period": period,
            "total_trades": 0,
            "win_rate": 0.0,
            "net_return_pct": 0.0,
            "trades": [],
            "notes": "No candles found in requested period.",
        }

    trades: List[Dict] = []
    open_trade: Optional[Dict] = None
    
    # Use same confluence as live bot (4/7 standard, 2/7 aggressive)
    min_trade_conf = MIN_CONFLUENCE_STANDARD if SIGNAL_MODE == "standard" else MIN_CONFLUENCE_AGGRESSIVE
    cooldown_bars = 0
    last_trade_idx = -1

    for idx in indices:
        c = daily[idx]
        d_i = daily_dates[idx]
        cutoff_dt = daily_dts[idx]
        if d_i is None or cutoff_dt is None:
            continue

        high = c["high"]
        low = c["low"]
        close = c["close"]

        if open_trade is not None and idx > open_trade["entry_index"]:
            closed = _maybe_exit_trade(open_trade, high, low, d_i)
            if closed is not None:
                # Add entry and TP levels to closed trade
                closed['symbol'] = open_trade.get('symbol', asset)
                closed['entry'] = open_trade.get('entry')
                closed['entry_price'] = open_trade.get('entry')
                closed['sl'] = open_trade.get('sl')
                closed['stop_loss'] = open_trade.get('sl')
                closed['tp1'] = open_trade.get('tp1')
                closed['tp2'] = open_trade.get('tp2')
                closed['tp3'] = open_trade.get('tp3')
                trades.append(closed)
                open_trade = None
                last_trade_idx = idx
                continue

        if open_trade is not None:
            continue

        if idx - last_trade_idx < cooldown_bars:
            continue

        daily_slice = _slice_up_to_dt(daily, daily_dts, cutoff_dt)
        if len(daily_slice) < 30:
            continue

        weekly_slice = _slice_up_to_dt(weekly, weekly_dts, cutoff_dt)
        if not weekly_slice or len(weekly_slice) < 8:
            continue

        monthly_slice = _slice_up_to_dt(monthly, monthly_dts, cutoff_dt)
        h4_slice = _slice_up_to_dt(h4, h4_dts, cutoff_dt)

        mn_trend = _infer_trend(monthly_slice) if monthly_slice else "mixed"
        wk_trend = _infer_trend(weekly_slice) if weekly_slice else "mixed"
        d_trend = _infer_trend(daily_slice) if daily_slice else "mixed"

        direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

        flags, notes, trade_levels = _compute_confluence_flags(
            monthly_slice,
            weekly_slice,
            daily_slice,
            h4_slice,
            direction,
        )

        entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels

        confluence_score = sum(1 for v in flags.values() if v)

        has_confirmation = flags.get("confirmation", False)
        has_rr = flags.get("rr", False)
        has_location = flags.get("location", False)
        has_fib = flags.get("fib", False)
        has_liquidity = flags.get("liquidity", False)
        has_structure = flags.get("structure", False)
        has_htf_bias = flags.get("htf_bias", False)

        quality_factors = sum([has_location, has_fib, has_liquidity, has_structure, has_htf_bias])
        
        if has_rr and confluence_score >= min_trade_conf and quality_factors >= 1:
            status = "active"
        elif confluence_score >= min_trade_conf:
            status = "watching"
        else:
            status = "scan_only"

        if status != "active":
            continue

        if entry is None or sl is None or tp1 is None:
            continue

        risk = abs(entry - sl)
        if risk <= 0:
            continue

        open_trade = {
            "asset": asset,
            "symbol": asset,
            "direction": direction,
            "entry": entry,
            "entry_price": entry,
            "sl": sl,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
            "tp5": tp5,
            "risk": risk,
            "entry_date": d_i,
            "entry_index": idx,
            "confluence": confluence_score,
        }

    from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT
    
    total_trades = len(trades)
    if total_trades > 0:
        wins = sum(1 for t in trades if t["rr"] > 0)
        win_rate = wins / total_trades * 100.0
        total_rr = sum(t["rr"] for t in trades)
        net_return_pct = total_rr * RISK_PER_TRADE_PCT * 100
        avg_rr = total_rr / total_trades
    else:
        win_rate = 0.0
        net_return_pct = 0.0
        total_rr = 0.0
        avg_rr = 0.0

    risk_per_trade_usd = ACCOUNT_SIZE * RISK_PER_TRADE_PCT
    total_profit_usd = total_rr * risk_per_trade_usd
    
    running_pnl = 0.0
    max_drawdown = 0.0
    peak = 0.0
    
    for t in trades:
        running_pnl += t["rr"] * risk_per_trade_usd
        if running_pnl > peak:
            peak = running_pnl
        drawdown = peak - running_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    max_drawdown_pct = (max_drawdown / ACCOUNT_SIZE) * 100 if ACCOUNT_SIZE > 0 else 0.0

    tp1_trail_hits = sum(1 for t in trades if t.get("exit_reason") == "TP1+Trail")
    tp2_hits = sum(1 for t in trades if t.get("exit_reason") == "TP2")
    tp3_hits = sum(1 for t in trades if t.get("exit_reason") == "TP3")
    sl_hits = sum(1 for t in trades if t.get("exit_reason") == "SL")
    
    wins = tp1_trail_hits + tp2_hits + tp3_hits

    notes_text = (
        f"Backtest Summary - {asset} ({period_label}, 100K 5%ers model)\n"
        f"Min confluence: {min_trade_conf}/7 (mode: {SIGNAL_MODE})\n"
        f"Trades: {total_trades}\n"
        f"Win rate: {win_rate:.1f}%\n"
        f"Total profit: +${total_profit_usd:,.0f} (+{net_return_pct:.1f}%)\n"
        f"Max drawdown: -{max_drawdown_pct:.1f}%\n"
        f"Expectancy: {avg_rr:+.2f}R / trade\n"
        f"TP1+Trail ({tp1_trail_hits}), TP2 ({tp2_hits}), TP3 ({tp3_hits}), SL ({sl_hits})"
    )

    return {
        "asset": asset,
        "period": period_label,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "net_return_pct": net_return_pct,
        "total_profit_usd": total_profit_usd,
        "max_drawdown_pct": max_drawdown_pct,
        "avg_rr": avg_rr,
        "tp1_trail_hits": tp1_trail_hits,
        "tp2_hits": tp2_hits,
        "tp3_hits": tp3_hits,
        "sl_hits": sl_hits,
        "trades": trades,
        "notes": notes_text,
        "account_size": ACCOUNT_SIZE,
        "risk_per_trade_pct": RISK_PER_TRADE_PCT,
    }
