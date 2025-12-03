"""
5ers 2-Step Challenge Analysis
Analyzes each month from Jan 2024 to Nov 2025 to see if the bot's strategy 
would have passed the 5ers challenge.

Challenge Requirements (5ers High Stakes 10K):
- Step 1: 8% profit target + 3 profitable days
- Step 2: 5% profit target + 3 profitable days
- Max Daily Loss: 5%
- Max Total Drawdown: 10%
- Profitable day = 0.5%+ of initial balance profit
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import calendar

from backtest import run_backtest
from challenge_rules import FIVERS_10K_RULES

STEP1_TARGET_PCT = FIVERS_10K_RULES.step1_profit_target_pct
STEP2_TARGET_PCT = FIVERS_10K_RULES.step2_profit_target_pct
MAX_DAILY_LOSS = FIVERS_10K_RULES.max_daily_loss_pct
MAX_DRAWDOWN = FIVERS_10K_RULES.max_total_drawdown_pct
ACCOUNT_SIZE = FIVERS_10K_RULES.account_size
RISK_PER_TRADE_PCT = FIVERS_10K_RULES.risk_per_trade_pct / 100

ENABLED_ASSETS = ["XAU_USD", "USD_JPY", "NZD_USD", "GBP_USD"]


def get_months_in_range(start_year: int, start_month: int, end_year: int, end_month: int) -> List[Tuple[int, int]]:
    """Get list of (year, month) tuples in the range."""
    months = []
    current = date(start_year, start_month, 1)
    end = date(end_year, end_month, 1)
    
    while current <= end:
        months.append((current.year, current.month))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    
    return months


def format_month_period(year: int, month: int) -> str:
    """Format month as 'Jan 2024' style."""
    month_name = calendar.month_abbr[month]
    return f"{month_name} {year}"


def run_monthly_backtest(year: int, month: int) -> Dict:
    """Run backtest for a specific month across enabled assets."""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year, 12, 31)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    
    period = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
    
    all_trades = []
    total_profit_usd = 0.0
    total_rr = 0.0
    
    for asset in ENABLED_ASSETS:
        result = run_backtest(asset, period)
        if result["trades"]:
            all_trades.extend(result["trades"])
            total_profit_usd += result.get("total_profit_usd", 0.0)
            total_rr += sum(t["rr"] for t in result["trades"])
    
    all_trades.sort(key=lambda t: t.get("entry_date", ""))
    
    running_pnl = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_daily_loss = 0.0
    
    risk_per_trade_usd = ACCOUNT_SIZE * RISK_PER_TRADE_PCT
    
    daily_pnl: Dict[str, float] = {}
    
    for trade in all_trades:
        trade_pnl = trade["rr"] * risk_per_trade_usd
        running_pnl += trade_pnl
        
        trade_date = trade.get("exit_date", trade.get("entry_date", ""))
        if trade_date:
            daily_pnl[trade_date] = daily_pnl.get(trade_date, 0.0) + trade_pnl
        
        if running_pnl > peak:
            peak = running_pnl
        
        drawdown = peak - running_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    for day_pnl in daily_pnl.values():
        if day_pnl < 0 and abs(day_pnl) > max_daily_loss:
            max_daily_loss = abs(day_pnl)
    
    net_return_pct = (running_pnl / ACCOUNT_SIZE) * 100 if ACCOUNT_SIZE > 0 else 0.0
    max_drawdown_pct = (max_drawdown / ACCOUNT_SIZE) * 100 if ACCOUNT_SIZE > 0 else 0.0
    max_daily_loss_pct = (max_daily_loss / ACCOUNT_SIZE) * 100 if ACCOUNT_SIZE > 0 else 0.0
    
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["rr"] > 0)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    
    return {
        "year": year,
        "month": month,
        "period": format_month_period(year, month),
        "total_trades": total_trades,
        "wins": wins,
        "win_rate": win_rate,
        "net_return_pct": net_return_pct,
        "total_profit_usd": running_pnl,
        "max_drawdown_pct": max_drawdown_pct,
        "max_daily_loss_pct": max_daily_loss_pct,
        "trades": all_trades,
    }


def check_challenge_pass(result: Dict) -> Dict:
    """Check if a month's results would pass the 5ers challenge."""
    passed_step1 = result["net_return_pct"] >= STEP1_TARGET_PCT
    passed_step2 = result["net_return_pct"] >= STEP2_TARGET_PCT
    
    within_drawdown = result["max_drawdown_pct"] <= MAX_DRAWDOWN
    within_daily_loss = result["max_daily_loss_pct"] <= MAX_DAILY_LOSS
    
    step1_pass = passed_step1 and within_drawdown and within_daily_loss
    step2_pass = passed_step2 and within_drawdown and within_daily_loss
    
    if step1_pass:
        status = "STEP 1 PASS"
    elif step2_pass:
        status = "STEP 2 PASS"
    elif within_drawdown and within_daily_loss:
        status = "IN PROGRESS"
    else:
        status = "FAILED"
    
    return {
        "step1_pass": step1_pass,
        "step2_pass": step2_pass,
        "within_drawdown": within_drawdown,
        "within_daily_loss": within_daily_loss,
        "status": status,
        "fail_reason": None if within_drawdown and within_daily_loss else (
            "Max drawdown exceeded" if not within_drawdown else "Daily loss exceeded"
        )
    }


def run_challenge_analysis():
    """Run full challenge analysis from Jan 2024 to Nov 2025."""
    months = get_months_in_range(2024, 1, 2025, 11)
    
    print("\n" + "=" * 100)
    print("5ERS 2-STEP CHALLENGE ANALYSIS")
    print(f"Account Size: ${ACCOUNT_SIZE:,}")
    print(f"Risk Per Trade: {RISK_PER_TRADE_PCT * 100}%")
    print(f"Step 1 Target: {STEP1_TARGET_PCT}% | Step 2 Target: {STEP2_TARGET_PCT}%")
    print(f"Max Drawdown: {MAX_DRAWDOWN}% | Max Daily Loss: {MAX_DAILY_LOSS}%")
    print(f"Assets: {', '.join(ENABLED_ASSETS)}")
    print("=" * 100)
    
    print(f"\n{'Month':<12} {'Trades':>7} {'Win%':>7} {'Return%':>10} {'MaxDD%':>9} {'DailyL%':>9} {'Status':<15}")
    print("-" * 100)
    
    results = []
    step1_passes = 0
    step2_passes = 0
    failures = 0
    in_progress = 0
    
    for year, month in months:
        try:
            result = run_monthly_backtest(year, month)
            challenge = check_challenge_pass(result)
            result.update(challenge)
            results.append(result)
            
            status_display = result["status"]
            if result["step1_pass"]:
                step1_passes += 1
                status_display = "STEP 1 PASS"
            elif result["step2_pass"]:
                step2_passes += 1
                status_display = "STEP 2 PASS"
            elif result["status"] == "FAILED":
                failures += 1
            else:
                in_progress += 1
            
            print(f"{result['period']:<12} {result['total_trades']:>7} {result['win_rate']:>6.1f}% {result['net_return_pct']:>+9.2f}% {result['max_drawdown_pct']:>8.2f}% {result['max_daily_loss_pct']:>8.2f}% {status_display:<15}")
            
        except Exception as e:
            print(f"{format_month_period(year, month):<12} ERROR: {e}")
    
    print("-" * 100)
    print("\nSUMMARY:")
    print(f"  Total Months Analyzed: {len(results)}")
    print(f"  Step 1 Passes (8%+):   {step1_passes} ({step1_passes/len(results)*100:.1f}%)")
    print(f"  Step 2 Passes (5%+):   {step2_passes} ({step2_passes/len(results)*100:.1f}%)")
    print(f"  Failed (Risk Breach):  {failures} ({failures/len(results)*100:.1f}%)")
    print(f"  In Progress:           {in_progress} ({in_progress/len(results)*100:.1f}%)")
    
    total_return = sum(r["net_return_pct"] for r in results)
    avg_return = total_return / len(results) if results else 0
    total_trades = sum(r["total_trades"] for r in results)
    avg_win_rate = sum(r["win_rate"] for r in results) / len(results) if results else 0
    
    print(f"\n  Total Return ({len(results)} months): {total_return:+.2f}%")
    print(f"  Avg Monthly Return: {avg_return:+.2f}%")
    print(f"  Total Trades: {total_trades}")
    print(f"  Avg Win Rate: {avg_win_rate:.1f}%")
    print("=" * 100 + "\n")
    
    return results


if __name__ == "__main__":
    run_challenge_analysis()
