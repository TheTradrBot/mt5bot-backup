# Blueprint Trader AI - FTMO MT5 Trading Bot

## Overview
Blueprint Trader AI is an automated trading bot for FTMO Challenge accounts. It runs 24/7 on a Windows VM with MetaTrader 5, using the same proven strategy from backtests for live trading. Discord is used ONLY for monitoring commands - all trading happens independently on the VM.

## User Preferences
- Preferred communication style: Simple, everyday language
- Strategy must use EXACT SAME logic as backtests
- Bot must trade independently (no Discord dependency for trades)
- Pre-trade risk checks to prevent FTMO rule violations
- Using FTMO demo account for trading
- Using OANDA API for data fetching

## Tradable Assets (34 Total)

### Forex Pairs (28)
**Majors:** EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD
**EUR Crosses:** EURGBP, EURJPY, EURCHF, EURAUD, EURCAD, EURNZD
**GBP Crosses:** GBPJPY, GBPCHF, GBPAUD, GBPCAD, GBPNZD
**AUD Crosses:** AUDJPY, AUDCHF, AUDCAD, AUDNZD
**NZD Crosses:** NZDJPY, NZDCHF, NZDCAD
**Other Crosses:** CADJPY, CADCHF, CHFJPY

### Metals (2)
- XAUUSD (Gold)
- XAGUSD (Silver)

### Crypto (2)
- BTCUSD (Bitcoin)
- ETHUSD (Ethereum)

### Indices (2)
- US500 (S&P 500) - OANDA: SPX500_USD
- US100 (Nasdaq 100) - OANDA: NAS100_USD

## Symbol Naming

| Data Source (OANDA) | Trading (FTMO MT5) |
|---------------------|-------------------|
| EUR_USD | EURUSD |
| XAU_USD | XAUUSD |
| SPX500_USD | US500 |
| NAS100_USD | US100 |

See `symbol_mapping.py` for complete mapping between OANDA and FTMO formats.

## Architecture

### Two-Component System

**1. Standalone MT5 Bot (`main_live_bot.py`)** - Runs on Windows VM
- 24/7 trading loop, completely independent
- Uses `strategy_core.py` directly for signal generation
- Pre-trade risk simulation to prevent DD breaches
- Auto-reconnection on MT5 disconnect
- Scheduled task for auto-start on boot

**2. Minimal Discord Bot (`discord_minimal.py`)** - Optional monitoring
- `/status` - View challenge progress
- `/challenge start|stop|phase2` - Control tracking
- `/backtest <period> [asset]` - Run simulations
- `/output [lines]` - View bot logs

### Directory Structure
```
/
├── main_live_bot.py      # Standalone 24/7 trading bot (Windows VM)
├── discord_minimal.py    # Minimal Discord monitoring bot
├── strategy_core.py      # CORE STRATEGY - Single source of truth
├── symbol_mapping.py     # OANDA <-> FTMO symbol mapping
├── backtest.py           # Backtest engine using strategy_core
├── challenge_rules.py    # FTMO rules and tracking
├── config.py             # Configuration settings
├── data.py               # OANDA data source
├── tradr/                # Modular package
│   ├── strategy/         # Re-exports from strategy_core.py
│   ├── risk/             # Risk manager with DD simulation
│   ├── mt5/              # MT5 client (direct + bridge)
│   ├── data/             # Dukascopy + OANDA clients
│   └── utils/            # Logging, state management
├── scripts/              # Deployment scripts
│   ├── deploy.ps1        # Windows VM deployment
│   ├── update_rollback.ps1  # Update/rollback helper
│   └── compare.py        # Backtest vs MT5 parity check
└── logs/                 # Log files
```

### Strategy (7 Confluence Pillars)
The strategy evaluates setups across these pillars:
1. **HTF Bias** - Monthly/Weekly/Daily trend alignment
2. **Location** - Price at key S/R zones
3. **Fibonacci** - Price in golden pocket (61.8-78.6%)
4. **Liquidity** - Sweep or near equal highs/lows
5. **Structure** - BOS/CHoCH alignment with direction
6. **Confirmation** - 4H candle pattern (engulfing, pin bar)
7. **R:R** - Valid entry/SL/TP levels with min 1:1

**Signal Status:**
- `ACTIVE`: Confluence >= 4, quality >= 1, has R:R = Take trade
- `WATCHING`: Close to confluence threshold = Monitor
- `SCAN`: Below threshold = No action

## FTMO Challenge Rules

### Challenge Phase (Step 1)
- Profit Target: **10%** ($1,000 on $10K)
- Max Daily Loss: **5%** ($500)
- Max Total Drawdown: **10%** ($1,000)
- Min Trading Days: **None** (no minimum)

### Verification Phase (Step 2)
- Profit Target: **5%** ($500 on $10K)
- Same DD rules as Challenge Phase

### Risk Management
- Risk per trade: **1%** of account
- Lot reduction: Halved for each open position
- Pre-trade DD simulation: Blocks trades that would breach limits

## Environment Variables

### Required for Live Trading
```
MT5_SERVER=FTMO-Demo
MT5_LOGIN=12345678
MT5_PASSWORD=YourPassword
```

### Required for Data
```
OANDA_API_KEY=xxx
OANDA_ACCOUNT_ID=xxx
```

### Optional
```
DISCORD_BOT_TOKEN=your_token    # For Discord monitoring
SCAN_INTERVAL_HOURS=4            # How often to scan (default: 4)
SIGNAL_MODE=standard             # "standard" or "aggressive"
```

## Windows VM Deployment

### Quick Deploy
```powershell
# Run as Administrator
.\scripts\deploy.ps1
```

This will:
1. Install Python 3.11 and Git
2. Clone the repository
3. Set up virtual environment
4. Configure scheduled tasks for 24/7 operation
5. Start the bot

### Manual Control
```powershell
# View logs
Get-Content C:\tradr\logs\tradr_live.log -Tail 50

# Stop bot
Stop-ScheduledTask -TaskName TradrLive

# Start bot
Start-ScheduledTask -TaskName TradrLive

# Update code
.\scripts\update_rollback.ps1 -Action update

# Rollback
.\scripts\update_rollback.ps1 -Action rollback
```

## Recent Changes

### December 2024
- Updated for FTMO Challenge rules (10% target Phase 1, 5% Phase 2)
- Added symbol mapping for OANDA -> FTMO MT5 conversion
- Expanded to 34 tradable symbols (28 forex, 2 metals, 2 crypto, 2 indices)
- Created modular `/tradr/` package structure
- Built standalone `main_live_bot.py` using SAME strategy as backtests
- Implemented pre-trade DD simulation in `tradr/risk/manager.py`
- Added Dukascopy data integration for historical parity
- Refactored Discord to minimal slash commands only
- Created PowerShell deployment scripts for Windows VM
- Added parity comparison tool (`scripts/compare.py`)

## Development Notes

### Strategy Parity
The live bot MUST use `strategy_core.py` directly to ensure identical signals:
```python
from strategy_core import (
    compute_confluence,
    _infer_trend,
    _pick_direction_from_bias,
)
```

### Symbol Conversion
When fetching data from OANDA but trading on FTMO:
```python
from symbol_mapping import oanda_to_ftmo, ftmo_to_oanda

# Get OANDA data, convert to FTMO symbol for trading
oanda_symbol = "EUR_USD"
ftmo_symbol = oanda_to_ftmo(oanda_symbol)  # "EURUSD"
```

### Risk Manager
Pre-trade checks simulate worst-case scenario:
1. Calculate potential loss if ALL open positions hit SL
2. Add potential loss from new trade
3. Block if simulated DD would breach 5% daily or 10% max
4. Reduce lot size dynamically based on open positions

### Testing
```bash
# Run backtest
python -c "from backtest import run_backtest; print(run_backtest('EUR_USD', 'Jan 2024 - Dec 2024'))"

# Compare parity
python scripts/compare.py backtest_trades.json mt5_history.csv
```

## Dependencies
- discord-py
- pandas
- numpy
- requests
- python-dotenv
- flask
- flask-cors
- MetaTrader5 (Windows VM only)
