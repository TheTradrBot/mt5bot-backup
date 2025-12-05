"""
Challenge Risk Manager - Elite Risk Protection for FTMO/Prop Firm Challenges

This module implements comprehensive risk management to pass 2-step prop firm
challenges without EVER breaching any rule.

CORE RULES ENFORCED (FTMO Standard):
1. Daily Loss Limit: <= 5% of starting balance of the day
2. Overall Max Drawdown: <= 10% (from initial balance)
3. No excessive exposure or position clustering
4. Target: +10% Phase 1, +5% Phase 2

SAFETY LAYERS IMPLEMENTED:
1. Global Risk Controller - Real-time P/L tracking with proactive SL adjustment
2. Dynamic Position Sizing - 0.7-1% risk per trade with partial scaling
3. Smart Concurrent Trade Limit - Max 4-6 open trades
4. Pending Order Management - Risk-based cancellation
5. Live Equity Protection Loop - 30-60 second monitoring
6. Challenge-Optimized Behavior - Adaptive risk based on current DD

Author: Blueprint Trader AI
Version: 2.0.0 - Elite Protection
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
from enum import Enum
import logging

from tradr.risk.position_sizing import calculate_lot_size, get_pip_value


class RiskMode(Enum):
    AGGRESSIVE = "aggressive"
    NORMAL = "normal"
    CONSERVATIVE = "conservative"
    ULTRA_SAFE = "ultra_safe"
    HALTED = "halted"


class ActionType(Enum):
    NONE = "none"
    REDUCE_LOT = "reduce_lot"
    MOVE_SL_BREAKEVEN = "move_sl_breakeven"
    PARTIAL_CLOSE = "partial_close"
    CLOSE_WORST = "close_worst"
    CLOSE_ALL = "close_all"
    CANCEL_PENDING = "cancel_pending"
    HALT_TRADING = "halt_trading"


@dataclass
class RiskAction:
    action: ActionType
    reason: str
    positions_affected: List[int] = field(default_factory=list)
    priority: int = 0
    executed: bool = False
    timestamp: str = ""


@dataclass
class PositionRisk:
    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    potential_loss_at_sl: float
    risk_pct: float
    distance_to_sl_pct: float
    time_open_hours: float


@dataclass
class AccountSnapshot:
    timestamp: datetime
    balance: float
    equity: float
    margin: float
    free_margin: float
    unrealized_pnl: float
    daily_pnl: float
    daily_pnl_pct: float
    total_drawdown: float
    total_drawdown_pct: float
    open_positions: int
    pending_orders: int
    total_risk_usd: float
    total_risk_pct: float
    pending_risk_usd: float = 0.0


@dataclass
class ChallengeConfig:
    enabled: bool = True
    phase: int = 1
    
    account_size: float = 10000.0
    phase1_target_pct: float = 10.0
    phase2_target_pct: float = 5.0
    max_daily_loss_pct: float = 5.0
    max_total_drawdown_pct: float = 10.0
    
    max_risk_per_trade_pct: float = 0.75
    max_cumulative_risk_pct: float = 3.5
    max_concurrent_trades: int = 5
    max_pending_orders: int = 6
    
    tp1_close_pct: float = 0.45
    tp2_close_pct: float = 0.30
    tp3_close_pct: float = 0.25
    
    daily_loss_warning_pct: float = 2.5
    daily_loss_reduce_pct: float = 3.5
    daily_loss_halt_pct: float = 4.5
    total_dd_warning_pct: float = 5.0
    total_dd_emergency_pct: float = 8.0
    
    protection_loop_interval_sec: float = 30.0
    pending_order_max_age_hours: float = 48.0
    
    profit_ultra_safe_threshold_pct: float = 8.0
    ultra_safe_risk_pct: float = 0.3


class ChallengeRiskManager:
    """
    Elite Risk Manager for Prop Firm Challenges.
    
    Implements all 7 safety layers to protect the account and ensure
    challenge pass while maximizing profit potential.
    """
    
    def __init__(
        self,
        config: ChallengeConfig = None,
        mt5_client = None,
        state_file: str = "challenge_risk_state.json",
        log_file: str = "logs/challenge_risk.log",
    ):
        self.config = config or ChallengeConfig()
        self.mt5 = mt5_client
        self.state_file = Path(state_file)
        
        self._setup_logging(log_file)
        
        self.initial_balance: float = self.config.account_size
        self.day_start_balance: float = self.config.account_size
        self.highest_equity: float = self.config.account_size
        self.current_day: str = ""
        
        self.current_mode: RiskMode = RiskMode.NORMAL
        self.halted: bool = False
        self.halt_reason: str = ""
        
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.peak_daily_profit: float = 0.0
        
        self.position_risks: Dict[int, PositionRisk] = {}
        self.pending_order_risks: Dict[int, Dict] = {}
        
        self.action_history: List[RiskAction] = []
        self.snapshots: List[AccountSnapshot] = []
        
        self._protection_thread: Optional[threading.Thread] = None
        self._protection_running: bool = False
        self._lock = threading.Lock()
        
        self._load_state()
        self._check_new_day()
        
        self.log.info("=" * 70)
        self.log.info("CHALLENGE RISK MANAGER INITIALIZED")
        self.log.info(f"  Mode: {'ENABLED' if self.config.enabled else 'DISABLED'}")
        self.log.info(f"  Phase: {self.config.phase}")
        self.log.info(f"  Account Size: ${self.config.account_size:,.2f}")
        self.log.info(f"  Max Daily Loss: {self.config.max_daily_loss_pct}%")
        self.log.info(f"  Max Drawdown: {self.config.max_total_drawdown_pct}%")
        self.log.info(f"  Max Risk/Trade: {self.config.max_risk_per_trade_pct}%")
        self.log.info(f"  Max Concurrent Trades: {self.config.max_concurrent_trades}")
        self.log.info("=" * 70)
    
    def _setup_logging(self, log_file: str):
        Path(log_file).parent.mkdir(exist_ok=True)
        self.log = logging.getLogger("challenge_risk")
        self.log.setLevel(logging.INFO)
        
        if not self.log.handlers:
            fh = logging.FileHandler(log_file)
            fh.setFormatter(logging.Formatter(
                '%(asctime)s [%(levelname)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            self.log.addHandler(fh)
            
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('[RISK] %(message)s'))
            self.log.addHandler(ch)
    
    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                self.initial_balance = state.get("initial_balance", self.config.account_size)
                self.day_start_balance = state.get("day_start_balance", self.config.account_size)
                self.highest_equity = state.get("highest_equity", self.config.account_size)
                self.current_day = state.get("current_day", "")
                self.halted = state.get("halted", False)
                self.halt_reason = state.get("halt_reason", "")
                self.config.phase = state.get("phase", 1)
                self.log.info(f"Loaded state from {self.state_file}")
            except Exception as e:
                self.log.error(f"Error loading state: {e}")
    
    def _save_state(self):
        try:
            state = {
                "initial_balance": self.initial_balance,
                "day_start_balance": self.day_start_balance,
                "highest_equity": self.highest_equity,
                "current_day": self.current_day,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
                "phase": self.config.phase,
                "last_update": datetime.now(timezone.utc).isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.log.error(f"Error saving state: {e}")
    
    def _check_new_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.current_day != today:
            self.log.info(f"New trading day: {today}")
            self.current_day = today
            self.peak_daily_profit = 0.0
            
            if self.halted and "daily" in self.halt_reason.lower():
                self.log.info("Daily halt cleared - new day started")
                self.halted = False
                self.halt_reason = ""
                self.current_mode = RiskMode.NORMAL
            
            self._save_state()
    
    def sync_with_mt5(self, balance: float, equity: float):
        with self._lock:
            if abs(self.initial_balance - balance) > 100:
                self.log.info(f"Syncing initial balance: {self.initial_balance:.2f} -> {balance:.2f}")
                self.initial_balance = balance
            
            self._check_new_day()
            
            if self.current_day and self.day_start_balance != balance:
                account_info = self.mt5.get_account_info() if self.mt5 else None
                if account_info:
                    positions = self.mt5.get_my_positions() if self.mt5 else []
                    if not positions:
                        self.day_start_balance = balance
            
            if equity > self.highest_equity:
                self.highest_equity = equity
            
            self._save_state()
    
    def get_account_snapshot(self) -> Optional[AccountSnapshot]:
        if not self.mt5:
            return None
        
        account = self.mt5.get_account_info()
        if not account:
            return None
        
        balance = account.get('balance', 0)
        equity = account.get('equity', 0)
        margin = account.get('margin', 0)
        free_margin = account.get('free_margin', 0)
        
        unrealized_pnl = equity - balance
        daily_pnl = equity - self.day_start_balance
        daily_pnl_pct = (daily_pnl / self.day_start_balance * 100) if self.day_start_balance > 0 else 0
        
        total_dd = self.initial_balance - equity if equity < self.initial_balance else 0
        total_dd_pct = (total_dd / self.initial_balance * 100) if self.initial_balance > 0 else 0
        
        positions = self.mt5.get_my_positions()
        pending = self.mt5.get_my_pending_orders()
        
        open_risk = self._calculate_total_open_risk()
        pending_risk = self._calculate_pending_orders_risk()
        total_risk = open_risk + pending_risk
        total_risk_pct = (total_risk / balance * 100) if balance > 0 else 0
        
        snapshot = AccountSnapshot(
            timestamp=datetime.now(timezone.utc),
            balance=balance,
            equity=equity,
            margin=margin,
            free_margin=free_margin,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            total_drawdown=total_dd,
            total_drawdown_pct=total_dd_pct,
            open_positions=len(positions),
            pending_orders=len(pending),
            total_risk_usd=total_risk,
            total_risk_pct=total_risk_pct,
            pending_risk_usd=pending_risk,
        )
        
        self.snapshots.append(snapshot)
        if len(self.snapshots) > 1000:
            self.snapshots = self.snapshots[-500:]
        
        return snapshot
    
    def _calculate_total_open_risk(self) -> float:
        if not self.mt5:
            return 0.0
        
        total_risk = 0.0
        positions = self.mt5.get_my_positions()
        
        for pos in positions:
            if pos.sl and pos.sl > 0:
                stop_distance = abs(pos.price_open - pos.sl)
                pip_value = get_pip_value(pos.symbol, pos.price_open)
                specs = self._get_symbol_specs(pos.symbol)
                pip_size = specs.get("pip_value", 0.0001)
                stop_pips = stop_distance / pip_size if pip_size > 0 else stop_distance
                potential_loss = stop_pips * pip_value * pos.volume
                total_risk += potential_loss
        
        return total_risk
    
    def _calculate_pending_orders_risk(self) -> float:
        if not self.mt5:
            return 0.0
        
        total_risk = 0.0
        pending_orders = self.mt5.get_my_pending_orders()
        
        for order in pending_orders:
            if order.sl and order.sl > 0:
                stop_distance = abs(order.price - order.sl)
                pip_value = get_pip_value(order.symbol, order.price)
                specs = self._get_symbol_specs(order.symbol)
                pip_size = specs.get("pip_value", 0.0001)
                stop_pips = stop_distance / pip_size if pip_size > 0 else stop_distance
                potential_loss = stop_pips * pip_value * order.volume
                total_risk += potential_loss
        
        return total_risk
    
    def get_total_exposure_risk(self) -> float:
        return self._calculate_total_open_risk() + self._calculate_pending_orders_risk()
    
    def _get_symbol_specs(self, symbol: str) -> Dict:
        from tradr.risk.position_sizing import get_contract_specs
        return get_contract_specs(symbol)
    
    def determine_risk_mode(self, snapshot: AccountSnapshot) -> RiskMode:
        if self.halted:
            return RiskMode.HALTED
        
        daily_loss_pct = abs(snapshot.daily_pnl_pct) if snapshot.daily_pnl_pct < 0 else 0
        total_dd_pct = snapshot.total_drawdown_pct
        profit_pct = (snapshot.equity - self.initial_balance) / self.initial_balance * 100 if self.initial_balance > 0 else 0
        
        if profit_pct >= self.config.profit_ultra_safe_threshold_pct:
            return RiskMode.ULTRA_SAFE
        
        if daily_loss_pct >= self.config.daily_loss_halt_pct:
            self.halted = True
            self.halt_reason = f"Daily loss limit approached: {daily_loss_pct:.1f}%"
            self._save_state()
            return RiskMode.HALTED
        
        if daily_loss_pct >= self.config.daily_loss_reduce_pct or total_dd_pct >= self.config.total_dd_emergency_pct:
            return RiskMode.CONSERVATIVE
        
        if daily_loss_pct >= self.config.daily_loss_warning_pct or total_dd_pct >= self.config.total_dd_warning_pct:
            return RiskMode.NORMAL
        
        if daily_loss_pct < 2.0 and total_dd_pct < 3.0:
            return RiskMode.AGGRESSIVE
        
        return RiskMode.NORMAL
    
    def get_adjusted_risk_per_trade(self) -> float:
        base_risk = self.config.max_risk_per_trade_pct
        
        if self.current_mode == RiskMode.AGGRESSIVE:
            return base_risk
        elif self.current_mode == RiskMode.NORMAL:
            return base_risk * 0.85
        elif self.current_mode == RiskMode.CONSERVATIVE:
            return base_risk * 0.5
        elif self.current_mode == RiskMode.ULTRA_SAFE:
            return self.config.ultra_safe_risk_pct
        else:
            return 0.0
    
    def check_trade_allowed(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss_price: float,
        requested_lot: float = None,
    ) -> Tuple[bool, float, str]:
        if not self.config.enabled:
            return True, requested_lot or 0.01, "Challenge mode disabled"
        
        if self.halted:
            return False, 0.0, f"Trading halted: {self.halt_reason}"
        
        snapshot = self.get_account_snapshot()
        if not snapshot:
            return False, 0.0, "Cannot get account info"
        
        self.current_mode = self.determine_risk_mode(snapshot)
        
        if self.current_mode == RiskMode.HALTED:
            return False, 0.0, "Trading halted due to risk limits"
        
        if snapshot.open_positions >= self.config.max_concurrent_trades:
            return False, 0.0, f"Max concurrent trades reached ({self.config.max_concurrent_trades})"
        
        total_exposure = snapshot.open_positions + snapshot.pending_orders
        if total_exposure >= self.config.max_concurrent_trades + self.config.max_pending_orders:
            return False, 0.0, f"Max total exposure reached (positions: {snapshot.open_positions}, pending: {snapshot.pending_orders})"
        
        if snapshot.pending_orders >= self.config.max_pending_orders:
            return False, 0.0, f"Max pending orders reached ({self.config.max_pending_orders})"
        
        adjusted_risk_pct = self.get_adjusted_risk_per_trade()
        if adjusted_risk_pct <= 0:
            return False, 0.0, "Risk mode does not allow new trades"
        
        sizing = calculate_lot_size(
            symbol=symbol,
            account_balance=snapshot.balance,
            risk_percent=adjusted_risk_pct / 100,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            existing_positions=snapshot.open_positions,
        )
        
        calculated_lot = sizing.get("lot_size", 0.01)
        trade_risk_usd = sizing.get("risk_usd", 0)
        
        new_total_risk = snapshot.total_risk_usd + trade_risk_usd
        new_total_risk_pct = (new_total_risk / snapshot.balance * 100) if snapshot.balance > 0 else 100
        
        if new_total_risk_pct > self.config.max_cumulative_risk_pct:
            available_risk = (self.config.max_cumulative_risk_pct / 100 * snapshot.balance) - snapshot.total_risk_usd
            if available_risk <= 0:
                return False, 0.0, f"Cumulative risk limit reached ({snapshot.total_risk_pct:.1f}%)"
            
            reduction = available_risk / trade_risk_usd if trade_risk_usd > 0 else 0
            calculated_lot = round(calculated_lot * reduction * 0.95, 2)
            calculated_lot = max(0.01, calculated_lot)
        
        simulated_daily_loss = abs(snapshot.daily_pnl) + new_total_risk if snapshot.daily_pnl < 0 else new_total_risk
        simulated_daily_loss_pct = (simulated_daily_loss / self.day_start_balance * 100) if self.day_start_balance > 0 else 0
        
        if simulated_daily_loss_pct >= self.config.max_daily_loss_pct:
            return False, 0.0, f"Would breach daily loss limit (simulated: {simulated_daily_loss_pct:.1f}%)"
        
        simulated_dd = self.initial_balance - snapshot.equity + new_total_risk
        simulated_dd_pct = (simulated_dd / self.initial_balance * 100) if self.initial_balance > 0 else 0
        
        if simulated_dd_pct >= self.config.max_total_drawdown_pct:
            return False, 0.0, f"Would breach max drawdown (simulated: {simulated_dd_pct:.1f}%)"
        
        final_lot = min(calculated_lot, requested_lot) if requested_lot else calculated_lot
        final_lot = round(max(0.01, final_lot), 2)
        
        reason = f"Approved ({self.current_mode.value} mode, risk: {adjusted_risk_pct:.2f}%)"
        self.log.info(f"Trade check [{symbol}]: {reason}, lot: {final_lot}")
        
        return True, final_lot, reason
    
    def get_partial_close_volumes(self, total_volume: float) -> Tuple[float, float, float]:
        tp1_vol = round(total_volume * self.config.tp1_close_pct, 2)
        tp2_vol = round(total_volume * self.config.tp2_close_pct, 2)
        tp3_vol = round(total_volume * self.config.tp3_close_pct, 2)
        
        tp1_vol = max(0.01, tp1_vol)
        tp2_vol = max(0.01, tp2_vol)
        tp3_vol = max(0.01, tp3_vol)
        
        total_planned = tp1_vol + tp2_vol + tp3_vol
        if total_planned > total_volume:
            ratio = total_volume / total_planned
            tp1_vol = round(tp1_vol * ratio, 2)
            tp2_vol = round(tp2_vol * ratio, 2)
            tp3_vol = round(total_volume - tp1_vol - tp2_vol, 2)
        
        return tp1_vol, tp2_vol, tp3_vol
    
    def run_protection_check(self) -> List[RiskAction]:
        if not self.config.enabled or not self.mt5:
            return []
        
        actions: List[RiskAction] = []
        
        snapshot = self.get_account_snapshot()
        if not snapshot:
            return []
        
        self._check_new_day()
        self.current_mode = self.determine_risk_mode(snapshot)
        
        daily_loss_pct = abs(snapshot.daily_pnl_pct) if snapshot.daily_pnl_pct < 0 else 0
        total_dd_pct = snapshot.total_drawdown_pct
        
        if daily_loss_pct >= self.config.daily_loss_halt_pct or total_dd_pct >= self.config.max_total_drawdown_pct * 0.95:
            actions.append(RiskAction(
                action=ActionType.CLOSE_ALL,
                reason=f"EMERGENCY: Daily loss {daily_loss_pct:.1f}% or DD {total_dd_pct:.1f}% at critical levels",
                priority=100,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            self.halted = True
            self.halt_reason = f"Emergency close triggered: Daily {daily_loss_pct:.1f}%, DD {total_dd_pct:.1f}%"
            self._save_state()
            return actions
        
        if daily_loss_pct >= self.config.daily_loss_reduce_pct or total_dd_pct >= self.config.total_dd_emergency_pct:
            pending_orders = self.mt5.get_my_pending_orders()
            if pending_orders:
                actions.append(RiskAction(
                    action=ActionType.CANCEL_PENDING,
                    reason=f"Approaching limits (Daily: {daily_loss_pct:.1f}%, DD: {total_dd_pct:.1f}%) - cancel all pending",
                    positions_affected=[o.ticket for o in pending_orders],
                    priority=80,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
        
        if daily_loss_pct >= 4.0 or total_dd_pct >= 8.0:
            positions = self.mt5.get_my_positions()
            if positions:
                positions_sorted = sorted(positions, key=lambda p: p.profit)
                worst_positions = positions_sorted[:2]
                
                for pos in worst_positions:
                    if pos.profit < 0 and pos.sl > 0:
                        if pos.type == 0:
                            if pos.price_open > pos.sl:
                                actions.append(RiskAction(
                                    action=ActionType.MOVE_SL_BREAKEVEN,
                                    reason=f"Protective SL move for {pos.symbol} (P/L: ${pos.profit:.2f})",
                                    positions_affected=[pos.ticket],
                                    priority=70,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                ))
                        else:
                            if pos.price_open < pos.sl:
                                actions.append(RiskAction(
                                    action=ActionType.MOVE_SL_BREAKEVEN,
                                    reason=f"Protective SL move for {pos.symbol} (P/L: ${pos.profit:.2f})",
                                    positions_affected=[pos.ticket],
                                    priority=70,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                ))
        
        if daily_loss_pct >= 4.5:
            positions = self.mt5.get_my_positions()
            if positions:
                worst_pos = min(positions, key=lambda p: p.profit)
                if worst_pos.profit < -50:
                    actions.append(RiskAction(
                        action=ActionType.CLOSE_WORST,
                        reason=f"Close worst position to protect daily limit: {worst_pos.symbol} (P/L: ${worst_pos.profit:.2f})",
                        positions_affected=[worst_pos.ticket],
                        priority=90,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ))
        
        positions = self.mt5.get_my_positions()
        if len(positions) > self.config.max_concurrent_trades:
            pending_orders = self.mt5.get_my_pending_orders()
            if pending_orders:
                actions.append(RiskAction(
                    action=ActionType.CANCEL_PENDING,
                    reason=f"Too many positions ({len(positions)}) - cancel pending until under limit",
                    positions_affected=[o.ticket for o in pending_orders],
                    priority=60,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
        
        pending_orders = self.mt5.get_my_pending_orders()
        now = datetime.now(timezone.utc)
        for order in pending_orders:
            age_hours = (now - order.time_setup).total_seconds() / 3600
            if age_hours > self.config.pending_order_max_age_hours:
                actions.append(RiskAction(
                    action=ActionType.CANCEL_PENDING,
                    reason=f"Pending order too old ({age_hours:.1f}h): {order.symbol}",
                    positions_affected=[order.ticket],
                    priority=40,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
        
        for action in actions:
            self.action_history.append(action)
        
        if len(self.action_history) > 500:
            self.action_history = self.action_history[-250:]
        
        return actions
    
    def execute_action(self, action: RiskAction) -> bool:
        if not self.mt5:
            return False
        
        try:
            if action.action == ActionType.CANCEL_PENDING:
                for ticket in action.positions_affected:
                    result = self.mt5.cancel_pending_order(ticket)
                    self.log.info(f"Cancelled pending order {ticket}: {'success' if result else 'failed'}")
                action.executed = True
                return True
            
            elif action.action == ActionType.MOVE_SL_BREAKEVEN:
                for ticket in action.positions_affected:
                    positions = self.mt5.get_positions()
                    pos = next((p for p in positions if p.ticket == ticket), None)
                    if pos:
                        result = self.mt5.modify_sl_tp(ticket, sl=pos.price_open)
                        self.log.info(f"Moved SL to breakeven for {pos.symbol}: {'success' if result else 'failed'}")
                action.executed = True
                return True
            
            elif action.action == ActionType.CLOSE_WORST:
                for ticket in action.positions_affected:
                    result = self.mt5.close_position(ticket)
                    self.log.info(f"Closed position {ticket}: {'success' if result.success else result.error}")
                action.executed = True
                return True
            
            elif action.action == ActionType.CLOSE_ALL:
                positions = self.mt5.get_my_positions()
                for pos in positions:
                    result = self.mt5.close_position(pos.ticket)
                    self.log.info(f"Emergency close {pos.symbol}: {'success' if result.success else result.error}")
                
                pending = self.mt5.get_my_pending_orders()
                for order in pending:
                    self.mt5.cancel_pending_order(order.ticket)
                
                action.executed = True
                return True
            
            elif action.action == ActionType.HALT_TRADING:
                self.halted = True
                self.halt_reason = action.reason
                self._save_state()
                action.executed = True
                return True
            
        except Exception as e:
            self.log.error(f"Error executing action {action.action}: {e}")
            return False
        
        return False
    
    def _protection_loop(self):
        self.log.info("Protection loop started")
        
        while self._protection_running:
            try:
                actions = self.run_protection_check()
                
                actions_sorted = sorted(actions, key=lambda a: a.priority, reverse=True)
                
                for action in actions_sorted:
                    self.log.warning(f"Executing risk action: {action.action.value} - {action.reason}")
                    self.execute_action(action)
                
                time.sleep(self.config.protection_loop_interval_sec)
                
            except Exception as e:
                self.log.error(f"Error in protection loop: {e}")
                time.sleep(10)
        
        self.log.info("Protection loop stopped")
    
    def start_protection_loop(self):
        if self._protection_running:
            return
        
        self._protection_running = True
        self._protection_thread = threading.Thread(
            target=self._protection_loop,
            daemon=True,
            name="RiskProtection"
        )
        self._protection_thread.start()
        self.log.info("Risk protection loop started")
    
    def stop_protection_loop(self):
        self._protection_running = False
        if self._protection_thread:
            self._protection_thread.join(timeout=5)
        self.log.info("Risk protection loop stopped")
    
    def get_status(self) -> Dict[str, Any]:
        snapshot = self.get_account_snapshot()
        
        return {
            "enabled": self.config.enabled,
            "phase": self.config.phase,
            "mode": self.current_mode.value,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "initial_balance": self.initial_balance,
            "day_start_balance": self.day_start_balance,
            "highest_equity": self.highest_equity,
            "current_balance": snapshot.balance if snapshot else 0,
            "current_equity": snapshot.equity if snapshot else 0,
            "daily_pnl": snapshot.daily_pnl if snapshot else 0,
            "daily_pnl_pct": snapshot.daily_pnl_pct if snapshot else 0,
            "total_drawdown_pct": snapshot.total_drawdown_pct if snapshot else 0,
            "open_positions": snapshot.open_positions if snapshot else 0,
            "pending_orders": snapshot.pending_orders if snapshot else 0,
            "total_risk_pct": snapshot.total_risk_pct if snapshot else 0,
            "max_risk_per_trade": self.get_adjusted_risk_per_trade(),
            "actions_today": len([a for a in self.action_history if a.timestamp.startswith(self.current_day)]),
        }
    
    def reset_daily_tracking(self, new_balance: float):
        self.day_start_balance = new_balance
        self.current_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.peak_daily_profit = 0.0
        
        if self.halted and "daily" in self.halt_reason.lower():
            self.halted = False
            self.halt_reason = ""
            self.current_mode = RiskMode.NORMAL
        
        self._save_state()
        self.log.info(f"Daily tracking reset. New day start balance: ${new_balance:.2f}")
    
    def advance_to_phase2(self, new_balance: float):
        self.config.phase = 2
        self.initial_balance = new_balance
        self.day_start_balance = new_balance
        self.highest_equity = new_balance
        self.halted = False
        self.halt_reason = ""
        self.current_mode = RiskMode.NORMAL
        self._save_state()
        self.log.info(f"Advanced to Phase 2. Initial balance: ${new_balance:.2f}")
    
    def emergency_close_all(self, reason: str = "Manual emergency close"):
        self.log.warning(f"EMERGENCY CLOSE ALL: {reason}")
        
        action = RiskAction(
            action=ActionType.CLOSE_ALL,
            reason=reason,
            priority=100,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
        self.execute_action(action)
        self.halted = True
        self.halt_reason = reason
        self._save_state()
    
    def resume_trading(self):
        if not self.halted:
            return
        
        self.halted = False
        self.halt_reason = ""
        self.current_mode = RiskMode.NORMAL
        self._save_state()
        self.log.info("Trading resumed")


def create_challenge_manager(
    mt5_client,
    phase: int = 1,
    account_size: float = 10000.0,
    enabled: bool = True,
) -> ChallengeRiskManager:
    config = ChallengeConfig(
        enabled=enabled,
        phase=phase,
        account_size=account_size,
    )
    
    return ChallengeRiskManager(
        config=config,
        mt5_client=mt5_client,
    )
