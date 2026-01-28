"""Bybit REST API client - No CCXT dependency"""
import requests
from typing import List, Dict, Optional

from bot.config import BYBIT_API_BASE, BYBIT_API_TIMEOUT
from bot.utils.logger import logger


def fetch_tickers(category: str = 'linear') -> List[Dict]:
    """
    Fetch all tickers from Bybit.

    Args:
        category: 'linear' (futures/perpetuals) or 'spot'

    Returns:
        List of ticker dictionaries with price data

    API Response Structure:
    {
        "symbol": "BTCUSDT",
        "lastPrice": "100000.00",
        "prevPrice24h": "95000.00",
        "price24hPcnt": "0.0526",
        "highPrice24h": "102000.00",
        "lowPrice24h": "94000.00",
        "turnover24h": "5000000000.00",
        "volume24h": "50000.00"
    }
    """
    try:
        response = requests.get(
            f"{BYBIT_API_BASE}/v5/market/tickers",
            params={'category': category},
            timeout=BYBIT_API_TIMEOUT
        )

        # Check HTTP status
        response.raise_for_status()

        data = response.json()

        # Check Bybit API response code
        if data.get('retCode') != 0:
            logger.error(f"Bybit API error: {data.get('retMsg', 'Unknown error')}")
            return []

        tickers = data.get('result', {}).get('list', [])

        # Log rate limit info if available
        rate_limit_info = get_rate_limit_info(response)
        if rate_limit_info.get('remaining'):
            logger.debug(f"Bybit rate limit remaining: {rate_limit_info['remaining']}")

        logger.debug(f"Fetched {len(tickers)} tickers (category: {category})")

        return tickers

    except requests.Timeout:
        logger.error("Bybit API timeout")
        return []
    except requests.RequestException as e:
        logger.error(f"Bybit API request error: {e}")
        return []
    except Exception as e:
        logger.error(f"Bybit API unexpected error: {e}")
        return []


def get_rate_limit_info(response: requests.Response) -> Dict:
    """
    Extract rate limit info from response headers.

    Bybit rate limit headers:
    - X-Bapi-Limit: Total allowed requests
    - X-Bapi-Limit-Status: Remaining requests
    - X-Bapi-Limit-Reset-Timestamp: When limit resets
    """
    return {
        'limit': response.headers.get('X-Bapi-Limit'),
        'remaining': response.headers.get('X-Bapi-Limit-Status'),
        'reset_at': response.headers.get('X-Bapi-Limit-Reset-Timestamp')
    }


def get_bybit_category(mode: str) -> str:
    """
    Get Bybit API category based on mode.

    Args:
        mode: 'futures' or 'spot'

    Returns:
        'linear' for futures, 'spot' for spot markets
    """
    if mode == 'futures':
        return 'linear'
    elif mode == 'spot':
        return 'spot'
    else:
        logger.warning(f"Unknown mode '{mode}', defaulting to 'linear'")
        return 'linear'


def filter_usdt_pairs(tickers: List[Dict]) -> List[Dict]:
    """
    Filter tickers to only include USDT pairs.

    Args:
        tickers: List of ticker dictionaries

    Returns:
        Filtered list with only USDT pairs
    """
    usdt_tickers = [t for t in tickers if t.get('symbol', '').endswith('USDT')]
    logger.debug(f"Filtered to {len(usdt_tickers)} USDT pairs")
    return usdt_tickers


def filter_by_volume(tickers: List[Dict], min_volume_usd: float) -> List[Dict]:
    """
    Filter tickers by minimum 24h trading volume.

    Args:
        tickers: List of ticker dictionaries
        min_volume_usd: Minimum 24h volume in USD

    Returns:
        Filtered list with tickers meeting volume threshold
    """
    filtered = []

    for ticker in tickers:
        try:
            # turnover24h is the 24h volume in quote currency (USD for USDT pairs)
            volume = float(ticker.get('turnover24h', 0))
            if volume >= min_volume_usd:
                filtered.append(ticker)
        except (ValueError, TypeError):
            continue

    logger.debug(f"Filtered to {len(filtered)} pairs with volume >= ${min_volume_usd:,.0f}")
    return filtered


def parse_ticker_data(ticker: Dict) -> Optional[Dict]:
    """
    Parse and validate ticker data.

    Args:
        ticker: Raw ticker dictionary from Bybit API

    Returns:
        Parsed ticker data or None if invalid
    """
    try:
        return {
            'symbol': ticker['symbol'],
            'last_price': float(ticker['lastPrice']),
            'prev_price_24h': float(ticker.get('prevPrice24h', 0)),
            'price_24h_pct': float(ticker.get('price24hPcnt', 0)) * 100,  # Convert to percentage
            'high_24h': float(ticker.get('highPrice24h', 0)),
            'low_24h': float(ticker.get('lowPrice24h', 0)),
            'volume_24h': float(ticker.get('turnover24h', 0)),  # USD volume
            'volume_24h_coins': float(ticker.get('volume24h', 0))  # Coin volume
        }
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse ticker {ticker.get('symbol', 'unknown')}: {e}")
        return None


def get_ticker(symbol: str, category: str = 'linear') -> Optional[Dict]:
    """
    Get single ticker data for a specific symbol.

    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        category: 'linear' or 'spot'

    Returns:
        Ticker data or None if not found
    """
    try:
        response = requests.get(
            f"{BYBIT_API_BASE}/v5/market/tickers",
            params={'category': category, 'symbol': symbol},
            timeout=BYBIT_API_TIMEOUT
        )

        response.raise_for_status()
        data = response.json()

        if data.get('retCode') != 0:
            logger.error(f"Bybit API error for {symbol}: {data.get('retMsg')}")
            return None

        tickers = data.get('result', {}).get('list', [])

        if tickers:
            return parse_ticker_data(tickers[0])

        return None

    except Exception as e:
        logger.error(f"Error fetching ticker for {symbol}: {e}")
        return None


def test_api_connection() -> bool:
    """
    Test Bybit API connectivity.

    Returns:
        True if API is accessible, False otherwise
    """
    try:
        response = requests.get(
            f"{BYBIT_API_BASE}/v5/market/time",
            timeout=5
        )

        data = response.json()

        if data.get('retCode') == 0:
            server_time = data.get('result', {}).get('timeNano')
            if server_time:
                logger.info(f"Bybit API connection OK, server time: {server_time}")
                return True

        logger.error(f"Bybit API test failed: {data.get('retMsg')}")
        return False

    except Exception as e:
        logger.error(f"Bybit API connection test failed: {e}")
        return False
