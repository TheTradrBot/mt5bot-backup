"""
Symbol Mapping for OANDA (data) to FTMO MT5 (trading)

OANDA uses underscores (EUR_USD), FTMO MT5 uses no separators (EURUSD).
This module provides bidirectional mapping between the two naming conventions.
"""

from typing import Dict, List, Tuple

OANDA_TO_FTMO: Dict[str, str] = {
    # ============ FOREX MAJORS (7) ============
    "EUR_USD": "EURUSD",
    "GBP_USD": "GBPUSD",
    "USD_JPY": "USDJPY",
    "USD_CHF": "USDCHF",
    "USD_CAD": "USDCAD",
    "AUD_USD": "AUDUSD",
    "NZD_USD": "NZDUSD",
    
    # ============ EUR CROSSES (6) ============
    "EUR_GBP": "EURGBP",
    "EUR_JPY": "EURJPY",
    "EUR_CHF": "EURCHF",
    "EUR_AUD": "EURAUD",
    "EUR_CAD": "EURCAD",
    "EUR_NZD": "EURNZD",
    
    # ============ GBP CROSSES (5) ============
    "GBP_JPY": "GBPJPY",
    "GBP_CHF": "GBPCHF",
    "GBP_AUD": "GBPAUD",
    "GBP_CAD": "GBPCAD",
    "GBP_NZD": "GBPNZD",
    
    # ============ AUD CROSSES (4) ============
    "AUD_JPY": "AUDJPY",
    "AUD_CHF": "AUDCHF",
    "AUD_CAD": "AUDCAD",
    "AUD_NZD": "AUDNZD",
    
    # ============ NZD CROSSES (3) ============
    "NZD_JPY": "NZDJPY",
    "NZD_CHF": "NZDCHF",
    "NZD_CAD": "NZDCAD",
    
    # ============ CAD/CHF CROSSES (3) ============
    "CAD_JPY": "CADJPY",
    "CAD_CHF": "CADCHF",
    "CHF_JPY": "CHFJPY",
    
    # ============ METALS (2) ============
    "XAU_USD": "XAUUSD",
    "XAG_USD": "XAGUSD",
    
    # ============ CRYPTO (2) ============
    "BTC_USD": "BTCUSD",
    "ETH_USD": "ETHUSD",
    
    # ============ INDICES (2) ============
    "SPX500_USD": "US500.cash",
    "NAS100_USD": "US100.cash",
}

FTMO_TO_OANDA: Dict[str, str] = {v: k for k, v in OANDA_TO_FTMO.items()}

ALL_FOREX_PAIRS_OANDA: List[str] = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "USD_CAD", "AUD_USD", "NZD_USD",
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_CAD", "EUR_NZD",
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_CAD", "GBP_NZD",
    "AUD_JPY", "AUD_CHF", "AUD_CAD", "AUD_NZD",
    "NZD_JPY", "NZD_CHF", "NZD_CAD",
    "CAD_JPY", "CAD_CHF", "CHF_JPY",
]

ALL_FOREX_PAIRS_FTMO: List[str] = [OANDA_TO_FTMO[s] for s in ALL_FOREX_PAIRS_OANDA]

ALL_METALS_OANDA: List[str] = ["XAU_USD", "XAG_USD"]
ALL_METALS_FTMO: List[str] = ["XAUUSD", "XAGUSD"]

ALL_CRYPTO_OANDA: List[str] = ["BTC_USD", "ETH_USD"]
ALL_CRYPTO_FTMO: List[str] = ["BTCUSD", "ETHUSD"]

ALL_INDICES_OANDA: List[str] = ["SPX500_USD", "NAS100_USD"]
ALL_INDICES_FTMO: List[str] = ["US500.cash", "US100.cash"]

ALL_TRADABLE_OANDA: List[str] = (
    ALL_FOREX_PAIRS_OANDA + ALL_METALS_OANDA + ALL_CRYPTO_OANDA + ALL_INDICES_OANDA
)

ALL_TRADABLE_FTMO: List[str] = (
    ALL_FOREX_PAIRS_FTMO + ALL_METALS_FTMO + ALL_CRYPTO_FTMO + ALL_INDICES_FTMO
)


def oanda_to_ftmo(symbol: str) -> str:
    """Convert OANDA symbol name to FTMO MT5 symbol name."""
    return OANDA_TO_FTMO.get(symbol, symbol.replace("_", ""))


def ftmo_to_oanda(symbol: str) -> str:
    """Convert FTMO MT5 symbol name to OANDA symbol name."""
    if symbol in FTMO_TO_OANDA:
        return FTMO_TO_OANDA[symbol]
    if len(symbol) == 6:
        return f"{symbol[:3]}_{symbol[3:]}"
    return symbol


def get_contract_specs() -> Dict[str, Dict]:
    """Get contract specifications for all tradable symbols (OANDA format)."""
    return {
        "EUR_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "GBP_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "USD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "USD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "USD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "AUD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "NZD_USD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "EUR_GBP": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "EUR_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "EUR_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "EUR_AUD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "EUR_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "EUR_NZD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "GBP_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "GBP_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "GBP_AUD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "GBP_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "GBP_NZD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "AUD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "AUD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "AUD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "AUD_NZD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "NZD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "NZD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "NZD_CAD": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "CAD_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "CAD_CHF": {"pip_value": 0.0001, "contract_size": 100000, "pip_location": 4},
        "CHF_JPY": {"pip_value": 0.01, "contract_size": 100000, "pip_location": 2},
        "XAU_USD": {"pip_value": 0.01, "contract_size": 100, "pip_location": 2},
        "XAG_USD": {"pip_value": 0.001, "contract_size": 5000, "pip_location": 3},
        "BTC_USD": {"pip_value": 1.0, "contract_size": 1, "pip_location": 0},
        "ETH_USD": {"pip_value": 0.01, "contract_size": 1, "pip_location": 2},
        "SPX500_USD": {"pip_value": 0.1, "contract_size": 1, "pip_location": 1},
        "NAS100_USD": {"pip_value": 0.1, "contract_size": 1, "pip_location": 1},
    }


def print_summary():
    """Print a summary of all tradable symbols."""
    print("=" * 60)
    print("TRADABLE SYMBOLS SUMMARY")
    print("=" * 60)
    print(f"\nForex Pairs: {len(ALL_FOREX_PAIRS_OANDA)}")
    for i, (oanda, ftmo) in enumerate(zip(ALL_FOREX_PAIRS_OANDA, ALL_FOREX_PAIRS_FTMO), 1):
        print(f"  {i:2d}. {oanda:10s} -> {ftmo}")
    
    print(f"\nMetals: {len(ALL_METALS_OANDA)}")
    for oanda, ftmo in zip(ALL_METALS_OANDA, ALL_METALS_FTMO):
        print(f"      {oanda:10s} -> {ftmo}")
    
    print(f"\nCrypto: {len(ALL_CRYPTO_OANDA)}")
    for oanda, ftmo in zip(ALL_CRYPTO_OANDA, ALL_CRYPTO_FTMO):
        print(f"      {oanda:10s} -> {ftmo}")
    
    print(f"\nIndices: {len(ALL_INDICES_OANDA)}")
    for oanda, ftmo in zip(ALL_INDICES_OANDA, ALL_INDICES_FTMO):
        print(f"      {oanda:15s} -> {ftmo}")
    
    print(f"\nTotal: {len(ALL_TRADABLE_OANDA)} symbols")
    print("=" * 60)


if __name__ == "__main__":
    print_summary()
