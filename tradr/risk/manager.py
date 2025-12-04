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
    """
    
    MAX_DAILY_LOSS_PCT = 5.0
    MAX_TOTAL_DRAWDOWN_PCT = 10.0
    MIN_PROFITABLE_DAY_PCT = 0.0
    PHASE1_TARGET_PCT = 10.0
    PHASE2_TARGET_PCT = 5.0
    MIN_PROFITABLE_DAYS = 0
    
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
    ) -> RiskCheckResult:
        """
        Pre-trade risk check.
        
        Simulates worst-case scenario where all open positions + new trade hit SL.
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
        
        daily_dd_after, total_dd_after = self._simulate_worst_case_dd(new_trade_risk)
        
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
