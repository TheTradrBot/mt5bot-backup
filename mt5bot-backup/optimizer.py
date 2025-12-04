"""
Strategy Optimizer for Blueprint Trader AI.

This module provides parameter optimization for the trading strategy.
It searches through parameter space to find configurations that meet
the performance targets across multiple assets and years.

Optimization Targets:
- >= 50 trades per year
- 70-100% win rate
- >= 50% yearly return

The optimizer respects the core Blueprint strategy concept while
tuning numerical parameters and optional rule variations.
"""

from __future__ import annotations

import json
import itertools
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from data_loader import ASSETS, YEARS, get_available_assets
from strategy_core import StrategyParams, get_default_params
from backtest_engine import (
    run_backtest,
    BacktestResult,
    OptimizationTargets,
    print_summary,
    save_results_to_csv,
)


@dataclass
class SearchSpace:
    """
    Defines the parameter search space for optimization.
    
    Each parameter has a list of values to try.
    The optimizer will search combinations of these values.
    """
    min_confluence: List[int] = None
    min_quality_factors: List[int] = None
    
    atr_sl_multiplier: List[float] = None
    atr_tp1_multiplier: List[float] = None
    atr_tp2_multiplier: List[float] = None
    atr_tp3_multiplier: List[float] = None
    
    fib_low: List[float] = None
    fib_high: List[float] = None
    
    structure_sl_lookback: List[int] = None
    
    use_htf_filter: List[bool] = None
    use_structure_filter: List[bool] = None
    use_liquidity_filter: List[bool] = None
    use_fib_filter: List[bool] = None
    use_confirmation_filter: List[bool] = None
    
    require_htf_alignment: List[bool] = None
    require_confirmation_for_active: List[bool] = None
    require_rr_for_active: List[bool] = None
    
    cooldown_bars: List[int] = None
    
    risk_per_trade_pct: List[float] = None
    
    def __post_init__(self):
        if self.min_confluence is None:
            self.min_confluence = [1, 2, 3]
        if self.min_quality_factors is None:
            self.min_quality_factors = [0, 1, 2]
        if self.atr_sl_multiplier is None:
            self.atr_sl_multiplier = [1.0, 1.5, 2.0]
        if self.atr_tp1_multiplier is None:
            self.atr_tp1_multiplier = [0.5, 0.6, 0.8, 1.0]
        if self.atr_tp2_multiplier is None:
            self.atr_tp2_multiplier = [1.0, 1.1, 1.5, 2.0]
        if self.atr_tp3_multiplier is None:
            self.atr_tp3_multiplier = [1.5, 1.8, 2.5, 3.0]
        if self.fib_low is None:
            self.fib_low = [0.382]
        if self.fib_high is None:
            self.fib_high = [0.786, 0.886]
        if self.structure_sl_lookback is None:
            self.structure_sl_lookback = [25, 35, 50]
        if self.use_htf_filter is None:
            self.use_htf_filter = [True]
        if self.use_structure_filter is None:
            self.use_structure_filter = [True]
        if self.use_liquidity_filter is None:
            self.use_liquidity_filter = [True]
        if self.use_fib_filter is None:
            self.use_fib_filter = [True]
        if self.use_confirmation_filter is None:
            self.use_confirmation_filter = [True, False]
        if self.require_htf_alignment is None:
            self.require_htf_alignment = [False]
        if self.require_confirmation_for_active is None:
            self.require_confirmation_for_active = [True, False]
        if self.require_rr_for_active is None:
            self.require_rr_for_active = [True]
        if self.cooldown_bars is None:
            self.cooldown_bars = [0, 3, 5]
        if self.risk_per_trade_pct is None:
            self.risk_per_trade_pct = [1.0]
    
    def get_param_grid(self) -> List[Dict[str, Any]]:
        """Generate all parameter combinations."""
        keys = [
            "min_confluence", "min_quality_factors",
            "atr_sl_multiplier", "atr_tp1_multiplier", "atr_tp2_multiplier", "atr_tp3_multiplier",
            "fib_low", "fib_high", "structure_sl_lookback",
            "use_htf_filter", "use_structure_filter", "use_liquidity_filter",
            "use_fib_filter", "use_confirmation_filter",
            "require_htf_alignment", "require_confirmation_for_active", "require_rr_for_active",
            "cooldown_bars", "risk_per_trade_pct",
        ]
        
        values = [getattr(self, k) for k in keys]
        
        grid = []
        for combo in itertools.product(*values):
            grid.append(dict(zip(keys, combo)))
        
        return grid
    
    def get_random_sample(self, n: int = 100) -> List[Dict[str, Any]]:
        """Get a random sample of parameter combinations."""
        full_grid = self.get_param_grid()
        if len(full_grid) <= n:
            return full_grid
        return random.sample(full_grid, n)


@dataclass
class OptimizationResult:
    """Results from a single parameter configuration test."""
    params: Dict[str, Any]
    results: List[BacktestResult]
    
    total_passing: int = 0
    avg_win_rate: float = 0.0
    avg_return_pct: float = 0.0
    avg_drawdown_pct: float = 0.0
    total_trades: int = 0
    
    score: float = 0.0
    
    def compute_metrics(self, targets: OptimizationTargets):
        """Compute aggregate metrics from results."""
        if not self.results:
            return
        
        self.total_passing = sum(1 for r in self.results if targets.check(r))
        self.total_trades = sum(r.total_trades for r in self.results)
        
        wins = sum(r.wins for r in self.results)
        self.avg_win_rate = wins / self.total_trades if self.total_trades > 0 else 0
        
        self.avg_return_pct = sum(r.return_pct for r in self.results) / len(self.results)
        self.avg_drawdown_pct = sum(r.max_drawdown_pct for r in self.results) / len(self.results)
        
        self.score = self._compute_score(targets)
    
    def _compute_score(self, targets: OptimizationTargets) -> float:
        """Compute optimization score (higher is better)."""
        passing_ratio = self.total_passing / len(self.results) if self.results else 0
        
        return_score = min(self.avg_return_pct / targets.min_return_pct, 2.0)
        
        win_rate_score = 0
        if self.avg_win_rate >= targets.min_win_rate:
            win_rate_score = 1.0
        elif self.avg_win_rate >= targets.min_win_rate * 0.8:
            win_rate_score = 0.5
        
        trade_score = min(self.total_trades / (len(self.results) * targets.min_trades_per_year), 1.0)
        
        dd_penalty = max(0, 1 - self.avg_drawdown_pct / 50)
        
        score = (
            passing_ratio * 40 +
            return_score * 25 +
            win_rate_score * 20 +
            trade_score * 10 +
            dd_penalty * 5
        )
        
        return score
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "params": self.params,
            "total_passing": self.total_passing,
            "avg_win_rate": self.avg_win_rate,
            "avg_return_pct": self.avg_return_pct,
            "avg_drawdown_pct": self.avg_drawdown_pct,
            "total_trades": self.total_trades,
            "score": self.score,
        }


def evaluate_params(
    params_dict: Dict[str, Any],
    assets: List[str],
    years: List[int],
    targets: OptimizationTargets,
) -> OptimizationResult:
    """
    Evaluate a single parameter configuration across all assets and years.
    
    Args:
        params_dict: Parameter configuration to test
        assets: List of assets to test
        years: List of years to test
        targets: Performance targets
    
    Returns:
        OptimizationResult with all backtest results
    """
    params = StrategyParams.from_dict(params_dict)
    results = []
    
    for asset in assets:
        for year in years:
            try:
                result = run_backtest(asset, year, params)
                results.append(result)
            except Exception as e:
                print(f"Error testing {asset} {year}: {e}")
    
    opt_result = OptimizationResult(params=params_dict, results=results)
    opt_result.compute_metrics(targets)
    
    return opt_result


def run_optimization(
    assets: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    search_space: Optional[SearchSpace] = None,
    targets: Optional[OptimizationTargets] = None,
    max_configs: int = 100,
    parallel: bool = False,
    verbose: bool = True,
) -> List[OptimizationResult]:
    """
    Run strategy optimization across parameter space.
    
    Args:
        assets: List of assets to test
        years: List of years to test
        search_space: Parameter search space
        targets: Performance targets
        max_configs: Maximum number of configurations to test
        parallel: Whether to run in parallel (may hit API limits)
        verbose: Whether to print progress
    
    Returns:
        List of OptimizationResult sorted by score (best first)
    """
    if assets is None:
        available = get_available_assets()
        assets = available if available else ASSETS[:4]
    
    if years is None:
        years = [2023, 2024]
    
    if search_space is None:
        search_space = SearchSpace()
    
    if targets is None:
        targets = OptimizationTargets()
    
    param_grid = search_space.get_random_sample(max_configs)
    
    if verbose:
        print("\n" + "=" * 70)
        print("STRATEGY OPTIMIZATION")
        print("=" * 70)
        print(f"Assets: {', '.join(assets)}")
        print(f"Years: {', '.join(map(str, years))}")
        print(f"Parameter combinations to test: {len(param_grid)}")
        print("-" * 70)
    
    results = []
    
    for i, params_dict in enumerate(param_grid, 1):
        if verbose:
            print(f"Testing config {i}/{len(param_grid)}...", end=" ")
        
        opt_result = evaluate_params(params_dict, assets, years, targets)
        results.append(opt_result)
        
        if verbose:
            print(f"Score: {opt_result.score:.1f}, Passing: {opt_result.total_passing}/{len(opt_result.results)}")
    
    results.sort(key=lambda x: x.score, reverse=True)
    
    return results


def save_best_config(
    results: List[OptimizationResult],
    filename: str = "best_strategy_config.json",
    top_n: int = 5,
) -> Optional[Dict[str, Any]]:
    """
    Save the best configuration(s) to a JSON file.
    
    Args:
        results: Sorted list of optimization results
        filename: Output filename
        top_n: Number of top configs to save
    
    Returns:
        Best configuration dict
    """
    if not results:
        print("No results to save.")
        return None
    
    best = results[0]
    
    config = {
        "global": best.params,
        "per_asset": {},
        "metadata": {
            "score": best.score,
            "avg_win_rate": best.avg_win_rate,
            "avg_return_pct": best.avg_return_pct,
            "total_passing": best.total_passing,
            "total_trades": best.total_trades,
        },
        "alternatives": [r.to_dict() for r in results[1:top_n]],
    }
    
    with open(filename, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"\nBest configuration saved to: {filename}")
    return config


def load_best_config(filename: str = "best_strategy_config.json") -> Optional[Dict[str, Any]]:
    """Load best configuration from JSON file."""
    path = Path(filename)
    if not path.exists():
        print(f"Config file not found: {path}")
        return None
    
    with open(path) as f:
        return json.load(f)


def get_optimized_params(
    asset: Optional[str] = None,
    config_file: str = "best_strategy_config.json",
) -> StrategyParams:
    """
    Get optimized strategy parameters.
    
    Args:
        asset: If specified, use per-asset overrides if available
        config_file: Path to configuration file
    
    Returns:
        StrategyParams with optimized values
    """
    config = load_best_config(config_file)
    
    if config is None:
        print("Using default parameters (no optimization config found)")
        return get_default_params()
    
    params_dict = dict(config.get("global", {}))
    
    if asset and asset in config.get("per_asset", {}):
        per_asset = config["per_asset"][asset]
        params_dict.update(per_asset)
    
    return StrategyParams.from_dict(params_dict)


def print_optimization_summary(results: List[OptimizationResult], top_n: int = 10):
    """Print summary of optimization results."""
    if not results:
        print("No optimization results.")
        return
    
    print("\n" + "=" * 80)
    print("OPTIMIZATION RESULTS (Top Configurations)")
    print("=" * 80)
    print(f"{'Rank':<6} {'Score':<10} {'Pass':<8} {'WinRate':<10} {'Return%':<10} {'Trades':<10} {'MaxDD%':<10}")
    print("-" * 80)
    
    for i, r in enumerate(results[:top_n], 1):
        print(f"{i:<6} {r.score:>7.1f}   {r.total_passing:>4}/{len(r.results):<3} {r.avg_win_rate*100:>7.1f}%  {r.avg_return_pct:>8.1f}%  {r.total_trades:>8}  {r.avg_drawdown_pct:>8.1f}%")
    
    print("-" * 80)
    
    if results:
        best = results[0]
        print("\nBest Configuration:")
        for key, value in sorted(best.params.items()):
            print(f"  {key}: {value}")
    
    print("=" * 80 + "\n")


def run_optimization_cli():
    """CLI entry point for optimization."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Blueprint Trader AI Strategy Optimizer")
    parser.add_argument("--max-configs", type=int, default=50, help="Max configurations to test")
    parser.add_argument("--assets", type=str, nargs="+", default=None, help="Assets to test")
    parser.add_argument("--years", type=int, nargs="+", default=None, help="Years to test")
    parser.add_argument("--quick", action="store_true", help="Quick test with fewer configs")
    
    args = parser.parse_args()
    
    if args.quick:
        args.max_configs = 10
        args.years = args.years or [2024]
    
    results = run_optimization(
        assets=args.assets,
        years=args.years,
        max_configs=args.max_configs,
    )
    
    print_optimization_summary(results)
    save_best_config(results)


if __name__ == "__main__":
    run_optimization_cli()
