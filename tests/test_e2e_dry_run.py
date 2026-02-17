"""
End-to-end integration test for the full pipeline in DRY_RUN mode.
Tests: Scanner -> Signal Engine -> Executor with mocked external services.
"""
import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock


def make_mock_settings():
    """Create a mock settings object with all required attributes."""
    s = MagicMock()
    s.dry_run = True
    s.bankroll = 5000.0
    s.max_arb_position_pct = 2.0
    s.max_arb_position_size = 100.0
    s.max_late_position_pct = 1.5
    s.max_late_position_size = 75.0
    s.max_daily_exposure_pct = 25.0
    s.max_daily_exposure = 1250.0
    s.max_concurrent_positions = 10
    s.daily_loss_halt_pct = 5.0
    s.daily_loss_halt_amount = 250.0
    s.max_consecutive_fails = 3
    s.min_arb_edge_pct = 2.0
    s.max_slippage_pct = 0.3
    s.order_timeout_seconds = 5
    s.min_market_volume = 5000
    s.min_time_to_close_minutes = 30
    s.max_spread_one_of_many = 2.0
    s.max_spread_yes_no = 1.5
    s.max_spread_late_market = 1.0
    s.enable_one_of_many = False
    s.enable_yes_no = True
    s.enable_late_market = True
    s.scanner_interval_seconds = 10
    s.late_market_window_start = 180
    s.late_market_window_end = 60
    s.late_market_min_deviation_pct = 0.05
    s.late_market_max_volatility_pct = 1.5
    s.late_market_max_price = 0.95
    s.btc_5m_scan_interval_seconds = 2
    s.btc_5m_min_volume = 100
    return s


class TestE2ELateMarketDryRun:
    """
    End-to-end test: A BTC 5m market flows through the full pipeline.
    Scanner detects it -> Signal engine generates signal -> Executor DRY_RUN trades it.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_btc_5m(self):
        """
        Simulate the full BTC 5m pipeline with all external services mocked.
        """
        mock_settings = make_mock_settings()

        # Mock DB
        mock_db = AsyncMock()
        mock_db.count_open_positions.return_value = 0
        mock_db.get_total_exposure.return_value = 0.0
        mock_db.get_daily_pnl.return_value = None
        mock_db.create_position.return_value = "test_id"
        mock_db.update_position.return_value = None
        mock_db.log_event.return_value = None

        # Mock Binance feed — BTC trending up
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 97500.0
        mock_feed.get_volatility.return_value = 0.03
        mock_feed.price_history = {
            "btcusdt": [97000.0 + i * 16.67 for i in range(30)]
        }

        expires = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()

        # A BTC 5m market ready for the late-market strategy
        btc_market = {
            "market_id": "0xbtc5m_e2e",
            "condition_id": "0xbtc5m_e2e",
            "question": "Bitcoin Up or Down - February 17, 3:20PM-3:25PM ET",
            "slug": "btc-updown-5m",
            "volume": 5000.0,
            "liquidity": 2000.0,
            "expires_at": expires,
            "is_btc_5m": True,
            "neg_risk": True,
            "active": True,
            "accepting_orders": True,
            "outcomes": [
                {
                    "outcome": "Up",
                    "token_id": "tok_up_e2e_" + "a" * 50,
                    "orderbook": {
                        "asks": [{"price": 0.60, "size": 500}],
                        "bids": [{"price": 0.59, "size": 400}],
                        "best_ask": 0.60,
                        "best_bid": 0.59,
                        "spread_pct": 0.17,
                        "asks_depth": 500,
                        "bids_depth": 400,
                    }
                },
                {
                    "outcome": "Down",
                    "token_id": "tok_down_e2e_" + "b" * 50,
                    "orderbook": {
                        "asks": [{"price": 0.41, "size": 500}],
                        "bids": [{"price": 0.40, "size": 400}],
                        "best_ask": 0.41,
                        "best_bid": 0.40,
                        "spread_pct": 0.24,
                        "asks_depth": 500,
                        "bids_depth": 400,
                    }
                }
            ],
            "outcome_prices": [0.60, 0.40],
        }

        # Step 1: Signal engine processes the market
        with patch("signal_engine.settings", mock_settings), \
             patch("signal_engine.db", mock_db), \
             patch("signal_engine.binance_feed", mock_feed):

            from signal_engine import SignalEngine
            market_q = asyncio.Queue()
            signal_q = asyncio.Queue()
            engine = SignalEngine(market_q, signal_q)

            signal = await engine._check_late_market(btc_market)

        assert signal is not None, "Signal engine should detect late-market opportunity"
        assert signal["strategy"] == "late_market"
        assert signal["legs"][0]["outcome"] == "Up"  # BTC trending up
        assert signal["legs"][0]["token_id"] is not None
        assert signal["expected_edge"] == pytest.approx(40.0, abs=0.5)  # 1.0 - 0.60 = 40%

        # Step 2: Executor processes the signal in DRY_RUN
        with patch("executor.settings", mock_settings), \
             patch("executor.db", mock_db), \
             patch("executor.get_risk_guard") as mock_rg_fn:

            mock_rg = AsyncMock()
            mock_rg.validate_trade.return_value = (True, "OK")
            mock_rg.record_trade_result.return_value = None
            mock_rg_fn.return_value = mock_rg

            from executor import OrderExecutor
            executor = OrderExecutor(asyncio.Queue())
            position = executor._create_position_record(signal)
            success = await executor._execute_dry_run(signal, position)

        assert success is True, "DRY_RUN execution should succeed"

        # Verify DB was updated
        mock_db.update_position.assert_called()
        call_args = mock_db.update_position.call_args
        updated_pos = call_args[0][1]
        assert updated_pos["status"] == "open"
        assert len(updated_pos["orders"]) == 1
        assert updated_pos["orders"][0]["status"] == "filled"

        # Verify log_event was called with correct signature
        mock_db.log_event.assert_called()
        log_call = mock_db.log_event.call_args
        assert log_call.kwargs.get("event_type") == "dry_run_trade_executed"
        assert "details" in log_call.kwargs


class TestE2EYesNoArbDryRun:
    """End-to-end test for YES/NO arb pipeline."""

    @pytest.mark.asyncio
    async def test_arb_pipeline(self):
        mock_settings = make_mock_settings()

        mock_db = AsyncMock()
        mock_db.count_open_positions.return_value = 0
        mock_db.get_total_exposure.return_value = 0.0
        mock_db.get_daily_pnl.return_value = None
        mock_db.create_position.return_value = "test_id"
        mock_db.update_position.return_value = None
        mock_db.log_event.return_value = None

        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        arb_market = {
            "market_id": "0xarb_e2e",
            "question": "Will X happen?",
            "expires_at": expires,
            "neg_risk": False,
            "outcomes": [
                {
                    "outcome": "Yes",
                    "token_id": "tok_yes_arb",
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
                    "token_id": "tok_no_arb",
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

        # Signal engine detects arb
        with patch("signal_engine.settings", mock_settings), \
             patch("signal_engine.db", mock_db):

            from signal_engine import SignalEngine
            engine = SignalEngine(asyncio.Queue(), asyncio.Queue())
            signal = await engine._check_yes_no_arb(arb_market)

        assert signal is not None
        assert signal["strategy"] == "yes_no"
        assert signal["expected_edge"] == pytest.approx(5.0, abs=0.1)

        # Executor DRY_RUN trades it
        with patch("executor.settings", mock_settings), \
             patch("executor.db", mock_db), \
             patch("executor.get_risk_guard") as mock_rg_fn:

            mock_rg = AsyncMock()
            mock_rg.validate_trade.return_value = (True, "OK")
            mock_rg.record_trade_result.return_value = None
            mock_rg_fn.return_value = mock_rg

            from executor import OrderExecutor
            executor = OrderExecutor(asyncio.Queue())
            position = executor._create_position_record(signal)
            success = await executor._execute_dry_run(signal, position)

        assert success is True
        mock_db.update_position.assert_called()
