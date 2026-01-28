"""PostgreSQL database operations"""
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import time
from typing import Optional, Dict, Any, List

from bot.config import (
    DATABASE_URL, DEFAULT_MODE, DEFAULT_MODEL,
    DEFAULT_MIN_VOLUME_USD, DEFAULT_SCAN_INTERVAL
)
from bot.utils.logger import logger

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
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
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
            ('scan_interval', %s, 'system'),
            ('paused', 'false', 'system')
        ON CONFLICT (key) DO NOTHING
    """, (DEFAULT_MODE, DEFAULT_MODEL, str(DEFAULT_MIN_VOLUME_USD), str(DEFAULT_SCAN_INTERVAL)))

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
