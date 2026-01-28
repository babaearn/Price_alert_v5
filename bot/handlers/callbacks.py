"""Callback query handlers for inline buttons"""
from telegram import Update
from telegram.ext import ContextTypes

from bot.utils.logger import logger


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle inline button callbacks.

    Currently, all buttons link to external URLs, so this handler
    is primarily for logging and future expansion.
    """
    query = update.callback_query

    if query is None:
        return

    await query.answer()

    callback_data = query.data
    user_id = query.from_user.id

    logger.info(f"Callback received: {callback_data} from user {user_id}")

    # Currently no interactive callbacks needed
    # All buttons use URL links

    # Future callback handlers can be added here:
    # if callback_data.startswith('confirm_'):
    #     await handle_confirmation(query, context)
    # elif callback_data.startswith('cancel_'):
    #     await handle_cancellation(query, context)
