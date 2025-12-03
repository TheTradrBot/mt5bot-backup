"""
Settings Module for Blueprint Trader AI.

This module provides a centralized way to load and manage strategy
configurations, supporting both default and optimized parameters.

The bot can toggle between baseline and optimized strategy modes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

from strategy_core import StrategyParams, get_default_params


USE_OPTIMIZED_STRATEGY = os.getenv("USE_OPTIMIZED_STRATEGY", "true").lower() == "true"

CONFIG_FILE = "best_strategy_config.json"


def load_strategy_config() -> Optional[Dict[str, Any]]:
    """Load strategy configuration from JSON file."""
    path = Path(CONFIG_FILE)
    if not path.exists():
        return None
    
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def get_strategy_params(asset: Optional[str] = None) -> StrategyParams:
    """
    Get strategy parameters for the bot.
    
    If USE_OPTIMIZED_STRATEGY is True and a config file exists,
    returns optimized parameters. Otherwise returns defaults.
    
    Args:
        asset: Optional asset name for per-asset overrides
    
    Returns:
        StrategyParams configured for the asset
    """
    if not USE_OPTIMIZED_STRATEGY:
        return get_default_params()
    
    config = load_strategy_config()
    
    if config is None:
        return get_default_params()
    
    params_dict = dict(config.get("global", {}))
    
    if asset and asset in config.get("per_asset", {}):
        per_asset = config["per_asset"][asset]
        params_dict.update(per_asset)
    
    return StrategyParams.from_dict(params_dict)


def get_all_asset_params() -> Dict[str, StrategyParams]:
    """
    Get strategy parameters for all configured assets.
    
    Returns:
        Dict mapping asset names to their StrategyParams
    """
    from data_loader import ASSETS
    
    return {asset: get_strategy_params(asset) for asset in ASSETS}


def save_strategy_config(params: StrategyParams, asset: Optional[str] = None):
    """
    Save strategy parameters to config file.
    
    Args:
        params: Parameters to save
        asset: If specified, save as per-asset override
    """
    config = load_strategy_config() or {"global": {}, "per_asset": {}}
    
    if asset:
        config["per_asset"][asset] = params.to_dict()
    else:
        config["global"] = params.to_dict()
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_config_status() -> Dict[str, Any]:
    """Get current configuration status."""
    config = load_strategy_config()
    
    return {
        "optimized_mode": USE_OPTIMIZED_STRATEGY,
        "config_file_exists": config is not None,
        "config_file": CONFIG_FILE,
        "global_params": config.get("global", {}) if config else None,
        "per_asset_count": len(config.get("per_asset", {})) if config else 0,
    }


def print_config_status():
    """Print current configuration status."""
    status = get_config_status()
    
    print("\n" + "=" * 50)
    print("STRATEGY CONFIGURATION STATUS")
    print("=" * 50)
    print(f"Optimized Mode: {'ENABLED' if status['optimized_mode'] else 'DISABLED'}")
    print(f"Config File: {status['config_file']}")
    print(f"Config Exists: {'YES' if status['config_file_exists'] else 'NO'}")
    
    if status['global_params']:
        print("\nGlobal Parameters:")
        for key, value in sorted(status['global_params'].items()):
            print(f"  {key}: {value}")
    
    print("=" * 50 + "\n")


if __name__ == "__main__":
    print_config_status()
