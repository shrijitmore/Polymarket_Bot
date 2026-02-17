"""
Utility helper functions for the Polymarket arbitrage bot.
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import hashlib
import uuid


def calculate_spread(best_bid: float, best_ask: float) -> float:
    """
    Calculate spread percentage.
    
    Args:
        best_bid: Best bid price
        best_ask: Best ask price
    
    Returns:
        Spread as a percentage
    """
    if best_ask == 0:
        return 100.0
    return ((best_ask - best_bid) / best_ask) * 100.0


def validate_orderbook_depth(
    orderbook: List[Dict],
    required_size: float,
    side: str = "asks"
) -> bool:
    """
    Validate that orderbook has sufficient liquidity.
    
    Args:
        orderbook: List of order levels [{"price": x, "size": y}, ...]
        required_size: Required liquidity in outcome tokens
        side: "asks" or "bids"
    
    Returns:
        True if sufficient liquidity exists
    """
    if not orderbook:
        return False
    
    cumulative_size = 0.0
    for level in orderbook:
        cumulative_size += float(level.get("size", 0))
        if cumulative_size >= required_size:
            return True
    
    return False


def calculate_kelly_fraction(
    probability: float,
    odds: float,
    kelly_fraction: float = 0.25
) -> float:
    """
    Calculate Kelly criterion position size.
    
    Args:
        probability: Estimated probability of winning (0-1)
        odds: Decimal odds (e.g., 2.0 for even money)
        kelly_fraction: Fraction of full Kelly to use (default: quarter Kelly)
    
    Returns:
        Recommended bet size as fraction of bankroll
    """
    if odds <= 1.0 or probability <= 0 or probability >= 1:
        return 0.0
    
    # Kelly formula: f = (bp - q) / b
    # where b = odds - 1, p = probability, q = 1 - p
    b = odds - 1
    p = probability
    q = 1 - p
    
    full_kelly = (b * p - q) / b
    
    # Apply fractional Kelly (quarter Kelly for safety)
    return max(0.0, full_kelly * kelly_fraction)


def format_usd(amount: float) -> str:
    """Format amount as USD string."""
    return f"${amount:,.2f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format value as percentage string."""
    return f"{value:.{decimals}f}%"


def calculate_slippage(expected_price: float, actual_price: float) -> float:
    """
    Calculate slippage percentage.
    
    Args:
        expected_price: Expected fill price
        actual_price: Actual fill price
    
    Returns:
        Slippage as a percentage (positive = worse than expected)
    """
    if expected_price == 0:
        return 0.0
    return ((actual_price - expected_price) / expected_price) * 100.0


def generate_position_id(market_id: str, strategy: str) -> str:
    """
    Generate unique position ID.
    
    Args:
        market_id: Polymarket market ID
        strategy: Strategy name
    
    Returns:
        Unique position ID
    """
    timestamp = datetime.utcnow().isoformat()
    unique_str = f"{market_id}_{strategy}_{timestamp}_{uuid.uuid4()}"
    return hashlib.sha256(unique_str.encode()).hexdigest()[:16]


def time_to_close(expires_at: datetime) -> int:
    """
    Calculate seconds until market close.

    Args:
        expires_at: Market expiration datetime (naive or tz-aware)

    Returns:
        Seconds until close (negative if already closed)
    """
    from datetime import timezone as tz
    now = datetime.now(tz.utc)
    # Make expires_at tz-aware if naive (assume UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=tz.utc)
    delta = expires_at - now
    return int(delta.total_seconds())


def is_crypto_market(market_title: str) -> bool:
    """
    Heuristic to detect if market is crypto-related.
    
    Args:
        market_title: Market title or question
    
    Returns:
        True if likely a crypto market
    """
    crypto_keywords = [
        "btc", "bitcoin", "eth", "ethereum", "sol", "solana",
        "xrp", "ripple", "crypto", "cryptocurrency"
    ]
    title_lower = market_title.lower()
    return any(keyword in title_lower for keyword in crypto_keywords)


def extract_time_frame(market_title: str) -> Optional[str]:
    """
    Extract time frame from market title (e.g., "5-min", "15-min").
    
    Args:
        market_title: Market title or question
    
    Returns:
        Time frame string if found, else None
    """
    import re
    patterns = [
        r"(\d+)-?min",
        r"(\d+)\s*minute",
    ]
    
    title_lower = market_title.lower()
    for pattern in patterns:
        match = re.search(pattern, title_lower)
        if match:
            return f"{match.group(1)}-min"
    
    return None


def calculate_volatility(prices: List[float]) -> float:
    """
    Calculate simple volatility (standard deviation) from price list.
    
    Args:
        prices: List of prices
    
    Returns:
        Volatility as percentage
    """
    if len(prices) < 2:
        return 0.0
    
    mean = sum(prices) / len(prices)
    variance = sum((p - mean) ** 2 for p in prices) / len(prices)
    std_dev = variance ** 0.5
    
    if mean == 0:
        return 0.0
    
    return (std_dev / mean) * 100.0


def is_within_late_window(
    expires_at: datetime,
    window_start: int,
    window_end: int
) -> bool:
    """
    Check if current time is within late-market trading window.
    
    Args:
        expires_at: Market expiration datetime
        window_start: Window start in seconds before close
        window_end: Window end in seconds before close
    
    Returns:
        True if within trading window
    """
    seconds_to_close = time_to_close(expires_at)
    return window_end <= seconds_to_close <= window_start


def validate_binary_market(outcomes: List[Dict]) -> bool:
    """
    Validate that market is a true binary market (YES/NO or Up/Down).

    Args:
        outcomes: List of outcome dictionaries

    Returns:
        True if valid binary market
    """
    if len(outcomes) != 2:
        return False

    outcome_names = [o.get("outcome", "").upper() for o in outcomes]
    is_yes_no = "YES" in outcome_names and "NO" in outcome_names
    is_up_down = "UP" in outcome_names and "DOWN" in outcome_names
    return is_yes_no or is_up_down


def safe_float(value, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    """Safely convert value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_btc_5m_market(question: str) -> bool:
    """
    Detect if a market is a BTC 5-minute Up/Down market.

    Polymarket BTC 5m market titles follow patterns like:
    - "Bitcoin Up or Down - February 16, 3:20PM-3:25PM ET"
    - "BTC Up/Down - Feb 16, 10:00AM-10:05AM ET"

    Args:
        question: Market question/title

    Returns:
        True if this is a BTC 5-minute market
    """
    q = question.lower()
    has_btc = "bitcoin" in q or "btc" in q
    has_direction = "up or down" in q or "up/down" in q
    return has_btc and has_direction
