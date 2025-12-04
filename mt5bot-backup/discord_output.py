"""
Discord embed formatting for Blueprint Trader AI.

Provides clean, professional Discord embeds for:
- New trade setups
- Trade activations
- Trade updates (TP/SL hits)
- Trade closes

Uses 5%ers 100K High Stakes risk model for lot sizing.
"""

import discord
import hashlib
from datetime import datetime
from typing import Optional, List

from config import ACCOUNT_SIZE, RISK_PER_TRADE_PCT
from position_sizing import (
    calculate_position_size_5ers,
    calculate_rr_values,
    format_lot_size_display,
    format_risk_display,
)


COLOR_LONG = 0x00C853
COLOR_SHORT = 0xFF1744
COLOR_NEUTRAL = 0x607D8B
COLOR_SUCCESS = 0x00E676
COLOR_WARNING = 0xFFAB00
COLOR_ERROR = 0xF44336


def generate_trade_id(symbol: str, direction: str, timestamp: Optional[datetime] = None) -> str:
    """Generate a short unique trade ID."""
    ts = timestamp or datetime.utcnow()
    data = f"{symbol}_{direction}_{ts.isoformat()}"
    return hashlib.md5(data.encode()).hexdigest()[:8].upper()


def create_setup_embed(
    symbol: str,
    direction: str,
    timeframe: str,
    entry: float,
    stop_loss: float,
    tp1: float = None,
    tp2: float = None,
    tp3: float = None,
    confluence_score: int = 0,
    confluence_items: List[str] = None,
    description: str = None,
    account_size: float = ACCOUNT_SIZE,
    risk_pct: float = RISK_PER_TRADE_PCT,
    entry_datetime: Optional[datetime] = None,
) -> discord.Embed:
    """
    Create a professional embed for a new trade setup.

    Args:
        symbol: Trading instrument (e.g., "EUR_USD")
        direction: "bullish", "bearish", "long", or "short"
        timeframe: Chart timeframe (e.g., "H4")
        entry: Entry price
        stop_loss: Stop loss price
        tp1, tp2, tp3: Take profit levels
        confluence_score: Score out of 7
        confluence_items: List of confluence factors
        description: Brief trade description
        account_size: Account balance for sizing
        risk_pct: Risk percentage per trade

    Returns:
        discord.Embed object ready to send
    """
    is_long = direction.lower() in ("bullish", "long")
    emoji = "🟢" if is_long else "🔴"
    dir_text = "LONG" if is_long else "SHORT"
    color = COLOR_LONG if is_long else COLOR_SHORT

    display_symbol = symbol.replace("_", "/")
    title = f"{emoji} {display_symbol} {dir_text} ({timeframe})"

    desc = description or f"Trade setup identified with {confluence_score}/7 confluence."

    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=entry_datetime or datetime.utcnow()
    )

    sizing = calculate_position_size_5ers(
        symbol=symbol,
        entry_price=entry,
        stop_price=stop_loss,
        account_size=account_size,
        risk_pct=risk_pct,
    )

    rr_values = calculate_rr_values(
        entry=entry,
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        direction=direction,
    )

    stop_pips = sizing.get("stop_pips", 0)

    entry_date_str = (entry_datetime or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    levels_text = f"**Entry Date:** {entry_date_str}\n"
    levels_text += f"**Entry:** {entry:.5f}\n"
    levels_text += f"**Stoploss:** {stop_loss:.5f}  ({stop_pips:.1f} pips)\n"
    if tp1:
        levels_text += f"**TP1:** {tp1:.5f}  ({rr_values['tp1_rr']:.2f}R)\n"
    if tp2:
        levels_text += f"**TP2:** {tp2:.5f}  ({rr_values['tp2_rr']:.2f}R)\n"
    if tp3:
        levels_text += f"**TP3:** {tp3:.5f}  ({rr_values['tp3_rr']:.2f}R)"

    embed.add_field(
        name="Entry & Levels",
        value=levels_text,
        inline=False
    )

    risk_text = f"**Account:** ${account_size:,.0f} (High Stakes)\n"
    risk_text += f"**Risk:** {sizing['risk_pct']*100:.2f}%  |  ${sizing['risk_usd']:,.0f}\n"
    risk_text += f"**Lot size:** {sizing['lot_size']:.2f} lots"

    embed.add_field(
        name="Risk & Lot Size (100K 5%ers)",
        value=risk_text,
        inline=False
    )

    if confluence_items and len(confluence_items) > 0:
        conf_text = "\n".join([f"• {item}" for item in confluence_items[:5]])
        embed.add_field(
            name=f"Confluence ({confluence_score}/7)",
            value=conf_text,
            inline=False
        )

    trade_id = generate_trade_id(symbol, direction)
    embed.set_footer(text=f"Blueprint Trader AI • ID: {trade_id} • Backtested with 5%ers 100K risk settings")

    return embed


def create_activation_embed(
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    lot_size: float,
    risk_usd: float,
    risk_pct: float,
    trade_id: str = None,
    entry_datetime: Optional[datetime] = None,
) -> discord.Embed:
    """Create embed for trade activation (order filled)."""
    is_long = direction.lower() == "bullish"
    emoji = "🟢" if is_long else "🔴"
    dir_text = "LONG" if is_long else "SHORT"

    display_symbol = symbol.replace("_", "/")
    title = f"✅ Trade Activated - {display_symbol} {dir_text}"

    embed = discord.Embed(
        title=title,
        color=COLOR_SUCCESS,
        timestamp=entry_datetime or datetime.utcnow()
    )

    entry_date_str = (entry_datetime or datetime.utcnow()).strftime("%Y-%m-%d %H:%M UTC")
    embed.add_field(name="Entry Date", value=entry_date_str, inline=True)
    embed.add_field(name="Entry", value=f"{entry:.5f}", inline=True)
    embed.add_field(name="Stop Loss", value=f"{stop_loss:.5f}", inline=True)

    embed.add_field(
        name="Risk",
        value=f"${risk_usd:,.0f} ({risk_pct*100:.2f}%)",
        inline=True
    )
    embed.add_field(name="Lot Size", value=f"{lot_size:.2f}", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    if trade_id:
        embed.set_footer(text=f"Trade ID: {trade_id}")

    return embed


def create_tp_hit_embed(
    symbol: str,
    direction: str,
    tp_level: int,
    tp_price: float,
    realized_usd: float,
    realized_pct: float,
    realized_r: float,
    remaining_pct: float,
    remaining_lots: float,
    current_sl: Optional[float] = None,
    moved_to_be: bool = False,
    entry_datetime: Optional[datetime] = None,
) -> discord.Embed:
    """Create embed for TP hit notification."""
    color = 0x00FF00  # Green

    direction_emoji = "📈" if direction.lower() in ("bullish", "long") else "📉"
    direction_text = "LONG" if direction.lower() in ("bullish", "long") else "SHORT"

    display_symbol = symbol.replace("_", "/")
    title = f"🎯 TP{tp_level} Hit - {display_symbol} {direction_text}"

    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.utcnow()
    )

    if entry_datetime:
        entry_date_str = entry_datetime.strftime("%Y-%m-%d %H:%M UTC")
        embed.add_field(name="Entered", value=entry_date_str, inline=False)

    embed.add_field(name=f"TP{tp_level}", value=f"{tp_price:.5f}", inline=True)

    # Format profit with explicit + sign only if positive
    profit_text = f"${realized_usd:,.0f}  ({realized_pct:.2f}%, {realized_r:.2f}R)"
    if realized_usd >= 0:
        profit_text = f"+{profit_text}"
    embed.add_field(name="Realized", value=profit_text, inline=True)

    if remaining_pct < 100:
        embed.add_field(
            name="Remaining",
            value=f"{remaining_pct:.0f}% position",
            inline=True
        )

    if moved_to_be and current_sl:
        embed.add_field(
            name="Stop Loss",
            value=f"Moved to BE ({current_sl:.5f})",
            inline=True
        )

    if remaining_lots is not None:
        embed.add_field(
            name="Lots Remaining",
            value=f"{remaining_lots:.2f}",
            inline=True
        )

    return embed


def create_sl_hit_embed(
    symbol: str,
    direction: str,
    sl_price: float,
    result_usd: float,
    result_pct: float,
    result_r: float,
    daily_pnl_usd: float = None,
    daily_pnl_pct: float = None,
    entry_datetime: Optional[datetime] = None,
) -> discord.Embed:
    """Create embed for stop loss hit."""
    display_symbol = symbol.replace("_", "/")
    is_long = direction.lower() == "bullish"
    dir_text = "LONG" if is_long else "SHORT"

    title = f"🛑 Stoploss Hit - {display_symbol} {dir_text}"

    embed = discord.Embed(
        title=title,
        color=COLOR_ERROR,
        timestamp=datetime.utcnow()
    )

    if entry_datetime:
        entry_date_str = entry_datetime.strftime("%Y-%m-%d %H:%M UTC")
        embed.add_field(name="Entered", value=entry_date_str, inline=False)

    embed.add_field(name="SL", value=f"{sl_price:.5f}", inline=True)

    result_text = f"${result_usd:,.0f}  ({result_pct:.2f}%, {result_r:.2f}R)"
    embed.add_field(name="Result", value=result_text, inline=True)

    if daily_pnl_usd is not None:
        daily_text = f"${daily_pnl_usd:,.0f}  ({daily_pnl_pct:.2f}%)"
        status = "Within limits" if abs(daily_pnl_pct) < 5.0 else "Near 5% limit"
        embed.add_field(
            name="Daily P/L",
            value=f"{daily_text}\n{status}",
            inline=False
        )

    return embed


def create_trade_closed_embed(
    symbol: str,
    direction: str,
    avg_exit: float,
    total_result_usd: float,
    total_result_pct: float,
    total_result_r: float,
    exit_reason: str = "Manual",
    daily_pnl_usd: float = None,
    daily_pnl_pct: float = None,
    entry_datetime: Optional[datetime] = None,
) -> discord.Embed:
    """Create embed for trade closed."""
    display_symbol = symbol.replace("_", "/")
    is_long = direction.lower() == "bullish"
    dir_text = "LONG" if is_long else "SHORT"

    is_winner = total_result_usd > 0
    emoji = "✅" if is_winner else "❌"
    color = COLOR_SUCCESS if is_winner else COLOR_ERROR

    title = f"{emoji} Trade Closed - {display_symbol} {dir_text}"

    embed = discord.Embed(
        title=title,
        color=color,
        timestamp=datetime.utcnow()
    )

    if entry_datetime:
        entry_date_str = entry_datetime.strftime("%Y-%m-%d %H:%M UTC")
        embed.add_field(name="Entered", value=entry_date_str, inline=False)

    embed.add_field(name="Exit Price", value=f"{avg_exit:.5f}", inline=True)
    embed.add_field(name="Exit Reason", value=exit_reason, inline=True)

    sign = "+" if total_result_usd >= 0 else ""
    result_text = f"{sign}${total_result_usd:,.0f}  ({sign}{total_result_pct:.2f}%, {sign}{total_result_r:.2f}R)"
    embed.add_field(name="Total Result", value=result_text, inline=False)

    if daily_pnl_usd is not None:
        daily_sign = "+" if daily_pnl_usd >= 0 else ""
        daily_text = f"{daily_sign}${daily_pnl_usd:,.0f}  ({daily_sign}{daily_pnl_pct:.2f}%)"
        embed.add_field(name="Day P/L", value=daily_text, inline=True)

    return embed


def create_backtest_embed(
    asset: str,
    period: str,
    total_trades: int,
    win_rate: float,
    total_profit_usd: float,
    total_profit_pct: float,
    max_drawdown_pct: float,
    tp1_hits: int,
    tp2_hits: int,
    tp3_hits: int,
    sl_hits: int,
    avg_rr: float = 0.0,
    account_size: float = ACCOUNT_SIZE,
) -> discord.Embed:
    """Create embed for backtest results."""
    display_asset = asset.replace("_", "/")

    is_profitable = total_profit_usd > 0
    color = COLOR_SUCCESS if is_profitable else COLOR_ERROR
    profit_emoji = "📈" if is_profitable else "📉"

    title = f"📊 Backtest Results - {display_asset}"

    embed = discord.Embed(
        title=title,
        description=f"Period: {period} | Account: ${account_size:,.0f} (5%ers High Stakes)",
        color=color,
        timestamp=datetime.utcnow()
    )

    wr_emoji = "🎯" if win_rate >= 70 else "📊" if win_rate >= 50 else "⚠️"

    sign = "+" if total_profit_usd >= 0 else ""
    perf_text = f"{profit_emoji} **Total Profit:** {sign}${total_profit_usd:,.0f} ({sign}{total_profit_pct:.1f}%)\n"
    perf_text += f"{wr_emoji} **Win Rate:** {win_rate:.1f}%\n"
    perf_text += f"📉 **Max Drawdown:** {max_drawdown_pct:.1f}%\n"
    perf_text += f"📈 **Avg R/Trade:** {avg_rr:.2f}R"

    embed.add_field(name="Performance", value=perf_text, inline=False)

    tp1_trail = tp1_hits
    exit_text = f"**Trades:** {total_trades}\n"
    exit_text += f"TP1+Trail: {tp1_trail} | TP2: {tp2_hits} | TP3: {tp3_hits}\n"
    exit_text += f"SL: {sl_hits}"

    embed.add_field(name="Exit Breakdown", value=exit_text, inline=False)

    embed.set_footer(text="Blueprint Trader AI • 5%ers 100K Risk Model • 1% risk per trade")

    return embed


def build_confluence_list(scan_result) -> List[str]:
    """Build confluence list from scan result for embed."""
    items = []

    if scan_result.htf_bias and ("alignment" in scan_result.htf_bias.lower() or "reversal" in scan_result.htf_bias.lower()):
        items.append(f"HTF: {scan_result.htf_bias[:50]}")

    if scan_result.location_note and "score:" in scan_result.location_note:
        items.append(f"S/R: {scan_result.location_note[:50]}")

    if scan_result.fib_note and "retracement" in scan_result.fib_note.lower():
        items.append(f"Fib: {scan_result.fib_note[:50]}")

    if scan_result.liquidity_note:
        liq = scan_result.liquidity_note.lower()
        if "sweep" in liq or "equal" in liq:
            items.append(f"Liquidity: {scan_result.liquidity_note[:50]}")

    if scan_result.structure_note:
        items.append(f"Structure: {scan_result.structure_note[:50]}")

    return items[:5]