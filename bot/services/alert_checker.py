"""Alert threshold checking and sending"""
import time
from typing import List, Dict, Optional, Tuple

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import (
    BASE_THRESHOLDS, EXTENDED_THRESHOLD_STEP, MAX_THRESHOLD,
    TELEGRAM_CHANNEL_ID, TELEGRAM_TOPIC_ID
)
from bot.services.database import (
    get_bot_setting, get_24h_ago_price, get_session_start_price,
    can_fire_alert, record_alert, get_custom_thresholds,
    can_fire_milestone_alert, record_milestone_alert, get_crossed_milestones
)
from bot.utils.formatters import format_alert_message, get_symbol_link
from bot.utils.logger import logger


def get_crossed_thresholds(pct_change: float, custom_thresholds: List[int] = None,
                           is_incremental: bool = False) -> List[int]:
    """
    Determine which thresholds were crossed.

    Supports two modes:
    1. Standard mode (default): Specific thresholds like [10, 30, 60, 80, 100]
    2. Incremental mode: Alert every X% (e.g., [2] means every 2%)

    Args:
        pct_change: Percentage change from reference price
        custom_thresholds: Custom thresholds for this symbol (optional)
        is_incremental: If True, custom_thresholds[0] is the increment

    Returns:
        List of crossed thresholds (positive or negative based on direction)

    Examples:
        # Standard mode
        >>> get_crossed_thresholds(25, None, False)
        [10]  # Only 10% crossed, 30% not yet

        # Incremental mode (every 2%)
        >>> get_crossed_thresholds(7, [2], True)
        [2, 4, 6]  # Hit 2%, 4%, 6%, but not 8% yet

        >>> get_crossed_thresholds(-11, [3], True)
        [-3, -6, -9]  # Hit -3%, -6%, -9%, but not -12% yet
    """
    thresholds = []
    abs_change = abs(pct_change)
    sign = 1 if pct_change >= 0 else -1

    if custom_thresholds and is_incremental:
        # INCREMENTAL MODE: Alert every X%
        # Example: BTC with increment=2%, change=7% → fire [2, 4, 6]
        increment = custom_thresholds[0]

        # Calculate how many increments have been crossed
        num_increments = int(abs_change / increment)

        # Generate all crossed thresholds
        for i in range(1, num_increments + 1):
            threshold = i * increment
            thresholds.append(threshold * sign)

        return thresholds

    # STANDARD MODE: Specific thresholds
    # Use custom thresholds if provided, otherwise use defaults
    base_thresholds = custom_thresholds if custom_thresholds else BASE_THRESHOLDS

    for threshold in base_thresholds:
        if abs_change >= threshold:
            thresholds.append(threshold * sign)

    # Extended thresholds (after 100%) - only for standard mode
    if abs_change >= 100 and not custom_thresholds:
        current_threshold = 100 + EXTENDED_THRESHOLD_STEP

        while current_threshold <= MAX_THRESHOLD and abs_change >= current_threshold:
            thresholds.append(current_threshold * sign)
            current_threshold += EXTENDED_THRESHOLD_STEP

    return thresholds


def get_symbol_thresholds(symbol: str) -> Tuple[Optional[List[int]], bool]:
    """
    Get thresholds for a specific symbol.

    Checks for custom thresholds first, falls back to defaults.

    Args:
        symbol: Trading pair symbol

    Returns:
        Tuple of (thresholds_list, is_incremental)
    """
    # Check for custom thresholds
    custom, is_incremental = get_custom_thresholds(symbol)

    if custom:
        return (custom, is_incremental)

    # Return None to use defaults
    return (None, False)


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

    Uses symbol-specific links for BTC and ETH, otherwise gainer/loser links.

    Args:
        symbol: Trading pair symbol
        pct_change: Percentage change

    Returns:
        InlineKeyboardMarkup with trade button
    """
    button_text = f"💰 TRADE NOW - {symbol} 🔥"
    url = get_symbol_link(symbol, pct_change)

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

        # Build message parameters
        send_params = {
            'chat_id': TELEGRAM_CHANNEL_ID,
            'text': message,
            'reply_markup': keyboard,
            'parse_mode': 'HTML'
        }

        # Add topic ID if configured (for forum groups)
        if TELEGRAM_TOPIC_ID:
            send_params['message_thread_id'] = TELEGRAM_TOPIC_ID

        # Send to channel/topic
        await bot.send_message(**send_params)

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

    Supports custom incremental thresholds per symbol.

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

    # Get custom thresholds for this symbol (if any)
    custom_thresholds, is_incremental = get_symbol_thresholds(symbol)

    # Get crossed thresholds
    crossed_thresholds = get_crossed_thresholds(pct_change, custom_thresholds, is_incremental)

    if not crossed_thresholds:
        return False, 0

    # Log if using custom thresholds
    if custom_thresholds:
        mode_str = f"every ±{custom_thresholds[0]}%" if is_incremental else f"at {custom_thresholds}"
        logger.debug(f"{symbol}: Using custom thresholds ({mode_str})")

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


def format_milestone_alert(symbol: str, current_price: float, milestone: float,
                            direction: str, volume_24h: float) -> str:
    """
    Format Telegram milestone alert message.

    Args:
        symbol: Trading pair symbol
        current_price: Current price
        milestone: Price milestone crossed
        direction: 'up' or 'down'
        volume_24h: 24-hour trading volume

    Returns:
        Formatted milestone alert message
    """
    if direction == 'up':
        title_emoji = "🚀"
        alert_type = "PRICE MILESTONE!"
        arrow = "↑"
    else:
        title_emoji = "📉"
        alert_type = "PRICE MILESTONE!"
        arrow = "↓"

    # Format prices
    if current_price >= 1:
        price_format = ",.2f"
    elif current_price >= 0.001:
        price_format = ",.4f"
    else:
        price_format = ",.8f"

    # Format volume
    if volume_24h >= 1_000_000_000:
        volume_str = f"${volume_24h / 1_000_000_000:.2f}B"
    elif volume_24h >= 1_000_000:
        volume_str = f"${volume_24h / 1_000_000:.2f}M"
    else:
        volume_str = f"${volume_24h:,.0f}"

    message = f"""
{title_emoji} <b>{alert_type}</b> ${milestone:,.0f} {arrow}

💰 <b>{symbol}</b>
📈 Current: ${current_price:{price_format}}
🎯 Crossed: ${milestone:,.0f}
💵 Volume: {volume_str}
"""

    return message.strip()


async def send_milestone_alert(
    bot: Bot,
    symbol: str,
    current_price: float,
    milestone: float,
    direction: str,
    volume_24h: float
) -> bool:
    """
    Send milestone alert to Telegram channel.

    Args:
        bot: Telegram bot instance
        symbol: Trading pair symbol
        current_price: Current price
        milestone: Price milestone crossed
        direction: 'up' or 'down'
        volume_24h: 24-hour trading volume

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Format message
        message = format_milestone_alert(
            symbol, current_price, milestone, direction, volume_24h
        )

        # Create keyboard with symbol-specific link
        pct_change = 1 if direction == 'up' else -1  # Dummy for link selection
        keyboard = create_alert_keyboard(symbol, pct_change)

        # Build message parameters
        send_params = {
            'chat_id': TELEGRAM_CHANNEL_ID,
            'text': message,
            'reply_markup': keyboard,
            'parse_mode': 'HTML'
        }

        # Add topic ID if configured
        if TELEGRAM_TOPIC_ID:
            send_params['message_thread_id'] = TELEGRAM_TOPIC_ID

        await bot.send_message(**send_params)

        logger.info(f"Milestone alert sent: {symbol} ${milestone} ({direction})")
        return True

    except Exception as e:
        logger.error(f"Failed to send milestone alert for {symbol}: {e}")
        return False


def is_btc_eth_milestone_mode() -> bool:
    """Check if BTC/ETH are in milestone alert mode."""
    alert_mode = get_bot_setting('btc_eth_alert_mode') or 'percentage'
    return alert_mode == 'milestone'


def get_btc_eth_milestone_step(symbol: str) -> Optional[int]:
    """
    Get milestone step for BTC or ETH.

    Args:
        symbol: Trading pair symbol

    Returns:
        Milestone step (e.g., 1000 for BTC, 100 for ETH) or None
    """
    if 'BTC' in symbol.upper():
        return int(get_bot_setting('btc_milestone') or 1000)
    elif 'ETH' in symbol.upper():
        return int(get_bot_setting('eth_milestone') or 100)
    return None


async def check_and_send_milestone_alerts(
    bot: Bot,
    symbol: str,
    current_price: float,
    ticker: Dict,
    current_time: int
) -> Tuple[bool, int]:
    """
    Check and send milestone-based alerts for BTC/ETH.

    Only used when btc_eth_alert_mode is 'milestone'.

    Args:
        bot: Telegram bot instance
        symbol: Trading pair symbol
        current_price: Current price
        ticker: Full ticker data
        current_time: Current Unix timestamp

    Returns:
        Tuple of (alert_sent, number_of_alerts)
    """
    # Get milestone step for this symbol
    milestone_step = get_btc_eth_milestone_step(symbol)

    if not milestone_step:
        return False, 0

    # Get reference price
    reference_price = get_reference_price(symbol, ticker, current_time)

    if not reference_price or reference_price == 0:
        return False, 0

    # Calculate crossed milestones
    crossed = get_crossed_milestones(symbol, current_price, reference_price, milestone_step)

    if not crossed:
        return False, 0

    alerts_sent = 0
    volume_24h = float(ticker.get('turnover24h', 0))

    for item in crossed:
        milestone = item['milestone']
        direction = item['direction']

        if can_fire_milestone_alert(symbol, milestone, direction, current_time):
            success = await send_milestone_alert(
                bot, symbol, current_price, milestone, direction, volume_24h
            )

            if success:
                record_milestone_alert(symbol, milestone, direction, current_price, current_time)
                alerts_sent += 1
                logger.info(f"🎯 Milestone fired: {symbol} ${milestone} ({direction})")

    return alerts_sent > 0, alerts_sent
