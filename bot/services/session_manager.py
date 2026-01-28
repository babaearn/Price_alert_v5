"""Session management for Model 1 (00:00 UTC reset)"""
from datetime import datetime
from typing import Dict, List

from bot.services.database import (
    get_bot_setting, set_session_start_price, get_connection
)
from bot.services.bybit_api import fetch_tickers, get_bybit_category
from bot.utils.logger import logger


def reset_daily_sessions() -> int:
    """
    Reset all session prices at 00:00 UTC (Model 1 only).

    Called daily by APScheduler at midnight UTC.
    Sets session start prices for all monitored pairs.

    Returns:
        Number of pairs updated
    """
    # Only reset if using Model 1
    current_model = get_bot_setting('model')

    if current_model != 'model1':
        logger.debug("Skipping session reset - not using Model 1")
        return 0

    mode = get_bot_setting('mode')
    category = get_bybit_category(mode)
    today = datetime.utcnow().date()

    logger.info(f"Starting daily session reset for {mode} mode")

    try:
        # Fetch current prices from Bybit
        tickers = fetch_tickers(category)

        if not tickers:
            logger.error("No tickers received for session reset")
            return 0

        updated_count = 0

        for ticker in tickers:
            try:
                symbol = ticker['symbol']
                price = float(ticker['lastPrice'])

                # Store as session start price
                set_session_start_price(symbol, mode, price, today)
                updated_count += 1

            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to set session price for {ticker.get('symbol', 'unknown')}: {e}")
                continue

        logger.info(f"✅ Session reset complete: {updated_count} pairs updated")
        return updated_count

    except Exception as e:
        logger.error(f"Session reset failed: {e}")
        return 0


def force_reset_sessions() -> int:
    """
    Force reset session prices to current prices (admin command).

    Used when admin wants to manually reset reference prices.

    Returns:
        Number of pairs updated
    """
    mode = get_bot_setting('mode')
    category = get_bybit_category(mode)
    today = datetime.utcnow().date()

    logger.info(f"Force resetting sessions for {mode} mode")

    try:
        # Fetch current prices
        tickers = fetch_tickers(category)

        if not tickers:
            logger.error("No tickers received for force reset")
            return 0

        updated_count = 0

        for ticker in tickers:
            try:
                symbol = ticker['symbol']
                price = float(ticker['lastPrice'])

                set_session_start_price(symbol, mode, price, today)
                updated_count += 1

            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to set session price for {ticker.get('symbol', 'unknown')}: {e}")
                continue

        logger.info(f"✅ Force session reset complete: {updated_count} pairs")
        return updated_count

    except Exception as e:
        logger.error(f"Force session reset failed: {e}")
        return 0


def initialize_session_prices() -> int:
    """
    Initialize session prices on bot startup (Model 1).

    If no session prices exist for today, set them to current prices.

    Returns:
        Number of pairs initialized
    """
    current_model = get_bot_setting('model')

    if current_model != 'model1':
        return 0

    mode = get_bot_setting('mode')
    today = datetime.utcnow().date()

    # Check if sessions already exist for today
    conn, cursor = get_connection()
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM session_prices
        WHERE mode = %s AND session_date = %s
    """, (mode, today))

    result = cursor.fetchone()
    existing_count = result['count'] if result else 0

    if existing_count > 0:
        logger.info(f"Session prices already exist for today: {existing_count} pairs")
        return existing_count

    # No sessions exist, initialize
    logger.info("No session prices for today, initializing...")
    return force_reset_sessions()


def get_session_info() -> Dict:
    """
    Get information about current session.

    Returns:
        Dictionary with session information
    """
    mode = get_bot_setting('mode')
    today = datetime.utcnow().date()

    conn, cursor = get_connection()
    cursor.execute("""
        SELECT COUNT(*) as count,
               MIN(created_at) as first_created,
               MAX(created_at) as last_created
        FROM session_prices
        WHERE mode = %s AND session_date = %s
    """, (mode, today))

    result = cursor.fetchone()

    return {
        'mode': mode,
        'session_date': str(today),
        'pairs_count': result['count'] if result else 0,
        'first_created': str(result['first_created']) if result and result['first_created'] else None,
        'last_created': str(result['last_created']) if result and result['last_created'] else None
    }
