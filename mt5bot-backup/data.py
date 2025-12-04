"""
Data access layer for Blueprint Trader AI.

Uses OANDA v20 REST API for OHLCV candles with intelligent caching
to reduce latency and API calls.
"""

import datetime as dt
import os
from typing import List, Dict, Any, Optional

import requests

from config import OANDA_API_URL, GRANULARITY_MAP
from cache import get_cache


def _get_api_key() -> str:
    """Get OANDA API key from environment."""
    return os.getenv("OANDA_API_KEY", "").strip()


def _oanda_headers() -> Optional[Dict[str, str]]:
    """Get OANDA API headers, or None if API key not configured."""
    api_key = _get_api_key()
    if not api_key:
        print("[data] OANDA_API_KEY not configured")
        return None
    return {"Authorization": f"Bearer {api_key}"}


def get_ohlcv(
    instrument: str,
    timeframe: str = "D",
    count: int = 200,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles from OANDA for a given instrument and timeframe.
    
    Args:
        instrument: OANDA instrument name (e.g. EUR_USD)
        timeframe: Candle timeframe - "D", "H4", "W", "M"
        count: Number of candles to fetch
        use_cache: Whether to use caching (default True)

    Returns:
        List of candle dicts with keys: time, open, high, low, close, volume
    """
    cache = get_cache()
    
    if use_cache:
        cached = cache.get(instrument, timeframe, count)
        if cached is not None:
            return cached

    headers = _oanda_headers()
    if headers is None:
        print(f"[data.get_ohlcv] OANDA_API_KEY not configured. Set it in Replit Secrets.")
        return []

    granularity = GRANULARITY_MAP.get(timeframe, timeframe)
    url = f"{OANDA_API_URL}/v3/instruments/{instrument}/candles"

    params = {
        "granularity": granularity,
        "count": count,
        "price": "M",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[data.get_ohlcv] Network error for {instrument}, {timeframe}: {e}")
        return []
    
    if resp.status_code != 200:
        print(f"[data.get_ohlcv] Error {resp.status_code} for {instrument}, {timeframe}: {resp.text}")
        return []

    data = resp.json()
    candles = []

    for c in data.get("candles", []):
        if not c.get("complete", True):
            continue
        time_str = c["time"]
        t = time_str.split(".")[0].replace("Z", "")
        time_dt = dt.datetime.fromisoformat(t)

        mid = c["mid"]
        candles.append({
            "time": time_dt,
            "open": float(mid["o"]),
            "high": float(mid["h"]),
            "low": float(mid["l"]),
            "close": float(mid["c"]),
            "volume": float(c.get("volume", 0)),
        })

    if use_cache and candles:
        cache.set(instrument, timeframe, count, candles)

    return candles


def get_cache_stats() -> Dict[str, Any]:
    """Get statistics about the data cache."""
    return get_cache().get_stats()


def clear_cache() -> None:
    """Clear all cached data."""
    get_cache().clear()


def clear_instrument_cache(instrument: str) -> None:
    """Clear cache for a specific instrument."""
    get_cache().clear_instrument(instrument)


def get_current_prices(instruments: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Get current bid/ask prices from OANDA.
    
    Returns dict like: {"EUR_USD": {"bid": 1.0950, "ask": 1.0952, "mid": 1.0951}}
    """
    headers = _oanda_headers()
    if headers is None:
        return {}
    
    if not instruments:
        return {}
    
    account_id = _get_account_id()
    if not account_id:
        print("[data.get_current_prices] No OANDA_ACCOUNT_ID configured")
        return {}
    
    # OANDA requires comma-separated instrument list
    instruments_str = ",".join(instruments)
    url = f"{OANDA_API_URL}/v3/accounts/{account_id}/pricing"
    
    params = {"instruments": instruments_str}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"[data.get_current_prices] Network error: {e}")
        return {}
    
    if resp.status_code != 200:
        print(f"[data.get_current_prices] Error {resp.status_code}: {resp.text}")
        return {}
    
    result = {}
    data = resp.json()
    
    for price in data.get("prices", []):
        instrument = price.get("instrument")
        bid = float(price.get("bids", [{}])[0].get("price", 0)) if price.get("bids") else 0
        ask = float(price.get("asks", [{}])[0].get("price", 0)) if price.get("asks") else 0
        mid = (bid + ask) / 2 if bid and ask else 0
        
        if instrument and mid:
            result[instrument] = {"bid": bid, "ask": ask, "mid": mid}
    
    return result


def _get_account_id() -> str:
    """Get OANDA account ID from environment."""
    import os
    account_id = os.getenv("OANDA_ACCOUNT_ID", "").strip()
    if not account_id:
        print("[data._get_account_id] OANDA_ACCOUNT_ID not set or empty")
    return account_id
