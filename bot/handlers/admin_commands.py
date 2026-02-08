"""Admin command handlers (restricted commands)"""
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_USER_IDS, BASE_THRESHOLDS
from bot.services.database import (
    get_bot_setting, set_bot_setting,
    set_custom_thresholds, delete_custom_thresholds, get_all_custom_thresholds
)
from bot.services.session_manager import force_reset_sessions
from bot.utils.validators import is_valid_mode, parse_volume_amount
from bot.utils.formatters import format_volume
from bot.utils.logger import logger


def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    return user_id in ADMIN_USER_IDS


def is_private_chat(update: Update) -> bool:
    """Check if message is from a private chat (DM)"""
    return update.message.chat.type == 'private'


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mode <futures|spot> - Switch market mode

    Admin only, DM only. Switches between futures and spot markets.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    if not context.args or len(context.args) != 1:
        current_mode = get_bot_setting('mode')
        await update.message.reply_text(
            f"Current mode: <b>{current_mode}</b>\n\n"
            f"Usage: /mode &lt;futures|spot&gt;",
            parse_mode='HTML'
        )
        return

    new_mode = context.args[0].lower()

    if not is_valid_mode(new_mode):
        await update.message.reply_text("❌ Invalid mode. Use: futures or spot")
        return

    set_bot_setting('mode', new_mode, str(user_id))

    await update.message.reply_text(
        f"✅ Mode switched to: <b>{new_mode.upper()}</b>\n"
        f"Now monitoring {new_mode} markets on Bybit",
        parse_mode='HTML'
    )

    logger.info(f"Mode changed to {new_mode} by user {user_id}")


async def cmd_model1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /model1 - Switch to session-based calculation

    Admin only, DM only. Sets calculation model to session-based (00:00 UTC reset).
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('model', 'model1', str(user_id))

    await update.message.reply_text(
        "✅ Switched to <b>MODEL 1</b>\n\n"
        "📊 <b>Session-Based Calculation</b>\n"
        "- Reference: Price at 00:00 UTC\n"
        "- Reset: Daily at midnight UTC\n"
        "- Alerts: Once per threshold per day\n\n"
        "Use /resetsession to manually reset reference prices.",
        parse_mode='HTML'
    )

    logger.info(f"Model changed to model1 by user {user_id}")


async def cmd_model2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /model2 - Switch to rolling 24h calculation

    Admin only, DM only. Sets calculation model to rolling 24-hour window (Bybit default).
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('model', 'model2', str(user_id))

    await update.message.reply_text(
        "✅ Switched to <b>MODEL 2</b> (Default)\n\n"
        "📊 <b>Rolling 24H Window</b>\n"
        "- Reference: Price 24 hours ago\n"
        "- Updates: Continuously as time moves\n"
        "- Alerts: Once per 24h from first detection\n\n"
        "This matches Bybit's gainer/loser calculation.",
        parse_mode='HTML'
    )

    logger.info(f"Model changed to model2 by user {user_id}")


async def cmd_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /volume <amount> - Set minimum volume filter

    Admin only, DM only. Sets minimum 24h trading volume threshold.
    Supports formats: 5M, 5000000, $5M
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    if not context.args or len(context.args) != 1:
        current_volume = float(get_bot_setting('min_volume_usd') or 5000000)
        await update.message.reply_text(
            f"Current min volume: <b>{format_volume(current_volume)}</b>\n\n"
            f"Usage: /volume &lt;amount&gt;\n"
            f"Example: /volume 10M or /volume 5000000",
            parse_mode='HTML'
        )
        return

    amount = parse_volume_amount(context.args[0])

    if amount is None or amount < 0:
        await update.message.reply_text(
            "❌ Invalid amount. Use: 5M or 5000000\n"
            "Supported suffixes: K (thousands), M (millions), B (billions)"
        )
        return

    set_bot_setting('min_volume_usd', str(int(amount)), str(user_id))

    await update.message.reply_text(
        f"✅ Volume filter updated\n"
        f"Min 24h Volume: <b>{format_volume(amount)}</b>",
        parse_mode='HTML'
    )

    logger.info(f"Volume changed to {amount} by user {user_id}")


async def cmd_volume1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /volume1 <amount> - Set minimum volume filter for FUTURES

    Admin only, DM only. Sets minimum 24h trading volume threshold for futures mode.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    if not context.args or len(context.args) != 1:
        current_volume = float(get_bot_setting('min_volume_futures') or 25000000)
        await update.message.reply_text(
            f"📊 <b>Futures Volume Filter</b>\n\n"
            f"Current: <b>{format_volume(current_volume)}</b>\n\n"
            f"Usage: /volume1 &lt;amount&gt;\n"
            f"Example: /volume1 25M",
            parse_mode='HTML'
        )
        return

    amount = parse_volume_amount(context.args[0])

    if amount is None or amount < 0:
        await update.message.reply_text(
            "❌ Invalid amount. Use: 25M or 25000000\n"
            "Supported suffixes: K, M, B"
        )
        return

    set_bot_setting('min_volume_futures', str(int(amount)), str(user_id))

    await update.message.reply_text(
        f"✅ <b>Futures</b> volume filter updated\n"
        f"Min 24h Volume: <b>{format_volume(amount)}</b>",
        parse_mode='HTML'
    )

    logger.info(f"Futures volume changed to {amount} by user {user_id}")


async def cmd_volume2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /volume2 <amount> - Set minimum volume filter for SPOT

    Admin only, DM only. Sets minimum 24h trading volume threshold for spot mode.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    if not context.args or len(context.args) != 1:
        current_volume = float(get_bot_setting('min_volume_spot') or 25000000)
        await update.message.reply_text(
            f"📊 <b>Spot Volume Filter</b>\n\n"
            f"Current: <b>{format_volume(current_volume)}</b>\n\n"
            f"Usage: /volume2 &lt;amount&gt;\n"
            f"Example: /volume2 25M",
            parse_mode='HTML'
        )
        return

    amount = parse_volume_amount(context.args[0])

    if amount is None or amount < 0:
        await update.message.reply_text(
            "❌ Invalid amount. Use: 25M or 25000000\n"
            "Supported suffixes: K, M, B"
        )
        return

    set_bot_setting('min_volume_spot', str(int(amount)), str(user_id))

    await update.message.reply_text(
        f"✅ <b>Spot</b> volume filter updated\n"
        f"Min 24h Volume: <b>{format_volume(amount)}</b>",
        parse_mode='HTML'
    )

    logger.info(f"Spot volume changed to {amount} by user {user_id}")


async def cmd_percentage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /percentage - Switch BTC/ETH to percentage-based alerts

    Admin only, DM only. Switches BTC and ETH alerts to percentage mode.
    BTC: every ±3%, ETH: every ±2%
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('btc_eth_alert_mode', 'percentage', str(user_id))

    btc_pct = get_bot_setting('btc_percentage') or '3'
    eth_pct = get_bot_setting('eth_percentage') or '2'

    await update.message.reply_text(
        f"✅ <b>Percentage Mode Activated</b>\n\n"
        f"📊 BTC/ETH alerts now use percentage thresholds:\n\n"
        f"• <b>BTC:</b> Every ±{btc_pct}%\n"
        f"  (±{btc_pct}%, ±{int(btc_pct)*2}%, ±{int(btc_pct)*3}%, ...)\n\n"
        f"• <b>ETH:</b> Every ±{eth_pct}%\n"
        f"  (±{eth_pct}%, ±{int(eth_pct)*2}%, ±{int(eth_pct)*3}%, ...)\n\n"
        f"Use /btc &lt;%&gt; or /eth &lt;%&gt; to change percentage.",
        parse_mode='HTML'
    )

    logger.info(f"BTC/ETH alert mode changed to percentage by user {user_id}")


async def cmd_milestone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /milestone - Switch BTC/ETH to price milestone alerts

    Admin only, DM only. Switches BTC and ETH alerts to milestone mode.
    BTC: every $1000 (90000, 91000, 92000), ETH: every $100 (3100, 3200, 3300)
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('btc_eth_alert_mode', 'milestone', str(user_id))

    btc_milestone = get_bot_setting('btc_milestone') or '1000'
    eth_milestone = get_bot_setting('eth_milestone') or '100'

    await update.message.reply_text(
        f"✅ <b>Milestone Mode Activated</b>\n\n"
        f"📊 BTC/ETH alerts now use price milestones:\n\n"
        f"• <b>BTC:</b> Every ${btc_milestone}\n"
        f"  ($90,000, $91,000, $92,000, ...)\n\n"
        f"• <b>ETH:</b> Every ${eth_milestone}\n"
        f"  ($3,100, $3,200, $3,300, ...)\n\n"
        f"Use /btc &lt;$&gt; or /eth &lt;$&gt; to change milestone.",
        parse_mode='HTML'
    )

    logger.info(f"BTC/ETH alert mode changed to milestone by user {user_id}")


async def cmd_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cooldown <minutes> - Set milestone alert cooldown

    Admin only, DM only. Sets the cooldown period between same milestone alerts.
    Prevents spam when price oscillates around a level.
    Default: 60 minutes
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    current_cooldown = get_bot_setting('milestone_cooldown') or '60'

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            f"⏱️ <b>Milestone Cooldown</b>\n\n"
            f"Current: <b>{current_cooldown} minutes</b>\n\n"
            f"This prevents spam when BTC/ETH price oscillates around a milestone.\n\n"
            f"<b>Usage:</b> /cooldown &lt;minutes&gt;\n"
            f"<b>Examples:</b>\n"
            f"• /cooldown 30 - 30 minutes\n"
            f"• /cooldown 60 - 1 hour (default)\n"
            f"• /cooldown 120 - 2 hours",
            parse_mode='HTML'
        )
        return

    try:
        minutes = int(context.args[0])

        if minutes < 5:
            await update.message.reply_text("❌ Minimum cooldown is 5 minutes")
            return

        if minutes > 1440:
            await update.message.reply_text("❌ Maximum cooldown is 1440 minutes (24 hours)")
            return

        set_bot_setting('milestone_cooldown', str(minutes), str(user_id))

        # Format display
        if minutes >= 60:
            hours = minutes / 60
            display = f"{hours:.1f} hour{'s' if hours != 1 else ''}"
        else:
            display = f"{minutes} minutes"

        await update.message.reply_text(
            f"✅ <b>Milestone Cooldown Updated</b>\n\n"
            f"⏱️ New cooldown: <b>{display}</b>\n\n"
            f"Same milestone won't alert again for {display}.",
            parse_mode='HTML'
        )

        logger.info(f"Milestone cooldown changed to {minutes}min by user {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid number. Use: /cooldown 60")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pause - Pause the price scanner

    Admin only, DM only. Stops price monitoring and alert generation.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('paused', 'true', str(user_id))

    await update.message.reply_text(
        "⏸️ Scanner <b>PAUSED</b>\n\n"
        "No price monitoring or alerts until resumed.\n"
        "Use /resume to continue.",
        parse_mode='HTML'
    )

    logger.info(f"Scanner paused by user {user_id}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resume - Resume the price scanner

    Admin only, DM only. Resumes price monitoring and alert generation.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    set_bot_setting('paused', 'false', str(user_id))

    await update.message.reply_text(
        "▶️ Scanner <b>RESUMED</b>\n\n"
        "Price monitoring active.",
        parse_mode='HTML'
    )

    logger.info(f"Scanner resumed by user {user_id}")


async def cmd_resetsession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resetsession - Force session reset

    Admin only, DM only. Resets all session prices to current prices (Model 1 only).
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    current_model = get_bot_setting('model')

    if current_model != 'model1':
        await update.message.reply_text(
            "⚠️ This command only works in <b>MODEL 1</b>\n"
            "Use /model1 to switch first.",
            parse_mode='HTML'
        )
        return

    await update.message.reply_text("⏳ Resetting session prices...")

    reset_count = force_reset_sessions()

    await update.message.reply_text(
        f"✅ Session reset complete\n"
        f"Updated <b>{reset_count}</b> pairs to current prices",
        parse_mode='HTML'
    )

    logger.info(f"Session reset by user {user_id}: {reset_count} pairs")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /admin - Show admin status

    DM only. Shows whether user is an admin and current admin list.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id
    is_user_admin = is_admin(user_id)

    if is_user_admin:
        await update.message.reply_text(
            f"✅ You are an admin\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Admin count: {len(ADMIN_USER_IDS)}",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"❌ You are not an admin\n"
            f"Your User ID: <code>{user_id}</code>",
            parse_mode='HTML'
        )


async def cmd_241(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /241 <on|off> - Toggle short-term trend filter for milestone alerts

    Admin only, DM only. When ON, uses 1h price trend instead of 24h to filter
    milestone direction. Prevents false "BREAKS" alerts during dumps and
    false "DROPS TO" alerts during pumps.

    Name "241" = dual timeframe (24h + 1h).
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    current = get_bot_setting('short_term_trend') or 'true'

    if not context.args:
        status = "ON" if current == 'true' else "OFF"
        await update.message.reply_text(
            f"🔬 <b>241 - Short-Term Trend Filter</b>\n\n"
            f"Status: <b>{status}</b>\n\n"
            f"When ON: Uses 1h price trend to filter milestone\n"
            f"direction instead of 24h. Prevents false BREAKS\n"
            f"alerts during dumps and false DROPS during pumps.\n\n"
            f"<b>Usage:</b> /241 on | /241 off",
            parse_mode='HTML'
        )
        return

    arg = context.args[0].lower()

    if arg not in ('on', 'off'):
        await update.message.reply_text("❌ Usage: /241 on or /241 off")
        return

    new_value = 'true' if arg == 'on' else 'false'
    set_bot_setting('short_term_trend', new_value, str(user_id))

    status = "ON" if new_value == 'true' else "OFF"

    if arg == 'on':
        desc = "Using 1h trend for milestone direction filter."
    else:
        desc = "Using 24h trend for milestone direction filter (default behavior)."

    await update.message.reply_text(
        f"✅ <b>241 Mode: {status}</b>\n\n"
        f"{desc}",
        parse_mode='HTML'
    )

    logger.info(f"241 mode set to {arg} by user {user_id}")


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /time <minutes> - Set milestone lock period

    Admin only, DM only. After ANY milestone alert fires (BREAKS or DROPS),
    that milestone is locked for this many minutes. Prevents contradicting
    alerts like "BREAKS $71k" then "DROPS TO $71k" within minutes.

    Default: 30 minutes.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    current_lock = get_bot_setting('milestone_lock') or '30'

    if not context.args:
        await update.message.reply_text(
            f"⏱️ <b>Milestone Lock Period</b>\n\n"
            f"Current: <b>{current_lock} minutes</b>\n\n"
            f"After a milestone alert fires (BREAKS or DROPS),\n"
            f"that milestone is locked for this period.\n"
            f"Prevents contradicting alerts on the same level.\n\n"
            f"<b>Usage:</b> /time &lt;minutes&gt;\n"
            f"<b>Examples:</b>\n"
            f"• /time 30 - 30 minutes (default)\n"
            f"• /time 60 - 1 hour\n"
            f"• /time 120 - 2 hours",
            parse_mode='HTML'
        )
        return

    try:
        minutes = int(context.args[0])

        if minutes < 5:
            await update.message.reply_text("❌ Minimum lock is 5 minutes")
            return

        if minutes > 1440:
            await update.message.reply_text("❌ Maximum lock is 1440 minutes (24 hours)")
            return

        set_bot_setting('milestone_lock', str(minutes), str(user_id))

        if minutes >= 60:
            display = f"{minutes / 60:.1f} hour{'s' if minutes / 60 != 1 else ''}"
        else:
            display = f"{minutes} minutes"

        await update.message.reply_text(
            f"✅ <b>Milestone Lock Updated</b>\n\n"
            f"⏱️ Lock period: <b>{display}</b>\n\n"
            f"Same milestone won't alert again (any direction) for {display}.",
            parse_mode='HTML'
        )

        logger.info(f"Milestone lock changed to {minutes}min by user {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid number. Use: /time 30")


async def cmd_setthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dynamic threshold command handler.

    Admin only, DM only. Works for any symbol: /btc 2%, /eth 3%, /sol 5%

    For BTC and ETH:
    - Percentage mode: /btc 3% (every ±3%)
    - Milestone mode: /btc 1000 (every $1000)

    For other symbols:
    - Only percentage mode: /sol 5% (every ±5%)
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    # Extract symbol from command (e.g., "/btc" -> "BTC")
    command = update.message.text.split()[0][1:].upper()
    is_btc_eth = command in ['BTC', 'ETH']

    if not context.args:
        if is_btc_eth:
            current_mode = get_bot_setting('btc_eth_alert_mode') or 'percentage'
            if command == 'BTC':
                current_pct = get_bot_setting('btc_percentage') or '3'
                current_ms = get_bot_setting('btc_milestone') or '1000'
            else:
                current_pct = get_bot_setting('eth_percentage') or '2'
                current_ms = get_bot_setting('eth_milestone') or '100'

            await update.message.reply_text(
                f"📊 <b>{command} Alert Settings</b>\n\n"
                f"Current mode: <b>{current_mode.upper()}</b>\n\n"
                f"<b>Percentage:</b> ±{current_pct}%\n"
                f"<b>Milestone:</b> ${current_ms}\n\n"
                f"<b>Usage:</b>\n"
                f"• <code>/{command.lower()} 3%</code> - Set percentage\n"
                f"• <code>/{command.lower()} 1000</code> - Set milestone\n\n"
                f"<b>Switch modes:</b>\n"
                f"/percentage - Use percentage alerts\n"
                f"/milestone - Use price milestone alerts",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(
                f"❌ <b>Usage:</b> <code>/{command.lower()} &lt;percentage&gt;</code>\n\n"
                f"<b>Example:</b> <code>/{command.lower()} 5%</code>\n"
                f"This will alert EVERY ±5%: ±5%, ±10%, ±15%, ...",
                parse_mode='HTML'
            )
        return

    try:
        value_str = context.args[0]
        has_percent = '%' in value_str

        # Parse the value
        value = int(value_str.rstrip('%'))

        if is_btc_eth:
            # For BTC/ETH: determine if percentage or milestone based on value
            if has_percent or value <= 50:
                # Percentage mode
                if value < 1 or value > 50:
                    await update.message.reply_text("❌ Percentage must be between 1% and 50%")
                    return

                setting_key = 'btc_percentage' if command == 'BTC' else 'eth_percentage'
                set_bot_setting(setting_key, str(value), str(user_id))

                examples = [value * i for i in range(1, 6)]
                examples_str = ', '.join(f'±{t}%' for t in examples)

                await update.message.reply_text(
                    f"✅ <b>{command} Percentage Set</b>\n\n"
                    f"📊 <b>Alert every ±{value}%</b>\n"
                    f"🔔 Examples: {examples_str}, ...\n\n"
                    f"Mode: Use /percentage to activate",
                    parse_mode='HTML'
                )

                logger.info(f"{command} percentage set to {value}% by user {user_id}")

            else:
                # Milestone mode (value > 50, like 100 or 1000)
                setting_key = 'btc_milestone' if command == 'BTC' else 'eth_milestone'
                set_bot_setting(setting_key, str(value), str(user_id))

                # Generate example milestones
                if command == 'BTC':
                    base = 90000
                    examples = [f"${base + value * i:,}" for i in range(3)]
                else:
                    base = 3000
                    examples = [f"${base + value * i:,}" for i in range(3)]

                await update.message.reply_text(
                    f"✅ <b>{command} Milestone Set</b>\n\n"
                    f"📊 <b>Alert every ${value:,}</b>\n"
                    f"🔔 Examples: {', '.join(examples)}, ...\n\n"
                    f"Mode: Use /milestone to activate",
                    parse_mode='HTML'
                )

                logger.info(f"{command} milestone set to ${value} by user {user_id}")

        else:
            # For other symbols: only percentage mode
            if value < 1 or value > 50:
                await update.message.reply_text("❌ Percentage must be between 1% and 50%")
                return

            symbol = f"{command}USDT"

            # Save as incremental threshold
            set_custom_thresholds(
                symbol=symbol,
                thresholds=[value],
                is_incremental=True,
                user_id=user_id
            )

            examples = [value * i for i in range(1, 6)]
            examples_str = ', '.join(f'±{t}%' for t in examples)

            await update.message.reply_text(
                f"✅ <b>Alerts Set for {symbol}</b>\n\n"
                f"📊 <b>Alert every ±{value}%</b>\n"
                f"🔔 Examples: {examples_str}, ...",
                parse_mode='HTML'
            )

            logger.info(f"Threshold set for {symbol}: every ±{value}% by user {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid value. Use a number like: 2, 3, 5, 100, 1000")
    except Exception as e:
        logger.error(f"Error setting threshold: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_listthresholds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listthresholds - List all custom thresholds

    Admin only, DM only. Shows all symbols with custom thresholds.
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    try:
        results = get_all_custom_thresholds()

        if not results:
            default_str = ', '.join(f'±{t}%' for t in BASE_THRESHOLDS)
            await update.message.reply_text(
                "📊 <b>Custom Thresholds</b>\n\n"
                "No custom thresholds configured.\n\n"
                f"<b>Default:</b> {default_str}",
                parse_mode='HTML'
            )
            return

        message = "📊 <b>Custom Thresholds</b>\n\n"

        for row in results:
            symbol = row['symbol']
            thresholds_str = row['thresholds']
            is_incremental = row.get('is_incremental', False)

            if is_incremental:
                increment = thresholds_str
                message += f"• <b>{symbol}</b>: Every ±{increment}%\n"
            else:
                thresholds = ', '.join(f'±{t}%' for t in thresholds_str.split(','))
                message += f"• <b>{symbol}</b>: {thresholds}\n"

        default_str = ', '.join(f'±{t}%' for t in BASE_THRESHOLDS)
        message += f"\n🔄 <b>Default:</b> {default_str}"

        await update.message.reply_text(message, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error listing thresholds: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_resetthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resetthreshold <SYMBOL> - Reset symbol to default thresholds

    Admin only, DM only. Removes custom threshold for a symbol.
    Example: /resetthreshold BTC
    """
    # Only respond in private chat (DM)
    if not is_private_chat(update):
        return  # Silently ignore in group/topic

    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    if not context.args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/resetthreshold &lt;SYMBOL&gt;</code>\n\n"
            "<b>Example:</b> <code>/resetthreshold BTC</code>",
            parse_mode='HTML'
        )
        return

    symbol_input = context.args[0].upper()

    # Add USDT if not present
    if not symbol_input.endswith('USDT'):
        symbol = f"{symbol_input}USDT"
    else:
        symbol = symbol_input

    try:
        deleted = delete_custom_thresholds(symbol)

        if deleted:
            default_str = ', '.join(f'±{t}%' for t in BASE_THRESHOLDS)
            await update.message.reply_text(
                f"✅ <b>{symbol}</b> reset to default thresholds\n\n"
                f"<b>Default:</b> {default_str}",
                parse_mode='HTML'
            )
            logger.info(f"Custom threshold deleted for {symbol} by user {user_id}")
        else:
            await update.message.reply_text(
                f"ℹ️ <b>{symbol}</b> has no custom thresholds\n"
                f"(Already using defaults)",
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f"Error resetting threshold: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")
