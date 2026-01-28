"""Configuration and environment variables"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')  # @channel or -100123456789
ADMIN_USER_IDS = [int(id.strip()) for id in os.getenv('ADMIN_USER_IDS', '').split(',') if id.strip()]

# Database
DATABASE_URL = os.getenv('DATABASE_URL')

# Bybit API
BYBIT_API_BASE = "https://api.bybit.com"
BYBIT_API_TIMEOUT = 10  # seconds

# Adjust Links (Fixed - No database needed)
GAINER_LINK = "https://mudrex.go.link/FuturesGainer"
LOSER_LINK = "https://mudrex.go.link/TopLosers"

# Default Settings (can be changed via commands)
DEFAULT_MODE = 'futures'  # 'futures' or 'spot'
DEFAULT_MODEL = 'model2'  # 'model1' or 'model2'
DEFAULT_MIN_VOLUME_USD = 5_000_000  # $5M
DEFAULT_SCAN_INTERVAL = 30  # seconds

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
