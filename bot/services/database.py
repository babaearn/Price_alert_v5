"""PostgreSQL database operations"""
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import time
from typing import Optional, Dict, Any, List

from bot.config import (
    DATABASE_URL, DEFAULT_MODE, DEFAULT_MODEL,
    DEFAULT_MIN_VOLUME_USD, DEFAULT_SCAN_INTERVAL,
    DEFAULT_MIN_VOLUME_FUTURES, DEFAULT_MIN_VOLUME_SPOT,
    DEFAULT_BTC_ETH_ALERT_MODE, DEFAULT_BTC_PERCENTAGE, DEFAULT_ETH_PERCENTAGE,
    DEFAULT_BTC_MILESTONE, DEFAULT_ETH_MILESTONE, DEFAULT_MILESTONE_COOLDOWN,
    DEFAULT_SHORT_TERM_TREND, DEFAULT_SHORT_TERM_LOOKBACK
)
from bot.utils.logger import logger
from bot.utils.token_masker import mask_database_url, mask_error_message

# Connection pool
_conn = None
_cursor = None


def get_connection():
    """Get database connection, creating if needed"""
    global _conn, _cursor

    if _conn is None or _conn.closed:
        try:
            _conn = psycopg2.connect(DATABASE_URL)
            _conn.autocommit = False
            _cursor = _conn.cursor(cursor_factory=RealDictCursor)
            logger.info(f"Database connection established: {mask_database_url(DATABASE_URL)}")
        except Exception as e:
            masked_error = mask_error_message(str(e))
            logger.error(f"Failed to connect to database: {masked_error}")
            raise

    return _conn, _cursor


def init_database():
    """Initialize database connection and schema"""
    try:
        conn, cursor = get_connection()
        create_schema()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
        raise


def create_schema():
    """Create all database tables"""
    conn, cursor = get_connection()

    # Price snapshots (rolling 24h history)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_snapshots (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            mode VARCHAR(10) NOT NULL,
            price DECIMAL(20, 8) NOT NULL,
            timestamp BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_snapshots_lookup
        ON price_snapshots(symbol, mode, timestamp)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_snapshots_cleanup
        ON price_snapshots(timestamp)
    """)

    # Alert history (deduplication tracking)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            threshold INTEGER NOT NULL,
            mode VARCHAR(10) NOT NULL,
            model VARCHAR(10) NOT NULL,
            first_detected_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            price_at_detection DECIMAL(20, 8) NOT NULL,
            pct_change_at_detection DECIMAL(10, 4) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_alert_history_lookup
        ON alert_history(symbol, threshold, mode, model, expires_at)
    """)

    # Bot configuration (persistent settings)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_config (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by VARCHAR(50)
        )
    """)

    # Default configuration
    cursor.execute("""
        INSERT INTO bot_config (key, value, updated_by) VALUES
            ('mode', %s, 'system'),
            ('model', %s, 'system'),
            ('min_volume_usd', %s, 'system'),
            ('min_volume_futures', %s, 'system'),
            ('min_volume_spot', %s, 'system'),
            ('scan_interval', %s, 'system'),
            ('paused', 'false', 'system'),
            ('btc_eth_alert_mode', %s, 'system'),
            ('btc_percentage', %s, 'system'),
            ('eth_percentage', %s, 'system'),
            ('btc_milestone', %s, 'system'),
            ('eth_milestone', %s, 'system'),
            ('milestone_cooldown', %s, 'system')
        ON CONFLICT (key) DO NOTHING
    """, (
        DEFAULT_MODE, DEFAULT_MODEL, str(DEFAULT_MIN_VOLUME_USD),
        str(DEFAULT_MIN_VOLUME_FUTURES), str(DEFAULT_MIN_VOLUME_SPOT),
        str(DEFAULT_SCAN_INTERVAL), DEFAULT_BTC_ETH_ALERT_MODE,
        str(DEFAULT_BTC_PERCENTAGE), str(DEFAULT_ETH_PERCENTAGE),
        str(DEFAULT_BTC_MILESTONE), str(DEFAULT_ETH_MILESTONE),
        str(DEFAULT_MILESTONE_COOLDOWN)
    ))

    # Scanner logs (monitoring)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_logs (
            id SERIAL PRIMARY KEY,
            scan_count INTEGER NOT NULL,
            pairs_scanned INTEGER NOT NULL,
            alerts_sent INTEGER NOT NULL,
            errors_count INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scanner_logs_date
        ON scanner_logs(created_at)
    """)

    # Session prices (for Model 1 only)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_prices (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            mode VARCHAR(10) NOT NULL,
            session_date DATE NOT NULL,
            session_start_price DECIMAL(20, 8) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(symbol, mode, session_date)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_prices_lookup
        ON session_prices(symbol, mode, session_date)
    """)

    # Custom thresholds for specific symbols (e.g., BTC every 2%, ETH every 3%)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_thresholds (
            symbol VARCHAR(20) PRIMARY KEY,
            thresholds TEXT NOT NULL,
            is_incremental BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by BIGINT
        )
    """)

    # Price milestone history (for milestone-based alerts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS milestone_history (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            milestone DECIMAL(20, 2) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            price_at_detection DECIMAL(20, 8) NOT NULL,
            detected_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_milestone_history_lookup
        ON milestone_history(symbol, milestone, expires_at)
    """)

    # Last known price for milestone detection (tracks real-time movement)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS milestone_last_price (
            symbol VARCHAR(20) PRIMARY KEY,
            last_price DECIMAL(20, 8) NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # 241 mode: short-term trend setting
    cursor.execute("""
        INSERT INTO bot_config (key, value, updated_by) VALUES
            ('short_term_trend', %s, 'system')
        ON CONFLICT (key) DO NOTHING
    """, (DEFAULT_SHORT_TERM_TREND,))

    conn.commit()
    logger.info("✅ Database schema created/verified")


# Configuration helpers
def get_bot_setting(key: str) -> Optional[str]:
    """Get bot configuration value"""
    try:
        conn, cursor = get_connection()
        cursor.execute("SELECT value FROM bot_config WHERE key = %s", (key,))
        result = cursor.fetchone()
        return result['value'] if result else None
    except Exception as e:
        logger.error(f"Error getting bot setting {key}: {e}")
        return None


def set_bot_setting(key: str, value: str, updated_by: str):
    """Update bot configuration"""
    try:
        conn, cursor = get_connection()
        cursor.execute("""
            INSERT INTO bot_config (key, value, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
        """, (key, value, updated_by))
        conn.commit()
        logger.info(f"Setting updated: {key} = {value} by {updated_by}")
    except Exception as e:
        logger.error(f"Error setting bot config {key}: {e}")
        conn.rollback()


def get_all_settings() -> Dict[str, str]:
    """Get all bot settings"""
    try:
        conn, cursor = get_connection()
        cursor.execute("SELECT key, value FROM bot_config")
        results = cursor.fetchall()
        return {row['key']: row['value'] for row in results}
    except Exception as e:
        logger.error(f"Error getting all settings: {e}")
        return {}


# Price snapshot operations
def store_price_snapshot(symbol: str, mode: str, price: float, timestamp: int):
    """Store price snapshot in database"""
    try:
        conn, cursor = get_connection()
        cursor.execute("""
            INSERT INTO price_snapshots (symbol, mode, price, timestamp)
            VALUES (%s, %s, %s, %s)
        """, (symbol, mode, price, timestamp))
        conn.commit()
    except Exception as e:
        logger.error(f"Error storing price snapshot for {symbol}: {e}")
        conn.rollback()


def get_24h_ago_price(symbol: str, mode: str, current_timestamp: int) -> Optional[float]:
    """
    Get the price closest to exactly 24 hours ago.

    Args:
        symbol: Trading pair symbol
        mode: Market mode (futures/spot)
        current_timestamp: Current Unix timestamp

    Returns:
        Price from 24h ago, or None if not found
    """
    try:
        target_timestamp = current_timestamp - 86400  # 24 hours = 86400 seconds
        conn, cursor = get_connection()

        # Find closest price snapshot within 5 minutes of target time
        cursor.execute("""
            SELECT price, timestamp
            FROM price_snapshots
            WHERE symbol = %s AND mode = %s
              AND timestamp BETWEEN %s AND %s
            ORDER BY ABS(timestamp - %s)
            LIMIT 1
        """, (symbol, mode, target_timestamp - 300, target_timestamp + 300, target_timestamp))

        result = cursor.fetchone()

        if result:
            return float(result['price'])
        else:
            logger.debug(f"No 24h history for {symbol}, will use Bybit API")
            return None

    except Exception as e:
        logger.error(f"Error getting 24h ago price for {symbol}: {e}")
        return None


def get_short_term_price(symbol: str, mode: str, current_timestamp: int,
                         lookback_seconds: int = None) -> Optional[float]:
    """
    Get price from X seconds ago for short-term trend detection (241 mode).

    Used to determine the recent trend (e.g., 1h) instead of relying only on 24h.
    This catches dumps/pumps that the 24h filter misses.

    Args:
        symbol: Trading pair symbol
        mode: Market mode (futures/spot)
        current_timestamp: Current Unix timestamp
        lookback_seconds: How far back to look (default from config, ~1 hour)

    Returns:
        Price from lookback period ago, or None if not found
    """
    if lookback_seconds is None:
        lookback_seconds = DEFAULT_SHORT_TERM_LOOKBACK

    try:
        target_timestamp = current_timestamp - lookback_seconds
        conn, cursor = get_connection()

        # Find closest price snapshot within 5 minutes of target time
        cursor.execute("""
            SELECT price, timestamp
            FROM price_snapshots
            WHERE symbol = %s AND mode = %s
              AND timestamp BETWEEN %s AND %s
            ORDER BY ABS(timestamp - %s)
            LIMIT 1
        """, (symbol, mode, target_timestamp - 300, target_timestamp + 300, target_timestamp))

        result = cursor.fetchone()

        if result:
            return float(result['price'])
        else:
            logger.debug(f"No short-term history for {symbol} ({lookback_seconds}s lookback)")
            return None

    except Exception as e:
        logger.error(f"Error getting short-term price for {symbol}: {e}")
        return None


# Session price operations (Model 1)
def get_session_start_price(symbol: str, mode: str) -> Optional[float]:
    """Get price at 00:00 UTC today (Model 1)"""
    try:
        today = datetime.utcnow().date()
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT session_start_price
            FROM session_prices
            WHERE symbol = %s AND mode = %s AND session_date = %s
        """, (symbol, mode, today))

        result = cursor.fetchone()

        if result:
            return float(result['session_start_price'])
        return None

    except Exception as e:
        logger.error(f"Error getting session start price for {symbol}: {e}")
        return None


def set_session_start_price(symbol: str, mode: str, price: float, session_date=None):
    """Set session start price for Model 1"""
    try:
        if session_date is None:
            session_date = datetime.utcnow().date()

        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO session_prices (symbol, mode, session_date, session_start_price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (symbol, mode, session_date)
            DO UPDATE SET session_start_price = EXCLUDED.session_start_price
        """, (symbol, mode, session_date, price))

        conn.commit()

    except Exception as e:
        logger.error(f"Error setting session start price for {symbol}: {e}")
        conn.rollback()


# Alert history operations
def can_fire_alert(symbol: str, threshold: int, current_time: int) -> bool:
    """
    Check if alert can fire (24h deduplication).

    Args:
        symbol: Trading pair symbol
        threshold: Alert threshold (e.g., 10, -10, 30, -30)
        current_time: Current Unix timestamp

    Returns:
        True if alert can fire, False if within cooldown
    """
    try:
        conn, cursor = get_connection()
        mode = get_bot_setting('mode')
        model = get_bot_setting('model')

        cursor.execute("""
            SELECT expires_at
            FROM alert_history
            WHERE symbol = %s
              AND threshold = %s
              AND mode = %s
              AND model = %s
              AND expires_at > %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (symbol, threshold, mode, model, current_time))

        result = cursor.fetchone()

        # Can fire if no unexpired alert exists
        return result is None

    except Exception as e:
        logger.error(f"Error checking if alert can fire for {symbol}: {e}")
        return True  # Allow alert on error to be safe


def record_alert(symbol: str, threshold: int, current_time: int, price: float, pct_change: float):
    """Record alert in history for deduplication"""
    try:
        expires_at = current_time + 86400  # 24 hours from now
        mode = get_bot_setting('mode')
        model = get_bot_setting('model')

        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO alert_history (
                symbol, threshold, mode, model,
                first_detected_at, expires_at,
                price_at_detection, pct_change_at_detection
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            symbol, threshold, mode, model,
            current_time, expires_at, price, pct_change
        ))

        conn.commit()
        logger.debug(f"Alert recorded: {symbol} threshold {threshold}")

    except Exception as e:
        logger.error(f"Error recording alert for {symbol}: {e}")
        conn.rollback()


def get_recent_alerts(hours: int = 24) -> List[Dict]:
    """Get alerts from the last N hours"""
    try:
        conn, cursor = get_connection()
        cutoff_time = int(time.time()) - (hours * 3600)

        cursor.execute("""
            SELECT symbol, threshold, pct_change_at_detection, price_at_detection,
                   first_detected_at, created_at
            FROM alert_history
            WHERE first_detected_at > %s
            ORDER BY created_at DESC
            LIMIT 100
        """, (cutoff_time,))

        return cursor.fetchall()

    except Exception as e:
        logger.error(f"Error getting recent alerts: {e}")
        return []


# Scanner log operations
def log_scan(scan_count: int, pairs_scanned: int, alerts_sent: int,
             errors_count: int, duration_ms: int):
    """Log scan results"""
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO scanner_logs (scan_count, pairs_scanned, alerts_sent, errors_count, duration_ms)
            VALUES (%s, %s, %s, %s, %s)
        """, (scan_count, pairs_scanned, alerts_sent, errors_count, duration_ms))

        conn.commit()

    except Exception as e:
        logger.error(f"Error logging scan: {e}")
        conn.rollback()


def get_last_scan_log() -> Optional[Dict]:
    """Get the most recent scan log"""
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT scan_count, pairs_scanned, alerts_sent, duration_ms, created_at
            FROM scanner_logs
            ORDER BY created_at DESC
            LIMIT 1
        """)

        return cursor.fetchone()

    except Exception as e:
        logger.error(f"Error getting last scan log: {e}")
        return None


def get_scan_stats(hours: int = 24) -> Dict:
    """Get scan statistics for the last N hours"""
    try:
        conn, cursor = get_connection()
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        cursor.execute("""
            SELECT
                COUNT(*) as total_scans,
                SUM(alerts_sent) as total_alerts,
                SUM(errors_count) as total_errors,
                AVG(duration_ms) as avg_duration_ms,
                AVG(pairs_scanned) as avg_pairs
            FROM scanner_logs
            WHERE created_at > %s
        """, (cutoff_time,))

        result = cursor.fetchone()

        return {
            'total_scans': result['total_scans'] or 0,
            'total_alerts': result['total_alerts'] or 0,
            'total_errors': result['total_errors'] or 0,
            'avg_duration_ms': round(float(result['avg_duration_ms'] or 0), 2),
            'avg_pairs': round(float(result['avg_pairs'] or 0), 0)
        }

    except Exception as e:
        logger.error(f"Error getting scan stats: {e}")
        return {'total_scans': 0, 'total_alerts': 0, 'total_errors': 0,
                'avg_duration_ms': 0, 'avg_pairs': 0}


def get_all_time_stats() -> Dict:
    """Get all-time alert statistics (persistent across restarts)"""
    try:
        conn, cursor = get_connection()

        # Get total alerts and date range
        cursor.execute("""
            SELECT
                COALESCE(SUM(alerts_sent), 0) as total_alerts,
                MIN(created_at) as first_scan,
                MAX(created_at) as last_scan,
                COUNT(*) as total_scans
            FROM scanner_logs
        """)

        result = cursor.fetchone()

        total_alerts = int(result['total_alerts'] or 0)
        first_scan = result['first_scan']
        last_scan = result['last_scan']
        total_scans = int(result['total_scans'] or 0)

        # Calculate days active
        if first_scan and last_scan:
            days_active = max(1, (last_scan - first_scan).days + 1)
        else:
            days_active = 1

        # Calculate average per day
        avg_per_day = round(total_alerts / days_active, 1) if days_active > 0 else 0

        return {
            'total_alerts': total_alerts,
            'days_active': days_active,
            'avg_per_day': avg_per_day,
            'total_scans': total_scans,
            'first_scan': first_scan,
            'last_scan': last_scan
        }

    except Exception as e:
        logger.error(f"Error getting all-time stats: {e}")
        return {
            'total_alerts': 0,
            'days_active': 0,
            'avg_per_day': 0,
            'total_scans': 0,
            'first_scan': None,
            'last_scan': None
        }


# Cleanup operations
def cleanup_old_snapshots(retention_hours: int = 48) -> int:
    """Delete snapshots older than retention period"""
    try:
        cutoff_time = int(time.time()) - (retention_hours * 3600)
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM price_snapshots
            WHERE timestamp < %s
        """, (cutoff_time,))

        deleted_count = cursor.rowcount
        conn.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old price snapshots")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up old snapshots: {e}")
        conn.rollback()
        return 0


def cleanup_expired_alerts() -> int:
    """Delete expired alert history records"""
    try:
        current_time = int(time.time())
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM alert_history
            WHERE expires_at < %s
        """, (current_time,))

        deleted_count = cursor.rowcount
        conn.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} expired alerts")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up expired alerts: {e}")
        conn.rollback()
        return 0


def cleanup_old_logs(retention_days: int = 7) -> int:
    """Delete old scanner logs"""
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM scanner_logs
            WHERE created_at < %s
        """, (cutoff_date,))

        deleted_count = cursor.rowcount
        conn.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old scanner logs")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up old logs: {e}")
        conn.rollback()
        return 0


def cleanup_old_sessions(retention_days: int = 7) -> int:
    """Delete old session prices"""
    try:
        cutoff_date = datetime.utcnow().date() - timedelta(days=retention_days)
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM session_prices
            WHERE session_date < %s
        """, (cutoff_date,))

        deleted_count = cursor.rowcount
        conn.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old session prices")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up old sessions: {e}")
        conn.rollback()
        return 0


# Custom threshold operations
def get_custom_thresholds(symbol: str) -> tuple:
    """
    Get custom thresholds for a symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT")

    Returns:
        tuple: (thresholds_list, is_incremental)
            - thresholds_list: List of threshold values, or None if not set
            - is_incremental: If True, thresholds[0] is the increment value
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT thresholds, is_incremental FROM custom_thresholds
            WHERE symbol = %s
        """, (symbol,))

        result = cursor.fetchone()

        if result:
            thresholds_str = result['thresholds']
            is_incremental = result.get('is_incremental', False)

            # Parse thresholds
            thresholds = [int(t) for t in thresholds_str.split(',')]

            return (thresholds, is_incremental)

        return (None, False)

    except Exception as e:
        logger.error(f"Error getting custom thresholds for {symbol}: {e}")
        return (None, False)


def set_custom_thresholds(symbol: str, thresholds: list, is_incremental: bool, user_id: int = None):
    """
    Set custom thresholds for a symbol.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        thresholds: List of threshold values
        is_incremental: If True, thresholds[0] is the increment (alert every X%)
        user_id: Admin user ID who set this

    Examples:
        set_custom_thresholds("BTCUSDT", [2], True, user_id)
        → Alert every ±2%: 2, 4, 6, 8, 10, 12, ...

        set_custom_thresholds("XRPUSDT", [5, 15, 25], False, user_id)
        → Alert at ±5%, ±15%, ±25%
    """
    try:
        thresholds_str = ','.join(str(t) for t in thresholds)

        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO custom_thresholds
            (symbol, thresholds, is_incremental, updated_at, updated_by)
            VALUES (%s, %s, %s, NOW(), %s)
            ON CONFLICT (symbol)
            DO UPDATE SET
                thresholds = EXCLUDED.thresholds,
                is_incremental = EXCLUDED.is_incremental,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
        """, (symbol, thresholds_str, is_incremental, user_id))

        conn.commit()

        mode = "every" if is_incremental else "at"
        logger.info(f"Custom thresholds set for {symbol}: {mode} {thresholds}")

    except Exception as e:
        logger.error(f"Error setting custom thresholds for {symbol}: {e}")
        conn.rollback()


def delete_custom_thresholds(symbol: str) -> bool:
    """
    Delete custom thresholds for a symbol (reset to default).

    Args:
        symbol: Trading pair symbol

    Returns:
        True if deleted, False if not found or error
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM custom_thresholds WHERE symbol = %s
        """, (symbol,))

        deleted = cursor.rowcount > 0
        conn.commit()

        if deleted:
            logger.info(f"Custom thresholds deleted for {symbol}")

        return deleted

    except Exception as e:
        logger.error(f"Error deleting custom thresholds for {symbol}: {e}")
        conn.rollback()
        return False


def get_all_custom_thresholds() -> List[Dict]:
    """
    Get all custom thresholds.

    Returns:
        List of dictionaries with symbol, thresholds, is_incremental
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT symbol, thresholds, is_incremental, updated_at
            FROM custom_thresholds
            ORDER BY symbol
        """)

        return cursor.fetchall()

    except Exception as e:
        logger.error(f"Error getting all custom thresholds: {e}")
        return []


# Milestone alert functions
def can_fire_milestone_alert(symbol: str, milestone: float, direction: str, current_time: int) -> bool:
    """
    Check if milestone alert can fire (24h deduplication).

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        milestone: Price milestone (e.g., 91000 for BTC)
        direction: 'up' or 'down'
        current_time: Current Unix timestamp

    Returns:
        True if alert can fire, False if within cooldown
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT expires_at
            FROM milestone_history
            WHERE symbol = %s
              AND milestone = %s
              AND direction = %s
              AND expires_at > %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (symbol, milestone, direction, current_time))

        result = cursor.fetchone()
        return result is None

    except Exception as e:
        logger.error(f"Error checking milestone alert for {symbol}: {e}")
        return True


def record_milestone_alert(symbol: str, milestone: float, direction: str,
                           price: float, current_time: int):
    """Record milestone alert in history for deduplication."""
    try:
        # Get configurable cooldown (in minutes), default 60 minutes
        cooldown_minutes = int(get_bot_setting('milestone_cooldown') or DEFAULT_MILESTONE_COOLDOWN)
        expires_at = current_time + (cooldown_minutes * 60)  # Convert minutes to seconds

        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO milestone_history (
                symbol, milestone, direction, price_at_detection,
                detected_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (symbol, milestone, direction, price, current_time, expires_at))

        conn.commit()
        logger.debug(f"Milestone recorded: {symbol} ${milestone} ({direction})")

    except Exception as e:
        logger.error(f"Error recording milestone for {symbol}: {e}")
        conn.rollback()


def get_milestone_last_price(symbol: str) -> Optional[float]:
    """
    Get the last known price for milestone tracking.

    This is used to detect real-time milestone crossings by comparing
    last_price to current_price (not 24h reference).

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)

    Returns:
        Last known price or None if not set
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            SELECT last_price FROM milestone_last_price
            WHERE symbol = %s
        """, (symbol,))

        result = cursor.fetchone()
        return float(result['last_price']) if result else None

    except Exception as e:
        logger.error(f"Error getting last price for {symbol}: {e}")
        return None


def set_milestone_last_price(symbol: str, price: float):
    """
    Update the last known price for milestone tracking.

    Called after each scan to track price movement.

    Args:
        symbol: Trading pair symbol
        price: Current price to store
    """
    try:
        conn, cursor = get_connection()

        cursor.execute("""
            INSERT INTO milestone_last_price (symbol, last_price, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (symbol)
            DO UPDATE SET last_price = EXCLUDED.last_price, updated_at = NOW()
        """, (symbol, price))

        conn.commit()

    except Exception as e:
        logger.error(f"Error setting last price for {symbol}: {e}")
        conn.rollback()


def get_crossed_milestones_realtime(current_price: float, last_price: float,
                                     milestone_step: int) -> List[Dict]:
    """
    Calculate which price milestones have been crossed since last check.

    This compares CURRENT price to LAST KNOWN price (not 24h reference)
    to detect real-time milestone crossings.

    DEPRECATED: Use get_current_milestone_24h instead for 24h rolling reference approach.

    Args:
        current_price: Current price
        last_price: Last known price from previous scan
        milestone_step: Milestone increment (e.g., 1000 for BTC, 100 for ETH)

    Returns:
        List of crossed milestones with direction

    Example:
        last_price = 65500, current_price = 64900, step = 1000
        → Crossed $65,000 going DOWN
        → Returns [{'milestone': 65000, 'direction': 'down'}]
    """
    milestones = []

    if current_price == last_price:
        return milestones

    direction = 'up' if current_price > last_price else 'down'
    low_price = min(current_price, last_price)
    high_price = max(current_price, last_price)

    # Find the first milestone above low_price
    first_milestone = ((int(low_price) // milestone_step) + 1) * milestone_step

    # Generate all milestones between low and high
    milestone = first_milestone
    while milestone <= high_price:
        milestones.append({
            'milestone': milestone,
            'direction': direction
        })
        milestone += milestone_step

    return milestones


def get_current_milestone_24h(current_price: float, reference_price_24h: float,
                               milestone_step: int) -> Optional[Dict]:
    """
    DEPRECATED: Use get_milestone_realtime_with_trend instead.
    Kept for backwards compatibility.
    """
    if current_price == reference_price_24h:
        return None

    current_level = (int(current_price) // milestone_step) * milestone_step
    reference_level = (int(reference_price_24h) // milestone_step) * milestone_step

    if current_level == reference_level:
        return None

    pct_change = ((current_price - reference_price_24h) / reference_price_24h) * 100

    if pct_change < 0:
        return {'milestone': current_level, 'direction': 'down'}
    else:
        return {'milestone': current_level, 'direction': 'up'}

    return None


def get_milestone_realtime_with_trend(
    symbol: str,
    current_price: float,
    reference_price_24h: float,
    milestone_step: int,
    short_term_ref_price: float = None
) -> Optional[Dict]:
    """
    Get milestone alert using REAL-TIME level tracking + trend filter.

    Logic:
    1. Track last known milestone level (real-time)
    2. Determine direction by HOW price entered the zone (not 24h ref)
    3. Filter alerts based on trend:
       - If 241 mode ON (short_term_ref_price provided): use 1h trend
       - If 241 mode OFF: use 24h trend (original behavior)
       - Bearish trend → only allow "DROPS TO" alerts
       - Bullish trend → only allow "BREAKS" alerts

    The 241 mode fixes false "BREAKS" alerts during dumps where the 24h
    change is positive but the short-term move is clearly bearish.

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        current_price: Current price
        reference_price_24h: 24h reference price for trend filter (fallback)
        milestone_step: Milestone increment (e.g., 1000 for BTC, 100 for ETH)
        short_term_ref_price: Price from ~1h ago (241 mode). If provided,
                              used as primary trend filter instead of 24h.

    Returns:
        Dict with 'milestone' and 'direction', or None if no alert should fire

    Examples:
        # 241 ON: BTC dumped from $71k to $68k, 1h ago was $71k
        # 24h ref is $65k (looks bullish), but 1h ref is $71k (bearish)
        >>> get_milestone_realtime_with_trend('BTCUSDT', 68100, 65000, 1000, 71000)
        None  # BLOCKS false "BREAKS $68k" - 1h trend is bearish

        # 241 OFF: Same scenario falls back to 24h trend
        >>> get_milestone_realtime_with_trend('BTCUSDT', 68100, 65000, 1000)
        {'milestone': 68000, 'direction': 'up'}  # Would fire (24h looks bullish)
    """
    # Calculate current milestone level (floor)
    current_level = (int(current_price) // milestone_step) * milestone_step

    # Get last known price and calculate its level
    last_price = get_milestone_last_price(symbol)

    if last_price is None:
        # First run - store current price and return (no alert)
        set_milestone_last_price(symbol, current_price)
        logger.info(f"Initialized milestone tracking for {symbol} at ${current_price:,.2f} (level ${current_level:,})")
        return None

    last_level = (int(last_price) // milestone_step) * milestone_step

    # Always update stored price for next scan
    set_milestone_last_price(symbol, current_price)

    # Check if we moved to a different level
    if current_level == last_level:
        return None  # Same level, no alert

    # Determine REAL-TIME direction (how price entered this zone)
    if current_level > last_level:
        realtime_direction = 'up'  # Price rose into this zone
    else:
        realtime_direction = 'down'  # Price fell into this zone

    # Select trend reference: 1h (241 mode) or 24h (default)
    if short_term_ref_price and short_term_ref_price > 0:
        trend_ref_price = short_term_ref_price
        trend_label = "1h"
    else:
        trend_ref_price = reference_price_24h
        trend_label = "24h"

    # Calculate trend from selected reference
    pct_change_trend = ((current_price - trend_ref_price) / trend_ref_price) * 100
    is_bullish = pct_change_trend >= 0

    # Apply trend filter
    # Only send alert if real-time direction MATCHES trend
    if realtime_direction == 'up' and not is_bullish:
        # Price moved up but trend is bearish - SKIP (dead cat bounce)
        logger.debug(f"{symbol}: Skipping BREAKS alert ({trend_label} trend bearish: {pct_change_trend:.2f}%)")
        return None

    if realtime_direction == 'down' and is_bullish:
        # Price moved down but trend is bullish - SKIP (healthy pullback)
        logger.debug(f"{symbol}: Skipping DROPS alert ({trend_label} trend bullish: {pct_change_trend:.2f}%)")
        return None

    # Alert direction matches trend - allow alert
    logger.debug(f"{symbol}: Milestone ${current_level:,} ({realtime_direction}) allowed by {trend_label} trend ({pct_change_trend:+.2f}%)")
    return {
        'milestone': current_level,
        'direction': realtime_direction
    }


def get_crossed_milestones(symbol: str, current_price: float, reference_price: float,
                           milestone_step: int) -> List[Dict]:
    """
    Calculate which price milestones have been crossed.

    DEPRECATED: Use get_crossed_milestones_realtime instead.
    This function is kept for backwards compatibility.

    Args:
        symbol: Trading pair symbol
        current_price: Current price
        reference_price: Reference price (24h ago)
        milestone_step: Milestone increment (e.g., 1000 for BTC, 100 for ETH)

    Returns:
        List of crossed milestones with direction
    """
    milestones = []

    if current_price == reference_price:
        return milestones

    direction = 'up' if current_price > reference_price else 'down'
    low_price = min(current_price, reference_price)
    high_price = max(current_price, reference_price)

    # Find the first milestone above low_price
    first_milestone = ((int(low_price) // milestone_step) + 1) * milestone_step

    # Generate all milestones between low and high
    milestone = first_milestone
    while milestone <= high_price:
        milestones.append({
            'milestone': milestone,
            'direction': direction
        })
        milestone += milestone_step

    return milestones


def cleanup_expired_milestones() -> int:
    """Delete expired milestone history records."""
    try:
        current_time = int(time.time())
        conn, cursor = get_connection()

        cursor.execute("""
            DELETE FROM milestone_history
            WHERE expires_at < %s
        """, (current_time,))

        deleted_count = cursor.rowcount
        conn.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} expired milestones")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up milestones: {e}")
        conn.rollback()
        return 0


def close_connection():
    """Close database connection"""
    global _conn, _cursor

    try:
        if _cursor:
            _cursor.close()
        if _conn:
            _conn.close()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database connection: {e}")
    finally:
        _conn = None
        _cursor = None
