"""
OANDA API Client for real-time and historical data.

Used for live price feeds and as a backup data source.
"""

import os
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional


class OandaClient:
    """
    OANDA v20 API client for market data.
    """
    
    PRACTICE_URL = "https://api-fxpractice.oanda.com"
    LIVE_URL = "https://api-fxtrade.oanda.com"
    
    GRANULARITY_MAP = {
        "M1": "M1",
        "M5": "M5",
        "M15": "M15",
        "M30": "M30",
        "H1": "H1",
        "H4": "H4",
        "D": "D",
        "D1": "D",
        "W": "W",
        "W1": "W",
        "M": "M",
        "MN": "M",
    }
    
    def __init__(
        self,
        api_key: str = None,
        account_id: str = None,
        practice: bool = True,
    ):
        self.api_key = api_key or os.getenv("OANDA_API_KEY", "")
        self.account_id = account_id or os.getenv("OANDA_ACCOUNT_ID", "")
        self.base_url = self.PRACTICE_URL if practice else self.LIVE_URL
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Convert symbol format to OANDA format (e.g., EURUSD -> EUR_USD)."""
        symbol = symbol.upper().replace(".", "").replace("/", "")
        
        if "_" in symbol:
            return symbol
        
        if len(symbol) == 6:
            return f"{symbol[:3]}_{symbol[3:]}"
        
        return symbol
    
    def get_candles(
        self,
        symbol: str,
        granularity: str = "D",
        count: int = 500,
        from_time: datetime = None,
        to_time: datetime = None,
    ) -> List[Dict]:
        """
        Get OHLCV candle data from OANDA.
        
        Args:
            symbol: Trading symbol
            granularity: Timeframe (M1, M5, M15, M30, H1, H4, D, W, M)
            count: Number of candles (max 5000)
            from_time: Start time (optional)
            to_time: End time (optional)
            
        Returns:
            List of OHLCV candle dictionaries
        """
        if not self.api_key:
            return []
        
        instrument = self._normalize_symbol(symbol)
        gran = self.GRANULARITY_MAP.get(granularity.upper(), "D")
        
        params = {
            "granularity": gran,
            "count": min(count, 5000),
        }
        
        if from_time:
            params["from"] = from_time.isoformat()
        if to_time:
            params["to"] = to_time.isoformat()
        
        url = f"{self.base_url}/v3/instruments/{instrument}/candles"
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code != 200:
                print(f"[OANDA] Error: {response.status_code} - {response.text}")
                return []
            
            data = response.json()
            candles = []
            
            for candle in data.get("candles", []):
                if not candle.get("complete", True):
                    continue
                
                mid = candle.get("mid", {})
                
                candles.append({
                    "time": datetime.fromisoformat(candle["time"].replace("Z", "+00:00")),
                    "open": float(mid.get("o", 0)),
                    "high": float(mid.get("h", 0)),
                    "low": float(mid.get("l", 0)),
                    "close": float(mid.get("c", 0)),
                    "volume": int(candle.get("volume", 0)),
                })
            
            return candles
            
        except Exception as e:
            print(f"[OANDA] Error fetching candles: {e}")
            return []
    
    def get_current_price(self, symbol: str) -> Optional[Dict]:
        """
        Get current price for a symbol.
        
        Returns:
            Dict with bid, ask, mid prices
        """
        if not self.api_key:
            return None
        
        instrument = self._normalize_symbol(symbol)
        
        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing"
        params = {"instruments": instrument}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            prices = data.get("prices", [])
            
            if not prices:
                return None
            
            price = prices[0]
            
            return {
                "symbol": symbol,
                "bid": float(price.get("bids", [{}])[0].get("price", 0)),
                "ask": float(price.get("asks", [{}])[0].get("price", 0)),
                "mid": (
                    float(price.get("bids", [{}])[0].get("price", 0)) +
                    float(price.get("asks", [{}])[0].get("price", 0))
                ) / 2,
                "time": datetime.fromisoformat(price["time"].replace("Z", "+00:00")),
            }
            
        except Exception as e:
            print(f"[OANDA] Error fetching price: {e}")
            return None
    
    def get_current_prices(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Get current prices for multiple symbols.
        
        Returns:
            Dict mapping symbol to price data
        """
        if not self.api_key or not symbols:
            return {}
        
        instruments = ",".join(self._normalize_symbol(s) for s in symbols)
        
        url = f"{self.base_url}/v3/accounts/{self.account_id}/pricing"
        params = {"instruments": instruments}
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                return {}
            
            data = response.json()
            result = {}
            
            for price in data.get("prices", []):
                instrument = price.get("instrument", "")
                
                original_symbol = None
                for s in symbols:
                    if self._normalize_symbol(s) == instrument:
                        original_symbol = s
                        break
                
                if original_symbol:
                    result[original_symbol] = {
                        "bid": float(price.get("bids", [{}])[0].get("price", 0)),
                        "ask": float(price.get("asks", [{}])[0].get("price", 0)),
                        "mid": (
                            float(price.get("bids", [{}])[0].get("price", 0)) +
                            float(price.get("asks", [{}])[0].get("price", 0))
                        ) / 2,
                    }
            
            return result
            
        except Exception as e:
            print(f"[OANDA] Error fetching prices: {e}")
            return {}
