"""Alert threshold checking and sending"""
import time
from typing import List, Dict, Optional, Tuple

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import (
    BASE_THRESHOLDS, EXTENDED_THRESHOLD_STEP, MAX_THRESHOLD,
    GAINER_LINK, LOSER_LINK, TELEGRAM_CHANNEL_ID
)
from bot.services.database import (
    get_bot_setting, get_24h_ago_price, get_session_start_price,
    can_fire_alert, record_alert
)
from bot.utils.formatters import format_alert_message, get_adjust_link
from bot.utils.logger import logger


def get_crossed_thresholds(pct_change: float) -> List[int]:
    """
    Determine which thresholds were crossed.

    Threshold sequence:
    - Base: ±10%, ±30%, ±60%, ±80%, ±100%
    - After ±100%: Every ±50% (±150%, ±200%, ±250%, ..., ±950%)

    Args:
        pct_change: Percentage change from reference price

    Returns:
        List of crossed thresholds (positive or negative based on direction)
    """
    thresholds = []
    abs_change = abs(pct_change)

    # Base thresholds
    for threshold in BASE_THRESHOLDS:
        if abs_change >= threshold:
            thresholds.append(threshold if pct_change > 0 else -threshold)

    # Extended thresholds (after 100%)
    if abs_change >= 100:
        # Calculate how many 50% increments past 100%
        current_threshold = 100 + EXTENDED_THRESHOLD_STEP

        while current_threshold <= MAX_THRESHOLD and abs_change >= current_threshold:
            thresholds.append(current_threshold if pct_change > 0 else -current_threshold)
            current_threshold += EXTENDED_THRESHOLD_STEP

    return thresholds


def get_highest_crossed_threshold(pct_change: float) -> Optional[int]:
    """
    Get the highest threshold that was crossed.

    Args:
        pct_change: Percentage change

    Returns:
        Highest crossed threshold or None
    """
    thresholds = get_crossed_thresholds(pct_change)
    if not thresholds:
        return None

    # Return the threshold with highest absolute value
    return max(thresholds, key=abs)


def get_reference_price(symbol: str, ticker: Dict, current_time: int) -> Optional[float]:
    """
    Get reference price based on current calculation model.

    Model 1 (Session-based): Price at 00:00 UTC
    Model 2 (Rolling 24h): Price 24 hours ago

    Args:
        symbol: Trading pair symbol
        ticker: Ticker data from Bybit API
        current_time: Current Unix timestamp

    Returns:
        Reference price or None if unavailable
    """
    model = get_bot_setting('model')
    mode = get_bot_setting('mode')

    if model == 'model1':
        # Session-based (00:00 UTC reset)
        price = get_session_start_price(symbol, mode)
        if price is not None:
            return price
        # Fallback to Bybit's prevPrice24h for Model 1 as well
        return float(ticker.get('prevPrice24h', 0))

    else:
        # Rolling 24h window (Model 2 - default)
        price = get_24h_ago_price(symbol, mode, current_time)

        if price is None:
            # Fallback to Bybit API's prevPrice24h
            # This is used on cold start before we have 24h of data
            price = float(ticker.get('prevPrice24h', 0))
            logger.debug(f"Using Bybit prevPrice24h for {symbol}: {price}")

        return price


def calculate_percentage_change(current_price: float, reference_price: float) -> float:
    """
    Calculate percentage change.

    Implements Bybit's exact gainer/loser logic:
    - pct_change = ((current_price - reference_price) / reference_price) * 100
    - pct_change > 0 → GAINER
    - pct_change < 0 → LOSER
    - pct_change == 0 → NEUTRAL

    Args:
        current_price: Current price
        reference_price: Reference price (24h ago or session start)

    Returns:
        Percentage change
    """
    if reference_price == 0:
        return 0.0

    return ((current_price - reference_price) / reference_price) * 100


def create_alert_keyboard(symbol: str, pct_change: float) -> InlineKeyboardMarkup:
    """
    Create inline keyboard with trade button.

    Args:
        symbol: Trading pair symbol
        pct_change: Percentage change

    Returns:
        InlineKeyboardMarkup with trade button
    """
    button_text = f"💰 TRADE NOW - {symbol} 🔥"
    url = get_adjust_link(pct_change)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(button_text, url=url)]
    ])

    return keyboard


async def send_alert(
    bot: Bot,
    symbol: str,
    current_price: float,
    reference_price: float,
    pct_change: float,
    volume_24h: float
) -> bool:
    """
    Send formatted alert to Telegram channel.

    Args:
        bot: Telegram bot instance
        symbol: Trading pair symbol
        current_price: Current price
        reference_price: Reference price
        pct_change: Percentage change
        volume_24h: 24-hour trading volume

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Format message
        message = format_alert_message(
            symbol, current_price, reference_price,
            pct_change, volume_24h
        )

        # Create keyboard
        keyboard = create_alert_keyboard(symbol, pct_change)

        # Send to channel
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

        logger.info(f"Alert sent: {symbol} {pct_change:+.2f}%")
        return True

    except Exception as e:
        logger.error(f"Failed to send alert for {symbol}: {e}")
        return False


async def check_and_send_alerts(
    bot: Bot,
    symbol: str,
    current_price: float,
    ticker: Dict,
    current_time: int
) -> Tuple[bool, int]:
    """
    Check if thresholds crossed and send alerts.

    Args:
        bot: Telegram bot instance
        symbol: Trading pair symbol
        current_price: Current price
        ticker: Full ticker data from Bybit API
        current_time: Current Unix timestamp

    Returns:
        Tuple of (alert_sent, number_of_alerts)
    """
    # Get reference price based on model
    reference_price = get_reference_price(symbol, ticker, current_time)

    if not reference_price or reference_price == 0:
        return False, 0

    # Calculate percentage change
    pct_change = calculate_percentage_change(current_price, reference_price)

    # Get crossed thresholds
    crossed_thresholds = get_crossed_thresholds(pct_change)

    if not crossed_thresholds:
        return False, 0

    # Check each threshold
    alerts_sent = 0
    volume_24h = float(ticker.get('turnover24h', 0))

    for threshold in crossed_thresholds:
        if can_fire_alert(symbol, threshold, current_time):
            # Send alert
            success = await send_alert(
                bot, symbol, current_price, reference_price,
                pct_change, volume_24h
            )

            if success:
                # Record alert in history
                record_alert(symbol, threshold, current_time, current_price, pct_change)
                alerts_sent += 1
                logger.info(f"🚨 Alert fired: {symbol} {pct_change:+.2f}% (threshold: {threshold:+d}%)")

    return alerts_sent > 0, alerts_sent


def classify_movement(pct_change: float) -> str:
    """
    Classify price movement.

    Args:
        pct_change: Percentage change

    Returns:
        'GAINER', 'LOSER', or 'NEUTRAL'
    """
    if pct_change > 0:
        return "GAINER"
    elif pct_change < 0:
        return "LOSER"
    else:
        return "NEUTRAL"
