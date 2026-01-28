"""Logging configuration"""
import logging
import sys
from bot.config import LOG_LEVEL, LOG_FORMAT

def setup_logger(name: str = 'bot') -> logging.Logger:
    """
    Set up and return a configured logger.

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Formatter
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    return logger

# Default logger instance
logger = setup_logger('bot')
