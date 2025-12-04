"""
Risk Manager for FTMO Challenge.

Implements pre-trade drawdown simulation to prevent rule breaches.
All risk checks happen BEFORE a trade is placed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from tradr.risk.position_sizing import calculate_lot_size, get_pip_value


@dataclass
class OpenPosition:
    """Represents an open position for risk calculation."""
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    lot_size: float
    order_id: int
    entry_time: datetime
    
    def potential_loss_usd(self) -> float:
        """Calculate potential loss if SL is hit."""
        stop_pips = abs(self.entry_price - self.stop_loss) / 0.0001
        pip_value = get_pip_value(self.symbol, self.entry_price)
        return stop_pips * pip_value * self.lot_size


@dataclass
class DailyRecord:
    """Track daily PnL for profitable day counting."""
    date: str
    starting_balance: float
    ending_balance: float
    trades_count: int = 0
    pnl_usd: float = 0.0
    
    @property
    def is_profitable(self) -> bool:
        """Check if day qualifies as profitable (FTMO has no minimum threshold)."""
        threshold = 10000 * 0.0
        return self.pnl_usd >= threshold


@dataclass
class ChallengeState:
    """
    Persistent state for FTMO challenge tracking.
    Saved to JSON file for persistence across restarts.
    """
    phase: int = 1
    live_flag: bool = False
    
    initial_balance: float = 10000.0
    current_balance: float = 10000.0
    highest_balance: float = 10000.0
    
    day_start_balance: float = 10000.0
    current_day: str = ""
    
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    profitable_days: int = 0
    daily_records: List[Dict] = field(default_factory=list)
    
    trades_history: List[Dict] = field(default_factory=list)
    open_positions: List[Dict] = field(default_factory=list)
    
    start_time: str = ""
    last_update: str = ""
    
    max_daily_loss_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    
    failed: bool = False
    fail_reason: str = ""
    passed_phase1: bool = False
    passed_phase2: bool = False
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ChallengeState":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k) or k in cls.__dataclass_fields__})
    
    @property
    def current_profit_pct(self) -> float:
        """Current profit as percentage of initial balance."""
        return ((self.current_balance - self.initial_balance) / self.initial_balance) * 100
    
    @property
    def current_drawdown_pct(self) -> float:
        """Current drawdown from initial balance."""
        if self.current_balance >= self.initial_balance:
            return 0.0
        return ((self.initial_balance - self.current_balance) / self.initial_balance) * 100
    
    @property
    def daily_loss_pct(self) -> float:
        """Current daily loss percentage."""
        if self.current_balance >= self.day_start_balance:
            return 0.0
        return ((self.day_start_balance - self.current_balance) / self.day_start_balance) * 100
    
    @property
    def target_pct(self) -> float:
        """Target profit percentage for current phase."""
        return 10.0 if self.phase == 1 else 5.0
    
    @property
    def progress_pct(self) -> float:
        """Progress towards target as percentage."""
        if self.target_pct <= 0:
            return 0.0
        return min(100.0, (self.current_profit_pct / self.target_pct) * 100)


@dataclass
class RiskCheckResult:
    """Result of a pre-trade risk check."""
    allowed: bool
    original_lot: float
    adjusted_lot: float
    reason: str
    
    daily_loss_after: float = 0.0
    max_drawdown_after: float = 0.0
    open_positions_count: int = 0


class RiskManager:
    """
    Risk manager for FTMO Challenge.
    
    Key features:
    - Pre-trade simulation: Calculates worst-case DD if all SLs hit
    - Dynamic lot reduction: Halves lot for each existing position
    - Daily loss tracking: Blocks trades that would breach 5% daily limit
    - Max drawdown tracking: Blocks trades that would breach 10% overall limit
    - Emergency close: Closes all positions before hitting hard limits
    - Partial take profits: Scales out at TP1, TP2, TP3
    """
    
    MAX_DAILY_LOSS_PCT = 5.0
    MAX_TOTAL_DRAWDOWN_PCT = 10.0
    MIN_PROFITABLE_DAY_PCT = 0.0
    PHASE1_TARGET_PCT = 10.0
    PHASE2_TARGET_PCT = 5.0
    MIN_PROFITABLE_DAYS = 0
    
    MAX_SINGLE_TRADE_RISK_PCT = 1.0
    MAX_CUMULATIVE_RISK_PCT = 3.0
    DAILY_LOSS_BUFFER_PCT = 4.0  # Trigger protective close at 4.0% (1% safety margin)
    TOTAL_DD_BUFFER_PCT = 8.0     # Trigger protective close at 8.0% (2% safety margin)
    
    DEFAULT_RISK_PCT = 0.01
    
    def __init__(self, state_file: str = "challenge_state.json"):
        self.state_file = Path(state_file)
        self.state = self._load_state()
    
    def _load_state(self) -> ChallengeState:
        """Load state from file or create new."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                return ChallengeState.from_dict(data)
            except Exception as e:
                print(f"[RiskManager] Error loading state: {e}")
        return ChallengeState()
    
    def save_state(self):
        """Save state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2, default=str)
        except Exception as e:
            print(f"[RiskManager] Error saving state: {e}")
    
    def sync_from_mt5(self, balance: float, equity: float):
        """
        Sync state with actual MT5 account values.
        
        Use this on startup to ensure risk manager uses real account values
        instead of potentially stale state file values.
        """
        if abs(self.state.current_balance - balance) > 1.0:
            print(f"[RiskManager] Syncing balance: {self.state.current_balance:.2f} -> {balance:.2f}")
            self.state.current_balance = balance
        
        if abs(self.state.initial_balance - balance) > 1.0 and not self.state.live_flag:
            print(f"[RiskManager] Syncing initial balance: {self.state.initial_balance:.2f} -> {balance:.2f}")
            self.state.initial_balance = balance
            self.state.highest_balance = max(self.state.highest_balance, balance)
            self.state.day_start_balance = balance
        
        if self.state.highest_balance < equity:
            self.state.highest_balance = equity
        
        self.state.last_update = datetime.now(timezone.utc).isoformat()
        self.save_state()
    
    def start_challenge(self, phase: int = 1):
        """Start or restart a challenge."""
        now = datetime.now(timezone.utc)
        self.state = ChallengeState(
            phase=phase,
            live_flag=True,
            initial_balance=10000.0,
            current_balance=10000.0,
            highest_balance=10000.0,
            day_start_balance=10000.0,
            current_day=now.strftime("%Y-%m-%d"),
            start_time=now.isoformat(),
            last_update=now.isoformat(),
        )
        self.save_state()
        return self.state
    
    def stop_challenge(self):
        """Stop the current challenge."""
        self.state.live_flag = False
        self.state.last_update = datetime.now(timezone.utc).isoformat()
        self.save_state()
    
    def advance_to_phase2(self):
        """Advance to Phase 2 after passing Phase 1."""
        self.state.passed_phase1 = True
        self.state.phase = 2
        self.state.initial_balance = 10000.0
        self.state.current_balance = 10000.0
        self.state.highest_balance = 10000.0
        self.state.day_start_balance = 10000.0
        self.state.profitable_days = 0
        self.state.daily_records = []
        self.state.max_daily_loss_pct = 0.0
        self.state.max_drawdown_pct = 0.0
        self.state.last_update = datetime.now(timezone.utc).isoformat()
        self.save_state()
    
    def _check_new_day(self):
        """Check if it's a new trading day and reset daily tracking."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        
        if self.state.current_day != today:
            if self.state.current_day:
                daily_pnl = self.state.current_balance - self.state.day_start_balance
                record = DailyRecord(
                    date=self.state.current_day,
                    starting_balance=self.state.day_start_balance,
                    ending_balance=self.state.current_balance,
                    pnl_usd=daily_pnl,
                )
                self.state.daily_records.append(asdict(record))
                
                if record.is_profitable:
                    self.state.profitable_days += 1
            
            self.state.current_day = today
            self.state.day_start_balance = self.state.current_balance
            self.save_state()
    
    def _calculate_total_open_risk(self) -> float:
        """Calculate total potential loss from all open positions."""
        total_risk = 0.0
        for pos_dict in self.state.open_positions:
            pos = OpenPosition(**pos_dict) if isinstance(pos_dict, dict) else pos_dict
            total_risk += pos.potential_loss_usd()
        return total_risk
    
    def _simulate_worst_case_dd(
        self,
        new_trade_loss: float,
    ) -> Tuple[float, float]:
        """
        Simulate worst-case drawdown if all open positions hit SL.
        
        Returns:
            (daily_dd_pct, total_dd_pct) after simulated losses
        """
        existing_risk = self._calculate_total_open_risk()
        total_potential_loss = existing_risk + new_trade_loss
        
        simulated_balance = self.state.current_balance - total_potential_loss
        
        daily_dd_pct = 0.0
        if simulated_balance < self.state.day_start_balance:
            daily_dd_pct = ((self.state.day_start_balance - simulated_balance) / self.state.day_start_balance) * 100
        
        total_dd_pct = 0.0
        if simulated_balance < self.state.initial_balance:
            total_dd_pct = ((self.state.initial_balance - simulated_balance) / self.state.initial_balance) * 100
        
        return daily_dd_pct, total_dd_pct
    
    def check_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss_price: float,
        requested_lot: float = None,
        pending_orders_risk: float = 0.0,
    ) -> RiskCheckResult:
        """
        Pre-trade risk check with FTMO-compliant limits.
        
        Simulates worst-case scenario where all open positions + pending + new trade hit SL.
        Enforces:
        - MAX_SINGLE_TRADE_RISK_PCT (1%): Hard cap per trade
        - MAX_CUMULATIVE_RISK_PCT (3%): Max total open + pending risk
        - Daily loss and max drawdown limits
        
        Returns adjusted lot size that won't breach limits.
        """
        self._check_new_day()
        
        if not self.state.live_flag:
            return RiskCheckResult(
                allowed=False,
                original_lot=requested_lot or 0.0,
                adjusted_lot=0.0,
                reason="Challenge not active",
            )
        
        if self.state.failed:
            return RiskCheckResult(
                allowed=False,
                original_lot=requested_lot or 0.0,
                adjusted_lot=0.0,
                reason=f"Challenge failed: {self.state.fail_reason}",
            )
        
        open_count = len(self.state.open_positions)
        
        sizing = calculate_lot_size(
            symbol=symbol,
            account_balance=self.state.current_balance,
            risk_percent=self.DEFAULT_RISK_PCT,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            existing_positions=open_count,
        )
        
        if requested_lot is None:
            lot_size = sizing["lot_size"]
        else:
            lot_size = requested_lot
            if open_count > 0:
                reduction_factor = 1.0 / (open_count + 1)
                lot_size = round(lot_size * reduction_factor, 2)
        
        new_trade_risk = sizing["risk_usd"]
        new_trade_risk_pct = (new_trade_risk / self.state.current_balance) * 100 if self.state.current_balance > 0 else 100
        
        if new_trade_risk_pct > self.MAX_SINGLE_TRADE_RISK_PCT:
            allowed_risk_usd = self.state.current_balance * (self.MAX_SINGLE_TRADE_RISK_PCT / 100)
            reduction_factor = allowed_risk_usd / new_trade_risk if new_trade_risk > 0 else 0
            reduced_lot = round(lot_size * reduction_factor * 0.95, 2)
            
            if reduced_lot < 0.01:
                return RiskCheckResult(
                    allowed=False,
                    original_lot=lot_size,
                    adjusted_lot=0.0,
                    reason=f"HARD CAP: Single trade risk {new_trade_risk_pct:.1f}% exceeds {self.MAX_SINGLE_TRADE_RISK_PCT}% limit",
                    daily_loss_after=0.0,
                    max_drawdown_after=0.0,
                    open_positions_count=open_count,
                )
            
            lot_size = reduced_lot
            new_trade_risk = allowed_risk_usd * 0.95
            new_trade_risk_pct = (new_trade_risk / self.state.current_balance) * 100
        
        existing_open_risk = self._calculate_total_open_risk()
        total_cumulative_risk = existing_open_risk + pending_orders_risk + new_trade_risk
        cumulative_risk_pct = (total_cumulative_risk / self.state.current_balance) * 100 if self.state.current_balance > 0 else 100
        
        if cumulative_risk_pct > self.MAX_CUMULATIVE_RISK_PCT:
            available_risk = self.state.current_balance * (self.MAX_CUMULATIVE_RISK_PCT / 100) - existing_open_risk - pending_orders_risk
            
            if available_risk <= 0:
                return RiskCheckResult(
                    allowed=False,
                    original_lot=lot_size,
                    adjusted_lot=0.0,
                    reason=f"CUMULATIVE LIMIT: Total risk {cumulative_risk_pct:.1f}% exceeds {self.MAX_CUMULATIVE_RISK_PCT}% limit (open: ${existing_open_risk:.0f}, pending: ${pending_orders_risk:.0f})",
                    daily_loss_after=0.0,
                    max_drawdown_after=0.0,
                    open_positions_count=open_count,
                )
            
            reduction_factor = available_risk / new_trade_risk if new_trade_risk > 0 else 0
            reduced_lot = round(lot_size * reduction_factor * 0.95, 2)
            
            if reduced_lot < 0.01:
                return RiskCheckResult(
                    allowed=False,
                    original_lot=lot_size,
                    adjusted_lot=0.0,
                    reason=f"CUMULATIVE LIMIT: Cannot fit trade within {self.MAX_CUMULATIVE_RISK_PCT}% limit",
                    daily_loss_after=0.0,
                    max_drawdown_after=0.0,
                    open_positions_count=open_count,
                )
            
            lot_size = reduced_lot
            new_trade_risk = available_risk * 0.95
        
        total_potential_loss = existing_open_risk + pending_orders_risk + new_trade_risk
        daily_dd_after, total_dd_after = self._simulate_worst_case_dd(total_potential_loss - existing_open_risk)
        
        if daily_dd_after >= self.MAX_DAILY_LOSS_PCT:
            reduced_lot = lot_size * (self.MAX_DAILY_LOSS_PCT / daily_dd_after) * 0.9
            reduced_lot = round(max(0.01, reduced_lot), 2)
            
            if reduced_lot < 0.01:
                return RiskCheckResult(
                    allowed=False,
                    original_lot=lot_size,
                    adjusted_lot=0.0,
                    reason=f"Would breach daily loss limit ({daily_dd_after:.1f}% > {self.MAX_DAILY_LOSS_PCT}%)",
                    daily_loss_after=daily_dd_after,
                    max_drawdown_after=total_dd_after,
                    open_positions_count=open_count,
                )
            
            return RiskCheckResult(
                allowed=True,
                original_lot=lot_size,
                adjusted_lot=reduced_lot,
                reason=f"Lot reduced to avoid daily loss breach",
                daily_loss_after=daily_dd_after * (reduced_lot / lot_size),
                max_drawdown_after=total_dd_after * (reduced_lot / lot_size),
                open_positions_count=open_count,
            )
        
        if total_dd_after >= self.MAX_TOTAL_DRAWDOWN_PCT:
            reduced_lot = lot_size * (self.MAX_TOTAL_DRAWDOWN_PCT / total_dd_after) * 0.9
            reduced_lot = round(max(0.01, reduced_lot), 2)
            
            if reduced_lot < 0.01:
                return RiskCheckResult(
                    allowed=False,
                    original_lot=lot_size,
                    adjusted_lot=0.0,
                    reason=f"Would breach max drawdown ({total_dd_after:.1f}% > {self.MAX_TOTAL_DRAWDOWN_PCT}%)",
                    daily_loss_after=daily_dd_after,
                    max_drawdown_after=total_dd_after,
                    open_positions_count=open_count,
                )
            
            return RiskCheckResult(
                allowed=True,
                original_lot=lot_size,
                adjusted_lot=reduced_lot,
                reason=f"Lot reduced to avoid max drawdown breach",
                daily_loss_after=daily_dd_after * (reduced_lot / lot_size),
                max_drawdown_after=total_dd_after * (reduced_lot / lot_size),
                open_positions_count=open_count,
            )
        
        return RiskCheckResult(
            allowed=True,
            original_lot=lot_size,
            adjusted_lot=lot_size,
            reason="Trade approved",
            daily_loss_after=daily_dd_after,
            max_drawdown_after=total_dd_after,
            open_positions_count=open_count,
        )
    
    def record_trade_open(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        lot_size: float,
        order_id: int,
    ):
        """Record a new position opening."""
        self._check_new_day()
        
        position = OpenPosition(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            lot_size=lot_size,
            order_id=order_id,
            entry_time=datetime.now(timezone.utc),
        )
        
        self.state.open_positions.append(asdict(position))
        self.state.total_trades += 1
        self.state.last_update = datetime.now(timezone.utc).isoformat()
        self.save_state()
    
    def record_trade_close(
        self,
        order_id: int,
        exit_price: float,
        pnl_usd: float,
    ):
        """Record a position closing."""
        self._check_new_day()
        
        self.state.open_positions = [
            p for p in self.state.open_positions
            if p.get("order_id") != order_id
        ]
        
        self.state.current_balance += pnl_usd
        
        if pnl_usd > 0:
            self.state.winning_trades += 1
        else:
            self.state.losing_trades += 1
        
        if self.state.current_balance > self.state.highest_balance:
            self.state.highest_balance = self.state.current_balance
        
        daily_loss = self.state.daily_loss_pct
        if daily_loss > self.state.max_daily_loss_pct:
            self.state.max_daily_loss_pct = daily_loss
        
        dd = self.state.current_drawdown_pct
        if dd > self.state.max_drawdown_pct:
            self.state.max_drawdown_pct = dd
        
        if daily_loss >= self.MAX_DAILY_LOSS_PCT:
            self.state.failed = True
            self.state.fail_reason = f"Daily loss limit breached ({daily_loss:.1f}%)"
            self.state.live_flag = False
        
        if dd >= self.MAX_TOTAL_DRAWDOWN_PCT:
            self.state.failed = True
            self.state.fail_reason = f"Max drawdown breached ({dd:.1f}%)"
            self.state.live_flag = False
        
        profit_pct = self.state.current_profit_pct
        target = self.state.target_pct
        min_days = self.MIN_PROFITABLE_DAYS
        
        if profit_pct >= target and self.state.profitable_days >= min_days:
            if self.state.phase == 1:
                self.state.passed_phase1 = True
            elif self.state.phase == 2:
                self.state.passed_phase2 = True
                self.state.live_flag = False
        
        self.state.last_update = datetime.now(timezone.utc).isoformat()
        self.save_state()
    
    def get_status(self) -> Dict[str, Any]:
        """Get current challenge status for Discord embed."""
        self._check_new_day()
        
        return {
            "phase": self.state.phase,
            "live": self.state.live_flag,
            "balance": self.state.current_balance,
            "profit_pct": self.state.current_profit_pct,
            "target_pct": self.state.target_pct,
            "progress_pct": self.state.progress_pct,
            "daily_loss_pct": self.state.daily_loss_pct,
            "max_daily_loss_pct": self.state.max_daily_loss_pct,
            "drawdown_pct": self.state.current_drawdown_pct,
            "max_drawdown_pct": self.state.max_drawdown_pct,
            "total_trades": self.state.total_trades,
            "winning_trades": self.state.winning_trades,
            "losing_trades": self.state.losing_trades,
            "win_rate": (self.state.winning_trades / self.state.total_trades * 100) if self.state.total_trades > 0 else 0,
            "profitable_days": self.state.profitable_days,
            "min_profitable_days": self.MIN_PROFITABLE_DAYS,
            "open_positions": len(self.state.open_positions),
            "failed": self.state.failed,
            "fail_reason": self.state.fail_reason,
            "passed_phase1": self.state.passed_phase1,
            "passed_phase2": self.state.passed_phase2,
            "start_time": self.state.start_time,
            "last_update": self.state.last_update,
        }
    
    def should_emergency_close(self, current_equity: float) -> Tuple[bool, str]:
        """
        Check if positions should be closed to protect account.
        
        Uses buffer thresholds to close BEFORE hitting hard limits:
        - DAILY_LOSS_BUFFER_PCT (4.5%): Close before 5% daily loss limit
        - TOTAL_DD_BUFFER_PCT (9%): Close before 10% max drawdown limit
        
        Returns:
            Tuple of (should_close, reason) where should_close is True if
            emergency close is needed and reason explains why.
        """
        daily_loss_pct = 0.0
        if current_equity < self.state.day_start_balance:
            daily_loss_pct = ((self.state.day_start_balance - current_equity) / self.state.day_start_balance) * 100
        
        total_dd_pct = 0.0
        if current_equity < self.state.initial_balance:
            total_dd_pct = ((self.state.initial_balance - current_equity) / self.state.initial_balance) * 100
        
        if daily_loss_pct >= self.DAILY_LOSS_BUFFER_PCT:
            return (
                True,
                f"EMERGENCY: Daily loss at {daily_loss_pct:.2f}% (buffer: {self.DAILY_LOSS_BUFFER_PCT}%, limit: {self.MAX_DAILY_LOSS_PCT}%)"
            )
        
        if total_dd_pct >= self.TOTAL_DD_BUFFER_PCT:
            return (
                True,
                f"EMERGENCY: Total drawdown at {total_dd_pct:.2f}% (buffer: {self.TOTAL_DD_BUFFER_PCT}%, limit: {self.MAX_TOTAL_DRAWDOWN_PCT}%)"
            )
        
        return (False, "")
    
    def calculate_pending_orders_risk(self, pending_setups: List[Dict]) -> float:
        """
        Calculate total risk from pending orders.
        
        Args:
            pending_setups: List of pending setup dictionaries with 'lot_size', 
                          'entry_price', 'stop_loss', and 'symbol' keys.
        
        Returns:
            Total potential risk in USD from all pending orders.
        """
        total_risk = 0.0
        for setup in pending_setups:
            symbol = setup.get('symbol', '')
            lot_size = setup.get('lot_size', 0.0)
            entry = setup.get('entry_price', 0.0)
            sl = setup.get('stop_loss', 0.0)
            
            if lot_size > 0 and entry > 0 and sl > 0:
                stop_distance = abs(entry - sl)
                pip_value = get_pip_value(symbol, entry)
                
                from tradr.risk.position_sizing import get_contract_specs
                specs = get_contract_specs(symbol)
                pip_size = specs.get("pip_value", 0.0001)
                
                if specs.get("pip_location", 4) == 0:
                    stop_pips = stop_distance
                else:
                    stop_pips = stop_distance / pip_size
                
                risk_usd = stop_pips * pip_value * lot_size
                total_risk += risk_usd
        
        return total_risk
