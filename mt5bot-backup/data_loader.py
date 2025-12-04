"""
Data Loading Utilities for Blueprint Trader AI Backtest/Optimization.

This module provides CSV-based data loading for historical backtesting,
complementing the live OANDA API-based data fetching in data.py.

CSV File Requirements:
- Place CSV files in the /data folder
- Naming convention: {ASSET}.csv (e.g., EURUSD.csv, XAUUSD.csv)
- Required columns: timestamp (or time/date), open, high, low, close, volume (optional)
- Timestamp format: ISO 8601 (e.g., 2024-01-15 or 2024-01-15T10:00:00)

Example CSV structure:
    timestamp,open,high,low,close,volume
    2024-01-02,1.1050,1.1075,1.1020,1.1060,50000
    2024-01-03,1.1060,1.1100,1.1040,1.1085,55000
"""

from __future__ import annotations

import os
from datetime import datetime, date, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

ASSETS = [
    "EUR_USD", "GBP_USD", "USD_JPY",
    "XAU_USD", "XAG_USD",
    "WTICO_USD", "BCO_USD",
    "SPX500_USD", "NAS100_USD",
    "BTC_USD", "ETH_USD",
]

YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]

TIMEFRAME_MULTIPLIERS = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D": 1440,
    "W": 10080,
    "M": 43200,
}


def normalize_asset_name(asset: str) -> str:
    """Normalize asset name for file lookup (e.g., EUR_USD -> EURUSD)."""
    return asset.replace("_", "").replace("/", "").upper()


def denormalize_asset_name(asset: str) -> str:
    """Convert normalized asset name back to OANDA format (e.g., EURUSD -> EUR_USD)."""
    asset_upper = asset.upper().replace("/", "")
    
    forex_pairs = {
        "EURUSD": "EUR_USD", "GBPUSD": "GBP_USD", "USDJPY": "USD_JPY",
        "USDCHF": "USD_CHF", "AUDUSD": "AUD_USD", "USDCAD": "USD_CAD",
        "NZDUSD": "NZD_USD", "EURGBP": "EUR_GBP", "EURJPY": "EUR_JPY",
        "GBPJPY": "GBP_JPY",
    }
    
    commodities = {
        "XAUUSD": "XAU_USD", "XAGUSD": "XAG_USD",
        "WTICOUSD": "WTICO_USD", "BCOUSD": "BCO_USD",
        "USOIL": "WTICO_USD", "UKOIL": "BCO_USD",
    }
    
    indices = {
        "SPX500USD": "SPX500_USD", "NAS100USD": "NAS100_USD",
        "SPX500": "SPX500_USD", "NAS100": "NAS100_USD",
    }
    
    crypto = {
        "BTCUSD": "BTC_USD", "ETHUSD": "ETH_USD", "SOLUSD": "SOL_USD",
    }
    
    all_maps = {**forex_pairs, **commodities, **indices, **crypto}
    return all_maps.get(asset_upper, asset)


def find_csv_file(asset: str) -> Optional[Path]:
    """Find CSV file for an asset in the data directory."""
    if not DATA_DIR.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return None
    
    normalized = normalize_asset_name(asset)
    oanda_format = denormalize_asset_name(asset)
    
    possible_names = [
        f"{normalized}.csv",
        f"{oanda_format}.csv",
        f"{normalized.lower()}.csv",
        f"{asset}.csv",
        f"{asset.lower()}.csv",
    ]
    
    for name in possible_names:
        path = DATA_DIR / name
        if path.exists():
            return path
    
    return None


def load_ohlcv_from_csv(
    asset: str,
    timeframe: str = "D",
) -> pd.DataFrame:
    """
    Load OHLCV data from CSV file.
    
    Args:
        asset: Asset name (e.g., EUR_USD, XAUUSD, etc.)
        timeframe: Expected timeframe of the data (for validation)
    
    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        Index is a DatetimeIndex
    
    Raises:
        FileNotFoundError: If CSV file not found
        ValueError: If required columns are missing
    """
    csv_path = find_csv_file(asset)
    if csv_path is None:
        raise FileNotFoundError(
            f"CSV file for {asset} not found. "
            f"Please place it in {DATA_DIR} as {normalize_asset_name(asset)}.csv"
        )
    
    df = pd.read_csv(csv_path)
    
    time_cols = ["timestamp", "time", "date", "datetime", "Date", "Time", "Timestamp"]
    time_col = None
    for col in time_cols:
        if col in df.columns:
            time_col = col
            break
    
    if time_col is None:
        raise ValueError(f"No timestamp column found in {csv_path}. Expected one of: {time_cols}")
    
    df["timestamp"] = pd.to_datetime(df[time_col])
    df = df.sort_values("timestamp")
    df = df.set_index("timestamp")
    
    required_cols = ["open", "high", "low", "close"]
    col_mapping = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower in required_cols and col_lower not in col_mapping:
            col_mapping[col_lower] = col
        elif col_lower == "o":
            col_mapping["open"] = col
        elif col_lower == "h":
            col_mapping["high"] = col
        elif col_lower == "l":
            col_mapping["low"] = col
        elif col_lower == "c":
            col_mapping["close"] = col
    
    for req in required_cols:
        if req not in col_mapping:
            raise ValueError(f"Missing required column '{req}' in {csv_path}")
    
    result = pd.DataFrame()
    for new_col, old_col in col_mapping.items():
        result[new_col] = pd.to_numeric(df[old_col], errors="coerce")
    
    if "volume" in [c.lower() for c in df.columns]:
        vol_col = next(c for c in df.columns if c.lower() == "volume")
        result["volume"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(0)
    else:
        result["volume"] = 0
    
    result.index = df.index
    result = result.dropna(subset=["open", "high", "low", "close"])
    
    return result


def filter_by_year(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Filter DataFrame to only include data from a specific calendar year.
    
    Args:
        df: DataFrame with DatetimeIndex
        year: Calendar year to filter (e.g., 2024)
    
    Returns:
        Filtered DataFrame containing only rows from the specified year
    """
    start_date = pd.Timestamp(f"{year}-01-01")
    end_date = pd.Timestamp(f"{year}-12-31 23:59:59")
    
    return df[(df.index >= start_date) & (df.index <= end_date)]


def filter_by_date_range(
    df: pd.DataFrame,
    start_date: Optional[Union[str, date, datetime]] = None,
    end_date: Optional[Union[str, date, datetime]] = None,
) -> pd.DataFrame:
    """
    Filter DataFrame by date range.
    
    Args:
        df: DataFrame with DatetimeIndex
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        Filtered DataFrame
    """
    mask = pd.Series([True] * len(df), index=df.index)
    
    if start_date is not None:
        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date)
        mask &= df.index >= pd.Timestamp(start_date)
    
    if end_date is not None:
        if isinstance(end_date, str):
            end_date = pd.to_datetime(end_date)
        mask &= df.index <= pd.Timestamp(end_date)
    
    return df[mask]


def df_to_candle_list(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Convert DataFrame to list of candle dictionaries.
    
    This format is compatible with the existing strategy.py and backtest.py code.
    
    Args:
        df: DataFrame with OHLCV data
    
    Returns:
        List of candle dicts with keys: time, open, high, low, close, volume
    """
    candles = []
    for idx, row in df.iterrows():
        candles.append({
            "time": idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        })
    return candles


def candle_list_to_df(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    Convert list of candle dictionaries to DataFrame.
    
    Args:
        candles: List of candle dicts
    
    Returns:
        DataFrame with DatetimeIndex and OHLCV columns
    """
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    
    data = []
    for c in candles:
        time_val = c.get("time") or c.get("timestamp") or c.get("date")
        data.append({
            "timestamp": pd.to_datetime(time_val),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "volume": float(c.get("volume", 0)),
        })
    
    df = pd.DataFrame(data)
    df = df.set_index("timestamp")
    return df.sort_index()


def resample_to_timeframe(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample data to a different timeframe.
    
    Args:
        df: DataFrame with OHLCV data (expects minute or hourly data)
        target_tf: Target timeframe (H1, H4, D, W, M)
    
    Returns:
        Resampled DataFrame
    """
    tf_to_rule = {
        "M1": "1min",
        "M5": "5min",
        "M15": "15min",
        "M30": "30min",
        "H1": "1h",
        "H4": "4h",
        "D": "1D",
        "W": "1W",
        "M": "1ME",
    }
    
    rule = tf_to_rule.get(target_tf)
    if rule is None:
        raise ValueError(f"Unknown timeframe: {target_tf}")
    
    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    
    return resampled


def get_available_assets() -> List[str]:
    """
    Get list of assets that have CSV data available.
    
    Returns:
        List of asset names in OANDA format
    """
    if not DATA_DIR.exists():
        return []
    
    assets = []
    for csv_file in DATA_DIR.glob("*.csv"):
        asset_name = csv_file.stem.upper()
        oanda_format = denormalize_asset_name(asset_name)
        assets.append(oanda_format)
    
    return sorted(set(assets))


def get_year_range(df: pd.DataFrame) -> Tuple[int, int]:
    """
    Get the range of years covered by the data.
    
    Args:
        df: DataFrame with DatetimeIndex
    
    Returns:
        Tuple of (start_year, end_year)
    """
    if df.empty:
        return (0, 0)
    
    return (df.index.min().year, df.index.max().year)


def load_ohlcv(
    asset: str,
    timeframe: str = "D",
    year: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    High-level function to load OHLCV data.
    
    This function first tries to load from CSV, then falls back to OANDA API.
    
    Args:
        asset: Asset name
        timeframe: Timeframe (D, H4, W, M)
        year: If specified, filter to this year only
        start_date: Optional start date filter
        end_date: Optional end date filter
    
    Returns:
        List of candle dictionaries
    """
    try:
        df = load_ohlcv_from_csv(asset, timeframe)
        
        if year is not None:
            df = filter_by_year(df, year)
        elif start_date or end_date:
            df = filter_by_date_range(df, start_date, end_date)
        
        return df_to_candle_list(df)
    except FileNotFoundError:
        from data import get_ohlcv as get_ohlcv_api
        return get_ohlcv_api(asset, timeframe=timeframe, count=2000, use_cache=False)


def get_multi_timeframe_data(
    asset: str,
    year: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load data for all standard timeframes for an asset.
    
    Args:
        asset: Asset name
        year: If specified, filter to this year only
    
    Returns:
        Dict with keys "M", "W", "D", "H4" containing candle lists
    """
    timeframes = ["M", "W", "D", "H4"]
    result = {}
    
    for tf in timeframes:
        try:
            result[tf] = load_ohlcv(asset, timeframe=tf, year=year)
        except Exception as e:
            print(f"Warning: Could not load {tf} data for {asset}: {e}")
            result[tf] = []
    
    return result


def validate_data_availability() -> Dict[str, Dict[str, Any]]:
    """
    Check which assets have data available and their date ranges.
    
    Returns:
        Dict mapping asset names to their data info
    """
    info = {}
    
    for asset in ASSETS:
        try:
            df = load_ohlcv_from_csv(asset)
            start_year, end_year = get_year_range(df)
            info[asset] = {
                "available": True,
                "rows": len(df),
                "start_year": start_year,
                "end_year": end_year,
                "years": list(range(start_year, end_year + 1)),
            }
        except FileNotFoundError:
            info[asset] = {
                "available": False,
                "rows": 0,
                "start_year": None,
                "end_year": None,
                "years": [],
            }
        except Exception as e:
            info[asset] = {
                "available": False,
                "rows": 0,
                "error": str(e),
            }
    
    return info


def print_data_status():
    """Print a summary of available data for all configured assets."""
    print("\n" + "=" * 60)
    print("DATA AVAILABILITY STATUS")
    print("=" * 60)
    print(f"Data directory: {DATA_DIR}")
    print("-" * 60)
    
    info = validate_data_availability()
    
    for asset, data in info.items():
        if data.get("available"):
            years_str = f"{data['start_year']}-{data['end_year']}"
            print(f"[OK] {asset:12} | {data['rows']:6} rows | Years: {years_str}")
        else:
            error = data.get("error", "File not found")
            print(f"[--] {asset:12} | Not available ({error})")
    
    print("-" * 60)
    print(f"\nTo add data, place CSV files in: {DATA_DIR}")
    print("File naming: EURUSD.csv, XAUUSD.csv, etc.")
    print("Required columns: timestamp, open, high, low, close, volume")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    print_data_status()
