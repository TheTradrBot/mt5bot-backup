"""
MT5 Bridge Client - For connecting to MT5 via HTTP bridge.

Use this when running from Replit or remote server.
The MT5 Bridge Server must be running on the Windows VM.
"""

import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone


class MT5BridgeClient:
    """
    HTTP client for connecting to MT5 via bridge server.
    
    The bridge server runs on Windows VM where MT5 is installed.
    This client communicates with it via HTTP.
    """
    
    def __init__(
        self,
        bridge_url: str = "http://localhost:5555",
        server: str = "FTMO-Demo",
        login: int = 0,
        password: str = "",
        timeout: int = 30,
    ):
        self.bridge_url = bridge_url.rstrip('/')
        self.server = server
        self.login = login
        self.password = password
        self.timeout = timeout
        self.connected = False
        self.account_info: Dict = {}
        self.symbol_map: Dict[str, str] = {}
    
    def health_check(self) -> bool:
        """Check if bridge server is online."""
        try:
            response = requests.get(
                f"{self.bridge_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def connect(self) -> bool:
        """Connect to MT5 via bridge."""
        try:
            response = requests.post(
                f"{self.bridge_url}/connect",
                json={
                    'server': self.server,
                    'login': self.login,
                    'password': self.password
                },
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                error = response.json().get('error', 'Unknown error')
                print(f"[MT5Bridge] Connection failed: {error}")
                return False
            
            self.account_info = response.json().get('account', {})
            self.connected = True
            return True
            
        except Exception as e:
            print(f"[MT5Bridge] Connection error: {e}")
            return False
    
    def disconnect(self) -> bool:
        """Disconnect from MT5."""
        try:
            response = requests.post(
                f"{self.bridge_url}/disconnect",
                timeout=5
            )
            self.connected = False
            return response.status_code == 200
        except Exception:
            self.connected = False
            return False
    
    def get_account_info(self) -> Dict:
        """Get current account info."""
        return self.account_info
    
    def map_symbols(self, symbols: List[str]) -> Dict[str, str]:
        """Map our symbol format to broker format."""
        try:
            response = requests.post(
                f"{self.bridge_url}/symbols",
                json={'symbols': symbols},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                return {}
            
            symbol_data = response.json().get('symbols', {})
            self.symbol_map = {k: v['broker_symbol'] for k, v in symbol_data.items()}
            return self.symbol_map
            
        except Exception as e:
            print(f"[MT5Bridge] Symbol mapping error: {e}")
            return {}
    
    def get_tick(self, symbol: str) -> Optional[Dict]:
        """Get current tick data for a symbol."""
        broker_symbol = self.symbol_map.get(symbol, symbol)
        
        try:
            response = requests.post(
                f"{self.bridge_url}/market_data",
                json={'symbol': broker_symbol},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                return None
            
            return response.json()
            
        except Exception as e:
            print(f"[MT5Bridge] Tick error: {e}")
            return None
    
    def execute_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: float,
        tp: float,
    ) -> Optional[Dict]:
        """
        Execute a market order.
        
        Args:
            symbol: Trading symbol
            direction: 'bullish' or 'bearish'
            volume: Lot size
            sl: Stop loss price
            tp: Take profit price
            
        Returns:
            Trade result dict or None on failure
        """
        broker_symbol = self.symbol_map.get(symbol, symbol)
        
        try:
            response = requests.post(
                f"{self.bridge_url}/execute_trade",
                json={
                    'symbol': broker_symbol,
                    'direction': direction,
                    'volume': volume,
                    'sl': sl,
                    'tp': tp
                },
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                error = response.json().get('error', 'Unknown')
                print(f"[MT5Bridge] Trade execution failed: {error}")
                return None
            
            return response.json()
            
        except Exception as e:
            print(f"[MT5Bridge] Trade execution error: {e}")
            return None
    
    def close_position(
        self,
        symbol: str,
        volume: float,
        direction: str,
    ) -> Optional[Dict]:
        """Close an open position."""
        broker_symbol = self.symbol_map.get(symbol, symbol)
        
        try:
            response = requests.post(
                f"{self.bridge_url}/close_position",
                json={
                    'symbol': broker_symbol,
                    'volume': volume,
                    'direction': direction
                },
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                return None
            
            return response.json()
            
        except Exception as e:
            print(f"[MT5Bridge] Position close error: {e}")
            return None
    
    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        try:
            response = requests.get(
                f"{self.bridge_url}/positions",
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                return []
            
            return response.json().get('positions', [])
            
        except Exception:
            return []
    
    def get_history(self, days: int = 30) -> List[Dict]:
        """Get trade history."""
        try:
            response = requests.get(
                f"{self.bridge_url}/history",
                params={'days': days},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                return []
            
            return response.json().get('trades', [])
            
        except Exception:
            return []
