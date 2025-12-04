"""
MT5 Integration module.

Contains:
- MT5 Bridge client (for connecting from Replit to Windows VM)
- MT5 Direct client (for running directly on Windows VM with MT5)
"""

from tradr.mt5.client import MT5Client
from tradr.mt5.bridge_client import MT5BridgeClient

__all__ = [
    "MT5Client",
    "MT5BridgeClient",
]
