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
    can_fire_alert, record_alerts_batch, get_custom_thresholds,
    can_fire_milestone_alert, record_milestone_alert,
    record_milestone_alerts_batch,
    get_milestone_realtime_with_trend, get_short_term_price
)
from bot.utils.formatters import format_alert_message, get_symbol_link
from bot.utils.logger import logger


def _perf_inc(perf: Optional[Dict[str, int]], key: str, amount: int = 1):
    """Increment a lightweight scan performance counter."""
    if perf is None:
        return
    perf[key] = perf.get(key, 0) + amount


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


def get_reference_price(
    symbol: str,
    ticker: Dict,
    current_time: int,
    model: Optional[str] = None,
    mode: Optional[str] = None
) -> Optional[float]:
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
    model = model or get_bot_setting('model')
    mode = mode or get_bot_setting('mode')

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


def create_alert_keyboard_custom(display_name: str, symbol: str, pct_change: float) -> InlineKeyboardMarkup:
    """
    Create inline keyboard with custom display name.

    Args:
        display_name: Name to display on button (e.g., "BTC")
        symbol: Full symbol for link detection (e.g., "BTCUSDT")
        pct_change: Percentage change

    Returns:
        InlineKeyboardMarkup with trade button
    """
    button_text = f"💰 TRADE NOW - {display_name} 🔥"
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

        # Create keyboard with short name (SOL instead of SOLUSDT)
        short_name = symbol.replace('USDT', '').replace('PERP', '')
        keyboard = create_alert_keyboard_custom(short_name, symbol, pct_change)

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
    current_time: int,
    mode: Optional[str] = None,
    model: Optional[str] = None,
    perf: Optional[Dict[str, int]] = None
) -> Tuple[bool, int]:
    """
    Check if thresholds crossed and send alerts.

    Only sends ONE alert for the HIGHEST crossed threshold to avoid duplicates.
    E.g., if +69% crosses 10%, 30%, 60% → only alert once for 60%

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
    reference_price = get_reference_price(
        symbol, ticker, current_time, model=model, mode=mode
    )

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

    volume_24h = float(ticker.get('turnover24h', 0))

    # Find the HIGHEST threshold that can fire (to avoid duplicate alerts)
    # Sort by absolute value descending to get highest first
    sorted_thresholds = sorted(crossed_thresholds, key=abs, reverse=True)

    for threshold in sorted_thresholds:
        _perf_inc(perf, 'percentage_cooldown_checks')
        if can_fire_alert(symbol, threshold, current_time):
            # Send ONE alert for the highest threshold
            success = await send_alert(
                bot, symbol, current_price, reference_price,
                pct_change, volume_24h
            )

            if success:
                # Record fired threshold + lower crossed thresholds in one batch write.
                thresholds_to_record = [
                    t for t in sorted_thresholds if abs(t) <= abs(threshold)
                ]
                _perf_inc(perf, 'legacy_alert_write_calls', len(thresholds_to_record))
                _perf_inc(perf, 'new_alert_write_calls', 1)
                _perf_inc(perf, 'alert_rows_recorded', len(thresholds_to_record))
                record_alerts_batch(
                    symbol, thresholds_to_record, current_time, current_price, pct_change,
                    mode=mode, model=model
                )
                logger.info(f"🚨 Alert fired: {symbol} {pct_change:+.2f}% (threshold: {threshold:+d}%)")
                return True, 1  # Return immediately - only ONE alert per scan

    return False, 0


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
                            direction: str, volume_24h: float, pct_change: float) -> str:
    """
    Format Telegram milestone alert message.

    Args:
        symbol: Trading pair symbol
        current_price: Current price
        milestone: Price milestone crossed
        direction: 'up' or 'down'
        volume_24h: 24-hour trading volume
        pct_change: 24h percentage change

    Returns:
        Formatted milestone alert message
    """
    # Get display name (BITCOIN or ETHEREUM)
    if 'BTC' in symbol.upper():
        display_name = "BITCOIN"
    elif 'ETH' in symbol.upper():
        display_name = "ETHEREUM"
    else:
        display_name = symbol.replace('USDT', '')

    # Direction emoji
    if direction == 'up':
        emoji = "🚀"
        action = "BREAKS"
    else:
        emoji = "📉"
        action = "DROPS TO"

    # Format current price - show appropriate decimal places
    if current_price >= 1000:
        price_str = f"${current_price:,.2f}"
    else:
        price_str = f"${current_price:.2f}"

    # Format volume
    if volume_24h >= 1_000_000_000:
        volume_str = f"${volume_24h / 1_000_000_000:.2f}B"
    elif volume_24h >= 1_000_000:
        volume_str = f"${volume_24h / 1_000_000:.2f}M"
    else:
        volume_str = f"${volume_24h:,.0f}"

    # Format change with sign
    change_str = f"+{pct_change:.2f}%" if pct_change >= 0 else f"{pct_change:.2f}%"

    message = f"""<b>{display_name} {action} ${milestone:,.0f}</b> {emoji}

▸ Price: {price_str}
▸ 24h: {change_str}
▸ Vol: {volume_str}"""

    return message


async def send_milestone_alert(
    bot: Bot,
    symbol: str,
    current_price: float,
    milestone: float,
    direction: str,
    volume_24h: float,
    pct_change: float
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
        pct_change: 24h percentage change

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        # Format message
        message = format_milestone_alert(
            symbol, current_price, milestone, direction, volume_24h, pct_change
        )

        # Create keyboard with symbol-specific link
        # Use short name for button (BTC instead of BTCUSDT)
        short_name = symbol.replace('USDT', '').replace('PERP', '')
        keyboard = create_alert_keyboard_custom(short_name, symbol, pct_change)

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


def is_usdt_pair(symbol: str) -> bool:
    """
    Check if symbol is a USDT pair (not PERP).

    For milestone alerts, we only want BTCUSDT/ETHUSDT, not BTCPERP/ETHPERP.
    """
    return symbol.upper().endswith('USDT')


async def check_and_send_milestone_alerts(
    bot: Bot,
    symbol: str,
    current_price: float,
    ticker: Dict,
    current_time: int,
    mode: Optional[str] = None,
    use_short_term: Optional[bool] = None,
    btc_milestone_step: Optional[int] = None,
    eth_milestone_step: Optional[int] = None,
    milestone_cooldown_minutes: Optional[int] = None,
    perf: Optional[Dict[str, int]] = None
) -> Tuple[bool, int]:
    """
    Check and send milestone-based alerts for BTC/ETH.

    Uses REAL-TIME LEVEL TRACKING + 24H TREND FILTER:
    1. Track last known price level (real-time)
    2. Determine direction by HOW price entered the zone
    3. Filter alerts based on 24H trend:
       - 24H bullish → only send "BREAKS" alerts
       - 24H bearish → only send "DROPS TO" alerts

    This ensures:
    - Direction matches actual price movement (not 24h reference)
    - Alerts align with macro trend (no conflicting signals)
    - 24H cooldown per milestone (default 1440 minutes)

    Only works with USDT pairs (BTCUSDT, ETHUSDT) - not PERP.

    Args:
        bot: Telegram bot instance
        symbol: Trading pair symbol
        current_price: Current price
        ticker: Full ticker data
        current_time: Current Unix timestamp

    Returns:
        Tuple of (alert_sent, number_of_alerts)
    """
    # Only process USDT pairs for milestone alerts (not PERP)
    if not is_usdt_pair(symbol):
        return False, 0

    # Get milestone step for this symbol
    if 'BTC' in symbol.upper():
        milestone_step = btc_milestone_step or get_btc_eth_milestone_step(symbol)
    elif 'ETH' in symbol.upper():
        milestone_step = eth_milestone_step or get_btc_eth_milestone_step(symbol)
    else:
        milestone_step = get_btc_eth_milestone_step(symbol)

    if not milestone_step:
        return False, 0

    # Get 24h reference price from Bybit API (prevPrice24h)
    reference_price_24h = float(ticker.get('prevPrice24h', 0))

    if not reference_price_24h or reference_price_24h <= 0:
        logger.warning(f"No 24h reference price for {symbol}")
        return False, 0

    # Calculate 24h percentage change for display
    pct_change = calculate_percentage_change(current_price, reference_price_24h)

    # Check if 241 mode (short-term trend) is enabled
    short_term_ref_price = None
    if use_short_term is None:
        use_short_term = get_bot_setting('short_term_trend') == 'true'

    if use_short_term:
        mode = mode or get_bot_setting('mode') or 'futures'
        short_term_ref_price = get_short_term_price(symbol, mode, current_time)

    # Get milestone using REAL-TIME tracking + trend filter
    # When 241 ON: uses 1h trend (catches dumps that 24h misses)
    # When 241 OFF: uses 24h trend (original behavior)
    # Returns None if:
    # - Same level (no movement)
    # - Direction doesn't match trend (filtered out)
    milestone_info = get_milestone_realtime_with_trend(
        symbol, current_price, reference_price_24h, milestone_step,
        short_term_ref_price=short_term_ref_price
    )

    if not milestone_info:
        # No alert needed (same level or trend mismatch)
        return False, 0

    milestone = milestone_info['milestone']
    direction = milestone_info['direction']
    skipped = milestone_info.get('skipped_milestones', [])
    volume_24h = float(ticker.get('turnover24h', 0))

    # Record ALL skipped boundaries in cooldown first (so they won't fire later)
    eligible_skipped = [
        skipped_ms for skipped_ms in skipped
        if can_fire_milestone_alert(symbol, skipped_ms, direction, current_time)
    ]
    _perf_inc(perf, 'milestone_cooldown_checks', len(skipped))
    if eligible_skipped:
        _perf_inc(perf, 'legacy_milestone_write_calls', len(eligible_skipped))
        _perf_inc(perf, 'new_milestone_write_calls', 1)
        _perf_inc(perf, 'milestone_rows_recorded', len(eligible_skipped))
        record_milestone_alerts_batch(
            symbol, eligible_skipped, direction, current_price, current_time,
            cooldown_minutes=milestone_cooldown_minutes
        )
        logger.debug(
            f"Skipped milestones recorded in cooldown for {symbol}: "
            f"{['$' + format(ms, ',') for ms in eligible_skipped]}"
        )

    # Check if we can fire this alert (cooldown per milestone)
    _perf_inc(perf, 'milestone_cooldown_checks')
    if not can_fire_milestone_alert(symbol, milestone, direction, current_time):
        logger.debug(f"Milestone ${milestone:,} ({direction}) on cooldown for {symbol}")
        return False, 0

    # Send the alert
    success = await send_milestone_alert(
        bot, symbol, current_price, milestone, direction, volume_24h, pct_change
    )

    if success:
        _perf_inc(perf, 'legacy_milestone_write_calls')
        _perf_inc(perf, 'new_milestone_write_calls')
        _perf_inc(perf, 'milestone_rows_recorded')
        record_milestone_alert(
            symbol, milestone, direction, current_price, current_time,
            cooldown_minutes=milestone_cooldown_minutes
        )
        logger.info(f"🎯 Milestone fired: {symbol} ${milestone:,.0f} ({direction}) | 24h: {pct_change:+.2f}%")
        if skipped:
            logger.info(f"   Skipped milestones in cooldown: {['$' + f'{m:,}' for m in skipped]}")
        return True, 1

    return False, 0
