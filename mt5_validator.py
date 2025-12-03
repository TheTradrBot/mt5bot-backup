"""
MT5 Remote Validator - Connects to MT5 Bridge running on Windows VM.
This runs on Replit and sends requests to your Windows machine via HTTP.
"""

import requests
import pandas as pd
import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
import time

from strategy_core import (
    StrategyParams,
    generate_signals,
    get_default_params,
    _infer_trend,
    _pick_direction_from_bias,
    compute_confluence,
)
from data import get_ohlcv
from backtest import run_backtest
from position_sizing import calculate_position_size_5ers
from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT, CONTRACT_SPECS


class MT5RemoteValidator:
    """Validates live MT5 execution via remote bridge server."""

    def __init__(self, bridge_url: str, server: str, login: int, password: str):
        self.bridge_url = bridge_url.rstrip('/')
        self.server = server
        self.login = login
        self.password = password
        self.connected = False
        self.symbol_map = {}
        self.test_start_time = None
        self.live_trades: List[Dict] = []
        self.logs_dir = Path("/tmp/replit_test_logs")
        self.plots_dir = Path("/tmp/plots")

        # Create directories
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.plots_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """Connect to MT5 via bridge server."""
        print(f"\n{'='*70}")
        print("MT5 REMOTE CONNECTION")
        print(f"{'='*70}")
        print(f"Bridge URL: {self.bridge_url}")

        # Check bridge health
        try:
            response = requests.get(f"{self.bridge_url}/health", timeout=5)
            if response.status_code != 200:
                print(f"❌ Bridge server not responding")
                return False
            print(f"✓ Bridge server online")
        except requests.exceptions.RequestException as e:
            print(f"❌ Cannot reach bridge server: {e}")
            return False

        # Connect to MT5
        try:
            response = requests.post(
                f"{self.bridge_url}/connect",
                json={
                    'server': self.server,
                    'login': self.login,
                    'password': self.password
                },
                timeout=10
            )

            if response.status_code != 200:
                error = response.json().get('error', 'Unknown error')
                print(f"❌ MT5 login failed: {error}")
                return False

            account = response.json().get('account', {})
            self.connected = True

            print(f"✓ Connected to {self.server}")
            print(f"\n📊 Account Information:")
            print(f"   Login: {account.get('login')}")
            print(f"   Balance: ${account.get('balance', 0):,.2f}")
            print(f"   Equity: ${account.get('equity', 0):,.2f}")
            print(f"   Leverage: 1:{account.get('leverage', 0)}")

            return True

        except requests.exceptions.RequestException as e:
            print(f"❌ Connection failed: {e}")
            return False

    def map_symbols(self, our_symbols: List[str]) -> Dict[str, str]:
        """Map our symbol format to broker's format."""
        print(f"\n{'='*70}")
        print("SYMBOL MAPPING")
        print(f"{'='*70}")

        try:
            response = requests.post(
                f"{self.bridge_url}/symbols",
                json={'symbols': our_symbols},
                timeout=10
            )

            if response.status_code != 200:
                print(f"❌ Failed to get symbols")
                return {}

            symbol_map = response.json().get('symbols', {})

            for our_sym, info in symbol_map.items():
                broker_sym = info['broker_symbol']
                print(f"✓ {our_sym} -> {broker_sym}")
                print(f"   Digits: {info['digits']}")
                print(f"   Min Lot: {info['min_lot']}")
                print(f"   Spread: {info['spread']}")

            self.symbol_map = {k: v['broker_symbol'] for k, v in symbol_map.items()}
            return self.symbol_map

        except requests.exceptions.RequestException as e:
            print(f"❌ Symbol mapping failed: {e}")
            return {}

    def execute_trade(self, symbol: str, direction: str, entry: float, sl: float, 
                     tp1: float, volume: float) -> Optional[Dict]:
        """Execute a market order via bridge."""
        broker_symbol = self.symbol_map.get(symbol, symbol)

        try:
            response = requests.post(
                f"{self.bridge_url}/execute_trade",
                json={
                    'symbol': broker_symbol,
                    'direction': direction,
                    'volume': volume,
                    'sl': sl,
                    'tp': tp1
                },
                timeout=15
            )

            if response.status_code != 200:
                error = response.json().get('error', 'Unknown error')
                print(f"❌ Trade execution failed: {error}")
                return None

            result = response.json()

            execution_data = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "broker_symbol": broker_symbol,
                "direction": direction,
                "order_type": "BUY" if direction == "bullish" else "SELL",
                "executed_price": result['executed_price'],
                "volume": result['volume'],
                "slippage": result['slippage'],
                "execution_time_ms": result['execution_time_ms'],
                "order_id": result['order_id'],
                "deal_id": result['deal_id'],
                "stop_loss": sl,
                "take_profit": tp1,
                "reason": "OPEN",
                "balance": result['balance'],
            }

            print(f"\n✓ Order executed: {result['order_id']}")
            print(f"   Symbol: {broker_symbol}")
            print(f"   Direction: {direction.upper()}")
            print(f"   Volume: {result['volume']} lots")
            print(f"   Price: {result['executed_price']:.5f}")
            print(f"   Slippage: {result['slippage']:.5f}")
            print(f"   Execution: {result['execution_time_ms']:.1f}ms")

            return execution_data

        except requests.exceptions.RequestException as e:
            print(f"❌ Trade execution failed: {e}")
            return None

    def run_test(self, symbols: List[str], target_trades: int = 2) -> Dict:
        """Run live validation test until N trades execute."""
        print(f"\n{'='*70}")
        print(f"STARTING LIVE VALIDATION TEST")
        print(f"{'='*70}")
        print(f"Target: {target_trades} trades")
        print(f"Symbols: {', '.join(symbols)}")
        print(f"Risk per trade: {RISK_PER_TRADE_PCT*100:.2f}%")

        self.test_start_time = datetime.now(timezone.utc)
        params = get_default_params()

        # Map symbols
        self.map_symbols(symbols)

        trades_executed = 0
        open_positions = []

        while trades_executed < target_trades:
            print(f"\n--- Scan {trades_executed + 1} ---")

            for symbol in symbols:
                if symbol not in self.symbol_map:
                    continue

                print(f"\nScanning {symbol}...")

                # Load OHLCV data
                daily = get_ohlcv(symbol, timeframe="D", count=100, use_cache=False)
                weekly = get_ohlcv(symbol, timeframe="W", count=50, use_cache=False) or []
                monthly = get_ohlcv(symbol, timeframe="M", count=24, use_cache=False) or []
                h4 = get_ohlcv(symbol, timeframe="H4", count=100, use_cache=False) or []

                if not daily or len(daily) < 50:
                    print(f"  ⚠ Insufficient data")
                    continue

                # Run strategy logic
                mn_trend = _infer_trend(monthly) if monthly else "mixed"
                wk_trend = _infer_trend(weekly) if weekly else "mixed"
                d_trend = _infer_trend(daily) if daily else "mixed"

                direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

                flags, notes, trade_levels = compute_confluence(
                    monthly, weekly, daily, h4, direction, params
                )

                entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels
                confluence_score = sum(1 for v in flags.values() if v)
                has_rr = flags.get("rr", False)

                if confluence_score >= params.min_confluence and has_rr and entry and sl and tp1:
                    print(f"  ✓ SIGNAL FOUND: {direction} (confluence: {confluence_score}/7)")

                    sizing = calculate_position_size_5ers(symbol, entry, sl)
                    lot_size = sizing["lot_size"]

                    print(f"  Entry: {entry:.5f}, SL: {sl:.5f}, TP1: {tp1:.5f}")
                    print(f"  Lot size: {lot_size:.2f} (risk: ${sizing['risk_usd']:.2f})")

                    execution = self.execute_trade(symbol, direction, entry, sl, tp1, lot_size)

                    if execution:
                        self.live_trades.append(execution)
                        open_positions.append(execution)
                        trades_executed += 1
                        self.save_execution_log(execution)

                        if trades_executed >= target_trades:
                            break
                else:
                    print(f"  - No signal (confluence: {confluence_score}/7)")

            if trades_executed < target_trades:
                print(f"\nWaiting 15 minutes before next scan...")
                time.sleep(900)

        print(f"\n{'='*70}")
        print(f"TEST COMPLETE - {trades_executed} trades executed")
        print(f"{'='*70}")

        # Close positions
        for pos in open_positions:
            print(f"\nClosing position: {pos['symbol']}")
            try:
                response = requests.post(
                    f"{self.bridge_url}/close_position",
                    json={
                        'symbol': pos['broker_symbol'],
                        'volume': pos['volume'],
                        'direction': pos['direction']
                    },
                    timeout=10
                )
                if response.status_code == 200:
                    result = response.json()
                    print(f"  ✓ Closed at {result['executed_price']:.5f}")
            except Exception as e:
                print(f"  ❌ Close failed: {e}")

        return {
            "trades_executed": trades_executed,
            "live_trades": self.live_trades,
        }

    def save_execution_log(self, execution: Dict):
        """Save execution log to CSV and JSON."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_path = self.logs_dir / f"execution_{timestamp}.csv"
        with open(csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=execution.keys())
            writer.writeheader()
            writer.writerow(execution)

        json_path = self.logs_dir / f"execution_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump(execution, f, indent=2)

        print(f"  📝 Logs saved: {csv_path.name}")

    def disconnect(self):
        """Disconnect from MT5."""
        if self.connected:
            try:
                requests.post(f"{self.bridge_url}/disconnect", timeout=5)
                print("\n✓ Disconnected from MT5")
            except:
                pass
            self.connected = False


def run_mt5_validation(bridge_url: str, server: str, login: int, password: str, 
                       symbols: List[str], target_trades: int = 2):
    """Main entry point for remote MT5 validation."""
    validator = MT5RemoteValidator(bridge_url, server, login, password)

    try:
        if not validator.connect():
            return None

        result = validator.run_test(symbols, target_trades)
        return result

    finally:
        validator.disconnect()


if __name__ == "__main__":
    # FTMO Demo credentials
    # Update these with your actual Windows VM IP and port
    BRIDGE_URL = "http://YOUR_WINDOWS_VM_IP:5555"  # e.g., "http://192.168.1.100:5555"
    SERVER = "FTMO-Demo"
    LOGIN = 1512190437
    PASSWORD = "$c@mAU7F"
    
    # Test all forex pairs except exotics
    from config import FOREX_PAIRS

    print("Starting MT5 Remote Validation Test...")
    print(f"Bridge: {BRIDGE_URL}")
    print(f"Target: 2 trades")
    
    result = run_mt5_validation(
        bridge_url=BRIDGE_URL,
        server=SERVER,
        login=LOGIN,
        password=PASSWORD,
        symbols=FOREX_PAIRS[:10],  # Test first 10 major pairs
        target_trades=2
    )
    
    if result:
        print(f"\n✅ Validation complete!")
        print(f"Trades executed: {result['trades_executed']}")
        print(f"Logs saved to: /tmp/replit_test_logs/")
    else:
        print(f"\n❌ Validation failed")