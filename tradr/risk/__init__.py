"""
Risk Management module for FTMO Challenge.

Implements pre-trade drawdown simulation to prevent rule breaches.
"""

from tradr.risk.manager import (
    RiskManager,
    RiskCheckResult,
    ChallengeState,
)

from tradr.risk.position_sizing import (
    calculate_lot_size,
    get_pip_value,
)

__all__ = [
    "RiskManager",
    "RiskCheckResult",
    "ChallengeState",
    "calculate_lot_size",
    "get_pip_value",
]
