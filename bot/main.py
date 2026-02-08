"""
Bybit Price Alert Bot - Main Entry Point

A 24/7 automated cryptocurrency price monitoring bot that:
- Scans 475+ Bybit trading pairs every 30 seconds
- Implements TRUE Bybit-style rolling 24-hour gainer/loser calculation
- Sends Telegram alerts when price thresholds cross
- Fires each threshold alert ONCE per 24-hour period from first detection
- Supports both Futures (linear) and Spot markets
"""
import asyncio
import sys

import re

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from bot.config import TELEGRAM_BOT_TOKEN, validate_config, log_masked_config
from bot.services.database import init_database, close_connection
from bot.services.bybit_api import test_api_connection
from bot.services.price_monitor import init_price_monitor, start_price_monitor, stop_price_monitor
from bot.handlers.user_commands import (
    cmd_start, cmd_help, cmd_status, cmd_stats, cmd_listpairs
)
from bot.handlers.admin_commands import (
    cmd_mode, cmd_model1, cmd_model2, cmd_volume, cmd_volume1, cmd_volume2,
    cmd_pause, cmd_resume, cmd_resetsession, cmd_admin,
    cmd_setthreshold, cmd_listthresholds, cmd_resetthreshold,
    cmd_percentage, cmd_milestone, cmd_cooldown, cmd_241
)
from bot.handlers.callbacks import handle_callback_query
from bot.utils.logger import logger


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in the bot"""
    logger.error(f"Update {update} caused error {context.error}")


async def post_init(application: Application):
    """Run after application initialization"""
    logger.info("Bot application initialized")

    # Initialize price monitor with bot instance
    init_price_monitor(application.bot)

    # Start the price monitor scheduler
    start_price_monitor()

    logger.info("✅ Bot is ready and monitoring prices")


async def post_shutdown(application: Application):
    """Run before application shutdown"""
    logger.info("Shutting down bot...")

    # Stop price monitor
    stop_price_monitor()

    # Close database connection
    close_connection()

    logger.info("Bot shutdown complete")


def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("Starting Bybit Price Alert Bot v2.0")
    logger.info("=" * 50)

    # Validate configuration
    config_errors = validate_config()
    if config_errors:
        for error in config_errors:
            logger.error(f"Config error: {error}")
        sys.exit(1)

    logger.info("✅ Configuration validated")

    # Initialize database
    try:
        init_database()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        sys.exit(1)

    # Log configuration with masked credentials
    log_masked_config()

    # Test Bybit API connection
    if not test_api_connection():
        logger.warning("⚠️ Bybit API test failed - continuing anyway")

    # Build application
    logger.info("Building Telegram application...")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register user command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("listpairs", cmd_listpairs))

    # Register admin command handlers
    application.add_handler(CommandHandler("mode", cmd_mode))
    application.add_handler(CommandHandler("model1", cmd_model1))
    application.add_handler(CommandHandler("model2", cmd_model2))
    application.add_handler(CommandHandler("volume", cmd_volume))
    application.add_handler(CommandHandler("volume1", cmd_volume1))
    application.add_handler(CommandHandler("volume2", cmd_volume2))
    application.add_handler(CommandHandler("pause", cmd_pause))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("resetsession", cmd_resetsession))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(CommandHandler("percentage", cmd_percentage))
    application.add_handler(CommandHandler("milestone", cmd_milestone))
    application.add_handler(CommandHandler("cooldown", cmd_cooldown))
    application.add_handler(CommandHandler("241", cmd_241))

    # Register threshold commands
    application.add_handler(CommandHandler("listthresholds", cmd_listthresholds))
    application.add_handler(CommandHandler("resetthreshold", cmd_resetthreshold))

    # Dynamic symbol threshold commands (e.g., /btc 2%, /eth 3%, /sol 5%)
    # Matches any 2-5 letter command followed by a number (percentage)
    # Common symbols: btc, eth, sol, doge, xrp, ada, matic, link, etc.
    common_symbols = [
        "btc", "eth", "sol", "doge", "xrp", "ada", "matic", "link",
        "avax", "dot", "atom", "near", "apt", "arb", "op", "bnb",
        "ltc", "bch", "etc", "fil", "icp", "vet", "algo", "ftm",
        "sand", "mana", "axs", "gala", "enj", "imx", "ldo", "rpl",
        "crv", "aave", "mkr", "snx", "comp", "uni", "sushi", "cake",
        "pepe", "shib", "floki", "wld", "sei", "sui", "inj", "tia"
    ]
    for symbol in common_symbols:
        application.add_handler(CommandHandler(symbol, cmd_setthreshold))

    # Register callback handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Register error handler
    application.add_error_handler(error_handler)

    logger.info("✅ All handlers registered")

    # Run the bot
    logger.info("Starting bot polling...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
