"""
Data module - Data sources for backtesting and live trading.

Includes:
- Dukascopy historical data for backtest parity
- OANDA API for real-time data
- MT5 data adapter
"""

from tradr.data.dukascopy import DukascopyDownloader
from tradr.data.oanda import OandaClient

__all__ = [
    "DukascopyDownloader",
    "OandaClient",
]
