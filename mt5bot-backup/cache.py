"""
Caching layer for Blueprint Trader AI.

Provides in-memory caching with TTL (time-to-live) for OANDA API responses
to reduce latency and API calls.
"""

import time
from typing import Dict, Any, Optional, List
from threading import Lock


class DataCache:
    """Thread-safe in-memory cache with TTL support."""
    
    def __init__(self, default_ttl: int = 300):
        """
        Initialize the cache.
        
        Args:
            default_ttl: Default time-to-live in seconds (5 minutes default)
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0
    
    def _make_key(self, instrument: str, timeframe: str, count: int) -> str:
        """Generate a unique cache key."""
        return f"{instrument}:{timeframe}:{count}"
    
    def get(self, instrument: str, timeframe: str, count: int) -> Optional[List[Dict]]:
        """
        Get cached data if available and not expired.
        
        Returns:
            Cached candle data or None if not found/expired
        """
        key = self._make_key(instrument, timeframe, count)
        
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            if time.time() > entry["expires_at"]:
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return entry["data"]
    
    def set(
        self,
        instrument: str,
        timeframe: str,
        count: int,
        data: List[Dict],
        ttl: Optional[int] = None
    ) -> None:
        """
        Store data in cache with TTL.
        
        Args:
            instrument: Trading instrument (e.g. EUR_USD)
            timeframe: Candle timeframe (D, H4, W, M)
            count: Number of candles
            data: Candle data to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        key = self._make_key(instrument, timeframe, count)
        effective_ttl = ttl if ttl is not None else self._get_ttl_for_timeframe(timeframe)
        
        with self._lock:
            self._cache[key] = {
                "data": data,
                "expires_at": time.time() + effective_ttl,
                "cached_at": time.time()
            }
    
    def _get_ttl_for_timeframe(self, timeframe: str) -> int:
        """
        Get appropriate TTL based on timeframe.
        Higher timeframes can be cached longer.
        """
        ttl_map = {
            "M": 3600,      # Monthly: 1 hour cache
            "W": 1800,      # Weekly: 30 minutes cache
            "D": 600,       # Daily: 10 minutes cache
            "H4": 300,      # 4-Hour: 5 minutes cache
        }
        return ttl_map.get(timeframe, self._default_ttl)
    
    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def clear_instrument(self, instrument: str) -> None:
        """Clear cache for a specific instrument."""
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(f"{instrument}:")]
            for key in keys_to_delete:
                del self._cache[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0
            
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate_pct": round(hit_rate, 1),
                "cached_items": len(self._cache),
            }
    
    def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.
        
        Returns:
            Number of entries removed
        """
        now = time.time()
        removed = 0
        
        with self._lock:
            keys_to_delete = [
                k for k, v in self._cache.items()
                if now > v["expires_at"]
            ]
            for key in keys_to_delete:
                del self._cache[key]
                removed += 1
        
        return removed


_cache_instance: Optional[DataCache] = None


def get_cache() -> DataCache:
    """Get the global cache instance (singleton)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DataCache()
    return _cache_instance
