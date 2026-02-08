"""User command handlers (admin-only, DM-only commands)"""
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_USER_IDS
from bot.services.database import (
    get_bot_setting, get_all_settings, get_last_scan_log,
    get_scan_stats, get_recent_alerts, get_all_time_stats
)
from bot.services.bybit_api import fetch_tickers, get_bybit_category
from bot.services.price_monitor import get_scan_count, is_monitor_running
from bot.utils.formatters import format_volume
from bot.utils.logger import logger


def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    return user_id in ADMIN_USER_IDS


def is_private_chat(update: Update) -> bool:
    """Check if message is from a private chat (DM)"""
    return update.message.chat.type == 'private'


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start - Welcome message

    Admin only, DM only. Shows bot introduction and current settings.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

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

    Admin only, DM only. Lists all admin commands.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

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
/volume &lt;amount&gt; - Set min volume (both modes)
/volume1 &lt;amount&gt; - Set min volume for futures
/volume2 &lt;amount&gt; - Set min volume for spot
/pause - Pause scanner
/resume - Resume scanner
/resetsession - Force session reset (Model 1)

🎯 <b>Custom Threshold Commands:</b>
/btc 2% - BTC alerts every ±2%
/eth 3% - ETH alerts every ±3%
/&lt;symbol&gt; &lt;%&gt; - Set any symbol threshold
/listthresholds - Show all custom thresholds
/resetthreshold BTC - Reset to default

📊 <b>BTC/ETH Alert Mode:</b>
/percentage - Use percentage mode (±X%)
/milestone - Use milestone mode (price levels)
/btc 1000 - Set BTC milestone step ($1000)
/eth 100 - Set ETH milestone step ($100)
/cooldown &lt;min&gt; - Set milestone cooldown (default: 60)

🔬 <b>Sensor Fix (241):</b>
/241 on - Use 1h trend filter (catches dumps)
/241 off - Use 24h trend filter (original)
"""

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /status - Show bot status

    Admin only, DM only. Displays current configuration and all active settings.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

    settings = get_all_settings()
    mode = settings.get('mode', 'futures')
    model = settings.get('model', 'model2')
    paused = settings.get('paused', 'false') == 'true'

    # Volume settings
    vol_futures = float(settings.get('min_volume_futures', 25000000))
    vol_spot = float(settings.get('min_volume_spot', 25000000))

    # BTC/ETH alert settings
    btc_eth_mode = settings.get('btc_eth_alert_mode', 'percentage')
    btc_pct = settings.get('btc_percentage', '3')
    eth_pct = settings.get('eth_percentage', '2')
    btc_milestone = settings.get('btc_milestone', '1000')
    eth_milestone = settings.get('eth_milestone', '100')
    cooldown = settings.get('milestone_cooldown', '60')

    # 241 mode
    short_term = settings.get('short_term_trend', 'true')
    st_display = "ON" if short_term == 'true' else "OFF"

    # Status indicators
    if paused:
        status_emoji = "⏸️ PAUSED"
    elif is_monitor_running():
        status_emoji = "🟢 ACTIVE"
    else:
        status_emoji = "🔴 STOPPED"

    mode_display = "FUTURES" if mode == 'futures' else "SPOT"
    active_volume = format_volume(vol_futures) if mode == 'futures' else format_volume(vol_spot)

    message = f"""
🤖 <b>Bot Status</b>

<b>Scanner:</b> {status_emoji}
<b>Mode:</b> {mode_display}

📊 <b>Volume Settings</b>
▸ Futures: {format_volume(vol_futures)}
▸ Spot: {format_volume(vol_spot)}
▸ Active: {active_volume} ({mode})

💰 <b>BTC/ETH Alert Mode:</b> {btc_eth_mode.upper()}
🔬 <b>241 (1h Trend):</b> {st_display}
"""

    if btc_eth_mode == 'milestone':
        message += f"""▸ BTC: Every ${btc_milestone}
▸ ETH: Every ${eth_milestone}
▸ Cooldown: {cooldown} min
"""
    else:
        message += f"""▸ BTC: Every ±{btc_pct}%
▸ ETH: Every ±{eth_pct}%
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
                time_ago = f"{int(diff.total_seconds())}s ago"
            elif diff.total_seconds() < 3600:
                time_ago = f"{int(diff.total_seconds() / 60)}m ago"
            else:
                time_ago = f"{int(diff.total_seconds() / 3600)}h ago"

            message += f"""
📈 <b>Last Scan:</b> {time_ago}
▸ Pairs: {last_scan['pairs_scanned']} | Alerts: {last_scan['alerts_sent']}
"""

    # Get all-time stats (persistent)
    all_time = get_all_time_stats()
    if all_time['total_alerts'] > 0:
        message += f"""
📊 <b>All-Time Stats</b>
▸ Total Alerts: {all_time['total_alerts']:,}
▸ Days Active: {all_time['days_active']}
▸ Avg/Day: {all_time['avg_per_day']}
"""

    await update.message.reply_text(message.strip(), parse_mode='HTML')


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats - Alert statistics

    Admin only, DM only. Shows recent alerts and top gainers/losers.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

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

    Admin only, DM only. Lists top pairs by volume that meet the minimum threshold.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    # Admin check
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only")
        return

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
