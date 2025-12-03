import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta

import os

from config import (
    DISCORD_TOKEN,
    SCAN_CHANNEL_ID,
    TRADES_CHANNEL_ID,
    TRADE_UPDATES_CHANNEL_ID,
    SCAN_INTERVAL_HOURS,
    FIRST_SCAN_DELAY_HOURS,
    FOREX_PAIRS,
    METALS,
    INDICES,
    ENERGIES,
    CRYPTO_ASSETS,
    SIGNAL_MODE,
    STEP1_PROFIT_TARGET_PCT,
    STEP2_PROFIT_TARGET_PCT,
    MIN_PROFITABLE_DAYS,
)

from strategy import (
    scan_single_asset,
    scan_forex,
    scan_crypto,
    scan_metals,
    scan_indices,
    scan_energies,
    scan_all_markets,
    ScanResult,
)

from formatting import (
    format_scan_group,
    format_detailed_scan,
    format_autoscan_output,
    format_backtest_result,
)

from discord_output import (
    create_setup_embed,
    create_tp_hit_embed,
    create_sl_hit_embed,
    create_trade_closed_embed,
    build_confluence_list,
)

from position_sizing import calculate_position_size_5ers
from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT

from backtest import run_backtest
from data import get_ohlcv, get_cache_stats, clear_cache, get_current_prices

from challenge_rules import (
    FIVERS_10K_RULES,
    format_challenge_summary,
    analyze_step_difficulty,
)
from src.backtest.engine import (
    run_fivers_challenge,
    BacktestTrade,
    format_challenge_result as format_step_result,
    format_backtest_result as format_backtest_10k,
    BacktestResult,
)


import json
from pathlib import Path

ACTIVE_TRADES: dict[str, ScanResult] = {}
TRADE_PROGRESS: dict[str, dict[str, bool]] = {}
TRADE_SIZING: dict[str, dict] = {}
TRADE_ENTRY_DATES: dict[str, object] = {}  # Track entry datetime for each trade

# Persistence file for trade state
TRADE_STATE_FILE = Path("trade_state.json")

def _save_trade_state():
    """Save active trades and entry dates to disk."""
    state = {
        "trades": {},
        "progress": TRADE_PROGRESS,
        "sizing": TRADE_SIZING,
        "entry_dates": {k: v.isoformat() if isinstance(v, datetime) else str(v) for k, v in TRADE_ENTRY_DATES.items()},
    }
    
    for key, trade in ACTIVE_TRADES.items():
        state["trades"][key] = {
            "symbol": trade.symbol,
            "direction": trade.direction,
            "entry": trade.entry,
            "stop_loss": trade.stop_loss,
            "tp1": trade.tp1,
            "tp2": trade.tp2,
            "tp3": trade.tp3,
            "confluence_score": trade.confluence_score,
        }
    
    try:
        with open(TRADE_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[save_trade_state] Error: {e}")

def _load_trade_state():
    """Load active trades from disk on bot startup."""
    global TRADE_ENTRY_DATES
    
    if not TRADE_STATE_FILE.exists():
        return
    
    try:
        with open(TRADE_STATE_FILE, 'r') as f:
            state = json.load(f)
        
        # Restore entry dates
        for key, date_str in state.get("entry_dates", {}).items():
            try:
                TRADE_ENTRY_DATES[key] = datetime.fromisoformat(date_str)
            except:
                pass
        
        # Restore progress
        TRADE_PROGRESS.update(state.get("progress", {}))
        
        # Restore sizing
        TRADE_SIZING.update(state.get("sizing", {}))
        
        # Restore trades (recreate ScanResult objects)
        from strategy import ScanResult
        for key, trade_data in state.get("trades", {}).items():
            try:
                trade = ScanResult(
                    symbol=trade_data["symbol"],
                    direction=trade_data["direction"],
                    confluence_score=trade_data["confluence_score"],
                    htf_bias="",
                    location_note="",
                    fib_note="",
                    liquidity_note="",
                    structure_note="",
                    confirmation_note="",
                    rr_note="",
                    summary_reason="",
                    status="active",
                    entry=trade_data.get("entry"),
                    stop_loss=trade_data.get("stop_loss"),
                    tp1=trade_data.get("tp1"),
                    tp2=trade_data.get("tp2"),
                    tp3=trade_data.get("tp3"),
                )
                ACTIVE_TRADES[key] = trade
            except Exception as e:
                print(f"[load_trade_state] Error restoring trade {key}: {e}")
        
        print(f"[load_trade_state] Restored {len(ACTIVE_TRADES)} active trades")
    except Exception as e:
        print(f"[load_trade_state] Error loading state: {e}")


def split_message(text: str, limit: int = 1900) -> list[str]:
    """Split a long message into chunks under Discord's character limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            if current:
                current += "\n" + line
            else:
                current = line

    if current:
        chunks.append(current)

    return chunks


def _ensure_trade_progress(trade_key: str) -> None:
    """Make sure TRADE_PROGRESS has an entry for this trade key."""
    if trade_key not in TRADE_PROGRESS:
        TRADE_PROGRESS[trade_key] = {
            "tp1": False, "tp2": False, "tp3": False,
            "tp4": False, "tp5": False, "sl": False,
        }


def _compute_trade_progress(idea: ScanResult, live_prices: dict = None) -> tuple[float, float]:
    """Compute (current_price, approx_RR) for a trade idea using live prices."""
    current_price = None
    
    if live_prices and idea.symbol in live_prices:
        price_data = live_prices[idea.symbol]
        current_price = price_data.get("mid", 0) if price_data else 0
    
    if not current_price or current_price <= 0:
        prices = get_current_prices([idea.symbol])
        if prices and idea.symbol in prices:
            current_price = prices[idea.symbol].get("mid", 0)
    
    if not current_price or current_price <= 0:
        return float("nan"), float("nan")

    if idea.entry is None or idea.stop_loss is None:
        return current_price, float("nan")

    entry = idea.entry
    sl = idea.stop_loss

    if idea.direction == "bullish":
        risk = entry - sl
        if risk <= 0:
            return current_price, float("nan")
        rr = (current_price - entry) / risk
    else:
        risk = sl - entry
        if risk <= 0:
            return current_price, float("nan")
        rr = (entry - current_price) / risk

    return current_price, rr


async def check_trade_updates(updates_channel: discord.abc.Messageable) -> None:
    """Check active trades for TP/SL hits and send updates using live prices."""
    if not ACTIVE_TRADES:
        return

    trade_keys = list(ACTIVE_TRADES.keys())
    
    all_symbols = list(set(ACTIVE_TRADES[k].symbol for k in trade_keys if k in ACTIVE_TRADES))
    live_prices = await asyncio.to_thread(get_current_prices, all_symbols) if all_symbols else {}

    for key in trade_keys:
        trade = ACTIVE_TRADES.get(key)
        if trade is None:
            continue

        live_price_data = live_prices.get(trade.symbol)
        if live_price_data:
            price = live_price_data.get("mid", 0)
            if price <= 0:
                print(f"[check_trade_updates] {trade.symbol}: Invalid live price, skipping update")
                continue
        else:
            print(f"[check_trade_updates] {trade.symbol}: Could not fetch live price, skipping update")
            continue
        _ensure_trade_progress(key)
        progress = TRADE_PROGRESS[key]

        entry = trade.entry
        sl = trade.stop_loss
        direction = trade.direction.lower()
        
        sizing = TRADE_SIZING.get(key, {})
        risk_usd = sizing.get("risk_usd", ACCOUNT_SIZE * RISK_PER_TRADE_PCT)
        lot_size = sizing.get("lot_size", 1.0)

        closed = False
        embeds_to_send = []

        if sl is not None and not progress["sl"]:
            if (direction == "bullish" and price <= sl) or (direction == "bearish" and price >= sl):
                progress["sl"] = True
                closed = True
                
                entry_dt = TRADE_ENTRY_DATES.get(key)
                embed = create_sl_hit_embed(
                    symbol=trade.symbol,
                    direction=direction,
                    sl_price=sl,
                    result_usd=-risk_usd,
                    result_pct=-RISK_PER_TRADE_PCT * 100,
                    result_r=-1.0,
                    entry_datetime=entry_dt,
                )
                embeds_to_send.append(embed)

        tp_levels = [
            ("TP1", "tp1", trade.tp1, 1),
            ("TP2", "tp2", trade.tp2, 2),
            ("TP3", "tp3", trade.tp3, 3),
        ]

        if not progress["sl"]:
            risk = abs(entry - sl) if entry and sl else 1.0
            
            for label, flag, level, tp_num in tp_levels:
                if level is None or progress[flag]:
                    continue

                hit = False
                if direction == "bullish" and price >= level:
                    hit = True
                elif direction == "bearish" and price <= level:
                    hit = True
                
                if hit:
                    progress[flag] = True
                    
                    # Calculate R-multiple correctly for each direction
                    if direction == "bullish":
                        rr = (level - entry) / risk if risk > 0 else 0
                    else:
                        rr = (entry - level) / risk if risk > 0 else 0
                    
                    # Ensure rr is always positive for TP hits
                    rr = abs(rr) if rr != 0 else (tp_num * 1.5)  # Use TP level as fallback
                    realized_usd = risk_usd * rr
                    realized_pct = RISK_PER_TRADE_PCT * rr * 100
                    
                    remaining_pct = 100 - (tp_num * 33.3)
                    remaining_lots = lot_size * (remaining_pct / 100)
                    
                    entry_dt = TRADE_ENTRY_DATES.get(key)
                    embed = create_tp_hit_embed(
                        symbol=trade.symbol,
                        direction=direction,
                        tp_level=tp_num,
                        tp_price=level,
                        realized_usd=realized_usd,
                        realized_pct=realized_pct,
                        realized_r=rr,
                        remaining_pct=max(0, remaining_pct),
                        remaining_lots=max(0, remaining_lots),
                        current_sl=entry if tp_num == 1 else None,
                        moved_to_be=(tp_num == 1),
                        entry_datetime=entry_dt,
                    )
                    embeds_to_send.append(embed)

        all_tps_hit = all(
            progress[flag] for label, flag, level, _ in tp_levels if level is not None
        )

        if progress["sl"] or all_tps_hit:
            closed = True

        if closed:
            if all_tps_hit and not progress["sl"]:
                risk = abs(entry - sl) if entry and sl else 1.0
                total_rr = sum(
                    ((level - entry) / risk if direction == "bullish" else (entry - level) / risk)
                    for _, _, level, _ in tp_levels if level is not None
                ) / 3
                
                entry_dt = TRADE_ENTRY_DATES.get(key)
                embed = create_trade_closed_embed(
                    symbol=trade.symbol,
                    direction=direction,
                    avg_exit=price,
                    total_result_usd=risk_usd * total_rr,
                    total_result_pct=RISK_PER_TRADE_PCT * total_rr * 100,
                    total_result_r=total_rr,
                    exit_reason="All TPs Hit",
                    entry_datetime=entry_dt,
                )
                embeds_to_send.append(embed)
            
            ACTIVE_TRADES.pop(key, None)
            TRADE_PROGRESS.pop(key, None)
            TRADE_SIZING.pop(key, None)
            TRADE_ENTRY_DATES.pop(key, None)
            _save_trade_state()  # Persist trade closure

        for embed in embeds_to_send:
            try:
                await updates_channel.send(embed=embed)
            except discord.Forbidden:
                print(f"[trade_updates] ERROR: Missing permissions for updates channel")
            except discord.HTTPException as e:
                print(f"[trade_updates] ERROR: HTTP error sending update: {e}")
            except Exception as e:
                print(f"[trade_updates] ERROR: Failed to send trade update: {e}")


class BlueprintTraderBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced!")


bot = BlueprintTraderBot()


@bot.event
async def on_ready():
    """
    Bot startup - minimal console output, NO Discord messages.
    First autoscan is delayed by FIRST_SCAN_DELAY_HOURS to prevent startup spam.
    """
    print(f"[startup] Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"[startup] Connected to {len(bot.guilds)} server(s)")
    
    # Load persisted trade state (silently - no Discord notifications)
    _load_trade_state()
    restored_count = len(ACTIVE_TRADES)
    if restored_count > 0:
        print(f"[startup] Restored {restored_count} active trades from state file")
    
    # Verify channels exist (console only, no Discord messages)
    scan_ch = bot.get_channel(SCAN_CHANNEL_ID)
    trades_ch = bot.get_channel(TRADES_CHANNEL_ID)
    updates_ch = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
    
    if not scan_ch:
        print(f"[startup] WARNING: Scan channel {SCAN_CHANNEL_ID} not found")
    if not trades_ch:
        print(f"[startup] WARNING: Trades channel {TRADES_CHANNEL_ID} not found")
    if not updates_ch:
        print(f"[startup] WARNING: Updates channel {TRADE_UPDATES_CHANNEL_ID} not found")
    
    # Start autoscan with delay (if OANDA configured)
    if os.getenv("OANDA_API_KEY") and os.getenv("OANDA_ACCOUNT_ID"):
        if not autoscan_loop.is_running():
            autoscan_loop.start()
            print(f"[startup] Autoscan scheduled (first in {FIRST_SCAN_DELAY_HOURS}H, then every {SCAN_INTERVAL_HOURS}H)")
    else:
        print("[startup] OANDA API not configured - autoscan disabled")
    
    print("[startup] Blueprint Trader AI is online and ready")


@bot.tree.command(name="help", description="Show all available commands.")
async def help_command(interaction: discord.Interaction):
    commands_text = """
**Blueprint Trader AI - Commands**

**Scanning:**
`/scan [asset]` - Detailed scan of a single asset
`/forex` - Scan all forex pairs
`/crypto` - Scan crypto assets
`/com` - Scan commodities (metals + energies)
`/indices` - Scan stock indices
`/market` - Full market scan

**Trading:**
`/trade` - Show active trades with status
`/live` - Latest prices for all assets
`/cleartrades` - Clear all active trade tracking

**Analysis:**
`/backtest [period] [asset]` - Test strategy performance
  Examples: 
  - `/backtest "Jan 2024 - Dec 2024"` (all assets)
  - `/backtest "Jan 2024 - Dec 2024" EUR_USD` (single asset)
  - `/backtest "Mar 2023 - Nov 2025"` (any period)
`/output [asset] [period]` - Export backtest to CSV
  Example: `/output EUR_USD "Jan 2024 - Dec 2024"`
`/challenge [start_month] [start_year] [end_month] [end_year]` - Simulate 5ers challenges
  Example: `/challenge Jan 2024 Dec 2024`

**System:**
`/cache` - View cache statistics
`/clearcache` - Clear data cache
`/debug` - Bot health and status check
"""
    await interaction.response.send_message(commands_text, ephemeral=True)


@bot.tree.command(name="scan", description="Scan a single asset with full analysis.")
@app_commands.describe(asset="The asset symbol to scan (e.g., EUR_USD, BTC_USD)")
async def scan(interaction: discord.Interaction, asset: str):
    await interaction.response.defer()
    
    try:
        result = scan_single_asset(asset.upper().replace("/", "_"))

        if not result:
            await interaction.followup.send(f"No data available for **{asset}**. Check the instrument name.")
            return

        if result.confluence_score < 3:
            status_msg = (
                f"**{result.symbol}** | {result.direction.upper()}\n"
                f"Confluence: {result.confluence_score}/7\n\n"
                f"_Low confluence - no actionable setup at this time._"
            )
            await interaction.followup.send(status_msg)
            return

        msg = format_detailed_scan(result)
        chunks = split_message(msg, limit=1900)

        for i, chunk in enumerate(chunks):
            if i == 0:
                await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/scan] Error scanning {asset}: {e}")
        await interaction.followup.send(f"Error scanning **{asset}**: {str(e)}")


@bot.tree.command(name="forex", description="Scan all forex pairs.")
async def forex(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_forex)

        if not scan_results:
            await interaction.followup.send("**Forex** - No setups found.")
            return

        msg = format_scan_group("Forex", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/forex] Error: {e}")
        await interaction.followup.send(f"Error scanning forex: {str(e)}")


@bot.tree.command(name="crypto", description="Scan crypto assets.")
async def crypto(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_crypto)

        if not scan_results:
            await interaction.followup.send("**Crypto** - No setups found.")
            return

        msg = format_scan_group("Crypto", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/crypto] Error: {e}")
        await interaction.followup.send(f"Error scanning crypto: {str(e)}")


@bot.tree.command(name="com", description="Scan commodities (metals + energies).")
async def com(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results_m, _ = await asyncio.to_thread(scan_metals)
        scan_results_e, _ = await asyncio.to_thread(scan_energies)
        combined = scan_results_m + scan_results_e

        if not combined:
            await interaction.followup.send("**Commodities** - No setups found.")
            return

        msg = format_scan_group("Commodities", combined)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/com] Error: {e}")
        await interaction.followup.send(f"Error scanning commodities: {str(e)}")


@bot.tree.command(name="indices", description="Scan stock indices.")
async def indices(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        scan_results, _ = await asyncio.to_thread(scan_indices)

        if not scan_results:
            await interaction.followup.send("**Indices** - No setups found.")
            return

        msg = format_scan_group("Indices", scan_results)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/indices] Error: {e}")
        await interaction.followup.send(f"Error scanning indices: {str(e)}")


@bot.tree.command(name="market", description="Full market scan across all asset classes.")
async def market(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        markets = await asyncio.to_thread(scan_all_markets)

        messages = format_autoscan_output(markets)
        
        if not messages:
            await interaction.followup.send("**Market Scan** - No setups found.")
            return

        for msg in messages:
            chunks = split_message(msg, limit=1900)
            for chunk in chunks:
                await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/market] Error: {e}")
        await interaction.followup.send(f"Error scanning markets: {str(e)}")


@bot.tree.command(name="trade", description="Show active trades with status.")
async def trade(interaction: discord.Interaction):
    if not ACTIVE_TRADES:
        await interaction.response.send_message("No active trades being tracked.")
        return

    lines: list[str] = []
    lines.append("**Active Trades**")
    lines.append("")

    for key, t in ACTIVE_TRADES.items():
        emoji = "[BULL]" if t.direction == "bullish" else "[BEAR]"
        entry = t.entry if t.entry is not None else 0.0
        sl = t.stop_loss if t.stop_loss is not None else 0.0

        current_price, rr = _compute_trade_progress(t)
        rr_str = f"{rr:+.2f}R" if rr == rr else "N/A"

        lines.append(f"{emoji} **{t.symbol}** | {t.direction.upper()} | {t.confluence_score}/7")
        lines.append(f"   Entry: {entry:.5f} | SL: {sl:.5f} | Progress: {rr_str}")
        lines.append("")

    msg = "\n".join(lines)
    await interaction.response.send_message(msg[:2000])


def _format_price(price: float) -> str:
    """Format price with appropriate decimals: 4 for small prices, 2 for larger."""
    if price < 10:
        return f"{price:.4f}"
    else:
        return f"{price:.2f}"


@bot.tree.command(name="live", description="Show latest prices for all assets.")
async def live(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        groups = {
            "Forex": FOREX_PAIRS,
            "Metals": METALS,
            "Indices": INDICES,
            "Energies": ENERGIES,
            "Crypto": CRYPTO_ASSETS,
        }

        lines: list[str] = []
        lines.append("**Live Prices (Real-time)**")
        lines.append("")

        for name, symbols in groups.items():
            lines.append(f"**{name}**")
            if not symbols:
                lines.append("_No instruments configured._")
                lines.append("")
                continue

            prices = await asyncio.to_thread(get_current_prices, symbols)
            
            for sym in symbols:
                if sym in prices:
                    mid = prices[sym]["mid"]
                    lines.append(f"{sym}: `{_format_price(mid)}`")
                else:
                    lines.append(f"{sym}: N/A")
            lines.append("")

        msg = "\n".join(lines)
        chunks = split_message(msg, limit=1900)

        for chunk in chunks:
            await interaction.followup.send(chunk)
    except Exception as e:
        print(f"[/live] Error: {e}")
        await interaction.followup.send(f"Error fetching live prices: {str(e)}")


@bot.tree.command(name="backtest", description="Backtest strategy for asset(s) over a period")
@app_commands.describe(
    asset="Optional: Specific asset to backtest (e.g., EUR_USD). Leave empty for all assets.",
    period="The time period (e.g., 'Jan 2024 - Dec 2024')"
)
async def backtest_cmd(interaction: discord.Interaction, period: str, asset: str = None):
    """Run backtest using 10K 5ers High Stakes account rules."""
    await interaction.response.defer()
    
    try:
        # Single asset backtest
        if asset:
            asset_upper = asset.upper().replace("/", "_")
            result = run_backtest(asset_upper, period)
            
            total_trades = result.get('total_trades', 0)
            if total_trades == 0:
                await interaction.followup.send(
                    f"**No trades found** for {asset_upper} in period: {period}\n\n"
                    f"This could mean:\n"
                    f"- No data available for this period\n"
                    f"- Strategy did not generate signals\n"
                    f"- Period format incorrect (try 'Jan 2024 - Dec 2024')"
                )
                return
            
            win_rate = result.get('win_rate', 0)
            net_return_pct = result.get('net_return_pct', 0)
            max_dd_pct = result.get('max_drawdown_pct', 0)
            trades = result.get('trades', [])
            
            total_r = sum(t.get('rr', 0) for t in trades) if trades else 0
            avg_r = total_r / total_trades if total_trades > 0 else 0
            
            would_pass_step1 = net_return_pct >= STEP1_PROFIT_TARGET_PCT
            would_pass_step2 = net_return_pct >= STEP2_PROFIT_TARGET_PCT
            
            step1_status = "PASS" if would_pass_step1 else "FAIL"
            step2_status = "PASS" if would_pass_step2 else "FAIL"
            
            profit_usd = FIVERS_10K_RULES.account_size * (net_return_pct / 100)
            final_balance = FIVERS_10K_RULES.account_size + profit_usd
            
            min_conf = 4 if SIGNAL_MODE == "standard" else 3
            
            msg = (
                f"**Backtest Results** - 5ers High Stakes 10K\n\n"
                f"**{asset_upper}** | {period}\n\n"
                f"**Account:** ${FIVERS_10K_RULES.account_size:,.0f}\n"
                f"**Risk/Trade:** {FIVERS_10K_RULES.risk_per_trade_pct}%\n"
                f"**Min Confluence:** {min_conf}/7 (mode: {SIGNAL_MODE})\n\n"
                f"**Total Trades:** {total_trades}\n"
                f"**Win Rate:** {win_rate:.1f}%\n"
                f"**Total R:** {total_r:+.2f}R\n"
                f"**Avg R/Trade:** {avg_r:+.2f}R\n\n"
                f"**Net Return:** {net_return_pct:+.1f}% (${profit_usd:+,.2f})\n"
                f"**Final Balance:** ${final_balance:,.2f}\n"
                f"**Max Drawdown:** {max_dd_pct:.2f}%\n\n"
                f"**Challenge Status:**\n"
                f"  Step 1 ({STEP1_PROFIT_TARGET_PCT}% target): {step1_status}\n"
                f"  Step 2 ({STEP2_PROFIT_TARGET_PCT}% target): {step2_status}\n"
            )
            
            if max_dd_pct >= FIVERS_10K_RULES.max_total_drawdown_pct:
                msg += f"\n**WARNING:** Max drawdown {max_dd_pct:.1f}% would breach 10% limit!"
            
            chunks = split_message(msg, limit=1900)
            for chunk in chunks:
                await interaction.followup.send(chunk)
            return
        
        # Multi-asset backtest (when no specific asset provided)
        all_assets = FOREX_PAIRS + METALS + INDICES + ENERGIES + CRYPTO_ASSETS
        
        all_results = []
        total_trades_all = 0
        total_wins_all = 0
        total_r_all = 0.0
        
        for asset_sym in all_assets[:10]:  # Limit to first 10 to avoid timeout
            try:
                result = run_backtest(asset_sym, period)
                
                total_trades = result.get('total_trades', 0)
                if total_trades > 0:
                    win_rate = result.get('win_rate', 0)
                    net_return_pct = result.get('net_return_pct', 0)
                    trades = result.get('trades', [])
                    total_r = sum(t.get('rr', 0) for t in trades) if trades else 0
                    
                    all_results.append({
                        'asset': asset_sym,
                        'trades': total_trades,
                        'win_rate': win_rate,
                        'total_r': total_r,
                        'return_pct': net_return_pct,
                    })
                    
                    total_trades_all += total_trades
                    total_wins_all += sum(1 for t in trades if t.get('rr', 0) > 0)
                    total_r_all += total_r
            except Exception as e:
                print(f"[/backtest] Error with {asset_sym}: {e}")
                continue
        
        if not all_results:
            await interaction.followup.send(
                f"**No trades found** for period: {period}\n\n"
                f"This could mean:\n"
                f"- No data available for this period\n"
                f"- Strategy did not generate signals\n"
                f"- Period format incorrect (try 'Jan 2024 - Dec 2024')"
            )
            return
        
        # Sort by total R
        all_results.sort(key=lambda x: x['total_r'], reverse=True)
        
        # Summary message
        avg_win_rate = (total_wins_all / total_trades_all * 100) if total_trades_all > 0 else 0
        avg_r = total_r_all / total_trades_all if total_trades_all > 0 else 0
        total_return_pct = total_r_all * FIVERS_10K_RULES.risk_per_trade_pct
        total_profit_usd = FIVERS_10K_RULES.account_size * (total_return_pct / 100)
        
        min_conf = 4 if SIGNAL_MODE == "standard" else 3
        
        msg = (
            f"**Multi-Asset Backtest Results** - 5ers High Stakes 10K\n\n"
            f"**Period:** {period}\n"
            f"**Assets Tested:** {len(all_results)}\n"
            f"**Min Confluence:** {min_conf}/7 (mode: {SIGNAL_MODE})\n\n"
            f"**Combined Performance:**\n"
            f"Total Trades: {total_trades_all}\n"
            f"Win Rate: {avg_win_rate:.1f}%\n"
            f"Total R: {total_r_all:+.2f}R\n"
            f"Avg R/Trade: {avg_r:+.2f}R\n"
            f"Net Return: {total_return_pct:+.1f}% (${total_profit_usd:+,.2f})\n\n"
            f"**Top Performers:**\n"
        )
        
        for i, res in enumerate(all_results[:5], 1):
            msg += (
                f"{i}. **{res['asset']}**: {res['trades']} trades, "
                f"{res['win_rate']:.1f}% WR, {res['total_r']:+.2f}R ({res['return_pct']:+.1f}%)\n"
            )
        
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await interaction.followup.send(chunk)
            
    except Exception as e:
        print(f"[/backtest] Error: {e}")
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"Error running backtest: {str(e)}")


@bot.tree.command(name="output", description="Export backtest results to CSV file")
@app_commands.describe(
    asset="The asset to backtest (e.g., EUR_USD)",
    period="The time period (e.g., 'Jan 2024 - Dec 2024')"
)
async def output_cmd(interaction: discord.Interaction, asset: str, period: str):
    """Export backtest results to CSV file."""
    await interaction.response.defer()
    
    try:
        import csv
        from io import StringIO
        
        asset_upper = asset.upper().replace("/", "_")
        result = run_backtest(asset_upper, period)
        
        total_trades = result.get('total_trades', 0)
        if total_trades == 0:
            await interaction.followup.send(
                f"**No trades found** for {asset_upper} in period: {period}"
            )
            return
        
        trades = result.get('trades', [])
        
        # Create CSV in memory
        output = StringIO()
        fieldnames = [
            'Trade #', 'Symbol', 'Direction', 'Confluence',
            'Entry Date', 'Entry Price', 
            'Stop Loss', 'TP1', 'TP2', 'TP3',
            'Exit Date', 'Exit Price', 'Exit Reason',
            'R Multiple', 'Result'
        ]
        
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        
        for i, trade in enumerate(trades, 1):
            entry_date = trade.get('entry_date', 'N/A')
            exit_date = trade.get('exit_date', 'N/A')
            
            rr = trade.get('rr', 0)
            result_text = "WIN" if rr > 0 else "LOSS" if rr < 0 else "BE"
            
            # Get entry and exit prices from the backtest result
            entry_price = result.get('trades', [{}])[i-1].get('entry', trade.get('entry', 0)) if i <= len(result.get('trades', [])) else trade.get('entry', 0)
            exit_price = result.get('trades', [{}])[i-1].get('exit_price', trade.get('exit_price', 0)) if i <= len(result.get('trades', [])) else trade.get('exit_price', 0)
            sl_price = result.get('trades', [{}])[i-1].get('sl', trade.get('sl', 0)) if i <= len(result.get('trades', [])) else trade.get('sl', 0)
            
            # Get TP levels - these should be in the result
            tp1_price = result.get('trades', [{}])[i-1].get('tp1', trade.get('tp1')) if i <= len(result.get('trades', [])) else trade.get('tp1')
            tp2_price = result.get('trades', [{}])[i-1].get('tp2', trade.get('tp2')) if i <= len(result.get('trades', [])) else trade.get('tp2')
            tp3_price = result.get('trades', [{}])[i-1].get('tp3', trade.get('tp3')) if i <= len(result.get('trades', [])) else trade.get('tp3')
            
            confluence = trade.get('confluence', 0)
            
            writer.writerow({
                'Trade #': i,
                'Symbol': trade.get('symbol', asset_upper),
                'Direction': trade.get('direction', '').upper(),
                'Confluence': f"{confluence}/7",
                'Entry Date': entry_date,
                'Entry Price': f"{entry_price:.5f}" if entry_price else 'N/A',
                'Stop Loss': f"{sl_price:.5f}" if sl_price else 'N/A',
                'TP1': f"{tp1_price:.5f}" if tp1_price else 'N/A',
                'TP2': f"{tp2_price:.5f}" if tp2_price else 'N/A',
                'TP3': f"{tp3_price:.5f}" if tp3_price else 'N/A',
                'Exit Date': exit_date,
                'Exit Price': f"{exit_price:.5f}" if exit_price else 'N/A',
                'Exit Reason': trade.get('exit_reason', 'Unknown'),
                'R Multiple': f"{rr:+.2f}R",
                'Result': result_text
            })
        
        # Convert to bytes for Discord file upload
        csv_content = output.getvalue()
        csv_bytes = csv_content.encode('utf-8')
        
        # Create filename
        period_clean = period.replace(" ", "_").replace("/", "-")
        filename = f"{asset_upper}_{period_clean}_backtest.csv"
        
        # Send as file
        file = discord.File(
            fp=StringIO(csv_content),
            filename=filename
        )
        
        summary_msg = (
            f"**Backtest CSV Export** - {asset_upper}\n"
            f"Period: {period}\n"
            f"Total Trades: {total_trades}\n"
            f"Win Rate: {result.get('win_rate', 0):.1f}%\n"
            f"Net Return: {result.get('net_return_pct', 0):+.1f}%"
        )
        
        await interaction.followup.send(content=summary_msg, file=file)
        
    except Exception as e:
        print(f"[/output] Error: {e}")
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"Error generating CSV: {str(e)}")


@bot.tree.command(name="cache", description="View cache statistics.")
async def cache_cmd(interaction: discord.Interaction):
    stats = get_cache_stats()
    
    msg = (
        f"**Cache Statistics**\n\n"
        f"Cached Items: {stats['cached_items']}\n"
        f"Hit Rate: {stats['hit_rate_pct']}%\n"
        f"Hits: {stats['hits']} | Misses: {stats['misses']}"
    )
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="clearcache", description="Clear the data cache.")
async def clearcache(interaction: discord.Interaction):
    clear_cache()
    await interaction.response.send_message("Cache cleared successfully.", ephemeral=True)


@bot.tree.command(name="cleartrades", description="Clear all active trade tracking.")
async def cleartrades(interaction: discord.Interaction):
    count = len(ACTIVE_TRADES)
    ACTIVE_TRADES.clear()
    TRADE_PROGRESS.clear()
    TRADE_SIZING.clear()
    TRADE_ENTRY_DATES.clear()
    _save_trade_state()  # Clear persisted state
    await interaction.response.send_message(f"Cleared {count} active trades.", ephemeral=True)


@bot.tree.command(name="challenge", description="Simulate 5ers 2-step challenge over a date range")
@app_commands.describe(
    start_month="Start month (e.g., 'Jan')",
    start_year="Start year (e.g., '2024' or '24')",
    end_month="End month (e.g., 'Jul')",
    end_year="End year (e.g., '2024' or '24')"
)
async def challenge_cmd(
    interaction: discord.Interaction,
    start_month: str,
    start_year: str,
    end_month: str,
    end_year: str
):
    """
    Simulate 5ers 10K High Stakes 2-step challenge over a date range.
    
    Each challenge = Step 1 (8% target) + Step 2 (5% target).
    Both steps require 3 profitable days (0.5%+ of initial balance).
    """
    await interaction.response.defer()
    
    try:
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        
        s_month = month_map.get(start_month.lower()[:3], 1)
        s_year = int(start_year)
        if s_year < 100:
            s_year += 2000
        
        e_month = month_map.get(end_month.lower()[:3], 12)
        e_year = int(end_year)
        if e_year < 100:
            e_year += 2000
        
        start_date = datetime(s_year, s_month, 1)
        if e_month == 12:
            end_date = datetime(e_year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(e_year, e_month + 1, 1) - timedelta(days=1)
        
        period = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
        
        assets = ["EUR_USD", "GBP_USD", "XAU_USD", "USD_JPY", "NZD_USD"]
        all_trades: list[BacktestTrade] = []
        asset_results = []
        
        for asset in assets:
            try:
                result = run_backtest(asset, period)
                if result and isinstance(result, dict) and result.get('trades'):
                    asset_results.append(f"{asset}: {len(result['trades'])} trades, {result.get('win_rate', 0):.1f}% WR")
                    for t in result['trades']:
                        entry_date_raw = t.get('entry_date') or t.get('entry_time')
                        exit_date_raw = t.get('exit_date') or t.get('exit_time')
                        
                        try:
                            if isinstance(entry_date_raw, str):
                                entry_dt = datetime.fromisoformat(entry_date_raw.replace('Z', '+00:00'))
                            elif isinstance(entry_date_raw, datetime):
                                entry_dt = entry_date_raw
                            else:
                                entry_dt = start_date
                        except:
                            entry_dt = start_date
                        
                        try:
                            if isinstance(exit_date_raw, str):
                                exit_dt = datetime.fromisoformat(exit_date_raw.replace('Z', '+00:00'))
                            elif isinstance(exit_date_raw, datetime):
                                exit_dt = exit_date_raw
                            else:
                                exit_dt = None
                        except:
                            exit_dt = None
                        
                        entry_price = t.get('entry', 0) or t.get('entry_price', 0)
                        stop_loss = t.get('sl', 0) or t.get('stop_loss', 0)
                        risk = abs(entry_price - stop_loss) if entry_price and stop_loss else 0
                        
                        bt = BacktestTrade(
                            symbol=asset,
                            direction=t.get('direction', 'bullish'),
                            entry_date=entry_dt,
                            entry_price=entry_price,
                            stop_loss=stop_loss,
                            tp1=t.get('tp1'),
                            tp2=t.get('tp2'),
                            tp3=t.get('tp3'),
                            exit_date=exit_dt,
                            exit_price=t.get('exit_price') or t.get('exit'),
                            exit_reason=t.get('exit_reason', ''),
                            risk=risk,
                        )
                        rr = t.get('rr', 0)
                        if rr != 0:
                            bt.partial_exits = [{"level": bt.exit_reason, "r_multiple": rr, "portion": 1.0}]
                        
                        all_trades.append(bt)
            except Exception as e:
                print(f"[/challenge] Error backtesting {asset}: {e}")
                continue
        
        if not all_trades:
            await interaction.followup.send(
                f"**5ers Challenge - {start_date.strftime('%b %Y')} to {end_date.strftime('%b %Y')}**\n\n"
                f"No historical trade data available for this period.\n"
                f"Please ensure OANDA API is configured for live scanning."
            )
            return
        
        challenge_result = run_fivers_challenge(
            trades=all_trades,
            start_date=start_date,
            end_date=end_date,
            starting_balance=FIVERS_10K_RULES.account_size,
            risk_per_trade_pct=FIVERS_10K_RULES.risk_per_trade_pct,
        )
        
        # Count challenges passed/failed
        challenges_attempted = len(challenge_result.challenges)
        challenges_passed = sum(1 for c in challenge_result.challenges if c.passed)
        challenges_failed = challenges_attempted - challenges_passed
        
        msg = format_challenge_summary(challenge_result)
        
        # Add passed/failed summary
        msg += f"\n**Summary:**\n"
        msg += f"- Challenges Attempted: {challenges_attempted}\n"
        msg += f"- Challenges Passed: {challenges_passed}\n"
        msg += f"- Challenges Failed: {challenges_failed}\n"
        
        if asset_results:
            msg += "\n**Assets Analyzed:**\n" + "\n".join(f"- {r}" for r in asset_results)
        
        if challenge_result.challenges and len(challenge_result.challenges) >= 1:
            first_challenge = challenge_result.challenges[0]
            if first_challenge.step1 and first_challenge.step2:
                analysis = analyze_step_difficulty(first_challenge.step1, first_challenge.step2)
                msg += f"\n\n{analysis}"
        
        chunks = split_message(msg, limit=1900)
        for chunk in chunks:
            await interaction.followup.send(chunk)
            
    except Exception as e:
        print(f"[/challenge] Error: {e}")
        import traceback
        traceback.print_exc()
        await interaction.followup.send(f"Error simulating challenge: {str(e)}")


@bot.tree.command(name="debug", description="Show bot health and status summary.")
async def debug_cmd(interaction: discord.Interaction):
    """Health and status check for the bot."""
    try:
        import platform
        from data import OANDA_API_KEY, OANDA_ACCOUNT_ID
        
        oanda_status = "Connected" if OANDA_API_KEY and OANDA_ACCOUNT_ID else "Not configured"
        
        cache_stats = get_cache_stats()
        
        autoscan_status = "Running" if autoscan_loop.is_running() else "Stopped"
        
        uptime_str = "N/A"
        if bot.user:
            uptime_str = f"Online as {bot.user.name}"
        
        scan_ch = bot.get_channel(SCAN_CHANNEL_ID)
        trades_ch = bot.get_channel(TRADES_CHANNEL_ID)
        updates_ch = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
        
        channels_status = []
        channels_status.append(f"Scan: {'OK' if scan_ch else 'NOT FOUND'}")
        channels_status.append(f"Trades: {'OK' if trades_ch else 'NOT FOUND'}")
        channels_status.append(f"Updates: {'OK' if updates_ch else 'NOT FOUND'}")
        
        msg = (
            "**Blueprint Trader AI - Debug Info**\n\n"
            f"**Status:** {uptime_str}\n"
            f"**OANDA API:** {oanda_status}\n"
            f"**Autoscan:** {autoscan_status} (every {SCAN_INTERVAL_HOURS}H)\n"
            f"**Signal Mode:** {SIGNAL_MODE}\n\n"
            f"**Channels:**\n"
            f"  {' | '.join(channels_status)}\n\n"
            f"**Active Trades:** {len(ACTIVE_TRADES)}\n"
            f"**Cache:** {cache_stats['cached_items']} items, {cache_stats['hit_rate_pct']}% hit rate\n\n"
            f"**Account Config:**\n"
            f"  Size: ${ACCOUNT_SIZE:,}\n"
            f"  Risk/Trade: {RISK_PER_TRADE_PCT*100:.1f}%\n\n"
            f"**System:** Python {platform.python_version()}"
        )
        
        await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error getting debug info: {str(e)}", ephemeral=True)


async def _safe_send(channel, content=None, embed=None):
    """Safely send a message to a Discord channel with error handling."""
    if channel is None:
        return False
    try:
        if embed:
            await channel.send(embed=embed)
        elif content:
            await channel.send(content)
        return True
    except discord.Forbidden:
        print(f"[discord] ERROR: Missing permissions to send to channel {channel.id}")
        return False
    except discord.HTTPException as e:
        print(f"[discord] ERROR: HTTP exception sending message: {e}")
        return False
    except Exception as e:
        print(f"[discord] ERROR: Failed to send message: {e}")
        return False


@tasks.loop(hours=SCAN_INTERVAL_HOURS)
async def autoscan_loop():
    """
    Periodic market scan - runs every SCAN_INTERVAL_HOURS.
    First run is delayed by FIRST_SCAN_DELAY_HOURS.
    
    Channel routing:
    - Autoscan results -> SCAN channel only
    - New trades -> TRADES channel
    - TP/SL updates -> TRADE_UPDATES channel
    """
    await bot.wait_until_ready()
    print("[autoscan] Running 4H market scan...")
    
    clear_cache()

    scan_channel = bot.get_channel(SCAN_CHANNEL_ID)
    trades_channel = bot.get_channel(TRADES_CHANNEL_ID)

    if scan_channel is None:
        print("[autoscan] WARNING: Scan channel not found, skipping autoscan output")
    
    # Run market scan
    try:
        markets = await asyncio.to_thread(scan_all_markets)
    except Exception as e:
        print(f"[autoscan] ERROR: Market scan failed: {e}")
        return

    # Send autoscan results to SCAN channel only
    if scan_channel:
        messages = format_autoscan_output(markets)
        for msg in messages:
            chunks = split_message(msg, limit=1900)
            for chunk in chunks:
                await _safe_send(scan_channel, content=chunk)

    if trades_channel is not None:
        active_trade_symbols = []
        pending_trades = []
        
        for group_name, (scan_results, trade_ideas) in markets.items():
            for trade in trade_ideas:
                if trade.status != "active":
                    continue
                trade_key = f"{trade.symbol}_{trade.direction}"
                if trade_key in ACTIVE_TRADES:
                    continue
                active_trade_symbols.append(trade.symbol)
                pending_trades.append(trade)
        
        live_prices = {}
        if active_trade_symbols:
            print(f"[autoscan] Fetching live prices for {len(active_trade_symbols)} symbols...")
            live_prices = await asyncio.to_thread(get_current_prices, list(set(active_trade_symbols)))
            print(f"[autoscan] Got live prices for {len(live_prices)} symbols")
        
        for trade in pending_trades:
            # Only activate trades that meet strict quality standards
            if trade.confluence_score < 4:
                continue
            if not trade.entry or not trade.stop_loss or not trade.tp1:
                continue
            
            # Must have confirmation flag to be tradeable
            if trade.status != "active":
                continue
            
            trade_key = f"{trade.symbol}_{trade.direction}"
            
            # Don't re-trigger existing trades
            if trade_key in ACTIVE_TRADES:
                continue
            
            live_price_data = live_prices.get(trade.symbol)
            if not live_price_data:
                print(f"[autoscan] {trade.symbol}: SKIPPED - Could not fetch live price")
                continue
            
            live_mid = live_price_data.get("mid", 0)
            if live_mid <= 0:
                print(f"[autoscan] {trade.symbol}: SKIPPED - Live price invalid ({live_mid})")
                continue
            
            # Validate price is still in valid entry zone (within 0.5%)
            if trade.entry:
                price_diff_pct = abs(live_mid - trade.entry) / trade.entry * 100
                if price_diff_pct > 0.5:
                    print(f"[autoscan] {trade.symbol}: SKIPPED - Price moved {price_diff_pct:.2f}% from signal")
                    continue
            
            # Validate risk/reward is still valid
            risk = abs(live_mid - trade.stop_loss)
            if risk <= 0:
                print(f"[autoscan] {trade.symbol}: SKIPPED - Invalid risk calculation")
                continue
            
            if trade.direction == "bullish":
                if live_mid <= trade.stop_loss:
                    print(f"[autoscan] {trade.symbol}: SKIPPED - Price below SL already")
                    continue
                rr_check = (trade.tp1 - live_mid) / risk
            else:
                if live_mid >= trade.stop_loss:
                    print(f"[autoscan] {trade.symbol}: SKIPPED - Price above SL already")
                    continue
                rr_check = (live_mid - trade.tp1) / risk
            
            if rr_check < 1.5:
                print(f"[autoscan] {trade.symbol}: SKIPPED - R:R too low ({rr_check:.2f}R)")
                continue
            
            # All checks passed - activate trade
            trade.entry = live_mid
            entry_time = datetime.utcnow()
            
            print(f"[autoscan] {trade.symbol}: ✓ Activating {trade.direction.upper()} at {live_mid:.5f} ({trade.confluence_score}/7)")
            
            TRADE_ENTRY_DATES[trade_key] = entry_time
            ACTIVE_TRADES[trade_key] = trade
            _ensure_trade_progress(trade_key)
            
            sizing = calculate_position_size_5ers(
                symbol=trade.symbol,
                entry_price=trade.entry,
                stop_price=trade.stop_loss,
            )
            TRADE_SIZING[trade_key] = sizing
            
            _save_trade_state()  # Persist after all data is set
            
            confluence_items = build_confluence_list(trade)
            
            embed = create_setup_embed(
                symbol=trade.symbol,
                direction=trade.direction,
                timeframe="H4",
                entry=trade.entry,
                stop_loss=trade.stop_loss,
                tp1=trade.tp1,
                tp2=trade.tp2,
                tp3=trade.tp3,
                confluence_score=trade.confluence_score,
                confluence_items=confluence_items,
                description=f"High-confluence setup with {trade.confluence_score}/7 factors aligned.",
                entry_datetime=entry_time,
            )
            
            # Send to TRADES channel with error handling
            await _safe_send(trades_channel, embed=embed)
            
            # Send brief notification to SCAN channel
            if scan_channel:
                note = f"[{trade.symbol}] {trade.direction.upper()} setup triggered and moved to live trade (see #trades)"
                await _safe_send(scan_channel, content=note)

    # Check for TP/SL updates and send to TRADE_UPDATES channel
    updates_channel = bot.get_channel(TRADE_UPDATES_CHANNEL_ID)
    if updates_channel is not None and ACTIVE_TRADES:
        try:
            await check_trade_updates(updates_channel)
        except Exception as e:
            print(f"[autoscan] ERROR: Trade updates check failed: {e}")

    print("[autoscan] Scan complete")


@autoscan_loop.before_loop
async def before_autoscan():
    """Delay the first autoscan run to prevent startup spam."""
    await bot.wait_until_ready()
    delay_seconds = FIRST_SCAN_DELAY_HOURS * 3600
    print(f"[autoscan] Waiting {FIRST_SCAN_DELAY_HOURS}H before first scan...")
    await asyncio.sleep(delay_seconds)


if not DISCORD_TOKEN:
    print("\n" + "=" * 60)
    print("❌ ERROR: DISCORD_BOT_TOKEN not found!")
    print("=" * 60)
    print("\nTo fix this:")
    print("1. Click the 'Secrets' tool (🔒) in the left sidebar")
    print("2. Add a new secret:")
    print("   Key: DISCORD_BOT_TOKEN")
    print("   Value: Your Discord bot token")
    print("\nGet your token from: https://discord.com/developers/applications")
    print("=" * 60 + "\n")
    raise ValueError("DISCORD_BOT_TOKEN not found. Set it in Replit Secrets.")

print("Starting Blueprint Trader AI Bot...")
print("Connecting to Discord...\n")

try:
    bot.run(DISCORD_TOKEN)
except discord.LoginFailure:
    print("\n" + "=" * 60)
    print("❌ ERROR: Invalid Discord Token!")
    print("=" * 60)
    print("\nYour DISCORD_BOT_TOKEN in Secrets is invalid.")
    print("Please verify the token at: https://discord.com/developers/applications")
    print("=" * 60 + "\n")
except Exception as e:
    print("\n" + "=" * 60)
    print(f"❌ ERROR: {type(e).__name__}")
    print("=" * 60)
    print(f"\n{str(e)}\n")
    print("=" * 60 + "\n")
    raise
