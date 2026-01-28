"""Input validation utilities"""
import re


def is_valid_mode(mode: str) -> bool:
    """Validate market mode"""
    return mode.lower() in ['futures', 'spot']


def is_valid_model(model: str) -> bool:
    """Validate calculation model"""
    return model.lower() in ['model1', 'model2']


def parse_volume_amount(amount_str: str) -> float | None:
    """
    Parse volume amount string.

    Supports formats:
    - Plain numbers: 5000000
    - K suffix: 500K
    - M suffix: 5M
    - B suffix: 1B

    Args:
        amount_str: Volume amount string

    Returns:
        Parsed amount as float, or None if invalid
    """
    try:
        amount_str = amount_str.strip().upper()

        # Remove $ if present
        if amount_str.startswith('$'):
            amount_str = amount_str[1:]

        # Check for suffixes
        if amount_str.endswith('B'):
            return float(amount_str[:-1]) * 1_000_000_000
        elif amount_str.endswith('M'):
            return float(amount_str[:-1]) * 1_000_000
        elif amount_str.endswith('K'):
            return float(amount_str[:-1]) * 1_000
        else:
            return float(amount_str)
    except (ValueError, TypeError):
        return None


def validate_symbol(symbol: str) -> bool:
    """Validate trading pair symbol format"""
    # Basic validation: alphanumeric, typically ends with USDT
    pattern = r'^[A-Z0-9]{2,20}$'
    return bool(re.match(pattern, symbol.upper()))


def validate_threshold(threshold: int) -> bool:
    """Validate threshold value"""
    # Must be in valid range
    return -950 <= threshold <= 950 and threshold != 0


def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent injection"""
    if not text:
        return ""

    # Remove potentially dangerous characters
    dangerous_chars = ['<', '>', '&', '"', "'", '\\', '\x00']
    result = text
    for char in dangerous_chars:
        result = result.replace(char, '')

    return result.strip()[:100]  # Limit length
