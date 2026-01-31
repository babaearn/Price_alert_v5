"""
Token masking utility for secure logging.

Prevents credential leaks in:
- Error messages
- Exception stack traces
- Connection logs
- Debug output
"""
import re
from typing import Optional


def mask_token(token: Optional[str], show_chars: int = 4) -> str:
    """
    Mask sensitive tokens for logging.

    Args:
        token: The token/key to mask
        show_chars: Number of characters to show at start and end

    Returns:
        Masked token string

    Examples:
        >>> mask_token("7234567890:ABCdefGHIjklMNOpqrsTUVwxyz")
        "7234...wxyz"

        >>> mask_token("postgresql://user:secret123@host:5432/db")
        "post...l/db"
    """
    if not token:
        return "***NONE***"

    if len(token) <= show_chars * 2:
        return "***MASKED***"

    return f"{token[:show_chars]}...{token[-show_chars:]}"


def mask_database_url(url: Optional[str]) -> str:
    """
    Mask password in DATABASE_URL for safe logging.

    Args:
        url: Database connection URL

    Returns:
        Masked URL with password hidden

    Examples:
        >>> mask_database_url("postgresql://user:password123@localhost:5432/mydb")
        "postgresql://user:***@localhost:5432/mydb"
    """
    if not url:
        return "***NONE***"

    # Match pattern: scheme://user:password@host:port/database
    masked = re.sub(
        r'(://[^:]+:)([^@]+)(@)',
        r'\1***\3',
        url
    )

    return masked


def mask_api_key(key: Optional[str]) -> str:
    """
    Mask API key for logging.

    Args:
        key: API key to mask

    Returns:
        Masked API key showing first and last 6 characters
    """
    return mask_token(key, show_chars=6)


def mask_error_message(error_msg: str) -> str:
    """
    Scan error message and mask any potential tokens.

    Args:
        error_msg: Error message that might contain tokens

    Returns:
        Error message with tokens masked
    """
    if not error_msg:
        return error_msg

    masked = str(error_msg)

    # Mask bot tokens (format: 1234567890:ABC...)
    masked = re.sub(
        r'\b\d{8,10}:[A-Za-z0-9_-]{30,}\b',
        '***BOT_TOKEN***',
        masked
    )

    # Mask passwords in URLs (postgresql://user:password@host)
    masked = re.sub(
        r'(://[^:]+:)([^@]+)(@)',
        r'\1***\3',
        masked
    )

    # Mask long alphanumeric strings (potential API keys - 32+ chars)
    masked = re.sub(
        r'\b[A-Za-z0-9]{32,}\b',
        '***API_KEY***',
        masked
    )

    # Mask potential secrets in key=value format
    masked = re.sub(
        r'(password|secret|token|key|api_key|apikey)(["\s:=]+)([^\s"\']+)',
        r'\1\2***',
        masked,
        flags=re.IGNORECASE
    )

    return masked


def mask_channel_id(channel_id: Optional[str]) -> str:
    """
    Partially mask channel ID for logging.

    Args:
        channel_id: Telegram channel ID

    Returns:
        Partially masked channel ID
    """
    if not channel_id:
        return "***NONE***"

    channel_str = str(channel_id)

    if len(channel_str) <= 6:
        return channel_str

    # Show first 4 and last 4 characters
    return f"{channel_str[:4]}...{channel_str[-4:]}"
