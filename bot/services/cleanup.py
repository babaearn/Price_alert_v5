"""Data cleanup and retention management"""
from bot.config import (
    PRICE_SNAPSHOT_RETENTION_HOURS,
    ALERT_HISTORY_RETENTION_HOURS,
    SCANNER_LOG_DAYS
)
from bot.services.database import (
    cleanup_old_snapshots,
    cleanup_expired_alerts,
    cleanup_old_logs,
    cleanup_old_sessions,
    cleanup_expired_milestones
)
from bot.utils.logger import logger


def run_cleanup():
    """
    Run all cleanup tasks.

    Called hourly by APScheduler to maintain database size.

    Cleanup tasks:
    - Delete price snapshots older than 48 hours
    - Delete expired alert history records
    - Delete scanner logs older than 7 days
    - Delete old session prices (Model 1)
    """
    logger.info("Starting cleanup tasks...")

    total_deleted = 0

    # Clean price snapshots
    try:
        snapshots_deleted = cleanup_old_snapshots(PRICE_SNAPSHOT_RETENTION_HOURS)
        total_deleted += snapshots_deleted
    except Exception as e:
        logger.error(f"Snapshot cleanup failed: {e}")

    # Clean expired alerts
    try:
        alerts_deleted = cleanup_expired_alerts()
        total_deleted += alerts_deleted
    except Exception as e:
        logger.error(f"Alert cleanup failed: {e}")

    # Clean old logs
    try:
        logs_deleted = cleanup_old_logs(SCANNER_LOG_DAYS)
        total_deleted += logs_deleted
    except Exception as e:
        logger.error(f"Log cleanup failed: {e}")

    # Clean old sessions
    try:
        sessions_deleted = cleanup_old_sessions(SCANNER_LOG_DAYS)
        total_deleted += sessions_deleted
    except Exception as e:
        logger.error(f"Session cleanup failed: {e}")

    # Clean expired milestones
    try:
        milestones_deleted = cleanup_expired_milestones()
        total_deleted += milestones_deleted
    except Exception as e:
        logger.error(f"Milestone cleanup failed: {e}")

    if total_deleted > 0:
        logger.info(f"✅ Cleanup complete: {total_deleted} total records deleted")
    else:
        logger.debug("Cleanup complete: no records to delete")


def get_storage_stats() -> dict:
    """
    Get database storage statistics.

    Returns:
        Dictionary with table row counts
    """
    from bot.services.database import get_connection

    conn, cursor = get_connection()

    stats = {}

    # Count rows in each table
    tables = ['price_snapshots', 'alert_history', 'scanner_logs', 'session_prices', 'milestone_history']

    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            result = cursor.fetchone()
            stats[table] = result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get count for {table}: {e}")
            stats[table] = 'error'

    return stats
