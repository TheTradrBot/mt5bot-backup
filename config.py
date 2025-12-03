# config.py
"""
Configuration for Blueprint Trader AI.

You keep:
- secrets (tokens, API keys) in Replit Secrets (env vars)
- public config (channel IDs, instruments, intervals) here
"""

import os
from pathlib import Path

# Load environment variables from .env file (for Windows VM or local dev)
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
        print(f"[config] ✓ Loaded environment from {env_file}")
    else:
        print(f"[config] WARNING: .env file not found at {env_file}")
        print(f"[config] Looking in: {Path(__file__).parent.absolute()}")
except ImportError:
    print("[config] ERROR: python-dotenv not installed!")
    print("[config] Install it with: pip install python-dotenv")
except Exception as e:
    print(f"[config] ERROR loading .env: {e}")

from challenge_rules import FIVERS_10K_RULES


# ==== 5%ers High Stakes 10K Risk Model ====
# All challenge rules are centralized in challenge_rules.py
# These values are exported for backward compatibility

ACCOUNT_CURRENCY = FIVERS_10K_RULES.account_currency
ACCOUNT_SIZE = FIVERS_10K_RULES.account_size  # 10,000 USD
MAX_DAILY_LOSS_PCT = FIVERS_10K_RULES.max_daily_loss_pct / 100  # 0.05 (5%)
MAX_TOTAL_LOSS_PCT = FIVERS_10K_RULES.max_total_drawdown_pct / 100  # 0.10 (10%)
RISK_PER_TRADE_PCT = FIVERS_10K_RULES.risk_per_trade_pct / 100  # 0.0075 (0.75%)
MAX_OPEN_RISK_PCT = FIVERS_10K_RULES.max_open_risk_pct / 100  # 0.03 (3%)
MIN_WITHDRAWAL_USD = 150

# Challenge-specific constants
STEP1_PROFIT_TARGET_PCT = FIVERS_10K_RULES.step1_profit_target_pct  # 8%
STEP2_PROFIT_TARGET_PCT = FIVERS_10K_RULES.step2_profit_target_pct  # 5%
MIN_PROFITABLE_DAYS = FIVERS_10K_RULES.min_profitable_days  # 3 days
PROFITABLE_DAY_THRESHOLD_PCT = FIVERS_10K_RULES.profitable_day_threshold_pct  # 0.5%

CONTRACT_SPECS = {
    "USD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
    "GBP_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "EUR_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "NZD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "AUD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "USD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
    "XAU_USD": {"pip_value": 0.01, "contract_size": 100, "pip_location": 2},
    "XAG_USD": {"pip_value": 0.001, "contract_size": 5000, "pip_location": 3},
    "NAS100_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "SPX500_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "WTICO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BCO_USD": {"pip_value": 0.01, "contract_size": 1000, "pip_location": 2},
    "BTC_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
    "ETH_USD": {"pip_value": 0.01, "contract_size": 1, "pip_location": 2},
}


# How strict the confluence engine is.
# "standard"  = balanced trades and quality (recommended for live trading)
# "aggressive" = more trades, looser filters (for experimentation/backtesting)
# Set SIGNAL_MODE environment variable to override, e.g., SIGNAL_MODE=aggressive
SIGNAL_MODE = os.getenv("SIGNAL_MODE", "standard")


# ==== Discord ====

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel IDs - read from environment or use defaults
# Set these in Replit Secrets or environment variables
def _get_channel_id(env_name: str, default: int) -> int:
    """Get channel ID from environment or use default."""
    val = os.getenv(env_name)
    if val:
        try:
            return int(val)
        except ValueError:
            print(f"[config] Warning: Invalid {env_name} value '{val}', using default")
    return default

# Channel configuration with environment variable overrides
SCAN_CHANNEL_ID = _get_channel_id("DISCORD_SCAN_CHANNEL_ID", 1442194985142190230)
TRADES_CHANNEL_ID = _get_channel_id("DISCORD_TRADES_CHANNEL_ID", 1442195008525565962)
TRADE_UPDATES_CHANNEL_ID = _get_channel_id("DISCORD_TRADE_UPDATES_CHANNEL_ID", 1438452127767859254)

# Autoscan interval (hours)
SCAN_INTERVAL_HOURS = 4  # every 4H as per your spec

# Delay first autoscan after bot startup (hours)
FIRST_SCAN_DELAY_HOURS = 4  # prevents startup spam


# ==== Data source: OANDA (practice) ====

OANDA_API_KEY = os.getenv("OANDA_API_KEY")          # set in Replit secrets
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID")    # set in Replit secrets
OANDA_API_URL = "https://api-fxpractice.oanda.com"  # practice endpoint

# Granularity mapping for OANDA
GRANULARITY_MAP = {
    "M": "M",      # Monthly
    "W": "W",      # Weekly
    "D": "D",      # Daily
    "H4": "H4",    # 4-hour
}


# ==== Instruments & groups ====
# All available OANDA instruments

# OANDA FX pairs - Majors and Crosses only
FOREX_PAIRS = [
    # Majors
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF",
    "USD_CAD", "AUD_USD", "NZD_USD",

    # EUR crosses
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD",
    "EUR_CAD", "EUR_NZD",

    # GBP crosses
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_CAD",
    "GBP_NZD",

    # AUD / NZD / CAD / CHF / JPY crosses
    "AUD_JPY", "AUD_CHF", "AUD_CAD", "AUD_NZD",
    "NZD_JPY", "NZD_CHF", "NZD_CAD",
    "CAD_JPY", "CAD_CHF", "CHF_JPY",
]

# Metals
METALS = [
    "XAU_USD",  # Gold
    "XAG_USD",  # Silver
    "XPT_USD",  # Platinum
    "XPD_USD",  # Palladium
    "XAU_EUR",  # Gold/Euro
    "XAU_GBP",  # Gold/GBP
    "XAU_AUD",  # Gold/AUD
    "XAG_EUR",  # Silver/Euro
    "XCU_USD",  # Copper
]

# Indices
INDICES = [
    "US30_USD",    # Dow Jones
    "SPX500_USD",  # S&P 500
    "NAS100_USD",  # Nasdaq 100
]

# Energies
ENERGIES = [
    "WTICO_USD",   # WTI Crude Oil
    "BCO_USD",     # Brent Crude Oil
    "NATGAS_USD",  # Natural Gas
]

# Crypto
CRYPTO_ASSETS = [
    "BTC_USD",   # Bitcoin
    "ETH_USD",   # Ethereum
    "LTC_USD",   # Litecoin
    "BCH_USD",   # Bitcoin Cash
]

# Convenience groups

def all_market_instruments() -> list[str]:
    """All instruments Blueprint can scan."""
    return sorted(set(
        FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
    ))
