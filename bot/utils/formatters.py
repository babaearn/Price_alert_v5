"""Message formatting utilities"""
from bot.config import GAINER_LINK, LOSER_LINK


def format_alert_message(symbol: str, current_price: float, reference_price: float,
                         pct_change: float, volume_24h: float) -> str:
    """
    Format Telegram alert message.

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        current_price: Current price
        reference_price: Reference price (24h ago or session start)
        pct_change: Percentage change
        volume_24h: 24-hour trading volume in USD

    Returns:
        Formatted alert message
    """
    # Determine alert type
    if pct_change > 0:
        alert_type = "ALERT PUMP!"
        emoji = "🚀"
    else:
        alert_type = "ALERT DUMP!"
        emoji = "📉"

    # Format prices based on value
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
{emoji} <b>{alert_type}</b> ({pct_change:+.2f}%)

💰 <b>{symbol}</b>
📈 ${reference_price:{price_format}} → ${current_price:{price_format}}
📊 {pct_change:+.2f}% (24h)
💵 Volume: {volume_str}
"""

    return message.strip()


def format_price(price: float) -> str:
    """Format price with appropriate decimal places"""
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    elif price >= 0.001:
        return f"${price:.6f}"
    else:
        return f"${price:.8f}"


def format_volume(volume: float) -> str:
    """Format volume with K/M/B suffixes"""
    if volume >= 1_000_000_000:
        return f"${volume / 1_000_000_000:.2f}B"
    elif volume >= 1_000_000:
        return f"${volume / 1_000_000:.2f}M"
    elif volume >= 1_000:
        return f"${volume / 1_000:.2f}K"
    else:
        return f"${volume:,.0f}"


def format_percentage(pct: float) -> str:
    """Format percentage with sign"""
    return f"{pct:+.2f}%"


def get_adjust_link(pct_change: float) -> str:
    """
    Return appropriate link based on price movement.

    Args:
        pct_change: Percentage change

    Returns:
        Gainer link if positive, loser link if negative
    """
    if pct_change > 0:
        return GAINER_LINK
    else:
        return LOSER_LINK


def format_status_message(mode: str, model: str, min_volume: float,
                          scan_interval: int, paused: bool,
                          last_scan_time: str = None, pairs_count: int = 0,
                          alerts_count: int = 0, scan_duration_ms: int = 0) -> str:
    """Format bot status message"""

    status_emoji = "⏸️ PAUSED" if paused else "🔄 ACTIVE"
    mode_display = "Futures (Linear)" if mode == 'futures' else "Spot"
    model_display = "Model 1 (Session-Based)" if model == 'model1' else "Model 2 (Rolling 24H)"

    message = f"""
🤖 <b>Bot Status</b>

🔄 Scanner: <b>{status_emoji}</b>
📊 Mode: <b>{mode_display}</b>
📈 Model: <b>{model_display}</b>
🎯 Min Volume: <b>${min_volume:,.0f}</b>
⏱️ Scan Interval: <b>{scan_interval} seconds</b>
"""

    if last_scan_time:
        message += f"""
📈 <b>Last Scan:</b>
- Time: {last_scan_time}
- Pairs: {pairs_count}
- Alerts: {alerts_count}
- Duration: {scan_duration_ms}ms
"""

    return message.strip()
