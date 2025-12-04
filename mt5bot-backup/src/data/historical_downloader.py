"""
Historical Data Downloader for Blueprint Trader AI.

Downloads free forex data from HistData.com and resamples to required timeframes.
Supports all major forex pairs, metals, indices from 2003 onwards.
"""

import os
import io
import zipfile
import datetime as dt
from typing import Optional, List, Dict, Tuple
from pathlib import Path

import requests
import pandas as pd


HISTDATA_BASE_URL = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes"

SUPPORTED_PAIRS = {
    "EUR_USD": "EURUSD",
    "GBP_USD": "GBPUSD",
    "USD_JPY": "USDJPY",
    "USD_CHF": "USDCHF",
    "USD_CAD": "USDCAD",
    "AUD_USD": "AUDUSD",
    "NZD_USD": "NZDUSD",
    "EUR_GBP": "EURGBP",
    "EUR_JPY": "EURJPY",
    "EUR_CHF": "EURCHF",
    "EUR_AUD": "EURAUD",
    "EUR_CAD": "EURCAD",
    "EUR_NZD": "EURNZD",
    "GBP_JPY": "GBPJPY",
    "GBP_CHF": "GBPCHF",
    "GBP_AUD": "GBPAUD",
    "GBP_CAD": "GBPCAD",
    "GBP_NZD": "GBPNZD",
    "AUD_JPY": "AUDJPY",
    "AUD_CHF": "AUDCHF",
    "AUD_CAD": "AUDCAD",
    "AUD_NZD": "AUDNZD",
    "NZD_JPY": "NZDJPY",
    "NZD_CHF": "NZDCHF",
    "NZD_CAD": "NZDCAD",
    "CAD_JPY": "CADJPY",
    "CAD_CHF": "CADCHF",
    "CHF_JPY": "CHFJPY",
    "XAU_USD": "XAUUSD",
    "XAG_USD": "XAGUSD",
}

DATA_DIR = Path("data")
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


def ensure_dirs():
    """Create data directories if they don't exist."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def get_histdata_symbol(oanda_symbol: str) -> Optional[str]:
    """Convert OANDA symbol to HistData symbol format."""
    return SUPPORTED_PAIRS.get(oanda_symbol)


def download_histdata_year(symbol: str, year: int) -> Optional[pd.DataFrame]:
    """
    Download 1-minute data from HistData for a specific year.
    
    Note: HistData requires manual download or paid FTP access.
    This function is a placeholder for when data is available locally.
    """
    histdata_sym = get_histdata_symbol(symbol)
    if not histdata_sym:
        print(f"Symbol {symbol} not supported for HistData download")
        return None
    
    raw_file = RAW_DIR / f"{histdata_sym}_{year}.csv"
    
    if raw_file.exists():
        return load_raw_csv(raw_file, symbol)
    
    print(f"Raw data file not found: {raw_file}")
    print(f"Please download {histdata_sym} data for {year} from https://www.histdata.com/download-free-forex-data/")
    return None


def load_raw_csv(file_path: Path, symbol: str) -> pd.DataFrame:
    """
    Load raw 1-minute CSV data from HistData format.
    
    HistData format: DateTime;Open;High;Low;Close;Volume
    DateTime format: YYYYMMDD HHMMSS
    """
    try:
        df = pd.read_csv(
            file_path,
            sep=';',
            names=['DateTime', 'Open', 'High', 'Low', 'Close', 'Volume'],
            parse_dates=['DateTime'],
            date_format='%Y%m%d %H%M%S'
        )
        
        df['Symbol'] = symbol
        df.set_index('DateTime', inplace=True)
        df.sort_index(inplace=True)
        
        df = df[~df.index.duplicated(keep='first')]
        
        return df
    
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return pd.DataFrame()


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample 1-minute data to higher timeframes.
    
    Timeframes:
        - H1: 1 hour
        - H4: 4 hours
        - D1: Daily
        - W1: Weekly
        - MN: Monthly
    """
    resample_map = {
        'H1': '1h',
        'H4': '4h',
        'D1': '1D',
        'W1': '1W',
        'MN': '1ME',
    }
    
    freq = resample_map.get(timeframe)
    if not freq:
        raise ValueError(f"Invalid timeframe: {timeframe}")
    
    if df.empty:
        return df
    
    resampled = df.resample(freq).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum',
    }).dropna()
    
    if 'Symbol' in df.columns:
        resampled['Symbol'] = df['Symbol'].iloc[0]
    
    return resampled


def load_or_create_processed(symbol: str, timeframe: str, start_year: int = 2003, end_year: int = None) -> pd.DataFrame:
    """
    Load processed OHLCV data for a symbol and timeframe.
    Creates from raw data if processed file doesn't exist.
    """
    ensure_dirs()
    
    if end_year is None:
        end_year = dt.datetime.now().year
    
    processed_file = PROCESSED_DIR / f"{symbol}_{timeframe}.parquet"
    
    if processed_file.exists():
        df = pd.read_parquet(processed_file)
        print(f"Loaded {len(df)} bars for {symbol} {timeframe}")
        return df
    
    all_data = []
    for year in range(start_year, end_year + 1):
        year_df = download_histdata_year(symbol, year)
        if year_df is not None and not year_df.empty:
            all_data.append(year_df)
    
    if not all_data:
        print(f"No raw data available for {symbol}")
        return pd.DataFrame()
    
    combined = pd.concat(all_data)
    combined.sort_index(inplace=True)
    combined = combined[~combined.index.duplicated(keep='first')]
    
    resampled = resample_ohlcv(combined, timeframe)
    
    resampled.to_parquet(processed_file)
    print(f"Created processed file: {processed_file} with {len(resampled)} bars")
    
    return resampled


def get_ohlcv_historical(
    symbol: str,
    timeframe: str,
    start_date: Optional[dt.datetime] = None,
    end_date: Optional[dt.datetime] = None,
) -> pd.DataFrame:
    """
    Get historical OHLCV data for a symbol and timeframe.
    
    Args:
        symbol: OANDA-format symbol (e.g., EUR_USD)
        timeframe: H1, H4, D1, W1, or MN
        start_date: Optional start date filter
        end_date: Optional end date filter
    
    Returns:
        DataFrame with OHLCV data
    """
    df = load_or_create_processed(symbol, timeframe)
    
    if df.empty:
        return df
    
    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]
    
    return df


def convert_df_to_candles(df: pd.DataFrame) -> List[Dict]:
    """Convert DataFrame to list of candle dicts for compatibility with existing code."""
    candles = []
    for idx, row in df.iterrows():
        candles.append({
            'time': idx,
            'open': row['Open'],
            'high': row['High'],
            'low': row['Low'],
            'close': row['Close'],
            'volume': row.get('Volume', 0),
        })
    return candles


def get_sr_levels_from_history(symbol: str, timeframe: str = 'MN', lookback: int = 60) -> List[Dict]:
    """
    Calculate Support/Resistance levels from historical data.
    
    Returns list of S/R zones with:
        - level: price level
        - type: 'support' or 'resistance'
        - strength: number of touches
        - first_touch: date of first touch
    """
    df = get_ohlcv_historical(symbol, timeframe)
    
    if df.empty or len(df) < 10:
        return []
    
    df = df.tail(lookback)
    
    tolerance = (df['High'].max() - df['Low'].min()) * 0.02
    
    swing_highs = []
    swing_lows = []
    
    for i in range(2, len(df) - 2):
        if (df['High'].iloc[i] > df['High'].iloc[i-1] and 
            df['High'].iloc[i] > df['High'].iloc[i-2] and
            df['High'].iloc[i] > df['High'].iloc[i+1] and
            df['High'].iloc[i] > df['High'].iloc[i+2]):
            swing_highs.append({
                'level': df['High'].iloc[i],
                'date': df.index[i],
            })
        
        if (df['Low'].iloc[i] < df['Low'].iloc[i-1] and 
            df['Low'].iloc[i] < df['Low'].iloc[i-2] and
            df['Low'].iloc[i] < df['Low'].iloc[i+1] and
            df['Low'].iloc[i] < df['Low'].iloc[i+2]):
            swing_lows.append({
                'level': df['Low'].iloc[i],
                'date': df.index[i],
            })
    
    sr_levels = []
    
    for sh in swing_highs:
        sr_levels.append({
            'level': sh['level'],
            'type': 'resistance',
            'first_touch': sh['date'],
            'strength': 1,
        })
    
    for sl in swing_lows:
        sr_levels.append({
            'level': sl['level'],
            'type': 'support',
            'first_touch': sl['date'],
            'strength': 1,
        })
    
    merged = []
    used = set()
    
    for i, sr1 in enumerate(sr_levels):
        if i in used:
            continue
        
        level_sum = sr1['level']
        count = 1
        
        for j, sr2 in enumerate(sr_levels):
            if j != i and j not in used:
                if abs(sr1['level'] - sr2['level']) < tolerance:
                    level_sum += sr2['level']
                    count += 1
                    used.add(j)
        
        merged.append({
            'level': level_sum / count,
            'type': sr1['type'],
            'first_touch': sr1['first_touch'],
            'strength': count,
        })
        used.add(i)
    
    merged.sort(key=lambda x: x['strength'], reverse=True)
    
    return merged[:20]


def calculate_supply_demand_zones(symbol: str, timeframe: str = 'D1', lookback: int = 100) -> List[Dict]:
    """
    Identify supply and demand zones (Order Blocks) from historical data.
    
    Returns list of zones with:
        - zone_high: upper boundary
        - zone_low: lower boundary
        - type: 'supply' or 'demand'
        - strength: impulse strength
        - fresh: whether zone is untested
    """
    df = get_ohlcv_historical(symbol, timeframe)
    
    if df.empty or len(df) < 20:
        return []
    
    df = df.tail(lookback)
    
    df['body'] = abs(df['Close'] - df['Open'])
    df['range'] = df['High'] - df['Low']
    df['body_ratio'] = df['body'] / df['range'].replace(0, 1)
    
    avg_range = df['range'].mean()
    
    zones = []
    
    for i in range(3, len(df) - 3):
        impulse_range = df['range'].iloc[i+1:i+4].sum()
        
        if impulse_range > avg_range * 4:
            if df['Close'].iloc[i+3] > df['Close'].iloc[i]:
                zone = {
                    'zone_high': max(df['Open'].iloc[i], df['Close'].iloc[i]),
                    'zone_low': df['Low'].iloc[i],
                    'type': 'demand',
                    'date': df.index[i],
                    'strength': impulse_range / avg_range,
                    'fresh': True,
                }
                
                for j in range(i+4, len(df)):
                    if df['Low'].iloc[j] < zone['zone_high']:
                        zone['fresh'] = False
                        break
                
                zones.append(zone)
            
            elif df['Close'].iloc[i+3] < df['Close'].iloc[i]:
                zone = {
                    'zone_high': df['High'].iloc[i],
                    'zone_low': min(df['Open'].iloc[i], df['Close'].iloc[i]),
                    'type': 'supply',
                    'date': df.index[i],
                    'strength': impulse_range / avg_range,
                    'fresh': True,
                }
                
                for j in range(i+4, len(df)):
                    if df['High'].iloc[j] > zone['zone_low']:
                        zone['fresh'] = False
                        break
                
                zones.append(zone)
    
    zones.sort(key=lambda x: (-int(x['fresh']), -x['strength']))
    
    return zones[:10]


if __name__ == "__main__":
    ensure_dirs()
    print("Historical data infrastructure ready.")
    print(f"Raw data directory: {RAW_DIR}")
    print(f"Processed data directory: {PROCESSED_DIR}")
    print(f"Supported symbols: {list(SUPPORTED_PAIRS.keys())}")
