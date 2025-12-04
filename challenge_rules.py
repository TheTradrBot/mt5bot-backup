"""
FTMO Challenge Rules

This module centralizes all FTMO challenge rules and configuration.
Used by backtest, challenge simulation, and live trading to ensure consistency.

Rules sourced from: https://ftmo.com/en/trading-objectives/
Last updated: December 2024

Note: Variable names kept as 'Fivers' for backward compatibility with existing code.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date, timedelta
from enum import Enum


class ChallengeStep(Enum):
    STEP_1 = 1  # FTMO Challenge
    STEP_2 = 2  # Verification
    FUNDED = 3


@dataclass
class FiversRules:
    """FTMO Challenge Rules (variable name kept for backward compatibility)"""

    account_size: float = 10_000.0
    account_currency: str = "USD"

    step1_profit_target_pct: float = 10.0  # FTMO Challenge: 10% target
    step2_profit_target_pct: float = 5.0   # Verification: 5% target
    funded_monthly_target_pct: float = 0.0  # No monthly target when funded

    max_daily_loss_pct: float = 5.0        # 5% daily loss limit
    max_total_drawdown_pct: float = 10.0   # 10% max drawdown

    min_profitable_days: int = 0           # FTMO has no min trading days
    profitable_day_threshold_pct: float = 0.0

    risk_per_trade_pct: float = 1.0        # 1% risk per trade (recommended)
    max_open_risk_pct: float = 3.0         # Max 3% total open risk

    inactivity_days_limit: int = 30        # 30 days inactivity limit
    news_trading_buffer_minutes: int = 2   # 2 min before/after news

    @property
    def step1_target_usd(self) -> float:
        return self.account_size * (self.step1_profit_target_pct / 100)

    @property
    def step2_target_usd(self) -> float:
        return self.account_size * (self.step2_profit_target_pct / 100)

    @property
    def max_daily_loss_usd(self) -> float:
        return self.account_size * (self.max_daily_loss_pct / 100)

    @property
    def max_total_drawdown_usd(self) -> float:
        return self.account_size * (self.max_total_drawdown_pct / 100)

    @property
    def profitable_day_threshold_usd(self) -> float:
        return self.account_size * (self.profitable_day_threshold_pct / 100)

    @property
    def risk_per_trade_usd(self) -> float:
        return self.account_size * (self.risk_per_trade_pct / 100)

    def get_target_pct(self, step: ChallengeStep) -> float:
        if step == ChallengeStep.STEP_1:
            return self.step1_profit_target_pct
        elif step == ChallengeStep.STEP_2:
            return self.step2_profit_target_pct
        else:
            return self.funded_monthly_target_pct

    def get_target_usd(self, step: ChallengeStep) -> float:
        return self.account_size * (self.get_target_pct(step) / 100)


FIVERS_10K_RULES = FiversRules()


@dataclass
class DailyPnL:
    """Track daily PnL for a single trading day"""
    date: date
    starting_balance: float
    ending_balance: float
    trades_count: int = 0

    @property
    def pnl_usd(self) -> float:
        return self.ending_balance - self.starting_balance

    @property
    def pnl_pct(self) -> float:
        if self.starting_balance <= 0:
            return 0.0
        return (self.pnl_usd / self.starting_balance) * 100

    def is_profitable_day(self, initial_balance: float, threshold_pct: float = 0.5) -> bool:
        """Check if this day qualifies as a profitable day per 5ers rules.

        A profitable day requires net positive profit of at least 0.5% of INITIAL balance.
        """
        threshold_usd = initial_balance * (threshold_pct / 100)
        return self.pnl_usd >= threshold_usd


@dataclass
class StepResult:
    """Result of a single challenge step (Step 1 or Step 2)"""
    step: ChallengeStep
    start_date: datetime
    end_date: Optional[datetime] = None

    starting_balance: float = 10_000.0
    final_balance: float = 10_000.0
    target_pct: float = 8.0

    passed: bool = False
    failed: bool = False
    fail_reason: str = ""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    profitable_days: int = 0
    total_trading_days: int = 0

    max_daily_loss_pct: float = 0.0
    max_drawdown_pct: float = 0.0

    daily_pnl: List[DailyPnL] = field(default_factory=list)

    @property
    def return_pct(self) -> float:
        return ((self.final_balance - self.starting_balance) / self.starting_balance) * 100

    @property
    def return_usd(self) -> float:
        return self.final_balance - self.starting_balance

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def days_to_pass(self) -> int:
        if self.end_date is None:
            return 0
        return (self.end_date - self.start_date).days


@dataclass
class FullChallengeResult:
    """Result of a full 5ers challenge (Step 1 + Step 2)"""
    start_date: datetime
    end_date: Optional[datetime] = None

    step1: Optional[StepResult] = None
    step2: Optional[StepResult] = None

    passed: bool = False

    @property
    def total_trades(self) -> int:
        total = 0
        if self.step1:
            total += self.step1.total_trades
        if self.step2:
            total += self.step2.total_trades
        return total

    @property
    def total_return_usd(self) -> float:
        total = 0.0
        if self.step1:
            total += self.step1.return_usd
        if self.step2:
            total += self.step2.return_usd
        return total

    @property
    def total_return_pct(self) -> float:
        return (self.total_return_usd / FIVERS_10K_RULES.account_size) * 100

    @property
    def total_days(self) -> int:
        if self.end_date is None:
            return 0
        return (self.end_date - self.start_date).days


@dataclass
class ChallengeSimulationResult:
    """Result of running challenge simulation over a date range"""
    period_start: datetime
    period_end: datetime

    full_challenges_passed: int = 0
    step1_passes: int = 0
    step2_passes: int = 0

    challenges: List[FullChallengeResult] = field(default_factory=list)

    total_trades: int = 0
    total_profitable_days: int = 0

    final_equity: float = 10_000.0
    total_profit_usd: float = 0.0
    total_profit_pct: float = 0.0

    rule_violations: List[str] = field(default_factory=list)

    step1_stats: Dict = field(default_factory=dict)
    step2_stats: Dict = field(default_factory=dict)


def check_daily_loss_breach(
    current_balance: float,
    day_start_balance: float,
    max_daily_loss_pct: float = 5.0
) -> Tuple[bool, float]:
    """Check if daily loss limit has been breached.

    Daily loss is calculated from the previous day's closing equity.

    Returns: (is_breached, current_daily_loss_pct)
    """
    if day_start_balance <= 0:
        return False, 0.0

    daily_loss = day_start_balance - current_balance
    daily_loss_pct = (daily_loss / day_start_balance) * 100

    is_breached = daily_loss_pct >= max_daily_loss_pct
    return is_breached, max(0, daily_loss_pct)


def check_max_drawdown_breach(
    current_balance: float,
    initial_balance: float,
    max_drawdown_pct: float = 10.0
) -> Tuple[bool, float]:
    """Check if max total drawdown has been breached.

    Max drawdown is from initial balance (absolute, not trailing).

    Returns: (is_breached, current_drawdown_pct)
    """
    if initial_balance <= 0:
        return False, 0.0

    drawdown = initial_balance - current_balance
    drawdown_pct = (drawdown / initial_balance) * 100

    is_breached = drawdown_pct >= max_drawdown_pct
    return is_breached, max(0, drawdown_pct)


def count_profitable_days(
    daily_pnl_list: List[DailyPnL],
    initial_balance: float,
    threshold_pct: float = 0.5
) -> int:
    """Count days that qualify as profitable days per 5ers rules."""
    return sum(
        1 for day in daily_pnl_list
        if day.is_profitable_day(initial_balance, threshold_pct)
    )


def analyze_step_difficulty(step1: StepResult, step2: StepResult) -> str:
    """Analyze why Step 2 is typically harder than Step 1.

    Returns human-readable explanation.
    """
    lines = [
        "**Why Step 2 is Harder Than Step 1**",
        "",
    ]

    if step1.total_trades == 0 or step2.total_trades == 0:
        lines.append("Insufficient data to compare steps.")
        return "\n".join(lines)

    lines.append(f"**Trade Statistics:**")
    lines.append(f"- Step 1: {step1.total_trades} trades, {step1.win_rate:.1f}% WR, +{step1.return_pct:.1f}%")
    lines.append(f"- Step 2: {step2.total_trades} trades, {step2.win_rate:.1f}% WR, +{step2.return_pct:.1f}%")
    lines.append("")

    lines.append(f"**Profitable Days:**")
    lines.append(f"- Step 1: {step1.profitable_days} profitable days")
    lines.append(f"- Step 2: {step2.profitable_days} profitable days")
    lines.append("")

    lines.append(f"**Max Drawdown:**")
    lines.append(f"- Step 1: {step1.max_drawdown_pct:.1f}%")
    lines.append(f"- Step 2: {step2.max_drawdown_pct:.1f}%")
    lines.append("")

    reasons = []

    if step2.win_rate < step1.win_rate:
        reasons.append(f"Lower win rate ({step2.win_rate:.1f}% vs {step1.win_rate:.1f}%)")

    if step2.max_drawdown_pct > step1.max_drawdown_pct:
        reasons.append(f"Higher drawdown ({step2.max_drawdown_pct:.1f}% vs {step1.max_drawdown_pct:.1f}%)")

    if step2.profitable_days < step1.profitable_days:
        reasons.append(f"Fewer profitable days ({step2.profitable_days} vs {step1.profitable_days})")

    reasons.append("Same risk rules but lower profit target (5% vs 8%) means less margin for error")
    reasons.append("Market conditions may differ between steps")
    reasons.append("Psychological pressure after passing Step 1 can affect decision-making")

    lines.append("**Key Factors Making Step 2 Harder:**")
    for i, reason in enumerate(reasons[:5], 1):
        lines.append(f"{i}. {reason}")

    return "\n".join(lines)


def format_challenge_summary(result: ChallengeSimulationResult) -> str:
    """Format challenge simulation result for Discord."""
    from config import SIGNAL_MODE
    min_conf = 4 if SIGNAL_MODE == "standard" else 3

    challenges_attempted = len(result.challenges)
    challenges_failed = challenges_attempted - result.full_challenges_passed
    
    lines = [
        f"**5ers Challenge Simulation** - {result.period_start.strftime('%b %Y')} to {result.period_end.strftime('%b %Y')}",
        f"**Min Confluence:** {min_conf}/7 (mode: {SIGNAL_MODE})",
        f"",
        f"**Challenge Results:**",
        f"  Attempted: {challenges_attempted}",
        f"  ✅ Passed: {result.full_challenges_passed}",
        f"  ❌ Failed: {challenges_failed}",
        f"",
        f"**Step Breakdown:**",
        f"  Step 1 Passes: {result.step1_passes}",
        f"  Step 2 Passes: {result.step2_passes}",
        f"",
        f"**Trading Stats:**",
        f"  Total Trades: {result.total_trades}",
        f"  Profitable Days: {result.total_profitable_days}",
        f"",
        f"**Performance:**",
        f"  Cumulative Profit: ${result.total_profit_usd:+,.2f} ({result.total_profit_pct:+.1f}%)",
        f"  Final Equity: ${result.final_equity:,.2f}",
        f"",
    ]

    if result.rule_violations:
        lines.append("-" * 50)
        lines.append("**RULE VIOLATIONS**")
        lines.append("-" * 50)
        for violation in result.rule_violations:
            lines.append(f"- {violation}")
        lines.append("")

    if result.challenges:
        lines.append("-" * 50)
        lines.append("**CHALLENGE DETAILS**")
        lines.append("-" * 50)

        for i, challenge in enumerate(result.challenges, 1):
            status = "PASSED" if challenge.passed else "IN PROGRESS"
            lines.append(f"\n**Challenge {i}:** {status}")

            if challenge.step1:
                s1 = challenge.step1
                s1_status = "PASSED" if s1.passed else ("FAILED" if s1.failed else "In Progress")
                lines.append(f"  Step 1: {s1_status} | {s1.total_trades} trades | +{s1.return_pct:.1f}% | {s1.profitable_days} profitable days")
                if s1.failed:
                    lines.append(f"    Fail Reason: {s1.fail_reason}")

            if challenge.step2:
                s2 = challenge.step2
                s2_status = "PASSED" if s2.passed else ("FAILED" if s2.failed else "In Progress")
                lines.append(f"  Step 2: {s2_status} | {s2.total_trades} trades | +{s2.return_pct:.1f}% | {s2.profitable_days} profitable days")
                if s2.failed:
                    lines.append(f"    Fail Reason: {s2.fail_reason}")

    lines.append("")
    lines.append("=" * 50)

    return "\n".join(lines)