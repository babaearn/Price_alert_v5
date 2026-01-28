"""User command handlers (public commands)"""
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.database import (
    get_bot_setting, get_all_settings, get_last_scan_log,
    get_scan_stats, get_recent_alerts
)
from bot.services.bybit_api import fetch_tickers, get_bybit_category
from bot.services.price_monitor import get_scan_count, is_monitor_running
from bot.utils.formatters import format_volume
from bot.utils.logger import logger


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start - Welcome message

    Shows bot introduction and current settings.
    """
    settings = get_all_settings()
    mode = settings.get('mode', 'futures')
    model = settings.get('model', 'model2')
    min_volume = float(settings.get('min_volume_usd', 5000000))
    scan_interval = settings.get('scan_interval', '30')

    model_display = "Rolling 24H (Bybit Default)" if model == 'model2' else "Session-Based (00:00 UTC)"

    message = f"""
🤖 <b>Welcome to Bybit Price Alert Bot!</b>

I monitor 475+ crypto pairs and send alerts when prices pump or dump!

📊 <b>Current Mode:</b> {mode.title()}
📈 <b>Model:</b> {model_display}
🎯 <b>Min Volume:</b> {format_volume(min_volume)}
⏱️ <b>Scan Interval:</b> {scan_interval}s

Use /help to see available commands.
"""

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help - Show available commands

    Lists all user and admin commands.
    """
    message = """
📖 <b>Available Commands</b>

👥 <b>User Commands:</b>
/start - Welcome message
/help - Show this help
/status - Bot status
/stats - Alert statistics
/listpairs - Show monitored pairs

🔐 <b>Admin Commands:</b>
/mode &lt;futures|spot&gt; - Switch market mode
/model1 - Session-based (00:00 UTC reset)
/model2 - Rolling 24h window (default)
/volume &lt;amount&gt; - Set min volume filter
/pause - Pause scanner
/resume - Resume scanner
/resetsession - Force session reset (Model 1)
"""

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status - Show bot status

    Displays current configuration and last scan info.
    """
    settings = get_all_settings()
    mode = settings.get('mode', 'futures')
    model = settings.get('model', 'model2')
    min_volume = float(settings.get('min_volume_usd', 5000000))
    scan_interval = settings.get('scan_interval', '30')
    paused = settings.get('paused', 'false') == 'true'

    # Status indicators
    if paused:
        status_emoji = "⏸️ PAUSED"
    elif is_monitor_running():
        status_emoji = "🔄 ACTIVE"
    else:
        status_emoji = "❌ STOPPED"

    mode_display = "Futures (Linear)" if mode == 'futures' else "Spot"
    model_display = "Model 1 (Session-Based)" if model == 'model1' else "Model 2 (Rolling 24H)"

    message = f"""
🤖 <b>Bot Status</b>

🔄 Scanner: <b>{status_emoji}</b>
📊 Mode: <b>{mode_display}</b>
📈 Model: <b>{model_display}</b>
🎯 Min Volume: <b>{format_volume(min_volume)}</b>
⏱️ Scan Interval: <b>{scan_interval} seconds</b>
"""

    # Get last scan info
    last_scan = get_last_scan_log()
    if last_scan:
        scan_time = last_scan['created_at']
        if scan_time:
            # Calculate time ago
            now = datetime.utcnow()
            diff = now - scan_time
            if diff.total_seconds() < 60:
                time_ago = f"{int(diff.total_seconds())} seconds ago"
            elif diff.total_seconds() < 3600:
                time_ago = f"{int(diff.total_seconds() / 60)} minutes ago"
            else:
                time_ago = f"{int(diff.total_seconds() / 3600)} hours ago"

            message += f"""
📈 <b>Last Scan:</b>
- Time: {time_ago}
- Pairs: {last_scan['pairs_scanned']}
- Alerts: {last_scan['alerts_sent']}
- Duration: {last_scan['duration_ms']}ms
"""

    # Get 24h stats
    stats = get_scan_stats(24)
    if stats['total_scans'] > 0:
        message += f"""
📊 <b>Today's Stats:</b>
- Total Scans: {stats['total_scans']:,}
- Alerts Sent: {stats['total_alerts']:,}
- Errors: {stats['total_errors']:,}
"""

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats - Alert statistics

    Shows recent alerts and top gainers/losers.
    """
    # Get recent alerts
    alerts = get_recent_alerts(24)

    if not alerts:
        message = """
📊 <b>Alert Statistics (Last 24h)</b>

No alerts sent in the last 24 hours.
"""
        await update.message.reply_text(message.strip(), parse_mode='HTML')
        return

    # Categorize alerts
    gainers = {}
    losers = {}

    for alert in alerts:
        symbol = alert['symbol']
        pct = float(alert['pct_change_at_detection'])

        if pct > 0:
            if symbol not in gainers:
                gainers[symbol] = {'pct': pct, 'count': 0}
            gainers[symbol]['count'] += 1
            if pct > gainers[symbol]['pct']:
                gainers[symbol]['pct'] = pct
        else:
            if symbol not in losers:
                losers[symbol] = {'pct': pct, 'count': 0}
            losers[symbol]['count'] += 1
            if pct < losers[symbol]['pct']:
                losers[symbol]['pct'] = pct

    # Sort by percentage
    top_gainers = sorted(gainers.items(), key=lambda x: x[1]['pct'], reverse=True)[:5]
    top_losers = sorted(losers.items(), key=lambda x: x[1]['pct'])[:5]

    message = "📊 <b>Alert Statistics (Last 24h)</b>\n\n"

    if top_gainers:
        message += "🚀 <b>Top Gainers:</b>\n"
        for i, (symbol, data) in enumerate(top_gainers, 1):
            message += f"{i}. {symbol}: +{data['pct']:.2f}% → {data['count']} alert(s)\n"
        message += "\n"

    if top_losers:
        message += "📉 <b>Top Losers:</b>\n"
        for i, (symbol, data) in enumerate(top_losers, 1):
            message += f"{i}. {symbol}: {data['pct']:.2f}% → {data['count']} alert(s)\n"
        message += "\n"

    total_alerts = len(alerts)
    message += f"📈 <b>Total Alerts:</b> {total_alerts}"

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_listpairs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listpairs - Show monitored pairs

    Lists top pairs by volume that meet the minimum threshold.
    """
    mode = get_bot_setting('mode') or 'futures'
    category = get_bybit_category(mode)
    min_volume = float(get_bot_setting('min_volume_usd') or 5000000)

    # Fetch tickers
    tickers = fetch_tickers(category)

    if not tickers:
        await update.message.reply_text("❌ Failed to fetch pairs from Bybit")
        return

    # Filter and sort by volume
    filtered = []
    for t in tickers:
        try:
            volume = float(t.get('turnover24h', 0))
            if volume >= min_volume:
                filtered.append({
                    'symbol': t['symbol'],
                    'volume': volume
                })
        except (ValueError, TypeError):
            continue

    filtered.sort(key=lambda x: x['volume'], reverse=True)

    message = f"📋 <b>Monitored Pairs</b> ({len(filtered)} total)\n\n"
    message += "🔝 <b>Top by Volume:</b>\n"

    for i, pair in enumerate(filtered[:15], 1):
        message += f"{i}. {pair['symbol']}: {format_volume(pair['volume'])} (24h)\n"

    if len(filtered) > 15:
        message += f"\n... and {len(filtered) - 15} more pairs"

    message += f"\n\n💡 Showing pairs with >{format_volume(min_volume)} volume\n"
    message += "Use /volume to change filter"

    await update.message.reply_text(message.strip(), parse_mode='HTML')
