"""Tests for the signal engine — all 3 strategies."""
import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, AsyncMock


# Patch settings and db before importing signal_engine
@pytest.fixture(autouse=True)
def patch_settings():
    """Patch settings for all tests in this module."""
    with patch("signal_engine.settings") as mock_settings:
        mock_settings.enable_one_of_many = True
        mock_settings.enable_yes_no = True
        mock_settings.enable_late_market = True
        mock_settings.min_arb_edge_pct = 2.0
        mock_settings.max_spread_one_of_many = 2.0
        mock_settings.max_spread_yes_no = 1.5
        mock_settings.max_spread_late_market = 1.0
        mock_settings.max_arb_position_size = 100.0
        mock_settings.max_late_position_size = 75.0
        mock_settings.min_time_to_close_minutes = 30
        mock_settings.late_market_window_start = 180
        mock_settings.late_market_window_end = 60
        mock_settings.late_market_min_deviation_pct = 0.05
        mock_settings.late_market_max_volatility_pct = 1.5
        mock_settings.late_market_max_price = 0.95
        yield mock_settings


@pytest.fixture(autouse=True)
def patch_db():
    with patch("signal_engine.db") as mock_db:
        yield mock_db


class TestYesNoArb:
    """Tests for the YES/NO arbitrage strategy."""

    @pytest.mark.asyncio
    async def test_arb_detected_when_cost_below_threshold(self, mock_binary_arb_market, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        # YES=0.45 + NO=0.50 = 0.95, edge=5% > min_arb_edge_pct=2%
        signal = await engine._check_yes_no_arb(mock_binary_arb_market)

        assert signal is not None
        assert signal["strategy"] == "yes_no"
        assert signal["expected_edge"] == pytest.approx(5.0, abs=0.1)
        assert len(signal["legs"]) == 2

    @pytest.mark.asyncio
    async def test_arb_not_detected_when_cost_above_threshold(self, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        market = {
            "market_id": "0xno_arb",
            "question": "Will X happen?",
            "expires_at": expires,
            "outcomes": [
                {
                    "outcome": "Yes",
                    "token_id": "tok_yes",
                    "orderbook": {
                        "asks": [{"price": 0.55, "size": 1000}],
                        "best_ask": 0.55, "best_bid": 0.54,
                        "spread_pct": 0.2, "asks_depth": 1000,
                    }
                },
                {
                    "outcome": "No",
                    "token_id": "tok_no",
                    "orderbook": {
                        "asks": [{"price": 0.50, "size": 1000}],
                        "best_ask": 0.50, "best_bid": 0.49,
                        "spread_pct": 0.2, "asks_depth": 1000,
                    }
                }
            ],
        }
        # YES=0.55 + NO=0.50 = 1.05 → negative edge → no arb
        signal = await engine._check_yes_no_arb(market)
        assert signal is None

    @pytest.mark.asyncio
    async def test_up_down_variant_detected(self, patch_settings):
        """Up/Down markets should also be detected as arb."""
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        market = {
            "market_id": "0xupdown_arb",
            "question": "Bitcoin Up or Down?",
            "expires_at": expires,
            "neg_risk": True,
            "outcomes": [
                {
                    "outcome": "Up",
                    "token_id": "tok_up",
                    "orderbook": {
                        "asks": [{"price": 0.44, "size": 1000}],
                        "best_ask": 0.44, "best_bid": 0.43,
                        "spread_pct": 0.2, "asks_depth": 1000,
                    }
                },
                {
                    "outcome": "Down",
                    "token_id": "tok_down",
                    "orderbook": {
                        "asks": [{"price": 0.50, "size": 1000}],
                        "best_ask": 0.50, "best_bid": 0.49,
                        "spread_pct": 0.2, "asks_depth": 1000,
                    }
                }
            ],
        }
        signal = await engine._check_yes_no_arb(market)
        assert signal is not None
        assert signal["expected_edge"] == pytest.approx(6.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_token_id_flows_through(self, mock_binary_arb_market, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        signal = await engine._check_yes_no_arb(mock_binary_arb_market)

        assert signal is not None
        for leg in signal["legs"]:
            assert leg["token_id"] is not None
            assert len(leg["token_id"]) > 0

    @pytest.mark.asyncio
    async def test_missing_orderbook_returns_none(self, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        market = {
            "market_id": "0xno_book",
            "question": "Will X?",
            "expires_at": expires,
            "outcomes": [
                {"outcome": "Yes", "token_id": "t1", "orderbook": {"best_ask": None}},
                {"outcome": "No", "token_id": "t2", "orderbook": {"best_ask": 0.50}},
            ],
        }
        signal = await engine._check_yes_no_arb(market)
        assert signal is None


class TestOneOfManyArb:
    """Tests for the One-of-Many arbitrage strategy."""

    @pytest.mark.asyncio
    async def test_arb_detected(self, mock_one_of_many_arb_market, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        # Sum of asks: 0.22 + 0.25 + 0.23 + 0.24 = 0.94 → edge = 6%
        signal = await engine._check_one_of_many_arb(mock_one_of_many_arb_market)

        assert signal is not None
        assert signal["strategy"] == "one_of_many"
        assert signal["expected_edge"] == pytest.approx(6.0, abs=0.1)
        assert len(signal["legs"]) == 4

    @pytest.mark.asyncio
    async def test_two_outcomes_rejected(self, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        market = {
            "market_id": "0x2out",
            "question": "Binary?",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "outcomes": [
                {"outcome": "A", "orderbook": {"best_ask": 0.40}},
                {"outcome": "B", "orderbook": {"best_ask": 0.50}},
            ],
        }
        signal = await engine._check_one_of_many_arb(market)
        assert signal is None

    @pytest.mark.asyncio
    async def test_token_ids_present(self, mock_one_of_many_arb_market, patch_settings):
        from signal_engine import SignalEngine

        engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
        signal = await engine._check_one_of_many_arb(mock_one_of_many_arb_market)

        assert signal is not None
        for leg in signal["legs"]:
            assert "token_id" in leg


class TestLateMarket:
    """Tests for the Late-Market BTC 5m strategy."""

    @pytest.mark.asyncio
    async def test_btc_up_signal(self, mock_btc_5m_market, mock_binance_feed, patch_settings):
        from signal_engine import SignalEngine

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is not None
        assert signal["strategy"] == "late_market"
        assert signal["legs"][0]["outcome"] == "Up"
        assert signal["btc_change_pct"] > 0

    @pytest.mark.asyncio
    async def test_btc_down_signal(self, mock_btc_5m_market, mock_binance_feed_down, patch_settings):
        from signal_engine import SignalEngine

        with patch("signal_engine.binance_feed", mock_binance_feed_down):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is not None
        assert signal["strategy"] == "late_market"
        assert signal["legs"][0]["outcome"] == "Down"
        assert signal["btc_change_pct"] < 0

    @pytest.mark.asyncio
    async def test_insufficient_deviation_rejected(self, mock_btc_5m_market, patch_settings):
        """BTC barely moved → should not signal."""
        from signal_engine import SignalEngine

        flat_feed = MagicMock()
        flat_feed.get_price.return_value = 97000.0
        flat_feed.get_volatility.return_value = 0.01
        # Flat: all prices essentially the same
        flat_feed.price_history = {"btcusdt": [97000.0] * 30}

        with patch("signal_engine.binance_feed", flat_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is None

    @pytest.mark.asyncio
    async def test_high_volatility_rejected(self, mock_btc_5m_market, patch_settings):
        from signal_engine import SignalEngine

        volatile_feed = MagicMock()
        volatile_feed.get_price.return_value = 97500.0
        volatile_feed.get_volatility.return_value = 5.0  # Way above 1.5% threshold
        volatile_feed.price_history = {"btcusdt": [97000.0 + i * 50 for i in range(30)]}

        with patch("signal_engine.binance_feed", volatile_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is None

    @pytest.mark.asyncio
    async def test_too_expensive_rejected(self, mock_btc_5m_market, mock_binance_feed, patch_settings):
        """Entry price above max_price → rejected."""
        from signal_engine import SignalEngine

        # Make Up ask = 0.96 (above max_price=0.95)
        mock_btc_5m_market["outcomes"][0]["orderbook"]["best_ask"] = 0.96
        mock_btc_5m_market["outcomes"][0]["orderbook"]["asks"] = [{"price": 0.96, "size": 500}]

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is None

    @pytest.mark.asyncio
    async def test_no_binance_price_returns_none(self, mock_btc_5m_market, patch_settings):
        from signal_engine import SignalEngine

        no_price_feed = MagicMock()
        no_price_feed.get_price.return_value = None

        with patch("signal_engine.binance_feed", no_price_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is None

    @pytest.mark.asyncio
    async def test_outside_window_returns_none(self, mock_binance_feed, patch_settings):
        """Market not in 60-180 second window → no signal."""
        from signal_engine import SignalEngine

        # Expires in 10 minutes (600s), outside window
        far_market = {
            "market_id": "0xfar",
            "question": "Bitcoin Up or Down - Feb 17, 3:20PM-3:25PM ET",
            "is_btc_5m": True,
            "neg_risk": True,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            "outcomes": [
                {"outcome": "Up", "token_id": "t1", "orderbook": {"best_ask": 0.55, "asks": [{"price": 0.55, "size": 500}], "spread_pct": 0.2}},
                {"outcome": "Down", "token_id": "t2", "orderbook": {"best_ask": 0.46, "asks": [{"price": 0.46, "size": 500}], "spread_pct": 0.2}},
            ],
        }

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(far_market)

        assert signal is None

    @pytest.mark.asyncio
    async def test_non_btc_market_ignored(self, mock_binance_feed, patch_settings):
        from signal_engine import SignalEngine

        non_btc = {
            "market_id": "0xeth",
            "question": "Will it rain tomorrow?",
            "is_btc_5m": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
            "outcomes": [],
        }

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(non_btc)

        assert signal is None

    @pytest.mark.asyncio
    async def test_duplicate_market_deduped(self, mock_btc_5m_market, mock_binance_feed, patch_settings):
        from signal_engine import SignalEngine

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())

            signal1 = await engine._check_late_market(mock_btc_5m_market)
            assert signal1 is not None

            # Same market again → should be deduped
            signal2 = await engine._check_late_market(mock_btc_5m_market)
            assert signal2 is None

    @pytest.mark.asyncio
    async def test_signal_has_token_id(self, mock_btc_5m_market, mock_binance_feed, patch_settings):
        from signal_engine import SignalEngine

        with patch("signal_engine.binance_feed", mock_binance_feed):
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_late_market(mock_btc_5m_market)

        assert signal is not None
        assert signal["legs"][0]["token_id"] is not None
        assert len(signal["legs"][0]["token_id"]) > 0
