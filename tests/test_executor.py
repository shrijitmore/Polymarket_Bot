"""Tests for the order executor."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("executor.settings") as mock_settings:
        mock_settings.dry_run = True
        mock_settings.order_timeout_seconds = 5
        mock_settings.max_slippage_pct = 0.3
        mock_settings.bankroll = 5000.0
        yield mock_settings


@pytest.fixture(autouse=True)
def patch_db():
    with patch("executor.db") as mock_db:
        mock_db.create_position = AsyncMock(return_value="test_id")
        mock_db.update_position = AsyncMock()
        mock_db.log_event = AsyncMock()
        yield mock_db


@pytest.fixture(autouse=True)
def patch_risk_guard():
    with patch("executor.get_risk_guard") as mock_rg_fn:
        mock_rg = AsyncMock()
        mock_rg.validate_trade = AsyncMock(return_value=(True, "OK"))
        mock_rg.record_trade_result = AsyncMock()
        mock_rg_fn.return_value = mock_rg
        yield mock_rg


@pytest.fixture
def sample_signal():
    return {
        "strategy": "yes_no",
        "market_id": "0xtest",
        "question": "Test market?",
        "position_id": "pos_test_123",
        "legs": [
            {
                "outcome": "Yes",
                "token_id": "tok_yes_abc",
                "neg_risk": False,
                "price": 0.45,
                "size_usd": 50.0,
                "size_tokens": 111.11,
                "spread_pct": 0.2,
            },
            {
                "outcome": "No",
                "token_id": "tok_no_def",
                "neg_risk": False,
                "price": 0.50,
                "size_usd": 50.0,
                "size_tokens": 100.0,
                "spread_pct": 0.2,
            },
        ],
        "total_cost": 0.95,
        "expected_payout": 1.0,
        "expected_edge": 5.0,
        "expires_at": "2026-12-31T23:59:59Z",
        "detected_at": "2026-02-17T12:00:00",
    }


class TestDryRunExecution:

    @pytest.mark.asyncio
    async def test_dry_run_succeeds(self, sample_signal, patch_db, patch_risk_guard):
        from executor import OrderExecutor

        executor = OrderExecutor(asyncio.Queue())
        success = await executor._execute_dry_run(sample_signal, executor._create_position_record(sample_signal))

        assert success is True
        # Verify position was updated
        patch_db.update_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_dry_run_creates_orders(self, sample_signal, patch_db):
        from executor import OrderExecutor

        executor = OrderExecutor(asyncio.Queue())
        position = executor._create_position_record(sample_signal)
        await executor._execute_dry_run(sample_signal, position)

        # Check the update_position call includes orders
        call_args = patch_db.update_position.call_args
        updated = call_args[0][1]
        assert len(updated["orders"]) == 2
        assert updated["orders"][0]["status"] == "filled"

    @pytest.mark.asyncio
    async def test_db_log_event_correct_signature(self, sample_signal, patch_db):
        """Verify db.log_event is called with correct keyword args."""
        from executor import OrderExecutor

        executor = OrderExecutor(asyncio.Queue())
        position = executor._create_position_record(sample_signal)
        await executor._execute_dry_run(sample_signal, position)

        patch_db.log_event.assert_called_once()
        call_kwargs = patch_db.log_event.call_args
        # Should be called with keyword arguments
        assert "event_type" in call_kwargs.kwargs or call_kwargs[1].get("event_type")


class TestRiskGuardIntegration:

    @pytest.mark.asyncio
    async def test_rejected_by_risk_guard(self, sample_signal, patch_risk_guard, patch_db):
        from executor import OrderExecutor

        patch_risk_guard.validate_trade.return_value = (False, "Position too large")

        executor = OrderExecutor(asyncio.Queue())
        await executor._execute_signal(sample_signal)

        # Should record failed trade
        patch_risk_guard.record_trade_result.assert_called_once()
        call_args = patch_risk_guard.record_trade_result.call_args
        assert call_args[0][1] is False  # success=False


class TestPositionRecord:

    def test_creates_correct_record(self, sample_signal):
        from executor import OrderExecutor

        executor = OrderExecutor(asyncio.Queue())
        record = executor._create_position_record(sample_signal)

        assert record["position_id"] == "pos_test_123"
        assert record["strategy"] == "yes_no"
        assert record["status"] == "pending"
        assert len(record["legs"]) == 2
        assert record["realized_pnl"] is None


class TestTokenIdInOrders:

    @pytest.mark.asyncio
    async def test_missing_token_id_returns_none(self, patch_settings):
        """Executor should fail gracefully if token_id missing from leg."""
        from executor import OrderExecutor

        patch_settings.dry_run = False

        with patch("executor.clob_client") as mock_clob:
            executor = OrderExecutor(asyncio.Queue())
            leg = {"outcome": "Yes", "price": 0.5, "size_tokens": 100}  # No token_id!
            result = await executor._place_order("0xmarket", leg)
            assert result is None
            mock_clob.place_order.assert_not_called()
