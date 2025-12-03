"""
Live Trading Bot for Blueprint Trader AI - FTMO MT5 Demo
Runs continuously, executing trades based on the same strategy as backtests.
"""

import time
import requests
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

from data import get_ohlcv
from config import FOREX_PAIRS, METALS, INDICES, ENERGIES, CRYPTO_ASSETS, RISK_PER_TRADE_PCT
from strategy_core import (
    get_default_params,
    _infer_trend,
    _pick_direction_from_bias,
    compute_confluence,
)
from position_sizing import calculate_position_size_5ers
import os
from pathlib import Path

# Load environment variables from .env file if it exists (for Windows VM)
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print("[config] Loaded environment from .env file")
except ImportError:
    pass  # dotenv not installed, will use system env vars

# MT5 Bridge Configuration - Read from environment
MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://localhost:5555")
MT5_SERVER = os.getenv("MT5_SERVER", "FTMO-Demo")
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")

# Trading Configuration
SCAN_INTERVAL_HOURS = 4
MIN_CONFLUENCE = 4
TRADE_LOG_FILE = Path("live_trades.json")

class LiveTradingBot:
    def __init__(self):
        self.bridge_url = MT5_BRIDGE_URL.rstrip('/')
        self.connected = False
        self.symbol_map = {}
        self.active_trades = []
        self.all_trades = []

    def connect_mt5(self) -> bool:
        """Connect to MT5 via bridge server."""
        print(f"\n{'='*70}")
        print("CONNECTING TO MT5")
        print(f"{'='*70}")

        try:
            # Check bridge health
            response = requests.get(f"{self.bridge_url}/health", timeout=5)
            if response.status_code != 200:
                print("❌ Bridge server not responding")
                return False
            print("✓ Bridge server online")

            # Connect to MT5
            response = requests.post(
                f"{self.bridge_url}/connect",
                json={
                    'server': MT5_SERVER,
                    'login': MT5_LOGIN,
                    'password': MT5_PASSWORD
                },
                timeout=10
            )

            if response.status_code != 200:
                error = response.json().get('error', 'Unknown error')
                print(f"❌ MT5 login failed: {error}")
                return False

            account = response.json().get('account', {})
            self.connected = True

            print(f"✓ Connected to {MT5_SERVER}")
            print(f"   Login: {account.get('login')}")
            print(f"   Balance: ${account.get('balance', 0):,.2f}")
            print(f"   Equity: ${account.get('equity', 0):,.2f}")

            return True

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False

    def map_symbols(self, our_symbols: List[str]) -> bool:
        """Map our symbols to broker format."""
        try:
            response = requests.post(
                f"{self.bridge_url}/symbols",
                json={'symbols': our_symbols},
                timeout=10
            )

            if response.status_code != 200:
                print("❌ Symbol mapping failed")
                return False

            symbol_map = response.json().get('symbols', {})
            self.symbol_map = {k: v['broker_symbol'] for k, v in symbol_map.items()}

            print(f"✓ Mapped {len(self.symbol_map)} symbols")
            return True

        except Exception as e:
            print(f"❌ Symbol mapping error: {e}")
            return False

    def scan_and_trade(self):
        """Scan all assets and execute trades on high-confluence setups."""
        print(f"\n{'='*70}")
        print(f"MARKET SCAN - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*70}")

        # All tradeable assets
        all_symbols = FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS

        # Remove exotics (keep major pairs only)
        forex_majors = [
            "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "USD_CAD", "AUD_USD", "NZD_USD",
            "EUR_GBP", "EUR_JPY", "GBP_JPY", "AUD_JPY", "NZD_JPY"
        ]

        # Custom crypto/indices
        crypto = ["BTC_USD", "ETH_USD"]
        indices = ["SPX500_USD", "NAS100_USD"]
        commodities = ["XAU_USD", "XAG_USD", "WTICO_USD"]

        all_symbols = forex_majors + crypto + indices + commodities

        params = get_default_params()
        signals_found = 0
        trades_executed = 0

        for symbol in all_symbols:
            if symbol not in self.symbol_map:
                continue

            print(f"\n[{symbol}] Scanning...")

            try:
                # Load OHLCV data
                daily = get_ohlcv(symbol, timeframe="D", count=100, use_cache=False)
                weekly = get_ohlcv(symbol, timeframe="W", count=50, use_cache=False) or []
                monthly = get_ohlcv(symbol, timeframe="M", count=24, use_cache=False) or []
                h4 = get_ohlcv(symbol, timeframe="H4", count=100, use_cache=False) or []

                if not daily or len(daily) < 50:
                    print(f"  ⚠ Insufficient data")
                    continue

                # Determine direction
                mn_trend = _infer_trend(monthly) if monthly else "mixed"
                wk_trend = _infer_trend(weekly) if weekly else "mixed"
                d_trend = _infer_trend(daily) if daily else "mixed"

                direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)

                # Calculate confluence
                flags, notes, trade_levels = compute_confluence(
                    monthly, weekly, daily, h4, direction, params
                )

                entry, sl, tp1, tp2, tp3, tp4, tp5 = trade_levels
                confluence_score = sum(1 for v in flags.values() if v)
                has_rr = flags.get("rr", False)
                has_confirmation = flags.get("confirmation", False)

                # Trade criteria (same as backtest)
                if confluence_score >= MIN_CONFLUENCE and has_rr and has_confirmation and entry and sl and tp1:
                    signals_found += 1
                    print(f"  ✓ SIGNAL: {direction.upper()} | {confluence_score}/7 confluence")

                    # Check if we already have a trade on this symbol
                    if any(t['symbol'] == symbol for t in self.active_trades):
                        print(f"  ⚠ Already in trade, skipping")
                        continue

                    # Calculate position size
                    sizing = calculate_position_size_5ers(symbol, entry, sl)
                    lot_size = sizing["lot_size"]

                    print(f"  Entry: {entry:.5f}, SL: {sl:.5f}, TP1: {tp1:.5f}")
                    print(f"  Lot size: {lot_size:.2f} (risk: ${sizing['risk_usd']:.2f})")

                    # Execute trade
                    success = self.execute_trade(symbol, direction, entry, sl, tp1, lot_size, confluence_score)
                    if success:
                        trades_executed += 1
                else:
                    reason = []
                    if confluence_score < MIN_CONFLUENCE:
                        reason.append(f"confluence {confluence_score}/7")
                    if not has_rr:
                        reason.append("no RR")
                    if not has_confirmation:
                        reason.append("no confirmation")
                    print(f"  - No trade ({', '.join(reason)})")

            except Exception as e:
                print(f"  ❌ Error: {e}")

        print(f"\n{'='*70}")
        print(f"SCAN COMPLETE")
        print(f"  Signals found: {signals_found}")
        print(f"  Trades executed: {trades_executed}")
        print(f"  Active trades: {len(self.active_trades)}")
        print(f"{'='*70}")

    def execute_trade(self, symbol: str, direction: str, entry: float, sl: float, tp1: float, volume: float, confluence: int) -> bool:
        """Execute trade via MT5 bridge."""
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
                error = response.json().get('error', 'Unknown')
                print(f"  ❌ Execution failed: {error}")
                return False

            result = response.json()

            trade_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "broker_symbol": broker_symbol,
                "direction": direction,
                "entry_price": result['executed_price'],
                "stop_loss": sl,
                "tp1": tp1,
                "volume": result['volume'],
                "order_id": result['order_id'],
                "deal_id": result['deal_id'],
                "confluence": confluence,
                "status": "open"
            }

            self.active_trades.append(trade_data)
            self.all_trades.append(trade_data)
            self.save_trades()

            print(f"  ✅ TRADE EXECUTED: Order #{result['order_id']}")
            print(f"     Price: {result['executed_price']:.5f}")
            print(f"     Slippage: {result['slippage']:.5f}")

            return True

        except Exception as e:
            print(f"  ❌ Execution error: {e}")
            return False

    def save_trades(self):
        """Save all trades to file."""
        with open(TRADE_LOG_FILE, 'w') as f:
            json.dump(self.all_trades, f, indent=2)

    def run_forever(self):
        """Main loop - runs continuously."""
        print(f"\n{'='*70}")
        print("BLUEPRINT TRADER AI - LIVE BOT")
        print(f"{'='*70}")
        print(f"Strategy: Same as /backtest and /challenge")
        print(f"Account: FTMO Demo (10K High Stakes simulation)")
        print(f"Scan Interval: {SCAN_INTERVAL_HOURS} hours")
        print(f"Min Confluence: {MIN_CONFLUENCE}/7")
        print(f"{'='*70}\n")

        # Connect to MT5
        if not self.connect_mt5():
            print("Failed to connect to MT5. Exiting.")
            return

        # Map all symbols
        all_symbols = FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
        if not self.map_symbols(all_symbols):
            print("Failed to map symbols. Exiting.")
            return

        # Main trading loop
        scan_count = 0
        while True:
            scan_count += 1
            print(f"\n\n=== SCAN #{scan_count} ===")

            try:
                self.scan_and_trade()
            except Exception as e:
                print(f"❌ Scan error: {e}")

            # Sleep until next scan
            sleep_seconds = SCAN_INTERVAL_HOURS * 3600
            next_scan = datetime.now(timezone.utc).timestamp() + sleep_seconds
            next_scan_time = datetime.fromtimestamp(next_scan, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

            print(f"\n💤 Sleeping until next scan at {next_scan_time}")
            time.sleep(sleep_seconds)


if __name__ == "__main__":
    bot = LiveTradingBot()
    bot.run_forever()