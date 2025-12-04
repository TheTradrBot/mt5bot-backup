#!/usr/bin/env python3
"""
Trade Parity Comparison Tool

Compares backtest trades with actual MT5 execution history
to verify strategy parity between simulation and live trading.

Usage:
    python scripts/compare.py backtest_trades.csv mt5_history.csv

Output:
    - Match rate percentage
    - Signal comparison (entry timing)
    - Exit comparison (SL/TP hits)
    - Drift analysis
"""

import csv
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def load_backtest_trades(filepath: str) -> List[Dict]:
    """Load trades from backtest CSV or JSON."""
    path = Path(filepath)
    
    if path.suffix == ".json":
        with open(path, 'r') as f:
            data = json.load(f)
            return data.get("trades", data) if isinstance(data, dict) else data
    
    trades = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append({
                "symbol": row.get("symbol", row.get("asset", "")),
                "direction": row.get("direction", ""),
                "entry_date": row.get("entry_date", ""),
                "exit_date": row.get("exit_date", ""),
                "entry_price": float(row.get("entry_price", row.get("entry", 0))),
                "stop_loss": float(row.get("stop_loss", row.get("sl", 0))),
                "tp1": float(row.get("tp1", 0)) if row.get("tp1") else None,
                "rr": float(row.get("rr", 0)),
                "exit_reason": row.get("exit_reason", ""),
            })
    
    return trades


def load_mt5_history(filepath: str) -> List[Dict]:
    """Load trades from MT5 history export."""
    path = Path(filepath)
    
    trades = []
    with open(path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append({
                "symbol": row.get("Symbol", row.get("symbol", "")),
                "direction": "bullish" if row.get("Type", "").lower() == "buy" else "bearish",
                "entry_date": row.get("Open Time", row.get("entry_date", "")),
                "exit_date": row.get("Close Time", row.get("exit_date", "")),
                "entry_price": float(row.get("Open Price", row.get("entry_price", 0))),
                "exit_price": float(row.get("Close Price", row.get("exit_price", 0))),
                "volume": float(row.get("Volume", row.get("volume", 0))),
                "profit": float(row.get("Profit", row.get("profit", 0))),
                "sl": float(row.get("S/L", row.get("sl", 0))) if row.get("S/L") else None,
                "tp": float(row.get("T/P", row.get("tp", 0))) if row.get("T/P") else None,
            })
    
    return trades


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse various date formats."""
    if not date_str:
        return None
    
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:len(fmt)], fmt)
        except:
            continue
    
    return None


def find_matching_trade(
    bt_trade: Dict,
    mt5_trades: List[Dict],
    time_tolerance_hours: int = 24,
) -> Optional[Dict]:
    """
    Find MT5 trade that matches a backtest trade.
    
    Matching criteria:
    - Same symbol
    - Same direction
    - Entry within time tolerance
    - Entry price within 0.5% tolerance
    """
    bt_date = parse_date(bt_trade["entry_date"])
    if bt_date is None:
        return None
    
    for mt5 in mt5_trades:
        if mt5["symbol"].replace(".", "") != bt_trade["symbol"].replace("_", "").replace(".", ""):
            continue
        
        if mt5["direction"] != bt_trade["direction"]:
            continue
        
        mt5_date = parse_date(mt5["entry_date"])
        if mt5_date is None:
            continue
        
        time_diff = abs((bt_date - mt5_date).total_seconds() / 3600)
        if time_diff > time_tolerance_hours:
            continue
        
        if bt_trade["entry_price"] > 0:
            price_diff = abs(bt_trade["entry_price"] - mt5["entry_price"]) / bt_trade["entry_price"]
            if price_diff > 0.005:
                continue
        
        return mt5
    
    return None


def analyze_parity(
    backtest_trades: List[Dict],
    mt5_trades: List[Dict],
) -> Dict:
    """
    Analyze parity between backtest and MT5 trades.
    """
    results = {
        "total_backtest": len(backtest_trades),
        "total_mt5": len(mt5_trades),
        "matched": 0,
        "unmatched_backtest": [],
        "unmatched_mt5": list(mt5_trades),
        "matches": [],
        "signal_drift": [],
        "exit_differences": [],
    }
    
    for bt in backtest_trades:
        match = find_matching_trade(bt, results["unmatched_mt5"])
        
        if match:
            results["matched"] += 1
            results["unmatched_mt5"].remove(match)
            
            bt_date = parse_date(bt["entry_date"])
            mt5_date = parse_date(match["entry_date"])
            
            time_drift = 0
            if bt_date and mt5_date:
                time_drift = (mt5_date - bt_date).total_seconds() / 3600
            
            price_drift = 0
            if bt["entry_price"] > 0:
                price_drift = ((match["entry_price"] - bt["entry_price"]) / bt["entry_price"]) * 100
            
            results["matches"].append({
                "symbol": bt["symbol"],
                "direction": bt["direction"],
                "bt_entry_date": bt["entry_date"],
                "mt5_entry_date": match["entry_date"],
                "time_drift_hours": round(time_drift, 2),
                "bt_entry_price": bt["entry_price"],
                "mt5_entry_price": match["entry_price"],
                "price_drift_pct": round(price_drift, 4),
                "bt_exit_reason": bt["exit_reason"],
                "mt5_profit": match["profit"],
            })
            
            results["signal_drift"].append(time_drift)
            
            if bt["exit_reason"] and match["profit"] != 0:
                bt_winner = bt["rr"] > 0
                mt5_winner = match["profit"] > 0
                if bt_winner != mt5_winner:
                    results["exit_differences"].append({
                        "symbol": bt["symbol"],
                        "bt_result": "WIN" if bt_winner else "LOSS",
                        "mt5_result": "WIN" if mt5_winner else "LOSS",
                        "bt_rr": bt["rr"],
                        "mt5_profit": match["profit"],
                    })
        else:
            results["unmatched_backtest"].append(bt)
    
    match_rate = (results["matched"] / len(backtest_trades) * 100) if backtest_trades else 0
    
    avg_time_drift = 0
    if results["signal_drift"]:
        avg_time_drift = sum(results["signal_drift"]) / len(results["signal_drift"])
    
    results["match_rate_pct"] = round(match_rate, 1)
    results["avg_time_drift_hours"] = round(avg_time_drift, 2)
    results["exit_difference_count"] = len(results["exit_differences"])
    
    return results


def print_report(results: Dict):
    """Print human-readable comparison report."""
    print("=" * 70)
    print("BACKTEST vs MT5 PARITY REPORT")
    print("=" * 70)
    print("")
    
    print(f"Backtest Trades: {results['total_backtest']}")
    print(f"MT5 Trades: {results['total_mt5']}")
    print(f"Matched Trades: {results['matched']}")
    print(f"Match Rate: {results['match_rate_pct']}%")
    print("")
    
    print("-" * 70)
    print("SIGNAL TIMING ANALYSIS")
    print("-" * 70)
    print(f"Average Entry Time Drift: {results['avg_time_drift_hours']:.1f} hours")
    
    if results["signal_drift"]:
        print(f"Max Drift: {max(results['signal_drift']):.1f} hours")
        print(f"Min Drift: {min(results['signal_drift']):.1f} hours")
    print("")
    
    print("-" * 70)
    print("EXIT OUTCOME DIFFERENCES")
    print("-" * 70)
    print(f"Trades with Different Outcomes: {results['exit_difference_count']}")
    
    if results["exit_differences"]:
        for diff in results["exit_differences"][:5]:
            print(f"  {diff['symbol']}: Backtest={diff['bt_result']} ({diff['bt_rr']:.2f}R), "
                  f"MT5={diff['mt5_result']} (${diff['mt5_profit']:.2f})")
    print("")
    
    if results["unmatched_backtest"]:
        print("-" * 70)
        print(f"UNMATCHED BACKTEST TRADES ({len(results['unmatched_backtest'])})")
        print("-" * 70)
        for trade in results["unmatched_backtest"][:5]:
            print(f"  {trade['symbol']} {trade['direction']} @ {trade['entry_date']}")
    
    if results["unmatched_mt5"]:
        print("-" * 70)
        print(f"UNMATCHED MT5 TRADES ({len(results['unmatched_mt5'])})")
        print("-" * 70)
        for trade in results["unmatched_mt5"][:5]:
            print(f"  {trade['symbol']} {trade['direction']} @ {trade['entry_date']}")
    
    print("")
    print("=" * 70)
    
    if results["match_rate_pct"] >= 90:
        print("VERDICT: EXCELLENT PARITY - Strategy is executing as designed")
    elif results["match_rate_pct"] >= 70:
        print("VERDICT: GOOD PARITY - Minor timing differences")
    elif results["match_rate_pct"] >= 50:
        print("VERDICT: FAIR PARITY - Review signal generation timing")
    else:
        print("VERDICT: POOR PARITY - Strategy implementation may differ")
    
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Compare backtest trades with MT5 execution history"
    )
    parser.add_argument("backtest_file", help="Backtest trades CSV/JSON file")
    parser.add_argument("mt5_file", help="MT5 history export CSV file")
    parser.add_argument("--output", "-o", help="Output JSON file for detailed results")
    parser.add_argument("--tolerance", "-t", type=int, default=24,
                        help="Time tolerance in hours for matching (default: 24)")
    
    args = parser.parse_args()
    
    print(f"Loading backtest trades from: {args.backtest_file}")
    backtest_trades = load_backtest_trades(args.backtest_file)
    print(f"  Loaded {len(backtest_trades)} trades")
    
    print(f"Loading MT5 history from: {args.mt5_file}")
    mt5_trades = load_mt5_history(args.mt5_file)
    print(f"  Loaded {len(mt5_trades)} trades")
    print("")
    
    results = analyze_parity(backtest_trades, mt5_trades)
    
    print_report(results)
    
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nDetailed results saved to: {args.output}")


if __name__ == "__main__":
    main()
