"""Shared test fixtures for Polymarket bot tests."""
import pytest
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_btc_5m_market():
    """A realistic BTC 5m market as it flows from scanner to signal engine."""
    expires = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    return {
        "market_id": "0xabc123def456",
        "condition_id": "0xabc123def456",
        "question": "Bitcoin Up or Down - February 17, 3:20PM-3:25PM ET",
        "slug": "btc-updown-5m-1771273200",
        "volume": 5000.0,
        "liquidity": 2000.0,
        "expires_at": expires,
        "is_btc_5m": True,
        "neg_risk": True,
        "outcomes": [
            {
                "outcome": "Up",
                "token_id": "token_up_" + "a" * 60,
                "orderbook": {
                    "asks": [{"price": 0.55, "size": 500}, {"price": 0.56, "size": 300}],
                    "bids": [{"price": 0.54, "size": 400}],
                    "best_ask": 0.55,
                    "best_bid": 0.54,
                    "spread_pct": 0.18,
                    "asks_depth": 800,
                    "bids_depth": 400,
                }
            },
            {
                "outcome": "Down",
                "token_id": "token_down_" + "b" * 60,
                "orderbook": {
                    "asks": [{"price": 0.46, "size": 500}],
                    "bids": [{"price": 0.45, "size": 400}],
                    "best_ask": 0.46,
                    "best_bid": 0.45,
                    "spread_pct": 0.22,
                    "asks_depth": 500,
                    "bids_depth": 400,
                }
            }
        ],
        "outcome_prices": [0.55, 0.45],
        "active": True,
        "accepting_orders": True,
    }


@pytest.fixture
def mock_binary_arb_market():
    """A binary YES/NO market with arb opportunity (cost < 0.97)."""
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    return {
        "market_id": "0xdef456789",
        "question": "Will it rain tomorrow in NYC?",
        "volume": 10000.0,
        "expires_at": expires,
        "neg_risk": False,
        "outcomes": [
            {
                "outcome": "Yes",
                "token_id": "yes_token_id_abc123",
                "orderbook": {
                    "asks": [{"price": 0.45, "size": 1000}],
                    "bids": [{"price": 0.44, "size": 800}],
                    "best_ask": 0.45,
                    "best_bid": 0.44,
                    "spread_pct": 0.22,
                    "asks_depth": 1000,
                    "bids_depth": 800,
                }
            },
            {
                "outcome": "No",
                "token_id": "no_token_id_def456",
                "orderbook": {
                    "asks": [{"price": 0.50, "size": 1000}],
                    "bids": [{"price": 0.49, "size": 800}],
                    "best_ask": 0.50,
                    "best_bid": 0.49,
                    "spread_pct": 0.20,
                    "asks_depth": 1000,
                    "bids_depth": 800,
                }
            }
        ],
    }


@pytest.fixture
def mock_one_of_many_arb_market():
    """A 4-outcome market with arb opportunity (total asks < 0.97)."""
    expires = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    return {
        "market_id": "0xmulti789",
        "question": "Which team wins the tournament?",
        "volume": 20000.0,
        "expires_at": expires,
        "neg_risk": False,
        "outcomes": [
            {
                "outcome": "Team A",
                "token_id": "token_a_" + "1" * 60,
                "orderbook": {
                    "asks": [{"price": 0.22, "size": 500}],
                    "bids": [{"price": 0.21, "size": 400}],
                    "best_ask": 0.22,
                    "best_bid": 0.21,
                    "spread_pct": 0.45,
                    "asks_depth": 500,
                }
            },
            {
                "outcome": "Team B",
                "token_id": "token_b_" + "2" * 60,
                "orderbook": {
                    "asks": [{"price": 0.25, "size": 500}],
                    "bids": [{"price": 0.24, "size": 400}],
                    "best_ask": 0.25,
                    "best_bid": 0.24,
                    "spread_pct": 0.40,
                    "asks_depth": 500,
                }
            },
            {
                "outcome": "Team C",
                "token_id": "token_c_" + "3" * 60,
                "orderbook": {
                    "asks": [{"price": 0.23, "size": 500}],
                    "bids": [{"price": 0.22, "size": 400}],
                    "best_ask": 0.23,
                    "best_bid": 0.22,
                    "spread_pct": 0.43,
                    "asks_depth": 500,
                }
            },
            {
                "outcome": "Team D",
                "token_id": "token_d_" + "4" * 60,
                "orderbook": {
                    "asks": [{"price": 0.24, "size": 500}],
                    "bids": [{"price": 0.23, "size": 400}],
                    "best_ask": 0.24,
                    "best_bid": 0.23,
                    "spread_pct": 0.42,
                    "asks_depth": 500,
                }
            },
        ],
    }


@pytest.fixture
def mock_binance_feed():
    """Mock Binance feed with BTC price data trending upward."""
    feed = MagicMock()
    feed.get_price.return_value = 97500.0
    feed.get_volatility.return_value = 0.03
    # Upward trend: 97000 -> 97500
    feed.price_history = {
        "btcusdt": [97000.0 + i * 16.67 for i in range(30)]
    }
    return feed


@pytest.fixture
def mock_binance_feed_down():
    """Mock Binance feed with BTC price data trending downward."""
    feed = MagicMock()
    feed.get_price.return_value = 96500.0
    feed.get_volatility.return_value = 0.03
    # Downward trend: 97000 -> 96500
    feed.price_history = {
        "btcusdt": [97000.0 - i * 16.67 for i in range(30)]
    }
    return feed


@pytest.fixture
def mock_db():
    """Mock MongoDB instance."""
    mock = AsyncMock()
    mock.count_open_positions.return_value = 0
    mock.get_total_exposure.return_value = 0.0
    mock.get_daily_pnl.return_value = None
    mock.create_position.return_value = "mock_id"
    mock.update_position.return_value = None
    mock.log_event.return_value = None
    mock.upsert_market.return_value = None
    return mock
