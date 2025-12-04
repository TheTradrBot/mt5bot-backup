from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

from data import get_ohlcv
from config import (
    FOREX_PAIRS,
    METALS,
    INDICES,
    CRYPTO_ASSETS,
    SIGNAL_MODE,
)

from strategy_core import (
    generate_signals,
    get_default_params,
    Signal,
)

MAX_SIGNAL_AGE_DAYS = 5


@dataclass
class ScanResult:
    symbol: str
    direction: str
    confluence_score: int
    htf_bias: str
    location_note: str
    fib_note: str
    liquidity_note: str
    structure_note: str
    confirmation_note: str
    rr_note: str
    summary_reason: str
    status: str = "scan_only"
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    tp4: Optional[float] = None
    tp5: Optional[float] = None
    setup_type: str = ""
    what_to_look_for: str = ""


def _signal_to_scan_result(signal: Signal) -> ScanResult:
    """Convert a strategy_core Signal to a ScanResult for Discord display."""
    setup_parts = []
    
    if signal.flags.get("fib"):
        setup_parts.append("Fib retracement")
    if signal.flags.get("liquidity"):
        setup_parts.append("Liquidity zone")
    if signal.flags.get("structure"):
        setup_parts.append("Structure aligned")
    
    setup_type = " + ".join(setup_parts) if setup_parts else "Price action"
    
    direction = signal.direction.upper()
    look_for_parts = []
    
    if direction == "BULLISH":
        look_for_parts.append("Bullish rejection from support")
        if not signal.flags.get("confirmation"):
            look_for_parts.append("Wait for 4H BOS up or bullish engulfing")
        else:
            look_for_parts.append("Entry trigger confirmed")
    else:
        look_for_parts.append("Bearish rejection from resistance")
        if not signal.flags.get("confirmation"):
            look_for_parts.append("Wait for 4H BOS down or bearish engulfing")
        else:
            look_for_parts.append("Entry trigger confirmed")
    
    what_to_look_for = ". ".join(look_for_parts)
    
    summary = (
        f"{direction} | {signal.confluence_score}/7 confluence | "
        f"HTF={'Y' if signal.flags.get('htf_bias') else 'N'}, "
        f"Loc={'Y' if signal.flags.get('location') else 'N'}, "
        f"Fib={'Y' if signal.flags.get('fib') else 'N'}, "
        f"Liq={'Y' if signal.flags.get('liquidity') else 'N'}, "
        f"Struct={'Y' if signal.flags.get('structure') else 'N'}, "
        f"4H={'Y' if signal.flags.get('confirmation') else 'N'}, "
        f"RR={'Y' if signal.flags.get('rr') else 'N'}"
    )
    
    min_trade_conf = 4 if SIGNAL_MODE == "standard" else 3
    
    if signal.flags.get("confirmation") and signal.confluence_score >= min_trade_conf and signal.flags.get("rr"):
        status = "active"
    elif signal.confluence_score >= min_trade_conf - 1 and (signal.flags.get("location") or signal.flags.get("fib") or signal.flags.get("liquidity")):
        status = "in_progress"
    else:
        status = "scan_only"
    
    return ScanResult(
        symbol=signal.symbol,
        direction=signal.direction.lower(),
        confluence_score=signal.confluence_score,
        htf_bias=signal.notes.get("htf_bias", ""),
        location_note=signal.notes.get("location", ""),
        fib_note=signal.notes.get("fib", ""),
        liquidity_note=signal.notes.get("liquidity", ""),
        structure_note=signal.notes.get("structure", ""),
        confirmation_note=signal.notes.get("confirmation", ""),
        rr_note=signal.notes.get("rr", ""),
        summary_reason=summary,
        status=status,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        tp1=signal.tp1,
        tp2=signal.tp2,
        tp3=signal.tp3,
        setup_type=setup_type,
        what_to_look_for=what_to_look_for,
    )


def scan_single_asset(symbol: str) -> Optional[ScanResult]:
    """Full Blueprint scan using unified strategy_core engine."""
    try:
        monthly = get_ohlcv(symbol, timeframe="M", count=24) or []
        weekly = get_ohlcv(symbol, timeframe="W", count=104) or []
        daily = get_ohlcv(symbol, timeframe="D", count=500) or []
        h4 = get_ohlcv(symbol, timeframe="H4", count=500) or []
        
        if not daily or not weekly:
            return None
        
        params = get_default_params()
        signals = generate_signals(
            candles=daily,
            symbol=symbol,
            params=params,
            monthly_candles=monthly,
            weekly_candles=weekly,
            h4_candles=h4,
        )
        
        if not signals:
            return None
        
        most_recent = signals[-1]
        return _signal_to_scan_result(most_recent)
    except Exception as e:
        print(f"[strategy] Error scanning {symbol}: {e}")
        return None


def scan_group(symbols: List[str]) -> Tuple[List[ScanResult], List[ScanResult]]:
    results: List[ScanResult] = []
    trade_ideas: List[ScanResult] = []
    total = len(symbols)

    for i, sym in enumerate(symbols, 1):
        print(f"  [{i}/{total}] Scanning {sym}...")
        res = scan_single_asset(sym)
        if not res:
            continue
        results.append(res)
        if res.status in ("active", "in_progress"):
            trade_ideas.append(res)

    return results, trade_ideas


def scan_forex() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(FOREX_PAIRS)


def scan_crypto() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(CRYPTO_ASSETS)


def scan_metals() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(METALS)


def scan_indices() -> Tuple[List[ScanResult], List[ScanResult]]:
    return scan_group(INDICES)


def scan_all_markets() -> Dict[str, Tuple[List[ScanResult], List[ScanResult]]]:
    markets: Dict[str, Tuple[List[ScanResult], List[ScanResult]]] = {}

    print("[scan] Scanning Forex...")
    fx_results, fx_trades = scan_forex()
    markets["Forex"] = (fx_results, fx_trades)
    print(f"[scan] Forex done: {len(fx_results)} results")

    print("[scan] Scanning Metals...")
    metals_results, metals_trades = scan_metals()
    markets["Metals"] = (metals_results, metals_trades)
    print(f"[scan] Metals done: {len(metals_results)} results")

    print("[scan] Scanning Indices...")
    indices_results, indices_trades = scan_indices()
    markets["Indices"] = (indices_results, indices_trades)
    print(f"[scan] Indices done: {len(indices_results)} results")

    print("[scan] Scanning Crypto...")
    crypto_results, crypto_trades = scan_crypto()
    markets["Crypto"] = (crypto_results, crypto_trades)
    print(f"[scan] Crypto done: {len(crypto_results)} results")

    return markets
