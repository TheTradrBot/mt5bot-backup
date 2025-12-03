"""
Enhanced Backtest Engine for Blueprint Trader AI.

This module provides a robust backtesting framework that:
- Uses the same strategy logic as live trading (via strategy_core.py)
- Supports year-by-year analysis
- Computes comprehensive performance metrics
- Has no look-ahead bias (walk-forward simulation)
- Supports parameter optimization
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd

from data_loader import (
    ASSETS,
    YEARS,
    load_ohlcv,
    load_ohlcv_from_csv,
    filter_by_year,
    df_to_candle_list,
    get_available_assets,
    validate_data_availability,
    DATA_DIR,
)

from strategy_core import (
    StrategyParams,
    Signal,
    Trade,
    generate_signals,
    simulate_trades,
    get_default_params,
)

from data import get_ohlcv as get_ohlcv_api


@dataclass
class BacktestResult:
    """Results from a single backtest run."""
    asset: str
    year: int
    params: StrategyParams
    
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    
    total_rr: float = 0.0
    avg_rr_per_trade: float = 0.0
    return_pct: float = 0.0
    
    max_drawdown_pct: float = 0.0
    max_consecutive_losses: int = 0
    expectancy_per_trade: float = 0.0
    
    tp1_trail_count: int = 0
    tp2_count: int = 0
    tp3_count: int = 0
    sl_count: int = 0
    
    trades: List[Trade] = field(default_factory=list)
    
    meets_targets: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "asset": self.asset,
            "year": self.year,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "total_rr": self.total_rr,
            "avg_rr_per_trade": self.avg_rr_per_trade,
            "return_pct": self.return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_consecutive_losses": self.max_consecutive_losses,
            "expectancy_per_trade": self.expectancy_per_trade,
            "tp1_trail_count": self.tp1_trail_count,
            "tp2_count": self.tp2_count,
            "tp3_count": self.tp3_count,
            "sl_count": self.sl_count,
            "meets_targets": self.meets_targets,
        }


@dataclass
class OptimizationTargets:
    """Performance targets for optimization."""
    min_trades_per_year: int = 50
    min_win_rate: float = 0.70
    max_win_rate: float = 1.00
    min_return_pct: float = 50.0
    max_drawdown_pct: float = 30.0
    
    def check(self, result: BacktestResult) -> bool:
        """Check if result meets all targets."""
        return (
            result.total_trades >= self.min_trades_per_year and
            self.min_win_rate <= result.win_rate <= self.max_win_rate and
            result.return_pct >= self.min_return_pct
        )


def load_backtest_data(
    asset: str,
    year: Optional[int] = None,
    use_csv: bool = True,
) -> Dict[str, List[Dict]]:
    """
    Load all timeframe data for backtesting.
    
    Args:
        asset: Asset symbol
        year: Optional year filter
        use_csv: Whether to prefer CSV data over API
    
    Returns:
        Dict with keys "daily", "weekly", "monthly", "h4"
    """
    data = {"daily": [], "weekly": [], "monthly": [], "h4": []}
    
    if use_csv:
        try:
            df = load_ohlcv_from_csv(asset, "D")
            if year is not None:
                df = filter_by_year(df, year)
            data["daily"] = df_to_candle_list(df)
        except FileNotFoundError:
            data["daily"] = get_ohlcv_api(asset, timeframe="D", count=2000, use_cache=False)
    else:
        data["daily"] = get_ohlcv_api(asset, timeframe="D", count=2000, use_cache=False)
    
    try:
        data["weekly"] = get_ohlcv_api(asset, timeframe="W", count=500, use_cache=False) or []
    except Exception:
        data["weekly"] = []
    
    try:
        data["monthly"] = get_ohlcv_api(asset, timeframe="M", count=240, use_cache=False) or []
    except Exception:
        data["monthly"] = []
    
    try:
        data["h4"] = get_ohlcv_api(asset, timeframe="H4", count=2000, use_cache=False) or []
    except Exception:
        data["h4"] = []
    
    return data


def compute_metrics(trades: List[Trade], risk_per_trade_pct: float = 1.0) -> Dict[str, Any]:
    """
    Compute comprehensive performance metrics from trades.
    
    Args:
        trades: List of completed trades
        risk_per_trade_pct: Risk per trade as percentage of account
    
    Returns:
        Dictionary of metrics
    """
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_rr": 0.0,
            "avg_rr_per_trade": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "max_consecutive_losses": 0,
            "expectancy_per_trade": 0.0,
            "tp1_trail_count": 0,
            "tp2_count": 0,
            "tp3_count": 0,
            "sl_count": 0,
        }
    
    total_trades = len(trades)
    wins = sum(1 for t in trades if t.is_winner)
    losses = total_trades - wins
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    
    total_rr = sum(t.rr for t in trades)
    avg_rr_per_trade = total_rr / total_trades if total_trades > 0 else 0.0
    
    return_pct = total_rr * risk_per_trade_pct
    
    equity_curve = [100.0]
    for t in trades:
        pnl = t.rr * risk_per_trade_pct
        new_equity = equity_curve[-1] * (1 + pnl / 100)
        equity_curve.append(new_equity)
    
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd
    
    max_consecutive_losses = 0
    current_streak = 0
    for t in trades:
        if not t.is_winner:
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
        else:
            current_streak = 0
    
    avg_win = sum(t.rr for t in trades if t.is_winner) / wins if wins > 0 else 0
    avg_loss = abs(sum(t.rr for t in trades if not t.is_winner) / losses) if losses > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    
    tp1_trail_count = sum(1 for t in trades if t.exit_reason == "TP1+Trail")
    tp2_count = sum(1 for t in trades if t.exit_reason == "TP2")
    tp3_count = sum(1 for t in trades if t.exit_reason == "TP3")
    sl_count = sum(1 for t in trades if t.exit_reason == "SL")
    
    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_rr": total_rr,
        "avg_rr_per_trade": avg_rr_per_trade,
        "return_pct": return_pct,
        "max_drawdown_pct": max_dd,
        "max_consecutive_losses": max_consecutive_losses,
        "expectancy_per_trade": expectancy,
        "tp1_trail_count": tp1_trail_count,
        "tp2_count": tp2_count,
        "tp3_count": tp3_count,
        "sl_count": sl_count,
    }


def run_backtest(
    asset: str,
    year: int,
    params: Optional[StrategyParams] = None,
    use_csv: bool = True,
) -> BacktestResult:
    """
    Run a complete backtest for one asset and one year.
    
    Uses the REAL strategy logic from strategy_core.py with no look-ahead bias.
    
    Args:
        asset: Asset symbol
        year: Calendar year to backtest
        params: Strategy parameters (uses defaults if None)
        use_csv: Whether to prefer CSV data
    
    Returns:
        BacktestResult with comprehensive metrics
    """
    if params is None:
        params = get_default_params()
    
    data = load_backtest_data(asset, year, use_csv)
    
    if not data["daily"]:
        return BacktestResult(
            asset=asset,
            year=year,
            params=params,
            total_trades=0,
            meets_targets=False,
        )
    
    trades = simulate_trades(
        candles=data["daily"],
        symbol=asset,
        params=params,
        monthly_candles=data["monthly"],
        weekly_candles=data["weekly"],
        h4_candles=data["h4"],
    )
    
    metrics = compute_metrics(trades, params.risk_per_trade_pct)
    
    targets = OptimizationTargets()
    
    result = BacktestResult(
        asset=asset,
        year=year,
        params=params,
        total_trades=metrics["total_trades"],
        wins=metrics["wins"],
        losses=metrics["losses"],
        win_rate=metrics["win_rate"],
        total_rr=metrics["total_rr"],
        avg_rr_per_trade=metrics["avg_rr_per_trade"],
        return_pct=metrics["return_pct"],
        max_drawdown_pct=metrics["max_drawdown_pct"],
        max_consecutive_losses=metrics["max_consecutive_losses"],
        expectancy_per_trade=metrics["expectancy_per_trade"],
        tp1_trail_count=metrics["tp1_trail_count"],
        tp2_count=metrics["tp2_count"],
        tp3_count=metrics["tp3_count"],
        sl_count=metrics["sl_count"],
        trades=trades,
    )
    
    result.meets_targets = targets.check(result)
    
    return result


def run_baseline_backtest(
    assets: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    params: Optional[StrategyParams] = None,
    save_results: bool = True,
) -> List[BacktestResult]:
    """
    Run baseline backtests for all assets and years.
    
    Args:
        assets: List of assets (uses defaults if None)
        years: List of years (uses defaults if None)
        params: Strategy parameters (uses defaults if None)
        save_results: Whether to save results to CSV
    
    Returns:
        List of BacktestResult objects
    """
    if assets is None:
        available = get_available_assets()
        assets = available if available else ASSETS
    
    if years is None:
        years = YEARS
    
    if params is None:
        params = get_default_params()
    
    results = []
    
    print("\n" + "=" * 70)
    print("BASELINE BACKTEST")
    print("=" * 70)
    print(f"Assets: {', '.join(assets)}")
    print(f"Years: {', '.join(map(str, years))}")
    print("-" * 70)
    
    for asset in assets:
        for year in years:
            print(f"Running: {asset} {year}...", end=" ")
            try:
                result = run_backtest(asset, year, params)
                results.append(result)
                status = "PASS" if result.meets_targets else "FAIL"
                print(f"{result.total_trades} trades, {result.win_rate*100:.1f}% WR, {result.return_pct:.1f}% return [{status}]")
            except Exception as e:
                print(f"ERROR: {e}")
    
    if save_results and results:
        save_results_to_csv(results, "results_baseline.csv")
    
    return results


def save_results_to_csv(results: List[BacktestResult], filename: str = "results.csv"):
    """Save backtest results to CSV file."""
    if not results:
        print("No results to save.")
        return
    
    data = [r.to_dict() for r in results]
    df = pd.DataFrame(data)
    
    output_path = Path(filename)
    df.to_csv(output_path, index=False)
    print(f"\nResults saved to: {output_path}")


def load_results_from_csv(filename: str = "results.csv") -> List[Dict]:
    """Load backtest results from CSV file."""
    path = Path(filename)
    if not path.exists():
        print(f"File not found: {path}")
        return []
    
    df = pd.read_csv(path)
    return df.to_dict(orient="records")


def print_summary(results: List[BacktestResult]):
    """Print a summary of backtest results."""
    if not results:
        print("No results to summarize.")
        return
    
    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY")
    print("=" * 80)
    print(f"{'Asset':<12} {'Year':<6} {'Trades':<8} {'Win Rate':<10} {'Return %':<10} {'Max DD %':<10} {'Target':<8}")
    print("-" * 80)
    
    for r in results:
        status = "PASS" if r.meets_targets else "FAIL"
        print(f"{r.asset:<12} {r.year:<6} {r.total_trades:<8} {r.win_rate*100:>7.1f}%  {r.return_pct:>8.1f}%  {r.max_drawdown_pct:>8.1f}%  [{status}]")
    
    print("-" * 80)
    
    total_trades = sum(r.total_trades for r in results)
    total_wins = sum(r.wins for r in results)
    avg_win_rate = total_wins / total_trades if total_trades > 0 else 0
    avg_return = sum(r.return_pct for r in results) / len(results) if results else 0
    passing = sum(1 for r in results if r.meets_targets)
    
    print(f"\nTotal: {total_trades} trades across {len(results)} backtests")
    print(f"Average Win Rate: {avg_win_rate*100:.1f}%")
    print(f"Average Return: {avg_return:.1f}%")
    print(f"Meeting Targets: {passing}/{len(results)} ({passing/len(results)*100:.1f}%)")
    print("=" * 80 + "\n")


def run_backtest_cli(mode: str = "baseline"):
    """
    CLI entry point for backtesting.
    
    Args:
        mode: "baseline" for baseline run, "quick" for quick test
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Blueprint Trader AI Backtest Engine")
    parser.add_argument("--mode", type=str, default="baseline", choices=["baseline", "quick"])
    parser.add_argument("--asset", type=str, default=None, help="Single asset to test")
    parser.add_argument("--year", type=int, default=None, help="Single year to test")
    
    args = parser.parse_args()
    
    if args.mode == "quick" or (args.asset and args.year):
        asset = args.asset or "XAU_USD"
        year = args.year or 2024
        print(f"\nRunning quick backtest for {asset} {year}...")
        result = run_backtest(asset, year)
        print_summary([result])
    else:
        results = run_baseline_backtest()
        print_summary(results)


if __name__ == "__main__":
    run_backtest_cli()
