"""
Position sizing module for 5%ers 100K High Stakes account.

Implements proper lot size calculation based on:
- Account size ($100,000)
- Risk per trade (default 1%)
- Stop loss distance
- Contract specifications per instrument
"""

from config import (
    ACCOUNT_SIZE,
    RISK_PER_TRADE_PCT,
    CONTRACT_SPECS,
)


def get_pip_value_per_lot(symbol: str, current_price: float = None, contract_specs: dict = None) -> float:
    """
    Get the pip value per standard lot for a symbol in USD.
    
    For XXX/USD pairs (e.g., EUR_USD): pip value = pip_size * contract_size = $10/lot
    For USD/XXX pairs (e.g., USD_JPY): pip value = (pip_size / price) * contract_size
    For metals/indices: varies by contract size
    
    Args:
        symbol: Trading instrument (e.g., "EUR_USD", "USD_JPY")
        current_price: Current price (required for USD/XXX pairs)
        contract_specs: Optional custom contract specifications
        
    Returns:
        Pip value in USD per standard lot
    """
    specs = (contract_specs or CONTRACT_SPECS).get(symbol, {})
    pip_size = specs.get("pip_value", 0.0001)
    contract_size = specs.get("contract_size", 100000)
    
    if symbol.endswith("_USD"):
        return pip_size * contract_size
    elif symbol.startswith("USD_") and current_price and current_price > 0:
        return (pip_size / current_price) * contract_size
    elif symbol.startswith("USD_"):
        if "JPY" in symbol:
            return (pip_size / 150.0) * contract_size
        else:
            return (pip_size / 1.0) * contract_size
    else:
        return pip_size * contract_size


def calculate_position_size(
    symbol: str,
    account_size: float,
    risk_pct: float,
    entry_price: float,
    stop_price: float,
    contract_specs: dict = None
) -> dict:
    """
    Calculate position size for 5%ers account.
    
    Args:
        symbol: Trading instrument (e.g., "EUR_USD", "XAU_USD")
        account_size: Account balance in USD
        risk_pct: Risk percentage per trade (e.g., 0.01 for 1%)
        entry_price: Entry price level
        stop_price: Stop loss price level
        contract_specs: Optional custom contract specifications
        
    Returns:
        Dict with lot_size, risk_usd, risk_pct, pip_risk, stop_pips
    """
    if entry_price is None or stop_price is None:
        return {
            "lot_size": 0.0,
            "risk_usd": 0.0,
            "risk_pct": risk_pct,
            "pip_risk": 0.0,
            "stop_pips": 0.0,
        }
    
    specs = (contract_specs or CONTRACT_SPECS).get(symbol, {
        "pip_value": 0.0001,
        "contract_size": 100000,
        "pip_location": 4
    })
    
    pip_value = specs.get("pip_value", 0.0001)
    pip_location = specs.get("pip_location", 4)
    
    stop_distance = abs(entry_price - stop_price)
    
    if pip_location == 0:
        stop_pips = stop_distance
    else:
        stop_pips = stop_distance / pip_value
    
    if stop_pips <= 0:
        return {
            "lot_size": 0.0,
            "risk_usd": 0.0,
            "risk_pct": risk_pct,
            "pip_risk": 0.0,
            "stop_pips": 0.0,
        }
    
    risk_usd = account_size * risk_pct
    
    pip_value_per_lot = get_pip_value_per_lot(symbol, current_price=entry_price, contract_specs=contract_specs)
    
    if pip_value_per_lot <= 0:
        return {
            "lot_size": 0.0,
            "risk_usd": risk_usd,
            "risk_pct": risk_pct,
            "pip_risk": 0.0,
            "stop_pips": stop_pips,
        }
    
    lot_size = risk_usd / (stop_pips * pip_value_per_lot)
    
    lot_size = round(lot_size, 2)
    lot_size = max(0.01, lot_size)
    
    actual_risk_usd = lot_size * stop_pips * pip_value_per_lot
    actual_risk_pct = actual_risk_usd / account_size
    
    return {
        "lot_size": lot_size,
        "risk_usd": round(actual_risk_usd, 2),
        "risk_pct": round(actual_risk_pct, 4),
        "pip_risk": round(pip_value_per_lot * lot_size, 2),
        "stop_pips": round(stop_pips, 1),
    }


def calculate_position_size_5ers(
    symbol: str,
    entry_price: float,
    stop_price: float,
    account_size: float = ACCOUNT_SIZE,
    risk_pct: float = RISK_PER_TRADE_PCT,
) -> dict:
    """
    Convenience wrapper using 5%ers default settings.
    
    Args:
        symbol: Trading instrument
        entry_price: Entry price level  
        stop_price: Stop loss price level
        account_size: Account balance (default: 100K)
        risk_pct: Risk per trade (default: 1%)
        
    Returns:
        Position sizing dict with lot_size, risk_usd, etc.
    """
    return calculate_position_size(
        symbol=symbol,
        account_size=account_size,
        risk_pct=risk_pct,
        entry_price=entry_price,
        stop_price=stop_price,
    )


def calculate_rr_values(
    entry: float,
    stop_loss: float,
    tp1: float = None,
    tp2: float = None,
    tp3: float = None,
    direction: str = "bullish"
) -> dict:
    """
    Calculate R:R values for each take profit level.
    
    Returns:
        Dict with tp1_rr, tp2_rr, tp3_rr values
    """
    if entry is None or stop_loss is None:
        return {"tp1_rr": 0.0, "tp2_rr": 0.0, "tp3_rr": 0.0}
    
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return {"tp1_rr": 0.0, "tp2_rr": 0.0, "tp3_rr": 0.0}
    
    def calc_rr(tp):
        if tp is None:
            return 0.0
        if direction == "bullish":
            return (tp - entry) / risk
        else:
            return (entry - tp) / risk
    
    return {
        "tp1_rr": round(calc_rr(tp1), 2),
        "tp2_rr": round(calc_rr(tp2), 2),
        "tp3_rr": round(calc_rr(tp3), 2),
    }


def format_lot_size_display(lot_size: float) -> str:
    """Format lot size for display."""
    if lot_size >= 1.0:
        return f"{lot_size:.2f} lots"
    else:
        return f"{lot_size:.2f} lot"


def format_risk_display(risk_usd: float, risk_pct: float) -> str:
    """Format risk for display."""
    return f"{risk_pct*100:.2f}%  |  ${risk_usd:,.0f}"
