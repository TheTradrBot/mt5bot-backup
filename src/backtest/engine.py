"""
Backtest Engine for Blueprint Trader AI - v4 Spec.

Implements realistic walk-forward backtesting with:
- Accurate trade accounting (partial exits, R multiples)
- No look-ahead bias
- Conservative exit logic (SL checked first)
- 5ers High Stakes 10K challenge simulation (2-step)
- Proper profitable day tracking (0.5% threshold)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, date
import pandas as pd

from challenge_rules import (
    FIVERS_10K_RULES,
    ChallengeStep,
    StepResult,
    FullChallengeResult,
    ChallengeSimulationResult,
    DailyPnL,
    check_daily_loss_breach,
    check_max_drawdown_breach,
    count_profitable_days,
    analyze_step_difficulty,
    format_challenge_summary,
)


@dataclass
class BacktestTrade:
    """Represents a single trade in backtest."""
    symbol: str
    direction: str
    entry_date: datetime
    entry_price: float
    stop_loss: float
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    tp3: Optional[float] = None
    
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    
    partial_exits: List[Dict] = field(default_factory=list)
    
    risk: float = 0.0
    
    confluence_score: int = 0
    
    @property
    def total_r(self) -> float:
        """Calculate total R for this trade including partials."""
        if not self.partial_exits:
            if self.exit_price is None:
                return 0.0
            if self.direction == "bullish":
                return (self.exit_price - self.entry_price) / self.risk if self.risk > 0 else 0
            else:
                return (self.entry_price - self.exit_price) / self.risk if self.risk > 0 else 0
        
        total = 0.0
        for exit in self.partial_exits:
            total += exit.get("r_multiple", 0) * exit.get("portion", 0.333)
        return total
    
    @property
    def is_winner(self) -> bool:
        """Trade is a winner if total R > 0."""
        return self.total_r > 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_date": str(self.entry_date),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "exit_date": str(self.exit_date) if self.exit_date else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "risk": self.risk,
            "total_r": self.total_r,
            "is_winner": self.is_winner,
            "confluence_score": self.confluence_score,
        }


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    symbol: str
    period_start: datetime
    period_end: datetime
    
    trades: List[BacktestTrade] = field(default_factory=list)
    
    starting_balance: float = 10_000.0
    risk_per_trade_pct: float = 0.75
    
    @property
    def total_trades(self) -> int:
        return len(self.trades)
    
    @property
    def winning_trades(self) -> int:
        return sum(1 for t in self.trades if t.is_winner)
    
    @property
    def losing_trades(self) -> int:
        return sum(1 for t in self.trades if not t.is_winner)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def total_r(self) -> float:
        return sum(t.total_r for t in self.trades)
    
    @property
    def avg_r_per_trade(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_r / self.total_trades
    
    @property
    def net_return_pct(self) -> float:
        """Net return based on actual risk per trade."""
        return self.total_r * self.risk_per_trade_pct
    
    @property
    def net_return_usd(self) -> float:
        """Net return in USD."""
        return self.starting_balance * (self.net_return_pct / 100)
    
    @property
    def final_balance(self) -> float:
        return self.starting_balance + self.net_return_usd
    
    @property
    def max_drawdown(self) -> float:
        """Calculate maximum drawdown in R."""
        if not self.trades:
            return 0.0
        
        equity = [0.0]
        for t in self.trades:
            equity.append(equity[-1] + t.total_r)
        
        peak = 0.0
        max_dd = 0.0
        
        for e in equity:
            if e > peak:
                peak = e
            dd = peak - e
            if dd > max_dd:
                max_dd = dd
        
        return max_dd
    
    @property
    def max_drawdown_pct(self) -> float:
        """Max drawdown as percentage of account."""
        return self.max_drawdown * self.risk_per_trade_pct
    
    @property
    def exit_breakdown(self) -> Dict[str, int]:
        """Count of trades by exit reason."""
        breakdown = {}
        for t in self.trades:
            reason = t.exit_reason or "Unknown"
            breakdown[reason] = breakdown.get(reason, 0) + 1
        return breakdown
    
    def would_pass_step1(self) -> bool:
        """Check if this backtest would pass Step 1 of 5ers challenge."""
        return self.net_return_pct >= FIVERS_10K_RULES.step1_profit_target_pct
    
    def would_pass_step2(self) -> bool:
        """Check if this backtest would pass Step 2 of 5ers challenge."""
        return self.net_return_pct >= FIVERS_10K_RULES.step2_profit_target_pct
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period_start": str(self.period_start),
            "period_end": str(self.period_end),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 1),
            "total_r": round(self.total_r, 2),
            "avg_r_per_trade": round(self.avg_r_per_trade, 2),
            "net_return_pct": round(self.net_return_pct, 1),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "exit_breakdown": self.exit_breakdown,
            "would_pass_step1": self.would_pass_step1(),
            "would_pass_step2": self.would_pass_step2(),
        }


@dataclass 
class FiversChallengeResult:
    """Legacy result class for backward compatibility."""
    start_date: datetime
    end_date: Optional[datetime] = None
    
    starting_balance: float = 10000.0
    final_balance: float = 10000.0
    
    target_pct: float = 8.0
    max_daily_loss_pct: float = 5.0
    max_total_loss_pct: float = 10.0
    
    passed: bool = False
    failed: bool = False
    fail_reason: str = ""
    
    days_to_pass: int = 0
    profitable_days: int = 0
    
    trades: List[BacktestTrade] = field(default_factory=list)
    
    daily_pnl: Dict[str, float] = field(default_factory=dict)
    
    @property
    def total_return_pct(self) -> float:
        return ((self.final_balance - self.starting_balance) / self.starting_balance) * 100
    
    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        winners = sum(1 for t in self.trades if t.is_winner)
        return (winners / len(self.trades)) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_date": str(self.start_date),
            "end_date": str(self.end_date) if self.end_date else None,
            "starting_balance": self.starting_balance,
            "final_balance": round(self.final_balance, 2),
            "target_pct": self.target_pct,
            "total_return_pct": round(self.total_return_pct, 2),
            "passed": self.passed,
            "failed": self.failed,
            "fail_reason": self.fail_reason,
            "days_to_pass": self.days_to_pass,
            "profitable_days": self.profitable_days,
            "total_trades": len(self.trades),
            "win_rate": round(self.win_rate, 1),
        }


def parse_period_string(period: str) -> Tuple[datetime, datetime]:
    """
    Parse human-friendly period string to datetime range.
    
    Examples:
        "Jan 2024 - Dec 2024"
        "Jan 24 - Dec 24"
        "2024"
        "Q1 2024"
    """
    period = period.strip()
    
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    if "-" in period:
        parts = [p.strip() for p in period.split("-")]
        if len(parts) == 2:
            start_str, end_str = parts
            
            start_parts = start_str.lower().split()
            end_parts = end_str.lower().split()
            
            if len(start_parts) >= 2:
                start_month = month_map.get(start_parts[0][:3], 1)
                start_year = int(start_parts[1])
                if start_year < 100:
                    start_year += 2000
            else:
                start_month = 1
                start_year = int(start_str)
            
            if len(end_parts) >= 2:
                end_month = month_map.get(end_parts[0][:3], 12)
                end_year = int(end_parts[1])
                if end_year < 100:
                    end_year += 2000
            else:
                end_month = 12
                end_year = int(end_str)
            
            start_date = datetime(start_year, start_month, 1)
            
            if end_month == 12:
                end_date = datetime(end_year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = datetime(end_year, end_month + 1, 1) - timedelta(days=1)
            
            return start_date, end_date
    
    if period.isdigit() and len(period) == 4:
        year = int(period)
        return datetime(year, 1, 1), datetime(year, 12, 31)
    
    if period.lower().startswith("q"):
        parts = period.split()
        quarter = int(period[1])
        year = int(parts[1]) if len(parts) > 1 else datetime.now().year
        
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        
        return (
            datetime(year, start_month, 1),
            datetime(year, end_month + 1, 1) - timedelta(days=1) if end_month < 12 
            else datetime(year, 12, 31)
        )
    
    return datetime(2024, 1, 1), datetime(2024, 12, 31)


def simulate_trade_exit(
    trade: BacktestTrade,
    candles: List[Dict],
    start_idx: int,
) -> BacktestTrade:
    """
    Simulate trade exit using walk-forward candle data.
    
    Exit logic:
    1. Check SL first (conservative)
    2. Check TP1, then TP2, then TP3
    3. Handle partial exits
    """
    if not candles or start_idx >= len(candles):
        return trade
    
    tp1_hit = False
    tp2_hit = False
    trailing_sl = trade.stop_loss
    
    for i in range(start_idx, len(candles)):
        candle = candles[i]
        high = candle["high"]
        low = candle["low"]
        time = candle.get("time", datetime.now())
        
        if trade.direction == "bullish":
            if low <= trailing_sl:
                trade.exit_date = time
                trade.exit_price = trailing_sl
                
                if tp1_hit:
                    trade.exit_reason = "TP1+Trail"
                else:
                    trade.exit_reason = "SL"
                    trade.partial_exits = [{
                        "level": "SL",
                        "price": trailing_sl,
                        "r_multiple": -1.0,
                        "portion": 1.0,
                    }]
                return trade
            
            if not tp1_hit and trade.tp1 and high >= trade.tp1:
                tp1_hit = True
                trailing_sl = trade.entry_price
                
                trade.partial_exits.append({
                    "level": "TP1",
                    "price": trade.tp1,
                    "r_multiple": (trade.tp1 - trade.entry_price) / trade.risk if trade.risk > 0 else 2.0,
                    "portion": 0.333,
                })
            
            if tp1_hit and not tp2_hit and trade.tp2 and high >= trade.tp2:
                tp2_hit = True
                
                trade.partial_exits.append({
                    "level": "TP2",
                    "price": trade.tp2,
                    "r_multiple": (trade.tp2 - trade.entry_price) / trade.risk if trade.risk > 0 else 3.0,
                    "portion": 0.333,
                })
            
            if tp2_hit and trade.tp3 and high >= trade.tp3:
                trade.exit_date = time
                trade.exit_price = trade.tp3
                trade.exit_reason = "TP3"
                
                trade.partial_exits.append({
                    "level": "TP3",
                    "price": trade.tp3,
                    "r_multiple": (trade.tp3 - trade.entry_price) / trade.risk if trade.risk > 0 else 4.5,
                    "portion": 0.334,
                })
                return trade
        
        else:
            if high >= trailing_sl:
                trade.exit_date = time
                trade.exit_price = trailing_sl
                
                if tp1_hit:
                    trade.exit_reason = "TP1+Trail"
                else:
                    trade.exit_reason = "SL"
                    trade.partial_exits = [{
                        "level": "SL",
                        "price": trailing_sl,
                        "r_multiple": -1.0,
                        "portion": 1.0,
                    }]
                return trade
            
            if not tp1_hit and trade.tp1 and low <= trade.tp1:
                tp1_hit = True
                trailing_sl = trade.entry_price
                
                trade.partial_exits.append({
                    "level": "TP1",
                    "price": trade.tp1,
                    "r_multiple": (trade.entry_price - trade.tp1) / trade.risk if trade.risk > 0 else 2.0,
                    "portion": 0.333,
                })
            
            if tp1_hit and not tp2_hit and trade.tp2 and low <= trade.tp2:
                tp2_hit = True
                
                trade.partial_exits.append({
                    "level": "TP2",
                    "price": trade.tp2,
                    "r_multiple": (trade.entry_price - trade.tp2) / trade.risk if trade.risk > 0 else 3.0,
                    "portion": 0.333,
                })
            
            if tp2_hit and trade.tp3 and low <= trade.tp3:
                trade.exit_date = time
                trade.exit_price = trade.tp3
                trade.exit_reason = "TP3"
                
                trade.partial_exits.append({
                    "level": "TP3",
                    "price": trade.tp3,
                    "r_multiple": (trade.entry_price - trade.tp3) / trade.risk if trade.risk > 0 else 4.5,
                    "portion": 0.334,
                })
                return trade
    
    if trade.exit_date is None:
        final_candle = candles[-1]
        trade.exit_date = final_candle.get("time", datetime.now())
        trade.exit_price = final_candle["close"]
        trade.exit_reason = "Period End"
    
    return trade


def simulate_single_step(
    trades: List[BacktestTrade],
    step: ChallengeStep,
    start_date: datetime,
    starting_balance: float = 10_000.0,
    risk_per_trade_pct: float = 0.75,
) -> StepResult:
    """
    Simulate a single step of the 5ers challenge.
    
    Properly tracks:
    - Daily PnL with correct reset at day boundaries
    - Profitable days (0.5%+ of initial balance threshold)
    - Daily loss limits (5% of previous day close)
    - Max drawdown (10% of initial balance)
    """
    rules = FIVERS_10K_RULES
    target_pct = rules.get_target_pct(step)
    
    result = StepResult(
        step=step,
        start_date=start_date,
        starting_balance=starting_balance,
        target_pct=target_pct,
    )
    
    sorted_trades = sorted(
        [t for t in trades if t.entry_date >= start_date],
        key=lambda t: t.entry_date
    )
    
    if not sorted_trades:
        result.final_balance = starting_balance
        return result
    
    balance = starting_balance
    prev_day_close_balance = starting_balance
    current_day: Optional[date] = None
    current_day_start_balance = starting_balance
    max_balance = starting_balance
    
    daily_pnl_tracker: Dict[date, float] = {}
    
    for trade in sorted_trades:
        trade_day = trade.entry_date.date()
        exit_day = trade.exit_date.date() if trade.exit_date else trade_day
        
        if current_day is None:
            current_day = trade_day
            current_day_start_balance = prev_day_close_balance
        elif trade_day != current_day:
            daily_pnl_tracker[current_day] = balance - current_day_start_balance
            
            prev_day_close_balance = balance
            current_day = trade_day
            current_day_start_balance = prev_day_close_balance
        
        risk_amount = balance * (risk_per_trade_pct / 100)
        trade_pnl = trade.total_r * risk_amount
        balance += trade_pnl
        
        result.total_trades += 1
        if trade.is_winner:
            result.winning_trades += 1
        else:
            result.losing_trades += 1
        
        if balance > max_balance:
            max_balance = balance
        
        is_daily_breach, daily_loss_pct = check_daily_loss_breach(
            balance, current_day_start_balance, rules.max_daily_loss_pct
        )
        
        if daily_loss_pct > result.max_daily_loss_pct:
            result.max_daily_loss_pct = daily_loss_pct
        
        if is_daily_breach:
            result.failed = True
            result.fail_reason = f"Daily loss limit breached ({daily_loss_pct:.1f}% > {rules.max_daily_loss_pct}%)"
            result.end_date = trade.exit_date or trade.entry_date
            result.final_balance = balance
            
            daily_pnl_tracker[current_day] = balance - current_day_start_balance
            result.daily_pnl = [
                DailyPnL(d, starting_balance, starting_balance + pnl)
                for d, pnl in daily_pnl_tracker.items()
            ]
            result.profitable_days = count_profitable_days(
                result.daily_pnl, starting_balance, rules.profitable_day_threshold_pct
            )
            return result
        
        is_dd_breach, dd_pct = check_max_drawdown_breach(
            balance, starting_balance, rules.max_total_drawdown_pct
        )
        
        if dd_pct > result.max_drawdown_pct:
            result.max_drawdown_pct = dd_pct
        
        if is_dd_breach:
            result.failed = True
            result.fail_reason = f"Max drawdown breached ({dd_pct:.1f}% > {rules.max_total_drawdown_pct}%)"
            result.end_date = trade.exit_date or trade.entry_date
            result.final_balance = balance
            
            daily_pnl_tracker[current_day] = balance - current_day_start_balance
            result.daily_pnl = [
                DailyPnL(d, starting_balance, starting_balance + pnl)
                for d, pnl in daily_pnl_tracker.items()
            ]
            result.profitable_days = count_profitable_days(
                result.daily_pnl, starting_balance, rules.profitable_day_threshold_pct
            )
            return result
        
        return_pct = ((balance - starting_balance) / starting_balance) * 100
        
        daily_pnl_tracker[current_day] = balance - current_day_start_balance
        temp_daily_pnl = [
            DailyPnL(d, starting_balance, starting_balance + pnl)
            for d, pnl in daily_pnl_tracker.items()
        ]
        profitable_day_count = count_profitable_days(
            temp_daily_pnl, starting_balance, rules.profitable_day_threshold_pct
        )
        
        if return_pct >= target_pct and profitable_day_count >= rules.min_profitable_days:
            result.passed = True
            result.end_date = trade.exit_date or trade.entry_date
            result.final_balance = balance
            result.daily_pnl = temp_daily_pnl
            result.profitable_days = profitable_day_count
            result.total_trading_days = len(daily_pnl_tracker)
            return result
    
    if current_day is not None:
        daily_pnl_tracker[current_day] = balance - current_day_start_balance
    
    result.final_balance = balance
    result.end_date = sorted_trades[-1].exit_date or sorted_trades[-1].entry_date
    result.daily_pnl = [
        DailyPnL(d, starting_balance, starting_balance + pnl)
        for d, pnl in daily_pnl_tracker.items()
    ]
    result.profitable_days = count_profitable_days(
        result.daily_pnl, starting_balance, rules.profitable_day_threshold_pct
    )
    result.total_trading_days = len(daily_pnl_tracker)
    
    return_pct = ((balance - starting_balance) / starting_balance) * 100
    if return_pct >= target_pct and result.profitable_days >= rules.min_profitable_days:
        result.passed = True
    
    return result


def run_fivers_challenge(
    trades: List[BacktestTrade],
    start_date: datetime,
    end_date: datetime,
    starting_balance: float = 10_000.0,
    risk_per_trade_pct: float = 0.75,
) -> ChallengeSimulationResult:
    """
    Run a complete 5ers 2-step challenge simulation over a date range.
    
    This simulates consecutive challenges where:
    - Each challenge = Step 1 (8% target) + Step 2 (5% target)
    - After Step 1 passes, Step 2 starts from fresh 10K
    - After Step 2 passes, a new challenge begins
    - If any step fails, that challenge is marked failed and a new one starts
    
    Returns comprehensive results with all challenges tracked.
    """
    rules = FIVERS_10K_RULES
    
    result = ChallengeSimulationResult(
        period_start=start_date,
        period_end=end_date,
    )
    
    sorted_trades = sorted(
        [t for t in trades if start_date <= t.entry_date <= end_date],
        key=lambda t: t.entry_date
    )
    
    if not sorted_trades:
        result.final_equity = starting_balance
        return result
    
    current_date = start_date
    remaining_trades = list(sorted_trades)
    cumulative_profit = 0.0
    
    while remaining_trades and current_date < end_date:
        challenge = FullChallengeResult(start_date=current_date)
        
        step1 = simulate_single_step(
            trades=remaining_trades,
            step=ChallengeStep.STEP_1,
            start_date=current_date,
            starting_balance=starting_balance,
            risk_per_trade_pct=risk_per_trade_pct,
        )
        challenge.step1 = step1
        
        result.total_trades += step1.total_trades
        result.total_profitable_days += step1.profitable_days
        
        if step1.passed:
            result.step1_passes += 1
            cumulative_profit += step1.return_usd
            
            step1_end = step1.end_date or current_date
            step2_start = step1_end + timedelta(days=1)
            
            step2_trades = [t for t in remaining_trades if t.entry_date >= step2_start]
            
            step2 = simulate_single_step(
                trades=step2_trades,
                step=ChallengeStep.STEP_2,
                start_date=step2_start,
                starting_balance=starting_balance,
                risk_per_trade_pct=risk_per_trade_pct,
            )
            challenge.step2 = step2
            
            result.total_trades += step2.total_trades
            result.total_profitable_days += step2.profitable_days
            
            if step2.passed:
                result.step2_passes += 1
                result.full_challenges_passed += 1
                cumulative_profit += step2.return_usd
                challenge.passed = True
                
                challenge.end_date = step2.end_date
                current_date = (step2.end_date or step2_start) + timedelta(days=1)
            else:
                if step2.failed:
                    result.rule_violations.append(
                        f"Challenge Step 2 failed: {step2.fail_reason}"
                    )
                challenge.end_date = step2.end_date
                current_date = (step2.end_date or step2_start) + timedelta(days=1)
            
            remaining_trades = [t for t in remaining_trades if t.entry_date >= current_date]
        
        else:
            if step1.failed:
                result.rule_violations.append(
                    f"Challenge Step 1 failed: {step1.fail_reason}"
                )
            
            challenge.end_date = step1.end_date
            current_date = (step1.end_date or current_date) + timedelta(days=1)
            remaining_trades = [t for t in remaining_trades if t.entry_date >= current_date]
        
        result.challenges.append(challenge)
        
        if not remaining_trades:
            break
    
    result.total_profit_usd = cumulative_profit
    result.total_profit_pct = (cumulative_profit / starting_balance) * 100
    result.final_equity = starting_balance + cumulative_profit
    
    if len(result.challenges) >= 2:
        step1_stats = {"trades": 0, "wins": 0, "profitable_days": 0, "max_dd": 0.0}
        step2_stats = {"trades": 0, "wins": 0, "profitable_days": 0, "max_dd": 0.0}
        
        for c in result.challenges:
            if c.step1:
                step1_stats["trades"] += c.step1.total_trades
                step1_stats["wins"] += c.step1.winning_trades
                step1_stats["profitable_days"] += c.step1.profitable_days
                step1_stats["max_dd"] = max(step1_stats["max_dd"], c.step1.max_drawdown_pct)
            if c.step2:
                step2_stats["trades"] += c.step2.total_trades
                step2_stats["wins"] += c.step2.winning_trades
                step2_stats["profitable_days"] += c.step2.profitable_days
                step2_stats["max_dd"] = max(step2_stats["max_dd"], c.step2.max_drawdown_pct)
        
        result.step1_stats = step1_stats
        result.step2_stats = step2_stats
    
    return result


def simulate_5ers_challenge(
    trades: List[BacktestTrade],
    start_date: datetime,
    step: int = 1,
    starting_balance: float = 10000.0,
    risk_per_trade_pct: float = 0.75,
) -> FiversChallengeResult:
    """
    Legacy function for backward compatibility.
    Simulate a single step of the 5ers challenge.
    """
    challenge_step = ChallengeStep.STEP_1 if step == 1 else ChallengeStep.STEP_2
    
    step_result = simulate_single_step(
        trades=trades,
        step=challenge_step,
        start_date=start_date,
        starting_balance=starting_balance,
        risk_per_trade_pct=risk_per_trade_pct,
    )
    
    legacy_result = FiversChallengeResult(
        start_date=start_date,
        end_date=step_result.end_date,
        starting_balance=starting_balance,
        final_balance=step_result.final_balance,
        target_pct=step_result.target_pct,
        passed=step_result.passed,
        failed=step_result.failed,
        fail_reason=step_result.fail_reason,
        days_to_pass=step_result.days_to_pass,
        profitable_days=step_result.profitable_days,
        trades=trades,
    )
    
    return legacy_result


def format_challenge_result(result: FiversChallengeResult) -> str:
    """Format 5ers challenge result for Discord output."""
    emoji = "PASSED" if result.passed else ("FAILED" if result.failed else "IN PROGRESS")
    status_emoji = "OK" if result.passed else ("X" if result.failed else "...")
    
    lines = [
        f"**5ers High Stakes 10K Challenge** [{status_emoji}]",
        f"",
        f"**Status:** {emoji}",
    ]
    
    if result.passed:
        lines.append(f"**Days to Pass:** {result.days_to_pass}")
    elif result.failed:
        lines.append(f"**Fail Reason:** {result.fail_reason}")
    
    lines.extend([
        f"",
        f"**Starting Balance:** ${result.starting_balance:,.0f}",
        f"**Final Balance:** ${result.final_balance:,.2f}",
        f"**Return:** {result.total_return_pct:+.1f}%",
        f"**Target:** {result.target_pct}%",
        f"",
        f"**Trades:** {len(result.trades)}",
        f"**Win Rate:** {result.win_rate:.1f}%",
        f"**Profitable Days:** {result.profitable_days} (min 3 required)",
    ])
    
    return "\n".join(lines)


def format_backtest_result(result: BacktestResult) -> str:
    """Format backtest result for Discord output with challenge pass/fail."""
    emoji = "OK" if result.total_r > 0 else "X"
    
    step1_status = "PASS" if result.would_pass_step1() else "FAIL"
    step2_status = "PASS" if result.would_pass_step2() else "FAIL"
    
    lines = [
        f"**Backtest Results** [{emoji}]",
        f"",
        f"**{result.symbol}** | {result.period_start.strftime('%b %Y')} - {result.period_end.strftime('%b %Y')}",
        f"",
        f"**Account:** ${result.starting_balance:,.0f} (10K 5ers High Stakes)",
        f"**Risk/Trade:** {result.risk_per_trade_pct}%",
        f"",
        f"**Total Trades:** {result.total_trades}",
        f"**Win Rate:** {result.win_rate:.1f}%",
        f"**Winners:** {result.winning_trades} | **Losers:** {result.losing_trades}",
        f"",
        f"**Total R:** {result.total_r:+.2f}R",
        f"**Avg R/Trade:** {result.avg_r_per_trade:+.2f}R",
        f"**Net Return:** {result.net_return_pct:+.1f}% (${result.net_return_usd:+,.2f})",
        f"**Final Balance:** ${result.final_balance:,.2f}",
        f"**Max Drawdown:** {result.max_drawdown_pct:.2f}%",
        f"",
        f"**Challenge Status:**",
        f"  Step 1 (8% target): {step1_status}",
        f"  Step 2 (5% target): {step2_status}",
        f"",
        f"**Exit Breakdown:**",
    ]
    
    for reason, count in result.exit_breakdown.items():
        lines.append(f"  {reason}: {count}")
    
    return "\n".join(lines)
