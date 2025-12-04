#!/usr/bin/env python3
"""
Tradr Bot - Standalone MT5 Live Trading Bot

This bot runs 24/7 on your Windows VM and trades using the EXACT SAME
strategy logic that produced the great backtest results. Discord is NOT
required for trading - the bot operates independently.

IMPORTANT: Uses strategy_core.py directly - the same code as backtests!

Usage:
    python main_live_bot.py

Configuration:
    Set environment variables in .env file:
    - MT5_SERVER: Broker server name (e.g., "FTMO-Demo")
    - MT5_LOGIN: Account login number
    - MT5_PASSWORD: Account password
    - SCAN_INTERVAL_HOURS: How often to scan (default: 4)
"""

import os
import sys
import time
import json
import signal as sig_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from strategy_core import (
    StrategyParams,
    compute_confluence,
    compute_trade_levels,
    _infer_trend,
    _pick_direction_from_bias,
)

from tradr.mt5.client import MT5Client, PendingOrder
from tradr.risk.manager import RiskManager
from tradr.utils.logger import setup_logger


@dataclass
class PendingSetup:
    """Tracks a pending trade setup waiting for entry."""
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]
    confluence: int
    quality_factors: int
    created_at: str
    order_ticket: Optional[int] = None
    status: str = "pending"
    lot_size: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PendingSetup":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

from config import SIGNAL_MODE, MIN_CONFLUENCE_STANDARD, MIN_CONFLUENCE_AGGRESSIVE
from symbol_mapping import ALL_TRADABLE_FTMO, ftmo_to_oanda, oanda_to_ftmo


MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
SCAN_INTERVAL_HOURS = int(os.getenv("SCAN_INTERVAL_HOURS", "4"))

# Use same confluence as backtest (4/7 standard, 2/7 aggressive)
MIN_CONFLUENCE = MIN_CONFLUENCE_STANDARD if SIGNAL_MODE == "standard" else MIN_CONFLUENCE_AGGRESSIVE

TRADABLE_SYMBOLS = ALL_TRADABLE_FTMO

log = setup_logger("tradr", log_file="logs/tradr_live.log")
running = True


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    global running
    log.info("Shutdown signal received, stopping bot...")
    running = False


sig_module.signal(sig_module.SIGINT, signal_handler)
sig_module.signal(sig_module.SIGTERM, signal_handler)


class LiveTradingBot:
    """
    Main live trading bot.
    
    Uses the EXACT SAME strategy logic as backtest.py for perfect parity.
    Now uses pending orders to match backtest entry behavior exactly.
    """
    
    PENDING_SETUPS_FILE = "pending_setups.json"
    VALIDATE_INTERVAL_MINUTES = 15
    
    def __init__(self):
        self.mt5 = MT5Client(
            server=MT5_SERVER,
            login=MT5_LOGIN,
            password=MT5_PASSWORD,
        )
        self.risk_manager = RiskManager(state_file="challenge_state.json")
        self.params = StrategyParams()
        self.last_scan_time: Optional[datetime] = None
        self.last_validate_time: Optional[datetime] = None
        self.scan_count = 0
        self.pending_setups: Dict[str, PendingSetup] = {}
        self._load_pending_setups()
    
    def _load_pending_setups(self):
        """Load pending setups from file."""
        try:
            if Path(self.PENDING_SETUPS_FILE).exists():
                with open(self.PENDING_SETUPS_FILE, 'r') as f:
                    data = json.load(f)
                for symbol, setup_dict in data.items():
                    self.pending_setups[symbol] = PendingSetup.from_dict(setup_dict)
                log.info(f"Loaded {len(self.pending_setups)} pending setups from file")
        except Exception as e:
            log.error(f"Error loading pending setups: {e}")
            self.pending_setups = {}
    
    def _save_pending_setups(self):
        """Save pending setups to file."""
        try:
            data = {symbol: setup.to_dict() for symbol, setup in self.pending_setups.items()}
            with open(self.PENDING_SETUPS_FILE, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            log.error(f"Error saving pending setups: {e}")
    
    def connect(self) -> bool:
        """Connect to MT5."""
        log.info("=" * 70)
        log.info("CONNECTING TO MT5")
        log.info("=" * 70)
        
        if not self.mt5.connect():
            log.error("Failed to connect to MT5")
            return False
        
        account = self.mt5.get_account_info()
        log.info(f"Connected: {account.get('login')} @ {account.get('server')}")
        log.info(f"Balance: ${account.get('balance', 0):,.2f}")
        log.info(f"Equity: ${account.get('equity', 0):,.2f}")
        log.info(f"Leverage: 1:{account.get('leverage', 0)}")
        
        return True
    
    def disconnect(self):
        """Disconnect from MT5."""
        self.mt5.disconnect()
        log.info("Disconnected from MT5")
    
    def get_candle_data(self, symbol: str) -> Dict[str, List[Dict]]:
        """
        Get multi-timeframe candle data for a symbol.
        Same timeframes used in backtests for parity.
        """
        data = {
            "monthly": self.mt5.get_ohlcv(symbol, "MN1", 24),
            "weekly": self.mt5.get_ohlcv(symbol, "W1", 104),
            "daily": self.mt5.get_ohlcv(symbol, "D1", 500),
            "h4": self.mt5.get_ohlcv(symbol, "H4", 500),
        }
        return data
    
    def check_existing_position(self, symbol: str) -> bool:
        """Check if we already have a position on this symbol."""
        positions = self.mt5.get_my_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return True
        return False
    
    def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Scan a single symbol for trade setup.
        
        Uses EXACT SAME logic as backtest.py:
        1. Get HTF trends (M/W/D)
        2. Pick direction from bias
        3. Compute confluence flags
        4. Check for active setup
        
        Returns trade setup dict if signal is active, None otherwise.
        """
        log.info(f"[{symbol}] Scanning...")
        
        if self.check_existing_position(symbol):
            log.info(f"[{symbol}] Already in position, skipping")
            return None
        
        data = self.get_candle_data(symbol)
        
        if not data["daily"] or len(data["daily"]) < 30:
            log.warning(f"[{symbol}] Insufficient daily data")
            return None
        
        if not data["weekly"] or len(data["weekly"]) < 8:
            log.warning(f"[{symbol}] Insufficient weekly data")
            return None
        
        monthly_candles = data["monthly"] if data["monthly"] else []
        weekly_candles = data["weekly"]
        daily_candles = data["daily"]
        h4_candles = data["h4"] if data["h4"] else daily_candles[-20:]
        
        mn_trend = _infer_trend(monthly_candles) if monthly_candles else "mixed"
        wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
        d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"
        
        direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)
        
        flags, notes, trade_levels = compute_confluence(
            monthly_candles,
            weekly_candles,
            daily_candles,
            h4_candles,
            direction,
            self.params,
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
        
        if has_rr and confluence_score >= MIN_CONFLUENCE and quality_factors >= 1:
            status = "active"
        elif confluence_score >= MIN_CONFLUENCE:
            status = "watching"
        else:
            status = "scan_only"
        
        log.info(f"[{symbol}] {direction.upper()} | Conf: {confluence_score}/7 | Quality: {quality_factors} | Status: {status}")
        
        for pillar, is_met in flags.items():
            marker = "+" if is_met else "-"
            note = notes.get(pillar, "")
            log.debug(f"  [{marker}] {pillar}: {note}")
        
        if status != "active":
            return None
        
        if entry is None or sl is None or tp1 is None:
            log.warning(f"[{symbol}] Missing entry/SL/TP levels")
            return None
        
        risk = abs(entry - sl)
        if risk <= 0:
            log.warning(f"[{symbol}] Invalid risk (entry={entry}, sl={sl})")
            return None
        
        log.info(f"[{symbol}] ACTIVE SIGNAL FOUND!")
        log.info(f"  Direction: {direction.upper()}")
        log.info(f"  Confluence: {confluence_score}/7")
        log.info(f"  Entry: {entry:.5f}")
        log.info(f"  SL: {sl:.5f}")
        log.info(f"  TP1: {tp1:.5f}")
        log.info(f"  TP2: {tp2:.5f if tp2 else 'N/A'}")
        log.info(f"  TP3: {tp3:.5f if tp3 else 'N/A'}")
        
        return {
            "symbol": symbol,
            "direction": direction,
            "confluence": confluence_score,
            "quality_factors": quality_factors,
            "entry": entry,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp4": tp4,
            "tp5": tp5,
            "flags": flags,
            "notes": notes,
        }
    
    def place_setup_order(self, setup: Dict) -> bool:
        """
        Place a pending limit order for a setup (like backtest does).
        
        Instead of executing at market price, this places a pending order
        at the calculated entry level to match backtest behavior exactly.
        
        Risk checks (before order):
        1. Simulate worst-case DD if all open positions + new trade hit SL
        2. Block trade if it would breach daily (5%) or max (10%) DD
        3. Reduce lot size dynamically based on open positions
        """
        symbol = setup["symbol"]
        direction = setup["direction"]
        entry = setup["entry"]
        sl = setup["stop_loss"]
        tp1 = setup["tp1"]
        tp2 = setup.get("tp2")
        tp3 = setup.get("tp3")
        confluence = setup["confluence"]
        quality_factors = setup["quality_factors"]
        
        if symbol in self.pending_setups:
            existing = self.pending_setups[symbol]
            if existing.status == "pending":
                log.info(f"[{symbol}] Already have pending setup at {existing.entry_price:.5f}, skipping")
                return False
        
        risk_check = self.risk_manager.check_trade(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss_price=sl,
        )
        
        if not risk_check.allowed:
            log.warning(f"[{symbol}] Trade BLOCKED by risk manager: {risk_check.reason}")
            return False
        
        lot_size = risk_check.adjusted_lot
        
        log.info(f"[{symbol}] Placing PENDING ORDER (like backtest):")
        log.info(f"  Direction: {direction.upper()}")
        log.info(f"  Entry Level: {entry:.5f}")
        log.info(f"  SL: {sl:.5f}")
        log.info(f"  TP1: {tp1:.5f}")
        log.info(f"  Lot Size: {lot_size}")
        log.info(f"  Expiration: 24 hours")
        
        if risk_check.original_lot != risk_check.adjusted_lot:
            log.info(f"  (Lot reduced from {risk_check.original_lot:.2f} - {risk_check.reason})")
        
        log.info(f"  Simulated DD after trade: Daily {risk_check.daily_loss_after:.1f}%, Max {risk_check.max_drawdown_after:.1f}%")
        
        result = self.mt5.place_pending_order(
            symbol=symbol,
            direction=direction,
            volume=lot_size,
            entry_price=entry,
            sl=sl,
            tp=tp1,
            expiration_hours=24,
        )
        
        if not result.success:
            log.error(f"[{symbol}] Pending order FAILED: {result.error}")
            return False
        
        log.info(f"[{symbol}] PENDING ORDER PLACED SUCCESSFULLY!")
        log.info(f"  Order Ticket: {result.order_id}")
        log.info(f"  Entry Level: {result.price:.5f}")
        log.info(f"  Volume: {result.volume}")
        
        pending_setup = PendingSetup(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_loss=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            confluence=confluence,
            quality_factors=quality_factors,
            created_at=datetime.now(timezone.utc).isoformat(),
            order_ticket=result.order_id,
            status="pending",
            lot_size=lot_size,
        )
        
        self.pending_setups[symbol] = pending_setup
        self._save_pending_setups()
        
        return True
    
    def check_position_updates(self):
        """
        Check for position closures (TP/SL hits) and update state.
        
        This syncs our internal state with actual MT5 positions.
        """
        my_positions = self.mt5.get_my_positions()
        open_tickets = {p.ticket for p in my_positions}
        
        state_positions = self.risk_manager.state.open_positions.copy()
        
        for pos_dict in state_positions:
            order_id = pos_dict.get("order_id")
            if order_id is None:
                continue
            
            if order_id not in open_tickets:
                log.info(f"Position {order_id} closed (detected from MT5)")
                
                self.risk_manager.record_trade_close(
                    order_id=order_id,
                    exit_price=0.0,
                    pnl_usd=0.0,
                )
    
    def check_pending_orders(self):
        """
        Check status of pending orders every minute (like backtest simulation).
        
        - Detect if pending orders were filled (position exists)
        - Detect if orders expired or were cancelled
        - Cancel orders if price moved past SL (setup invalidated)
        """
        if not self.pending_setups:
            return
        
        my_positions = self.mt5.get_my_positions()
        position_symbols = {p.symbol for p in my_positions}
        
        my_pending_orders = self.mt5.get_my_pending_orders()
        pending_order_tickets = {o.ticket for o in my_pending_orders}
        
        setups_to_remove = []
        
        for symbol, setup in self.pending_setups.items():
            if setup.status != "pending":
                continue
            
            if symbol in position_symbols:
                log.info(f"[{symbol}] Pending order FILLED! Position now open")
                setup.status = "filled"
                
                self.risk_manager.record_trade_open(
                    symbol=symbol,
                    direction=setup.direction,
                    entry_price=setup.entry_price,
                    stop_loss=setup.stop_loss,
                    lot_size=setup.lot_size,
                    order_id=setup.order_ticket or 0,
                )
                continue
            
            if setup.order_ticket and setup.order_ticket not in pending_order_tickets:
                log.info(f"[{symbol}] Pending order EXPIRED or CANCELLED (ticket {setup.order_ticket})")
                setup.status = "expired"
                setups_to_remove.append(symbol)
                continue
            
            tick = self.mt5.get_tick(symbol)
            if tick:
                if setup.direction == "bullish" and tick.bid <= setup.stop_loss:
                    log.warning(f"[{symbol}] Price ({tick.bid:.5f}) breached SL ({setup.stop_loss:.5f}) - cancelling pending order")
                    if setup.order_ticket:
                        self.mt5.cancel_pending_order(setup.order_ticket)
                    setup.status = "cancelled"
                    setups_to_remove.append(symbol)
                elif setup.direction == "bearish" and tick.ask >= setup.stop_loss:
                    log.warning(f"[{symbol}] Price ({tick.ask:.5f}) breached SL ({setup.stop_loss:.5f}) - cancelling pending order")
                    if setup.order_ticket:
                        self.mt5.cancel_pending_order(setup.order_ticket)
                    setup.status = "cancelled"
                    setups_to_remove.append(symbol)
        
        for symbol in setups_to_remove:
            del self.pending_setups[symbol]
        
        if setups_to_remove:
            self._save_pending_setups()
    
    def validate_setup(self, symbol: str) -> bool:
        """
        Re-validate a pending setup to check if it's still valid.
        
        Like the backtest, cancels if:
        - Structure has shifted
        - SL has been breached
        - Confluence is no longer met
        """
        if symbol not in self.pending_setups:
            return True
        
        setup = self.pending_setups[symbol]
        if setup.status != "pending":
            return True
        
        data = self.get_candle_data(symbol)
        
        if not data["daily"] or len(data["daily"]) < 30:
            return True
        
        monthly_candles = data["monthly"] if data["monthly"] else []
        weekly_candles = data["weekly"]
        daily_candles = data["daily"]
        h4_candles = data["h4"] if data["h4"] else daily_candles[-20:]
        
        mn_trend = _infer_trend(monthly_candles) if monthly_candles else "mixed"
        wk_trend = _infer_trend(weekly_candles) if weekly_candles else "mixed"
        d_trend = _infer_trend(daily_candles) if daily_candles else "mixed"
        
        direction, _, _ = _pick_direction_from_bias(mn_trend, wk_trend, d_trend)
        
        if direction != setup.direction:
            log.warning(f"[{symbol}] Direction changed from {setup.direction} to {direction} - cancelling setup")
            if setup.order_ticket:
                self.mt5.cancel_pending_order(setup.order_ticket)
            del self.pending_setups[symbol]
            self._save_pending_setups()
            return False
        
        flags, notes, trade_levels = compute_confluence(
            monthly_candles,
            weekly_candles,
            daily_candles,
            h4_candles,
            direction,
            self.params,
        )
        
        confluence_score = sum(1 for v in flags.values() if v)
        has_rr = flags.get("rr", False)
        quality_factors = sum([
            flags.get("location", False),
            flags.get("fib", False),
            flags.get("liquidity", False),
            flags.get("structure", False),
            flags.get("htf_bias", False)
        ])
        
        if not (has_rr and confluence_score >= MIN_CONFLUENCE and quality_factors >= 1):
            log.warning(f"[{symbol}] Setup no longer valid (conf: {confluence_score}/7, quality: {quality_factors}) - cancelling")
            if setup.order_ticket:
                self.mt5.cancel_pending_order(setup.order_ticket)
            del self.pending_setups[symbol]
            self._save_pending_setups()
            return False
        
        return True
    
    def validate_all_setups(self):
        """Validate all pending setups periodically."""
        if not self.pending_setups:
            return
        
        log.info(f"Validating {len(self.pending_setups)} pending setups...")
        
        symbols_to_validate = list(self.pending_setups.keys())
        
        for symbol in symbols_to_validate:
            try:
                self.validate_setup(symbol)
                time.sleep(0.5)
            except Exception as e:
                log.error(f"[{symbol}] Error validating setup: {e}")
        
        self.last_validate_time = datetime.now(timezone.utc)
    
    def scan_all_symbols(self):
        """
        Scan all tradable symbols and place pending orders.
        
        Uses the same logic as the backtest walk-forward loop.
        Now places pending limit orders instead of market orders
        to match backtest entry behavior exactly.
        """
        log.info("=" * 70)
        log.info(f"MARKET SCAN - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        log.info(f"Strategy Mode: {SIGNAL_MODE} (Min Confluence: {MIN_CONFLUENCE}/7)")
        log.info(f"Using PENDING ORDERS (like backtest)")
        log.info("=" * 70)
        
        self.scan_count += 1
        signals_found = 0
        orders_placed = 0
        
        for symbol in TRADABLE_SYMBOLS:
            try:
                symbol_info = self.mt5.get_symbol_info(symbol)
                if symbol_info is None:
                    log.warning(f"[{symbol}] Symbol not available on this broker")
                    continue
                
                setup = self.scan_symbol(symbol)
                
                if setup:
                    signals_found += 1
                    
                    if self.place_setup_order(setup):
                        orders_placed += 1
                
                time.sleep(0.5)
                
            except Exception as e:
                log.error(f"[{symbol}] Error during scan: {e}")
                continue
        
        log.info("=" * 70)
        log.info("SCAN COMPLETE")
        log.info(f"  Symbols scanned: {len(TRADABLE_SYMBOLS)}")
        log.info(f"  Active signals: {signals_found}")
        log.info(f"  Pending orders placed: {orders_placed}")
        
        positions = self.mt5.get_my_positions()
        pending_orders = self.mt5.get_my_pending_orders()
        log.info(f"  Open positions: {len(positions)}")
        log.info(f"  Pending orders: {len(pending_orders)}")
        log.info(f"  Tracked setups: {len(self.pending_setups)}")
        
        status = self.risk_manager.get_status()
        log.info(f"  Challenge Phase: {status['phase']}")
        log.info(f"  Balance: ${status['balance']:,.2f}")
        log.info(f"  Profit: {status['profit_pct']:+.2f}% (Target: {status['target_pct']}%)")
        log.info(f"  Daily DD: {status['daily_loss_pct']:.2f}%/5%")
        log.info(f"  Max DD: {status['drawdown_pct']:.2f}%/10%")
        log.info(f"  Profitable Days: {status['profitable_days']}/{status['min_profitable_days']}")
        log.info("=" * 70)
        
        self.last_scan_time = datetime.now(timezone.utc)
    
    def run(self):
        """
        Main trading loop - runs 24/7.
        
        Schedule:
        - Every minute: check_pending_orders() and check_position_updates()
        - Every 15 min: validate_all_setups() to ensure pending orders are still valid
        - Every 4 hours: scan_all_symbols() for new setups
        
        This matches backtest behavior where:
        - Limit orders wait for fill at entry price
        - Orders are cancelled if SL breached or structure changes
        """
        log.info("=" * 70)
        log.info("TRADR BOT - LIVE TRADING (PENDING ORDER MODE)")
        log.info("=" * 70)
        log.info(f"Using SAME strategy as backtests (strategy_core.py)")
        log.info(f"Now using PENDING ORDERS for exact backtest parity!")
        log.info(f"Server: {MT5_SERVER}")
        log.info(f"Login: {MT5_LOGIN}")
        log.info(f"Scan Interval: {SCAN_INTERVAL_HOURS} hours")
        log.info(f"Validate Interval: {self.VALIDATE_INTERVAL_MINUTES} minutes")
        log.info(f"Strategy Mode: {SIGNAL_MODE}")
        log.info(f"Min Confluence: {MIN_CONFLUENCE}/7")
        log.info(f"Symbols: {len(TRADABLE_SYMBOLS)}")
        log.info("=" * 70)
        
        if not self.connect():
            log.error("Failed to connect to MT5. Exiting.")
            return
        
        log.info("Starting trading loop...")
        log.info("Press Ctrl+C to stop")
        
        global running
        
        self.scan_all_symbols()
        self.last_validate_time = datetime.now(timezone.utc)
        
        while running:
            try:
                now = datetime.now(timezone.utc)
                
                self.check_pending_orders()
                self.check_position_updates()
                
                if self.last_validate_time:
                    next_validate = self.last_validate_time + timedelta(minutes=self.VALIDATE_INTERVAL_MINUTES)
                    if now >= next_validate:
                        self.validate_all_setups()
                
                if self.last_scan_time:
                    next_scan = self.last_scan_time + timedelta(hours=SCAN_INTERVAL_HOURS)
                    if now >= next_scan:
                        self.scan_all_symbols()
                
                if not self.mt5.connected:
                    log.warning("MT5 connection lost, attempting reconnect...")
                    if self.connect():
                        log.info("Reconnected successfully")
                    else:
                        log.error("Reconnect failed, waiting 60s...")
                        time.sleep(60)
                        continue
                
                time.sleep(60)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Error in main loop: {e}")
                import traceback
                log.error(traceback.format_exc())
                time.sleep(60)
        
        log.info("Shutting down...")
        self._save_pending_setups()
        self.disconnect()
        log.info("Bot stopped")


def main():
    """Entry point."""
    Path("logs").mkdir(exist_ok=True)
    
    if not MT5_LOGIN or not MT5_PASSWORD:
        print("=" * 70)
        print("TRADR BOT - CONFIGURATION REQUIRED")
        print("=" * 70)
        print("")
        print("ERROR: MT5 credentials not configured!")
        print("")
        print("Create a .env file with:")
        print("  MT5_SERVER=YourBrokerServer")
        print("  MT5_LOGIN=12345678")
        print("  MT5_PASSWORD=YourPassword")
        print("")
        print("Optional Discord monitoring:")
        print("  DISCORD_BOT_TOKEN=your_token")
        print("")
        sys.exit(1)
    
    bot = LiveTradingBot()
    bot.run()


if __name__ == "__main__":
    main()
