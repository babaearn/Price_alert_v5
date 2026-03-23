"""Main price monitoring service with APScheduler"""
import time
import asyncio
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from bot.config import DEFAULT_SCAN_INTERVAL, PERF_METRICS_ENABLED
from bot.services.database import (
    get_bot_setting, get_bot_settings, store_price_snapshot,
    store_price_snapshots_batch, log_scan
)
from bot.services.bybit_api import fetch_tickers, get_bybit_category
from bot.services.alert_checker import (
    check_and_send_alerts, check_and_send_milestone_alerts
)
from bot.services.session_manager import reset_daily_sessions, initialize_session_prices
from bot.services.cleanup import run_cleanup
from bot.utils.logger import logger

# Global state
_scheduler: Optional[AsyncIOScheduler] = None
_bot: Optional[Bot] = None
_scan_count = 0


def _is_btc_eth_related(symbol: str) -> bool:
    """True for BTC*/ETH* symbols like BTCUSDT, BTCPERP, ETHUSDT, ETHPERP."""
    upper = symbol.upper()
    return upper.startswith('BTC') or upper.startswith('ETH')


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
    perf = None
    if PERF_METRICS_ENABLED:
        perf = {
            # Snapshot write amplification (largest DB cost driver)
            'legacy_snapshot_write_calls': 0,
            'new_snapshot_write_calls': 0,
            'snapshot_rows_recorded': 0,
            # Settings read reduction from scan-level cache
            'legacy_settings_reads': 0,
            'new_settings_reads': 0,
            # Alert/milestone cooldown write comparison (filled by alert_checker)
            'legacy_alert_write_calls': 0,
            'new_alert_write_calls': 0,
            'alert_rows_recorded': 0,
            'legacy_milestone_write_calls': 0,
            'new_milestone_write_calls': 0,
            'milestone_rows_recorded': 0,
            'percentage_cooldown_checks': 0,
            'milestone_cooldown_checks': 0
        }

    try:
        # Get scan settings once to reduce DB chatter in hot path.
        settings = get_bot_settings([
            'mode',
            'model',
            'min_volume_futures',
            'min_volume_spot',
            'btc_eth_alert_mode',
            'btc_milestone',
            'eth_milestone',
            'short_term_trend',
            'milestone_cooldown'
        ])
        if perf is not None:
            perf['legacy_settings_reads'] += 9
            perf['new_settings_reads'] += 1

        mode = settings.get('mode') or 'futures'
        model = settings.get('model') or 'model2'
        category = get_bybit_category(mode)

        # Use mode-specific volume setting
        if mode == 'futures':
            min_volume = float(settings.get('min_volume_futures') or 25_000_000)
        else:
            min_volume = float(settings.get('min_volume_spot') or 25_000_000)

        # Check if BTC/ETH are in milestone mode
        use_milestone_mode = (settings.get('btc_eth_alert_mode') or 'percentage') == 'milestone'
        use_short_term = (settings.get('short_term_trend') or 'true') == 'true'
        milestone_cooldown_minutes = int(settings.get('milestone_cooldown') or 1440)
        btc_milestone_step = int(settings.get('btc_milestone') or 1000)
        eth_milestone_step = int(settings.get('eth_milestone') or 100)

        # Fetch all tickers from Bybit
        tickers = fetch_tickers(category)

        if not tickers:
            logger.warning("No tickers received from Bybit")
            errors_count += 1
            return

        current_time = int(time.time())
        snapshot_rows = []

        for ticker in tickers:
            try:
                symbol = ticker['symbol']
                current_price = float(ticker['lastPrice'])
                volume_24h = float(ticker.get('turnover24h', 0))

                # Volume filter
                if volume_24h < min_volume:
                    continue

                pairs_processed += 1

                # Buffer snapshots and flush once per scan for lower DB write cost.
                snapshot_rows.append((symbol, mode, current_price, current_time))

                # Check if this is BTCUSDT or ETHUSDT specifically (not BTCPERP, BTCDOMUSDT, etc.)
                is_btc_eth_usdt = symbol.upper() in ('BTCUSDT', 'ETHUSDT')

                if is_btc_eth_usdt and use_milestone_mode:
                    # Use milestone-based alerts for BTC/ETH (skip percentage entirely)
                    alert_sent, alert_count = await check_and_send_milestone_alerts(
                        _bot, symbol, current_price, ticker, current_time,
                        mode=mode,
                        use_short_term=use_short_term,
                        btc_milestone_step=btc_milestone_step,
                        eth_milestone_step=eth_milestone_step,
                        milestone_cooldown_minutes=milestone_cooldown_minutes,
                        perf=perf
                    )
                elif use_milestone_mode and _is_btc_eth_related(symbol):
                    # Milestone mode should suppress BTC/ETH percentage alerts
                    # from non-target contracts (e.g., BTCPERP/ETHPERP).
                    continue
                else:
                    # Use percentage-based alerts (standard or incremental)
                    alert_sent, alert_count = await check_and_send_alerts(
                        _bot, symbol, current_price, ticker, current_time,
                        mode=mode, model=model, perf=perf
                    )

                alerts_sent += alert_count

            except Exception as e:
                logger.error(f"Error processing {ticker.get('symbol', 'unknown')}: {e}")
                errors_count += 1
                continue

        # Flush buffered snapshots once at end of scan.
        if snapshot_rows:
            if perf is not None:
                perf['legacy_snapshot_write_calls'] += len(snapshot_rows)
                perf['snapshot_rows_recorded'] += len(snapshot_rows)
            inserted = store_price_snapshots_batch(snapshot_rows)
            if inserted != len(snapshot_rows):
                logger.warning(
                    f"Snapshot batch partial/failed: inserted {inserted}/{len(snapshot_rows)}"
                )
                if perf is not None:
                    perf['new_snapshot_write_calls'] += 1
                # Fallback to single-row writes to preserve behavior during transient DB issues.
                if inserted == 0:
                    for symbol, snap_mode, snap_price, snap_ts in snapshot_rows:
                        store_price_snapshot(symbol, snap_mode, snap_price, snap_ts)
                    if perf is not None:
                        perf['new_snapshot_write_calls'] += len(snapshot_rows)
            else:
                if perf is not None:
                    perf['new_snapshot_write_calls'] += 1

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

        # Lightweight perf/cost metrics (legacy estimate vs current path)
        if perf is not None:
            legacy_total_writes = (
                perf['legacy_snapshot_write_calls']
                + perf['legacy_alert_write_calls']
                + perf['legacy_milestone_write_calls']
            )
            new_total_writes = (
                perf['new_snapshot_write_calls']
                + perf['new_alert_write_calls']
                + perf['new_milestone_write_calls']
            )
            write_reduction_pct = (
                ((legacy_total_writes - new_total_writes) / legacy_total_writes) * 100
                if legacy_total_writes > 0 else 0.0
            )

            metrics_line = (
                f"Perf scan #{_scan_count} | "
                f"db_ops_before={legacy_total_writes} db_ops_after={new_total_writes} "
                f"write_reduction={write_reduction_pct:.1f}% | "
                f"snapshots rows={perf['snapshot_rows_recorded']} "
                f"calls_before={perf['legacy_snapshot_write_calls']} "
                f"calls_after={perf['new_snapshot_write_calls']} | "
                f"alerts rows={perf['alert_rows_recorded']} "
                f"calls_before={perf['legacy_alert_write_calls']} "
                f"calls_after={perf['new_alert_write_calls']} | "
                f"milestones rows={perf['milestone_rows_recorded']} "
                f"calls_before={perf['legacy_milestone_write_calls']} "
                f"calls_after={perf['new_milestone_write_calls']} | "
                f"settings_reads before={perf['legacy_settings_reads']} "
                f"after={perf['new_settings_reads']} | "
                f"cooldown_checks pct={perf['percentage_cooldown_checks']} "
                f"ms={perf['milestone_cooldown_checks']}"
            )
            if alerts_sent > 0 or (_scan_count % 20 == 0):
                logger.info(metrics_line)
            else:
                logger.debug(metrics_line)

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

    # Use mode-specific volume setting
    if mode == 'futures':
        min_volume = float(get_bot_setting('min_volume_futures') or 25_000_000)
    else:
        min_volume = float(get_bot_setting('min_volume_spot') or 25_000_000)

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
    mode = get_bot_setting('mode') or 'futures'

    # Get the correct volume setting based on mode
    if mode == 'futures':
        min_volume = get_bot_setting('min_volume_futures') or '25000000'
    else:
        min_volume = get_bot_setting('min_volume_spot') or '25000000'

    return {
        'running': is_monitor_running(),
        'paused': get_bot_setting('paused') == 'true',
        'scan_count': _scan_count,
        'mode': mode,
        'model': get_bot_setting('model'),
        'min_volume': min_volume,
        'scan_interval': get_bot_setting('scan_interval')
    }
