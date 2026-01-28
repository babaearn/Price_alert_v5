"""Admin command handlers (restricted commands)"""
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import ADMIN_USER_IDS
from bot.services.database import get_bot_setting, set_bot_setting
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
