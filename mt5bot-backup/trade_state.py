# trade_state.py
"""
Enhanced trade registry for Blueprint Trader AI.

Tracks active trades with notification state to prevent duplicate Discord messages.
Persists to trade_state.json for crash recovery.

Features:
- Track active trade ideas (4/7+ confluence)
- Track notification state (notified_open, notified_tp1, etc.)
- Persist and restore state across restarts
- Prevent duplicate Discord notifications
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict

from strategy import ScanResult
from data import get_ohlcv


TRADE_STATE_FILE = Path("trade_state.json")


@dataclass
class TradeNotificationState:
    """Tracks which notifications have been sent for a trade."""
    notified_open: bool = False
    notified_tp1: bool = False
    notified_tp2: bool = False
    notified_tp3: bool = False
    notified_sl: bool = False
    notified_close: bool = False
    entry_datetime: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeNotificationState":
        return cls(
            notified_open=data.get("notified_open", False),
            notified_tp1=data.get("notified_tp1", False),
            notified_tp2=data.get("notified_tp2", False),
            notified_tp3=data.get("notified_tp3", False),
            notified_sl=data.get("notified_sl", False),
            notified_close=data.get("notified_close", False),
            entry_datetime=data.get("entry_datetime"),
        )


_active_trades: Dict[str, ScanResult] = {}
_notification_states: Dict[str, TradeNotificationState] = {}
_last_sent_setups: Dict[str, str] = {}  # track last autoscan setups to avoid duplicates


def _key(res: ScanResult) -> str:
    """Generate unique key for a trade."""
    return f"{res.symbol}:{res.direction}"


def register_trade(res: ScanResult, is_new: bool = True) -> str:
    """
    Register or update an active trade idea.
    
    Args:
        res: The scan result / trade idea
        is_new: If True, this is a new trade (create notification state)
    
    Returns:
        The trade key
    """
    key = _key(res)
    _active_trades[key] = res
    
    if is_new and key not in _notification_states:
        _notification_states[key] = TradeNotificationState(
            entry_datetime=datetime.utcnow().isoformat()
        )
    
    save_state()
    return key


def get_trade(symbol: str, direction: str) -> Optional[ScanResult]:
    """Get a specific trade by symbol and direction."""
    key = f"{symbol}:{direction}"
    return _active_trades.get(key)


def get_notification_state(key: str) -> Optional[TradeNotificationState]:
    """Get notification state for a trade."""
    return _notification_states.get(key)


def mark_notified_open(key: str) -> None:
    """Mark that the trade open notification has been sent."""
    if key in _notification_states:
        _notification_states[key].notified_open = True
        save_state()


def mark_notified_tp(key: str, tp_level: int) -> None:
    """Mark that a TP hit notification has been sent."""
    if key in _notification_states:
        if tp_level == 1:
            _notification_states[key].notified_tp1 = True
        elif tp_level == 2:
            _notification_states[key].notified_tp2 = True
        elif tp_level == 3:
            _notification_states[key].notified_tp3 = True
        save_state()


def mark_notified_sl(key: str) -> None:
    """Mark that the SL hit notification has been sent."""
    if key in _notification_states:
        _notification_states[key].notified_sl = True
        save_state()


def mark_notified_close(key: str) -> None:
    """Mark that the trade close notification has been sent."""
    if key in _notification_states:
        _notification_states[key].notified_close = True
        save_state()


def should_notify_open(key: str) -> bool:
    """Check if we should send the open notification."""
    state = _notification_states.get(key)
    return state is not None and not state.notified_open


def should_notify_tp(key: str, tp_level: int) -> bool:
    """Check if we should send a TP notification."""
    state = _notification_states.get(key)
    if state is None:
        return False
    if tp_level == 1:
        return not state.notified_tp1
    elif tp_level == 2:
        return not state.notified_tp2
    elif tp_level == 3:
        return not state.notified_tp3
    return False


def should_notify_sl(key: str) -> bool:
    """Check if we should send the SL notification."""
    state = _notification_states.get(key)
    return state is not None and not state.notified_sl


def get_entry_datetime(key: str) -> Optional[datetime]:
    """Get the entry datetime for a trade."""
    state = _notification_states.get(key)
    if state and state.entry_datetime:
        try:
            return datetime.fromisoformat(state.entry_datetime)
        except (ValueError, TypeError):
            pass
    return None


def remove_trade(key: str) -> None:
    """Remove a trade and its notification state."""
    _active_trades.pop(key, None)
    _notification_states.pop(key, None)
    save_state()


def list_trades() -> List[ScanResult]:
    """Return a list of currently tracked trades."""
    return list(_active_trades.values())


def clear_all_trades() -> None:
    """Clear all trades and notification states."""
    _active_trades.clear()
    _notification_states.clear()
    save_state()


def is_setup_already_sent(symbol: str, direction: str, confluence_score: int) -> bool:
    """
    Check if an autoscan setup was already sent recently.
    Used to prevent duplicate autoscan outputs.
    """
    key = f"{symbol}:{direction}"
    fingerprint = f"{confluence_score}"
    return _last_sent_setups.get(key) == fingerprint


def mark_setup_sent(symbol: str, direction: str, confluence_score: int) -> None:
    """Mark an autoscan setup as sent."""
    key = f"{symbol}:{direction}"
    _last_sent_setups[key] = f"{confluence_score}"


def clear_sent_setups() -> None:
    """Clear the sent setups cache (call before each autoscan)."""
    _last_sent_setups.clear()


def save_state() -> None:
    """Save current state to file."""
    state = {
        "trades": {},
        "notifications": {},
    }
    
    for key, trade in _active_trades.items():
        state["trades"][key] = {
            "symbol": trade.symbol,
            "direction": trade.direction,
            "confluence_score": trade.confluence_score,
            "entry": trade.entry,
            "stop_loss": trade.stop_loss,
            "tp1": trade.tp1,
            "tp2": trade.tp2,
            "tp3": trade.tp3,
            "status": trade.status,
            "tp1_hit": getattr(trade, "tp1_hit", False),
            "tp2_hit": getattr(trade, "tp2_hit", False),
            "tp3_hit": getattr(trade, "tp3_hit", False),
            "sl_hit": getattr(trade, "sl_hit", False),
            "is_closed": getattr(trade, "is_closed", False),
        }
    
    for key, notif in _notification_states.items():
        state["notifications"][key] = notif.to_dict()
    
    try:
        with open(TRADE_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[trade_state] Error saving state: {e}")


def load_state() -> int:
    """
    Load state from file on startup.
    
    Returns:
        Number of trades restored
    """
    if not TRADE_STATE_FILE.exists():
        return 0
    
    try:
        with open(TRADE_STATE_FILE, 'r') as f:
            state = json.load(f)
        
        # Restore trades
        for key, trade_data in state.get("trades", {}).items():
            try:
                trade = ScanResult(
                    symbol=trade_data["symbol"],
                    direction=trade_data["direction"],
                    confluence_score=trade_data.get("confluence_score", 0),
                    htf_bias="",
                    location_note="",
                    fib_note="",
                    liquidity_note="",
                    structure_note="",
                    confirmation_note="",
                    rr_note="",
                    summary_reason="",
                    status=trade_data.get("status", "active"),
                    entry=trade_data.get("entry"),
                    stop_loss=trade_data.get("stop_loss"),
                    tp1=trade_data.get("tp1"),
                    tp2=trade_data.get("tp2"),
                    tp3=trade_data.get("tp3"),
                )
                # Restore hit states
                trade.tp1_hit = trade_data.get("tp1_hit", False)
                trade.tp2_hit = trade_data.get("tp2_hit", False)
                trade.tp3_hit = trade_data.get("tp3_hit", False)
                trade.sl_hit = trade_data.get("sl_hit", False)
                trade.is_closed = trade_data.get("is_closed", False)
                
                _active_trades[key] = trade
            except Exception as e:
                print(f"[trade_state] Error restoring trade {key}: {e}")
        
        # Restore notification states
        for key, notif_data in state.get("notifications", {}).items():
            try:
                _notification_states[key] = TradeNotificationState.from_dict(notif_data)
            except Exception as e:
                print(f"[trade_state] Error restoring notification state {key}: {e}")
        
        return len(_active_trades)
    
    except Exception as e:
        print(f"[trade_state] Error loading state: {e}")
        return 0


def evaluate_trades_for_updates() -> List[Tuple[ScanResult, str, float, float]]:
    """
    Check each active trade for TP/SL hits using the latest H4 candle.

    Returns a list of events:
      (ScanResult, event_type, event_price, event_rr)

    event_type in {"TP1", "TP2", "TP3", "SL"}
    event_rr is the R-multiple at that level (based on entry & SL), or NaN.
    """
    events: List[Tuple[ScanResult, str, float, float]] = []

    for trade in _active_trades.values():
        if getattr(trade, "is_closed", False):
            continue

        try:
            candles = get_ohlcv(trade.symbol, timeframe="H4", count=1)
            if not candles:
                continue

            c = candles[-1]
            high = c["high"]
            low = c["low"]

            entry = trade.entry
            sl = trade.stop_loss

            if entry is None or sl is None:
                continue

            # Compute risk (for RR calculation)
            if trade.direction == "bullish":
                risk = entry - sl
            else:
                risk = sl - entry

            if risk <= 0:
                risk = None  # invalid for RR, but we can still send update

            # ---- Bullish logic ----
            if trade.direction == "bullish":
                # 1) SL first (conservative)
                if not getattr(trade, "sl_hit", False) and low <= sl:
                    trade.sl_hit = True
                    trade.is_closed = True
                    trade.status = "closed - SL hit"
                    rr = -1.0 if risk else float("nan")
                    events.append((trade, "SL", sl, rr))
                    save_state()
                    continue  # no TP events once SL hit

                # 2) TP1 / TP2 / TP3
                if trade.tp1 is not None and not getattr(trade, "tp1_hit", False) and high >= trade.tp1:
                    trade.tp1_hit = True
                    rr = ((trade.tp1 - entry) / risk) if risk else float("nan")
                    events.append((trade, "TP1", trade.tp1, rr))

                if trade.tp2 is not None and not getattr(trade, "tp2_hit", False) and high >= trade.tp2:
                    trade.tp2_hit = True
                    rr = ((trade.tp2 - entry) / risk) if risk else float("nan")
                    events.append((trade, "TP2", trade.tp2, rr))

                if trade.tp3 is not None and not getattr(trade, "tp3_hit", False) and high >= trade.tp3:
                    trade.tp3_hit = True
                    trade.is_closed = True
                    trade.status = "closed - TP3 hit"
                    rr = ((trade.tp3 - entry) / risk) if risk else float("nan")
                    events.append((trade, "TP3", trade.tp3, rr))

            else:  # bearish
                # 1) SL first
                if not getattr(trade, "sl_hit", False) and high >= sl:
                    trade.sl_hit = True
                    trade.is_closed = True
                    trade.status = "closed - SL hit"
                    rr = -1.0 if risk else float("nan")
                    events.append((trade, "SL", sl, rr))
                    save_state()
                    continue

                # 2) TP1 / TP2 / TP3
                if trade.tp1 is not None and not getattr(trade, "tp1_hit", False) and low <= trade.tp1:
                    trade.tp1_hit = True
                    rr = ((entry - trade.tp1) / risk) if risk else float("nan")
                    events.append((trade, "TP1", trade.tp1, rr))

                if trade.tp2 is not None and not getattr(trade, "tp2_hit", False) and low <= trade.tp2:
                    trade.tp2_hit = True
                    rr = ((entry - trade.tp2) / risk) if risk else float("nan")
                    events.append((trade, "TP2", trade.tp2, rr))

                if trade.tp3 is not None and not getattr(trade, "tp3_hit", False) and low <= trade.tp3:
                    trade.tp3_hit = True
                    trade.is_closed = True
                    trade.status = "closed - TP3 hit"
                    rr = ((entry - trade.tp3) / risk) if risk else float("nan")
                    events.append((trade, "TP3", trade.tp3, rr))

            save_state()
            
        except Exception as e:
            print(f"[trade_state] Error evaluating {trade.symbol}: {e}")
            continue

    return events
