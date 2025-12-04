"""
Report Generator for Blueprint Trader AI.

This module provides comprehensive reporting and analysis of backtest
and optimization results.

Usage:
    python report.py                    # Full report
    python report.py --asset XAU_USD    # Asset-specific report
    python report.py --summary          # Summary only
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import pandas as pd

from data_loader import ASSETS, YEARS
from strategy_core import StrategyParams, get_default_params
from backtest_engine import (
    BacktestResult,
    run_backtest,
    print_summary,
    load_results_from_csv,
)
from optimizer import (
    load_best_config,
    get_optimized_params,
    OptimizationTargets,
)


def load_baseline_results() -> List[Dict]:
    """Load baseline backtest results."""
    return load_results_from_csv("results_baseline.csv")


def load_optimization_results() -> List[Dict]:
    """Load optimization backtest results."""
    return load_results_from_csv("results_optimization.csv")


def generate_asset_report(
    asset: str,
    years: Optional[List[int]] = None,
    use_optimized: bool = True,
) -> Dict[str, Any]:
    """
    Generate a detailed report for a single asset.
    
    Args:
        asset: Asset symbol
        years: Years to include (uses all if None)
        use_optimized: Whether to use optimized parameters
    
    Returns:
        Report dictionary with metrics and analysis
    """
    if years is None:
        years = YEARS
    
    if use_optimized:
        params = get_optimized_params(asset)
    else:
        params = get_default_params()
    
    results = []
    for year in years:
        try:
            result = run_backtest(asset, year, params)
            results.append(result)
        except Exception as e:
            print(f"Error running backtest for {asset} {year}: {e}")
    
    if not results:
        return {"asset": asset, "error": "No data available"}
    
    total_trades = sum(r.total_trades for r in results)
    total_wins = sum(r.wins for r in results)
    avg_win_rate = total_wins / total_trades if total_trades > 0 else 0
    avg_return = sum(r.return_pct for r in results) / len(results)
    avg_drawdown = sum(r.max_drawdown_pct for r in results) / len(results)
    
    targets = OptimizationTargets()
    passing_years = sum(1 for r in results if targets.check(r))
    
    yearly_data = []
    for r in results:
        yearly_data.append({
            "year": r.year,
            "trades": r.total_trades,
            "wins": r.wins,
            "losses": r.losses,
            "win_rate": r.win_rate,
            "return_pct": r.return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "meets_targets": targets.check(r),
        })
    
    return {
        "asset": asset,
        "years_tested": len(results),
        "years_passing": passing_years,
        "total_trades": total_trades,
        "total_wins": total_wins,
        "avg_win_rate": avg_win_rate,
        "avg_return_pct": avg_return,
        "avg_drawdown_pct": avg_drawdown,
        "yearly_data": yearly_data,
        "params_used": params.to_dict() if use_optimized else "default",
    }


def generate_full_report(
    assets: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    use_optimized: bool = True,
    save_to_file: bool = True,
) -> Dict[str, Any]:
    """
    Generate a comprehensive report for all assets.
    
    Args:
        assets: Assets to include
        years: Years to include
        use_optimized: Whether to use optimized parameters
        save_to_file: Whether to save report to JSON
    
    Returns:
        Complete report dictionary
    """
    if assets is None:
        assets = ASSETS
    
    if years is None:
        years = YEARS
    
    asset_reports = []
    for asset in assets:
        print(f"Generating report for {asset}...")
        report = generate_asset_report(asset, years, use_optimized)
        asset_reports.append(report)
    
    total_trades = sum(r.get("total_trades", 0) for r in asset_reports)
    total_wins = sum(r.get("total_wins", 0) for r in asset_reports)
    overall_win_rate = total_wins / total_trades if total_trades > 0 else 0
    
    avg_return = sum(r.get("avg_return_pct", 0) for r in asset_reports) / len(asset_reports) if asset_reports else 0
    
    total_years = sum(r.get("years_tested", 0) for r in asset_reports)
    passing_years = sum(r.get("years_passing", 0) for r in asset_reports)
    
    full_report = {
        "summary": {
            "total_assets": len(asset_reports),
            "total_years_tested": total_years,
            "years_meeting_targets": passing_years,
            "target_achievement_rate": passing_years / total_years if total_years > 0 else 0,
            "total_trades": total_trades,
            "overall_win_rate": overall_win_rate,
            "average_return_pct": avg_return,
        },
        "asset_reports": asset_reports,
        "config_used": "optimized" if use_optimized else "default",
    }
    
    if save_to_file:
        with open("full_report.json", "w") as f:
            json.dump(full_report, f, indent=2)
        print("\nReport saved to: full_report.json")
    
    return full_report


def print_report(report: Dict[str, Any]):
    """Print a formatted report to console."""
    print("\n" + "=" * 90)
    print("BLUEPRINT TRADER AI - PERFORMANCE REPORT")
    print("=" * 90)
    
    summary = report.get("summary", {})
    print("\nOVERALL SUMMARY")
    print("-" * 50)
    print(f"Assets Tested:           {summary.get('total_assets', 0)}")
    print(f"Total Year-Tests:        {summary.get('total_years_tested', 0)}")
    print(f"Years Meeting Targets:   {summary.get('years_meeting_targets', 0)}")
    print(f"Target Achievement:      {summary.get('target_achievement_rate', 0)*100:.1f}%")
    print(f"Total Trades:            {summary.get('total_trades', 0)}")
    print(f"Overall Win Rate:        {summary.get('overall_win_rate', 0)*100:.1f}%")
    print(f"Average Return:          {summary.get('average_return_pct', 0):.1f}%")
    
    print("\n" + "-" * 90)
    print("DETAILED RESULTS BY ASSET")
    print("-" * 90)
    print(f"{'Asset':<12} {'Years':<8} {'Pass':<6} {'Trades':<10} {'Win Rate':<12} {'Avg Return':<12} {'Meets Target':<12}")
    print("-" * 90)
    
    for ar in report.get("asset_reports", []):
        asset = ar.get("asset", "N/A")
        years = ar.get("years_tested", 0)
        passing = ar.get("years_passing", 0)
        trades = ar.get("total_trades", 0)
        wr = ar.get("avg_win_rate", 0)
        ret = ar.get("avg_return_pct", 0)
        meets = "YES" if passing == years and years > 0 else f"{passing}/{years}"
        
        print(f"{asset:<12} {years:<8} {passing:<6} {trades:<10} {wr*100:>8.1f}%    {ret:>8.1f}%     {meets:<12}")
    
    print("-" * 90)
    
    print("\nYEARLY BREAKDOWN")
    print("-" * 90)
    print(f"{'Asset':<12} {'Year':<6} {'Trades':<8} {'Win Rate':<10} {'Return %':<10} {'Max DD %':<10} {'Target':<8}")
    print("-" * 90)
    
    for ar in report.get("asset_reports", []):
        asset = ar.get("asset", "N/A")
        for yd in ar.get("yearly_data", []):
            year = yd.get("year", "N/A")
            trades = yd.get("trades", 0)
            wr = yd.get("win_rate", 0)
            ret = yd.get("return_pct", 0)
            dd = yd.get("max_drawdown_pct", 0)
            meets = "PASS" if yd.get("meets_targets", False) else "FAIL"
            
            print(f"{asset:<12} {year:<6} {trades:<8} {wr*100:>7.1f}%   {ret:>8.1f}%  {dd:>8.1f}%   [{meets}]")
    
    print("=" * 90)
    
    print("\nTARGET CRITERIA:")
    targets = OptimizationTargets()
    print(f"  - Minimum trades per year: {targets.min_trades_per_year}")
    print(f"  - Win rate range: {targets.min_win_rate*100:.0f}% - {targets.max_win_rate*100:.0f}%")
    print(f"  - Minimum yearly return: {targets.min_return_pct:.0f}%")
    print("=" * 90 + "\n")


def compare_baseline_vs_optimized(
    assets: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
):
    """
    Compare baseline vs optimized strategy performance.
    
    Args:
        assets: Assets to compare
        years: Years to compare
    """
    if assets is None:
        assets = ASSETS[:4]
    
    if years is None:
        years = [2023, 2024]
    
    print("\n" + "=" * 100)
    print("BASELINE vs OPTIMIZED COMPARISON")
    print("=" * 100)
    print(f"{'Asset':<12} {'Year':<6} {'Mode':<12} {'Trades':<8} {'Win Rate':<10} {'Return %':<10} {'Target':<8}")
    print("-" * 100)
    
    default_params = get_default_params()
    
    for asset in assets:
        optimized_params = get_optimized_params(asset)
        
        for year in years:
            baseline = run_backtest(asset, year, default_params)
            optimized = run_backtest(asset, year, optimized_params)
            
            targets = OptimizationTargets()
            
            b_status = "PASS" if targets.check(baseline) else "FAIL"
            o_status = "PASS" if targets.check(optimized) else "FAIL"
            
            print(f"{asset:<12} {year:<6} {'Baseline':<12} {baseline.total_trades:<8} {baseline.win_rate*100:>7.1f}%   {baseline.return_pct:>8.1f}%  [{b_status}]")
            print(f"{'':<12} {'':<6} {'Optimized':<12} {optimized.total_trades:<8} {optimized.win_rate*100:>7.1f}%   {optimized.return_pct:>8.1f}%  [{o_status}]")
            
            wr_diff = (optimized.win_rate - baseline.win_rate) * 100
            ret_diff = optimized.return_pct - baseline.return_pct
            print(f"{'':<12} {'':<6} {'Difference':<12} {'':<8} {wr_diff:>+7.1f}pp   {ret_diff:>+8.1f}%")
            print("-" * 100)
    
    print("=" * 100 + "\n")


def run_report_cli():
    """CLI entry point for report generation."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Blueprint Trader AI Report Generator")
    parser.add_argument("--asset", type=str, default=None, help="Single asset report")
    parser.add_argument("--summary", action="store_true", help="Summary only")
    parser.add_argument("--compare", action="store_true", help="Compare baseline vs optimized")
    parser.add_argument("--baseline", action="store_true", help="Use baseline (non-optimized) params")
    parser.add_argument("--years", type=int, nargs="+", default=None, help="Years to include")
    
    args = parser.parse_args()
    
    if args.compare:
        compare_baseline_vs_optimized(years=args.years)
        return
    
    if args.asset:
        report = generate_asset_report(
            args.asset,
            years=args.years,
            use_optimized=not args.baseline,
        )
        print_report({"summary": {}, "asset_reports": [report]})
    else:
        report = generate_full_report(
            years=args.years,
            use_optimized=not args.baseline,
        )
        print_report(report)


if __name__ == "__main__":
    run_report_cli()
