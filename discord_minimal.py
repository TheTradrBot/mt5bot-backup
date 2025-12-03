#!/usr/bin/env python3
"""
Tradr Bot - Minimal Discord Bot

This is a stripped-down Discord bot that ONLY provides monitoring commands.
It does NOT trigger any trades - that's handled by the standalone MT5 bot.

Commands:
    /backtest <period> [asset] - Run backtest simulation
    /challenge start|stop|phase2 - Control challenge tracking
    /status - View current challenge status
    /output [lines] - View recent log output

Usage:
    python discord_minimal.py

Configuration:
    Set DISCORD_BOT_TOKEN in .env file
"""

import os
import sys
import asyncio
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from tradr.risk.manager import RiskManager

from backtest import run_backtest


DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
LOG_FILE = Path("logs/tradr_live.log")


class MinimalBot(commands.Bot):
    """Minimal Discord bot for monitoring only."""
    
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.risk_manager = RiskManager(state_file="challenge_state.json")
    
    async def setup_hook(self):
        await self.tree.sync()
        print("[Discord] Slash commands synced")


bot = MinimalBot()


@bot.event
async def on_ready():
    """Bot startup."""
    print(f"[Discord] Logged in as {bot.user}")
    print(f"[Discord] Connected to {len(bot.guilds)} server(s)")
    print("[Discord] Minimal monitoring bot is ready")
    print("[Discord] Commands: /backtest, /challenge, /status, /output")


@bot.tree.command(name="status", description="View current challenge status")
async def status_command(interaction: discord.Interaction):
    """Show current challenge status."""
    await interaction.response.defer()
    
    status = bot.risk_manager.get_status()
    
    if status["failed"]:
        color = discord.Color.red()
        title = "Challenge FAILED"
    elif status["passed_phase2"]:
        color = discord.Color.gold()
        title = "Challenge COMPLETE"
    elif status["passed_phase1"]:
        color = discord.Color.blue()
        title = "Phase 2 In Progress"
    elif status["live"]:
        color = discord.Color.green()
        title = "Phase 1 In Progress"
    else:
        color = discord.Color.greyple()
        title = "Challenge Not Active"
    
    embed = discord.Embed(title=title, color=color)
    
    embed.add_field(
        name="Phase",
        value=f"Phase {status['phase']}",
        inline=True
    )
    
    embed.add_field(
        name="Balance",
        value=f"${status['balance']:,.2f}",
        inline=True
    )
    
    embed.add_field(
        name="Progress",
        value=f"{status['profit_pct']:+.2f}% / {status['target_pct']}% ({status['progress_pct']:.0f}%)",
        inline=True
    )
    
    embed.add_field(
        name="Drawdown",
        value=f"Daily: {status['daily_loss_pct']:.1f}%/5%\nMax: {status['drawdown_pct']:.1f}%/10%",
        inline=True
    )
    
    embed.add_field(
        name="Trades",
        value=f"{status['total_trades']} total\n{status['win_rate']:.0f}% WR",
        inline=True
    )
    
    embed.add_field(
        name="Profitable Days",
        value=f"{status['profitable_days']}/{status['min_profitable_days']}",
        inline=True
    )
    
    embed.add_field(
        name="Open Positions",
        value=str(status['open_positions']),
        inline=True
    )
    
    if status['failed']:
        embed.add_field(
            name="Fail Reason",
            value=status['fail_reason'],
            inline=False
        )
    
    embed.set_footer(text=f"Last update: {status['last_update'][:19] if status['last_update'] else 'N/A'}")
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="challenge", description="Start, stop, or advance challenge")
@app_commands.describe(action="Action: start, stop, or phase2")
@app_commands.choices(action=[
    app_commands.Choice(name="start", value="start"),
    app_commands.Choice(name="stop", value="stop"),
    app_commands.Choice(name="phase2", value="phase2"),
])
async def challenge_command(interaction: discord.Interaction, action: str):
    """Control challenge tracking."""
    await interaction.response.defer()
    
    if action == "start":
        state = bot.risk_manager.start_challenge(phase=1)
        embed = discord.Embed(
            title="Challenge Started",
            description="Phase 1 challenge tracking has begun.",
            color=discord.Color.green()
        )
        embed.add_field(name="Phase", value="1", inline=True)
        embed.add_field(name="Target", value="8%", inline=True)
        embed.add_field(name="Balance", value=f"${state.current_balance:,.2f}", inline=True)
        
    elif action == "stop":
        bot.risk_manager.stop_challenge()
        embed = discord.Embed(
            title="Challenge Stopped",
            description="Challenge tracking has been stopped.",
            color=discord.Color.orange()
        )
        
    elif action == "phase2":
        bot.risk_manager.advance_to_phase2()
        embed = discord.Embed(
            title="Advanced to Phase 2",
            description="Phase 2 challenge tracking has begun.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Phase", value="2", inline=True)
        embed.add_field(name="Target", value="5%", inline=True)
        embed.add_field(name="Balance", value="$10,000.00", inline=True)
    
    else:
        embed = discord.Embed(
            title="Invalid Action",
            description="Use: start, stop, or phase2",
            color=discord.Color.red()
        )
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="output", description="View recent bot log output")
@app_commands.describe(lines="Number of lines to show (default: 50)")
async def output_command(interaction: discord.Interaction, lines: int = 50):
    """Show recent log output."""
    await interaction.response.defer()
    
    if not LOG_FILE.exists():
        await interaction.followup.send("No log file found.")
        return
    
    try:
        with open(LOG_FILE, 'r') as f:
            all_lines = f.readlines()
        
        recent_lines = all_lines[-lines:]
        output = "".join(recent_lines)
        
        if len(output) > 1900:
            output = output[-1900:]
            output = "...(truncated)\n" + output
        
        await interaction.followup.send(f"```\n{output}\n```")
        
    except Exception as e:
        await interaction.followup.send(f"Error reading log: {e}")


def _parse_period(period_str: str):
    """Parse period string like 'Jan 2024 - Dec 2024'."""
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    
    if "-" in period_str:
        parts = [p.strip() for p in period_str.split("-")]
        if len(parts) == 2:
            start_str, end_str = parts
            
            start_parts = start_str.lower().split()
            end_parts = end_str.lower().split()
            
            if len(start_parts) >= 2:
                start_month = month_map.get(start_parts[0][:3], 1)
                start_year = int(start_parts[1])
                if start_year < 100:
                    start_year += 2000
            else:
                start_month = 1
                start_year = int(start_str)
            
            if len(end_parts) >= 2:
                end_month = month_map.get(end_parts[0][:3], 12)
                end_year = int(end_parts[1])
                if end_year < 100:
                    end_year += 2000
            else:
                end_month = 12
                end_year = int(end_str)
            
            start_date = date(start_year, start_month, 1)
            
            if end_month == 12:
                end_date = date(end_year, 12, 31)
            else:
                end_date = date(end_year, end_month + 1, 1) - timedelta(days=1)
            
            return start_date, end_date
    
    return date(2024, 1, 1), date(2024, 12, 31)


@bot.tree.command(name="backtest", description="Run backtest simulation")
@app_commands.describe(
    period="Period like 'Jan 2024 - Dec 2024' or 'Dec 3 2024 - Dec 5 2024'",
    asset="Asset to backtest (optional, defaults to EURUSD)"
)
async def backtest_command(
    interaction: discord.Interaction,
    period: str,
    asset: str = "EUR_USD"
):
    """Run a backtest simulation using the same strategy as live trading."""
    await interaction.response.defer()
    
    try:
        symbol = asset.upper().replace("/", "_")
        if "_" not in symbol and len(symbol) == 6:
            symbol = f"{symbol[:3]}_{symbol[3:]}"
        
        embed = discord.Embed(
            title="Running Backtest...",
            description=f"Testing {symbol} for period: {period}",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)
        
        result = await asyncio.to_thread(run_backtest, symbol, period)
        
        result_embed = discord.Embed(
            title=f"Backtest Results: {symbol}",
            description=f"Period: {result.get('period', period)}",
            color=discord.Color.green() if result.get("net_return_pct", 0) > 0 else discord.Color.red()
        )
        
        result_embed.add_field(
            name="Total Trades",
            value=str(result.get("total_trades", 0)),
            inline=True
        )
        
        result_embed.add_field(
            name="Win Rate",
            value=f"{result.get('win_rate', 0):.1f}%",
            inline=True
        )
        
        result_embed.add_field(
            name="Net Return",
            value=f"{result.get('net_return_pct', 0):+.1f}%",
            inline=True
        )
        
        result_embed.add_field(
            name="Profit (USD)",
            value=f"${result.get('total_profit_usd', 0):+,.0f}",
            inline=True
        )
        
        result_embed.add_field(
            name="Max Drawdown",
            value=f"{result.get('max_drawdown_pct', 0):.1f}%",
            inline=True
        )
        
        result_embed.add_field(
            name="Avg R/Trade",
            value=f"{result.get('avg_rr', 0):+.2f}R",
            inline=True
        )
        
        exits = f"TP1+Trail: {result.get('tp1_trail_hits', 0)}, "
        exits += f"TP2: {result.get('tp2_hits', 0)}, "
        exits += f"TP3: {result.get('tp3_hits', 0)}, "
        exits += f"SL: {result.get('sl_hits', 0)}"
        
        result_embed.add_field(
            name="Exit Breakdown",
            value=exits,
            inline=False
        )
        
        await interaction.followup.send(embed=result_embed)
        
    except Exception as e:
        error_embed = discord.Embed(
            title="Backtest Error",
            description=str(e),
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=error_embed)


@bot.tree.command(name="help", description="Show available commands")
async def help_command(interaction: discord.Interaction):
    """Show help message."""
    embed = discord.Embed(
        title="Tradr Bot - Commands",
        description="Minimal Discord bot for monitoring the MT5 trading bot.",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="/status",
        value="View current challenge status (balance, profit, drawdown, trades)",
        inline=False
    )
    
    embed.add_field(
        name="/challenge <action>",
        value="Control challenge tracking:\n- `start` - Start Phase 1\n- `stop` - Stop tracking\n- `phase2` - Advance to Phase 2",
        inline=False
    )
    
    embed.add_field(
        name="/backtest <period> [asset]",
        value="Run backtest simulation\nExample: `/backtest \"Jan 2024 - Dec 2024\" EUR_USD`",
        inline=False
    )
    
    embed.add_field(
        name="/output [lines]",
        value="View recent bot log output (default: 50 lines)",
        inline=False
    )
    
    embed.set_footer(text="Note: This bot only monitors. Trading is handled by the standalone MT5 bot.")
    
    await interaction.response.send_message(embed=embed)


def main():
    """Entry point."""
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set in environment")
        print("")
        print("Add to .env file:")
        print("  DISCORD_BOT_TOKEN=your_token_here")
        sys.exit(1)
    
    print("[Discord] Starting minimal monitoring bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
