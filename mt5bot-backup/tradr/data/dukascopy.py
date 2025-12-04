"""
Dukascopy Historical Data Downloader.

Provides free historical tick/OHLCV data from 2003+.
Essential for backtest parity with live trades.
"""

import os
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import struct
import lzma


DUKASCOPY_SYMBOLS = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "USDCHF": "USDCHF",
    "USDCAD": "USDCAD",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "EURJPY": "EURJPY",
    "GBPJPY": "GBPJPY",
    "EURGBP": "EURGBP",
    "XAUUSD": "XAUUSD",
}


class DukascopyDownloader:
    """
    Download historical data from Dukascopy.
    
    Provides tick-level data from 2003 onwards for accurate backtesting.
    Data is cached locally for reuse.
    """
    
    BASE_URL = "https://datafeed.dukascopy.com/datafeed"
    CACHE_DIR = Path("data_cache/dukascopy")
    
    def __init__(self, cache_dir: str = None):
        if cache_dir:
            self.CACHE_DIR = Path(cache_dir)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_path(self, symbol: str, year: int, month: int, day: int) -> Path:
        """Get cache file path for a specific date."""
        return self.CACHE_DIR / symbol / f"{year}" / f"{month:02d}" / f"{day:02d}.json"
    
    def _parse_bi5(self, data: bytes, symbol: str) -> List[Dict]:
        """Parse Dukascopy's bi5 format (LZMA compressed tick data)."""
        try:
            decompressed = lzma.decompress(data)
        except Exception:
            return []
        
        ticks = []
        record_size = 20
        
        for i in range(0, len(decompressed), record_size):
            if i + record_size > len(decompressed):
                break
            
            record = decompressed[i:i+record_size]
            
            try:
                timestamp_ms, ask, bid, ask_vol, bid_vol = struct.unpack('>IIIff', record)
                
                point = 0.00001 if "JPY" not in symbol else 0.001
                
                ticks.append({
                    "timestamp_ms": timestamp_ms,
                    "ask": ask * point,
                    "bid": bid * point,
                    "ask_volume": ask_vol,
                    "bid_volume": bid_vol,
                })
            except Exception:
                continue
        
        return ticks
    
    def download_ticks(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        use_cache: bool = True,
    ) -> List[Dict]:
        """
        Download tick data for a date range.
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            start_date: Start date
            end_date: End date
            use_cache: Use cached data if available
            
        Returns:
            List of tick dictionaries
        """
        duk_symbol = DUKASCOPY_SYMBOLS.get(symbol.upper().replace("_", ""), symbol)
        all_ticks = []
        
        current = start_date
        while current <= end_date:
            cache_path = self._get_cache_path(duk_symbol, current.year, current.month, current.day)
            
            if use_cache and cache_path.exists():
                try:
                    with open(cache_path, 'r') as f:
                        day_ticks = json.load(f)
                    all_ticks.extend(day_ticks)
                    current += timedelta(days=1)
                    continue
                except Exception:
                    pass
            
            day_ticks = self._download_day(duk_symbol, current)
            
            if day_ticks:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(cache_path, 'w') as f:
                        json.dump(day_ticks, f)
                except Exception:
                    pass
                
                all_ticks.extend(day_ticks)
            
            current += timedelta(days=1)
        
        return all_ticks
    
    def _download_day(self, symbol: str, day: date) -> List[Dict]:
        """Download tick data for a single day."""
        import requests
        
        all_ticks = []
        
        for hour in range(24):
            url = (
                f"{self.BASE_URL}/{symbol}/"
                f"{day.year}/{day.month - 1:02d}/{day.day:02d}/"
                f"{hour:02d}h_ticks.bi5"
            )
            
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    hour_ticks = self._parse_bi5(response.content, symbol)
                    
                    base_time = datetime(
                        day.year, day.month, day.day, hour,
                        tzinfo=timezone.utc
                    )
                    
                    for tick in hour_ticks:
                        tick_time = base_time + timedelta(milliseconds=tick["timestamp_ms"])
                        tick["time"] = tick_time.isoformat()
                        tick["mid"] = (tick["ask"] + tick["bid"]) / 2
                    
                    all_ticks.extend(hour_ticks)
            except Exception as e:
                print(f"[Dukascopy] Error downloading {symbol} {day} hour {hour}: {e}")
        
        return all_ticks
    
    def ticks_to_ohlcv(
        self,
        ticks: List[Dict],
        timeframe: str = "D",
    ) -> List[Dict]:
        """
        Convert tick data to OHLCV candles.
        
        Args:
            ticks: List of tick dictionaries
            timeframe: Timeframe - "M1", "M5", "M15", "M30", "H1", "H4", "D", "W"
            
        Returns:
            List of OHLCV candle dictionaries
        """
        if not ticks:
            return []
        
        tf_minutes = {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D": 1440,
            "W": 10080,
        }
        
        minutes = tf_minutes.get(timeframe.upper(), 1440)
        
        candles = {}
        
        for tick in ticks:
            tick_time = datetime.fromisoformat(tick["time"].replace("Z", "+00:00"))
            
            if minutes >= 1440:
                candle_time = tick_time.replace(hour=0, minute=0, second=0, microsecond=0)
                if minutes >= 10080:
                    candle_time -= timedelta(days=candle_time.weekday())
            else:
                total_minutes = tick_time.hour * 60 + tick_time.minute
                candle_minutes = (total_minutes // minutes) * minutes
                candle_time = tick_time.replace(
                    hour=candle_minutes // 60,
                    minute=candle_minutes % 60,
                    second=0,
                    microsecond=0
                )
            
            key = candle_time.isoformat()
            price = tick["mid"]
            
            if key not in candles:
                candles[key] = {
                    "time": candle_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0,
                }
            else:
                candles[key]["high"] = max(candles[key]["high"], price)
                candles[key]["low"] = min(candles[key]["low"], price)
                candles[key]["close"] = price
                candles[key]["volume"] += 1
        
        return sorted(candles.values(), key=lambda x: x["time"])
    
    def get_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str = "D",
        use_cache: bool = True,
    ) -> List[Dict]:
        """
        Get OHLCV candle data for a date range.
        
        Args:
            symbol: Trading symbol
            start_date: Start date
            end_date: End date
            timeframe: Candle timeframe
            use_cache: Use cached data
            
        Returns:
            List of OHLCV candle dictionaries
        """
        ticks = self.download_ticks(symbol, start_date, end_date, use_cache)
        return self.ticks_to_ohlcv(ticks, timeframe)
