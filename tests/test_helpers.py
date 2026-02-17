"""Tests for utility helper functions."""
import pytest
from datetime import datetime, timedelta, timezone
from utils.helpers import (
    calculate_spread,
    calculate_slippage,
    calculate_volatility,
    validate_orderbook_depth,
    validate_binary_market,
    is_btc_5m_market,
    is_within_late_window,
    is_crypto_market,
    time_to_close,
    safe_float,
    safe_int,
    generate_position_id,
    format_usd,
    format_percentage,
)


class TestCalculateSpread:
    def test_normal_spread(self):
        assert abs(calculate_spread(0.49, 0.51) - 3.92) < 0.1

    def test_zero_ask(self):
        assert calculate_spread(0.49, 0) == 100.0

    def test_tight_spread(self):
        result = calculate_spread(0.50, 0.51)
        assert result < 2.0


class TestCalculateSlippage:
    def test_no_slippage(self):
        assert calculate_slippage(0.50, 0.50) == 0.0

    def test_positive_slippage(self):
        result = calculate_slippage(0.50, 0.51)
        assert result > 0

    def test_zero_expected(self):
        assert calculate_slippage(0, 0.50) == 0.0


class TestCalculateVolatility:
    def test_stable_prices(self):
        prices = [100.0] * 10
        assert calculate_volatility(prices) == 0.0

    def test_volatile_prices(self):
        prices = [100.0, 110.0, 90.0, 105.0, 95.0]
        vol = calculate_volatility(prices)
        assert vol > 0

    def test_too_few_prices(self):
        assert calculate_volatility([100.0]) == 0.0
        assert calculate_volatility([]) == 0.0


class TestValidateOrderbookDepth:
    def test_sufficient_depth(self):
        orderbook = [{"price": 0.5, "size": 1000}]
        assert validate_orderbook_depth(orderbook, 500, "asks") is True

    def test_insufficient_depth(self):
        orderbook = [{"price": 0.5, "size": 100}]
        assert validate_orderbook_depth(orderbook, 500, "asks") is False

    def test_empty_orderbook(self):
        assert validate_orderbook_depth([], 100, "asks") is False

    def test_multiple_levels(self):
        orderbook = [
            {"price": 0.5, "size": 200},
            {"price": 0.51, "size": 200},
            {"price": 0.52, "size": 200},
        ]
        assert validate_orderbook_depth(orderbook, 500, "asks") is True


class TestValidateBinaryMarket:
    def test_yes_no_market(self):
        outcomes = [{"outcome": "Yes"}, {"outcome": "No"}]
        assert validate_binary_market(outcomes) is True

    def test_up_down_market(self):
        outcomes = [{"outcome": "Up"}, {"outcome": "Down"}]
        assert validate_binary_market(outcomes) is True

    def test_three_outcomes(self):
        outcomes = [{"outcome": "A"}, {"outcome": "B"}, {"outcome": "C"}]
        assert validate_binary_market(outcomes) is False

    def test_wrong_names(self):
        outcomes = [{"outcome": "Red"}, {"outcome": "Blue"}]
        assert validate_binary_market(outcomes) is False


class TestIsBtc5mMarket:
    def test_standard_title(self):
        assert is_btc_5m_market("Bitcoin Up or Down - February 17, 3:20PM-3:25PM ET") is True

    def test_btc_abbreviation(self):
        assert is_btc_5m_market("BTC Up or Down - Feb 17, 3:20PM-3:25PM ET") is True

    def test_slash_variant(self):
        assert is_btc_5m_market("Bitcoin Up/Down - Feb 17, 10:00AM-10:05AM ET") is True

    def test_non_btc_market(self):
        assert is_btc_5m_market("Will it rain in NYC tomorrow?") is False

    def test_btc_without_direction(self):
        assert is_btc_5m_market("Bitcoin will reach $100K") is False

    def test_direction_without_btc(self):
        assert is_btc_5m_market("ETH Up or Down - Feb 17") is False


class TestIsWithinLateWindow:
    def test_within_window(self):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
        assert is_within_late_window(expires_at, 180, 60) is True

    def test_before_window(self):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=300)
        assert is_within_late_window(expires_at, 180, 60) is False

    def test_after_window(self):
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert is_within_late_window(expires_at, 180, 60) is False


class TestTimeToClose:
    def test_future_close(self):
        expires_at = datetime.utcnow() + timedelta(seconds=100)
        result = time_to_close(expires_at)
        assert 98 <= result <= 102

    def test_past_close(self):
        expires_at = datetime.utcnow() - timedelta(seconds=100)
        result = time_to_close(expires_at)
        assert result < 0


class TestSafeConversions:
    def test_safe_float_valid(self):
        assert safe_float("3.14") == 3.14

    def test_safe_float_invalid(self):
        assert safe_float("abc") == 0.0

    def test_safe_float_none(self):
        assert safe_float(None) == 0.0

    def test_safe_float_default(self):
        assert safe_float("abc", -1.0) == -1.0

    def test_safe_int_valid(self):
        assert safe_int("42") == 42

    def test_safe_int_invalid(self):
        assert safe_int("abc") == 0


class TestGeneratePositionId:
    def test_generates_string(self):
        pid = generate_position_id("market_1", "yes_no")
        assert isinstance(pid, str)
        assert len(pid) == 16

    def test_unique_ids(self):
        pid1 = generate_position_id("market_1", "yes_no")
        pid2 = generate_position_id("market_1", "yes_no")
        assert pid1 != pid2  # uuid4 ensures uniqueness


class TestFormatting:
    def test_format_usd(self):
        assert format_usd(1234.56) == "$1,234.56"

    def test_format_percentage(self):
        assert format_percentage(3.14159) == "3.14%"
        assert format_percentage(3.14159, 3) == "3.142%"


class TestIsCryptoMarket:
    def test_bitcoin_market(self):
        assert is_crypto_market("Will Bitcoin reach $100K?") is True

    def test_eth_market(self):
        assert is_crypto_market("ETH price at end of month") is True

    def test_non_crypto(self):
        assert is_crypto_market("Will it rain tomorrow?") is False
