"""Configuration and environment variables"""
import os
import logging
from dotenv import load_dotenv

from bot.utils.token_masker import mask_token, mask_database_url

load_dotenv()

logger = logging.getLogger(__name__)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')  # @channel or -100123456789
TELEGRAM_TOPIC_ID = os.getenv('TELEGRAM_TOPIC_ID')  # Topic/Thread ID for forum groups (optional)
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv('ADMIN_USER_IDS', '').split(',') if id.strip()]

# Parse topic ID as integer if provided
if TELEGRAM_TOPIC_ID:
    try:
        TELEGRAM_TOPIC_ID = int(TELEGRAM_TOPIC_ID)
    except ValueError:
        TELEGRAM_TOPIC_ID = None

# Database
DATABASE_URL = os.getenv('DATABASE_URL')

# Bybit API
BYBIT_API_BASE = "https://api.bybit.com"
BYBIT_API_TIMEOUT = 10  # seconds

# Adjust Links (Fixed - No database needed)
GAINER_LINK = "https://mudrex.go.link/FuturesGainer"
LOSER_LINK = "https://mudrex.go.link/TopLosers"

# Custom links for BTC and ETH
BTC_LINK = "https://mudrex.go.link/1Yogo"
ETH_LINK = "https://mudrex.go.link/kmYNX"

# Default Settings (can be changed via commands)
DEFAULT_MODE = 'futures'  # 'futures' or 'spot'
DEFAULT_MODEL = 'model2'  # 'model1' or 'model2'
DEFAULT_MIN_VOLUME_USD = 5_000_000  # $5M (default, separate for futures/spot)
DEFAULT_MIN_VOLUME_FUTURES = 25_000_000  # $25M for futures
DEFAULT_MIN_VOLUME_SPOT = 25_000_000  # $25M for spot
DEFAULT_SCAN_INTERVAL = 30  # seconds

# BTC/ETH Alert Mode (percentage or milestone)
# 'percentage' = alert every X% (e.g., 3% for BTC, 2% for ETH)
# 'milestone' = alert at price milestones (e.g., every $1000 for BTC, every $100 for ETH)
DEFAULT_BTC_ETH_ALERT_MODE = 'percentage'
DEFAULT_BTC_PERCENTAGE = 3  # Alert every ±3%
DEFAULT_ETH_PERCENTAGE = 2  # Alert every ±2%
DEFAULT_BTC_MILESTONE = 1000  # Alert every $1000 (90000, 91000, 92000)
DEFAULT_ETH_MILESTONE = 100  # Alert every $100 (3100, 3200, 3300)
DEFAULT_MILESTONE_COOLDOWN = 1440  # Minutes between same milestone alerts (24 hours default)

# Thresholds
# Base: ±10%, ±30%, ±60%, ±80%, ±100%
# After ±100%: Alert every ±50%
BASE_THRESHOLDS = [10, 30, 60, 80, 100]
EXTENDED_THRESHOLD_STEP = 50  # After ±100%, alert every ±50%
MAX_THRESHOLD = 950  # Maximum threshold to track

# Data Retention
PRICE_SNAPSHOT_RETENTION_HOURS = 48
ALERT_HISTORY_RETENTION_HOURS = 48  # Keep for deduplication
SCANNER_LOG_DAYS = 7

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = '%(asctime)s | %(levelname)s | %(name)s | %(message)s'

# Validation
def validate_config():
    """Validate required configuration"""
    errors = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is required")

    if not TELEGRAM_CHANNEL_ID:
        errors.append("TELEGRAM_CHANNEL_ID is required")

    if not DATABASE_URL:
        errors.append("DATABASE_URL is required")

    if not ADMIN_USER_IDS:
        errors.append("ADMIN_USER_IDS is required (at least one admin)")

    return errors


def log_masked_config():
    """Log configuration with masked credentials (safe for production logs)"""
    logger.info("=" * 50)
    logger.info("BOT CONFIGURATION LOADED")
    logger.info("=" * 50)
    logger.info(f"Bot Token: {mask_token(TELEGRAM_BOT_TOKEN)}")
    logger.info(f"Channel ID: {TELEGRAM_CHANNEL_ID}")
    logger.info(f"Topic ID: {TELEGRAM_TOPIC_ID or 'Not configured'}")
    logger.info(f"Admin IDs: {len(ADMIN_USER_IDS)} configured")
    logger.info(f"Database: {mask_database_url(DATABASE_URL)}")
    logger.info(f"Min Volume: ${DEFAULT_MIN_VOLUME_USD:,.0f}")
    logger.info(f"Scan Interval: {DEFAULT_SCAN_INTERVAL}s")
    logger.info(f"Default Thresholds: {BASE_THRESHOLDS}")
    logger.info("=" * 50)
