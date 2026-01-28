"""Main price monitoring service with APScheduler"""
import time
import asyncio
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from bot.config import DEFAULT_SCAN_INTERVAL
from bot.services.database import (
    get_bot_setting, store_price_snapshot, log_scan
)
from bot.services.bybit_api import fetch_tickers, get_bybit_category
from bot.services.alert_checker import check_and_send_alerts
from bot.services.session_manager import reset_daily_sessions, initialize_session_prices
from bot.services.cleanup import run_cleanup
from bot.utils.logger import logger

# Global state
_scheduler: Optional[AsyncIOScheduler] = None
_bot: Optional[Bot] = None
_scan_count = 0


def get_scan_count() -> int:
    """Get current scan count"""
    return _scan_count


def init_price_monitor(bot: Bot):
    """
    Initialize the price monitor with bot instance.

    Args:
        bot: Telegram bot instance for sending alerts
    """
    global _bot
    _bot = bot
    logger.info("Price monitor initialized with bot instance")


def start_price_monitor():
    """Start the price monitoring scheduler"""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running")
        return

    _scheduler = AsyncIOScheduler()

    # Get scan interval from settings
    scan_interval = int(get_bot_setting('scan_interval') or DEFAULT_SCAN_INTERVAL)

    # Main scan task (every 30 seconds by default)
    _scheduler.add_job(
        scan_prices,
        'interval',
        seconds=scan_interval,
        id='price_scan',
        max_instances=1,  # Prevent overlapping scans
        coalesce=True,  # Combine missed runs
        misfire_grace_time=30  # Allow 30s grace period
    )

    # Cleanup task (every hour)
    _scheduler.add_job(
        run_cleanup,
        'interval',
        hours=1,
        id='cleanup',
        max_instances=1
    )

    # Session reset for Model 1 (daily at 00:00 UTC)
    _scheduler.add_job(
        reset_daily_sessions,
        'cron',
        hour=0,
        minute=0,
        second=5,  # 5 seconds after midnight to ensure date change
        id='session_reset',
        max_instances=1
    )

    _scheduler.start()
    logger.info(f"✅ Price monitor started (interval: {scan_interval}s)")

    # Initialize session prices if using Model 1
    initialize_session_prices()


def stop_price_monitor():
    """Stop the price monitoring scheduler"""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("Price monitor stopped")


def is_monitor_running() -> bool:
    """Check if price monitor is running"""
    return _scheduler is not None and _scheduler.running


async def scan_prices():
    """
    Main scanning loop - called every 30 seconds.

    Process:
    1. Check if paused
    2. Fetch all tickers from Bybit
    3. Filter by volume
    4. For each ticker:
       - Store price snapshot
       - Check and send alerts
    5. Log scan results
    """
    global _scan_count, _bot

    # Check if paused
    if get_bot_setting('paused') == 'true':
        logger.debug("Scanner paused, skipping scan")
        return

    if _bot is None:
        logger.error("Bot not initialized, skipping scan")
        return

    _scan_count += 1
    start_time = time.time()
    alerts_sent = 0
    errors_count = 0
    pairs_processed = 0

    try:
        # Get settings
        mode = get_bot_setting('mode') or 'futures'
        category = get_bybit_category(mode)
        min_volume = float(get_bot_setting('min_volume_usd') or 5_000_000)

        # Fetch all tickers from Bybit
        tickers = fetch_tickers(category)

        if not tickers:
            logger.warning("No tickers received from Bybit")
            errors_count += 1
            return

        current_time = int(time.time())

        for ticker in tickers:
            try:
                symbol = ticker['symbol']
                current_price = float(ticker['lastPrice'])
                volume_24h = float(ticker.get('turnover24h', 0))

                # Volume filter
                if volume_24h < min_volume:
                    continue

                pairs_processed += 1

                # Store price snapshot for rolling 24h calculation
                store_price_snapshot(symbol, mode, current_price, current_time)

                # Check and send alerts
                alert_sent, alert_count = await check_and_send_alerts(
                    _bot, symbol, current_price, ticker, current_time
                )

                alerts_sent += alert_count

            except Exception as e:
                logger.error(f"Error processing {ticker.get('symbol', 'unknown')}: {e}")
                errors_count += 1
                continue

        duration_ms = int((time.time() - start_time) * 1000)

        # Log scan results
        log_scan(_scan_count, pairs_processed, alerts_sent, errors_count, duration_ms)

        # Log summary
        if alerts_sent > 0:
            logger.info(
                f"Scan #{_scan_count}: {pairs_processed} pairs, "
                f"{alerts_sent} alerts, {duration_ms}ms"
            )
        else:
            logger.debug(
                f"Scan #{_scan_count}: {pairs_processed} pairs, "
                f"{alerts_sent} alerts, {duration_ms}ms"
            )

    except Exception as e:
        logger.error(f"Scan error: {e}")
        errors_count += 1

        # Still log failed scan
        duration_ms = int((time.time() - start_time) * 1000)
        log_scan(_scan_count, pairs_processed, alerts_sent, errors_count, duration_ms)


async def run_manual_scan() -> dict:
    """
    Run a manual scan (for testing/debugging).

    Returns:
        Dictionary with scan results
    """
    global _bot

    if _bot is None:
        return {'error': 'Bot not initialized'}

    start_time = time.time()

    # Get settings
    mode = get_bot_setting('mode') or 'futures'
    category = get_bybit_category(mode)
    min_volume = float(get_bot_setting('min_volume_usd') or 5_000_000)

    # Fetch tickers
    tickers = fetch_tickers(category)

    if not tickers:
        return {'error': 'No tickers received'}

    # Count pairs meeting volume threshold
    filtered_count = sum(
        1 for t in tickers
        if float(t.get('turnover24h', 0)) >= min_volume
    )

    duration_ms = int((time.time() - start_time) * 1000)

    return {
        'total_pairs': len(tickers),
        'filtered_pairs': filtered_count,
        'mode': mode,
        'min_volume': min_volume,
        'duration_ms': duration_ms
    }


def get_monitor_status() -> dict:
    """
    Get current monitor status.

    Returns:
        Dictionary with monitor status
    """
    return {
        'running': is_monitor_running(),
        'paused': get_bot_setting('paused') == 'true',
        'scan_count': _scan_count,
        'mode': get_bot_setting('mode'),
        'model': get_bot_setting('model'),
        'min_volume': get_bot_setting('min_volume_usd'),
        'scan_interval': get_bot_setting('scan_interval')
    }
