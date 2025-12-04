"""
Strategy module - Re-exports from proven strategy_core.py

This module re-exports the EXACT same strategy logic used in backtests
to ensure perfect parity between historical simulations and live trading.
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from strategy_core import (
    StrategyParams,
    Signal,
    Trade,
    get_default_params,
    get_aggressive_params,
    get_conservative_params,
    generate_signals,
    simulate_trades,
    compute_confluence,
    compute_trade_levels,
    _infer_trend as infer_trend,
    _pick_direction_from_bias as pick_direction_from_bias,
    _compute_confluence_flags as compute_confluence_flags,
    _atr as atr,
    _find_pivots as find_pivots,
    _h4_confirmation as h4_confirmation,
    _location_context as location_context,
    _fib_context as fib_context,
    _daily_liquidity_context as liquidity_context,
    _structure_context as structure_context,
)

__all__ = [
    "StrategyParams",
    "Signal",
    "Trade",
    "get_default_params",
    "get_aggressive_params",
    "get_conservative_params",
    "generate_signals",
    "simulate_trades",
    "compute_confluence",
    "compute_confluence_flags",
    "compute_trade_levels",
    "infer_trend",
    "pick_direction_from_bias",
    "atr",
    "find_pivots",
    "h4_confirmation",
    "location_context",
    "fib_context",
    "liquidity_context",
    "structure_context",
]
