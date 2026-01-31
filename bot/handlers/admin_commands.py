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


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /mode <futures|spot> - Switch market mode

    Admin only. Switches between futures and spot markets.
    """
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

    Admin only. Sets calculation model to session-based (00:00 UTC reset).
    """
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

    Admin only. Sets calculation model to rolling 24-hour window (Bybit default).
    """
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

    Admin only. Sets minimum 24h trading volume threshold.
    Supports formats: 5M, 5000000, $5M
    """
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


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pause - Pause the price scanner

    Admin only. Stops price monitoring and alert generation.
    """
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

    Admin only. Resumes price monitoring and alert generation.
    """
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

    Admin only. Resets all session prices to current prices (Model 1 only).
    """
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

    Shows whether user is an admin and current admin list.
    """
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


async def cmd_setthreshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Dynamic threshold command handler.

    Works for any symbol: /btc 2%, /eth 3%, /sol 5%

    This sets incremental alerts - e.g., /btc 2% means alert every ±2%:
    ±2%, ±4%, ±6%, ±8%, ±10%, ±12%, etc.
    """
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only command")
        return

    # Extract symbol from command (e.g., "/btc" -> "BTC")
    command = update.message.text.split()[0][1:].upper()

    if not context.args:
        await update.message.reply_text(
            f"❌ <b>Usage:</b> <code>/{command.lower()} &lt;percentage&gt;</code>\n\n"
            f"<b>Example:</b> <code>/{command.lower()} 2%</code>\n"
            f"This will alert EVERY ±2%: ±2%, ±4%, ±6%, ±8%, ...\n\n"
            f"<b>Works for any symbol:</b>\n"
            f"<code>/btc 2%</code> - BTC alerts every ±2%\n"
            f"<code>/eth 3%</code> - ETH alerts every ±3%\n"
            f"<code>/sol 5%</code> - SOL alerts every ±5%",
            parse_mode='HTML'
        )
        return

    try:
        # Parse percentage (remove % if present)
        threshold_str = context.args[0].rstrip('%')
        increment = int(threshold_str)

        if increment < 1 or increment > 50:
            await update.message.reply_text(
                "❌ Percentage must be between 1% and 50%"
            )
            return

        symbol = f"{command}USDT"

        # Save as incremental threshold
        set_custom_thresholds(
            symbol=symbol,
            thresholds=[increment],
            is_incremental=True,
            user_id=user_id
        )

        # Generate example thresholds
        examples = [increment * i for i in range(1, 6)]
        examples_str = ', '.join(f'±{t}%' for t in examples)

        await update.message.reply_text(
            f"✅ <b>Incremental Alerts Set for {symbol}</b>\n\n"
            f"📊 <b>Alert every ±{increment}%</b>\n"
            f"🔔 Examples: {examples_str}, ...\n\n"
            f"Next alerts will fire at every ±{increment}% move!",
            parse_mode='HTML'
        )

        logger.info(f"Custom threshold set for {symbol}: every ±{increment}% by user {user_id}")

    except ValueError:
        await update.message.reply_text("❌ Invalid percentage value. Use a number like: 2, 3, 5")
    except Exception as e:
        logger.error(f"Error setting threshold: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def cmd_listthresholds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listthresholds - List all custom thresholds

    Admin only. Shows all symbols with custom thresholds.
    """
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

    Admin only. Removes custom threshold for a symbol.
    Example: /resetthreshold BTC
    """
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
