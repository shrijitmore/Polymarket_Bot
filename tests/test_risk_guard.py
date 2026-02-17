"""Tests for risk guard validation."""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("risk_guard.settings") as mock_settings:
        mock_settings.bankroll = 5000.0
        mock_settings.max_arb_position_pct = 2.0
        mock_settings.max_arb_position_size = 100.0
        mock_settings.max_late_position_size = 75.0
        mock_settings.max_daily_exposure = 1250.0
        mock_settings.max_concurrent_positions = 10
        mock_settings.daily_loss_halt_amount = 250.0
        mock_settings.max_consecutive_fails = 3
        yield mock_settings


@pytest.fixture(autouse=True)
def patch_db():
    with patch("risk_guard.db") as mock_db:
        mock_db.count_open_positions = AsyncMock(return_value=0)
        mock_db.get_total_exposure = AsyncMock(return_value=0.0)
        mock_db.get_daily_pnl = AsyncMock(return_value=None)
        mock_db.upsert_daily_pnl = AsyncMock()
        yield mock_db


@pytest.fixture
def arb_signal():
    return {
        "strategy": "yes_no",
        "total_cost": 50.0,
        "position_id": "test_pos_1",
    }


@pytest.fixture
def late_signal():
    return {
        "strategy": "late_market",
        "total_cost": 50.0,
        "position_id": "test_late_1",
    }


class TestValidateTrade:

    @pytest.mark.asyncio
    async def test_valid_trade_passes(self, arb_signal, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        is_valid, reason = await guard.validate_trade(arb_signal)
        assert is_valid is True
        assert reason == "OK"

    @pytest.mark.asyncio
    async def test_position_size_limit_arb(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        oversized = {"strategy": "yes_no", "total_cost": 200.0}  # > max 100
        is_valid, reason = await guard.validate_trade(oversized)
        assert is_valid is False
        assert "limit" in reason.lower()

    @pytest.mark.asyncio
    async def test_position_size_limit_late_market(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        oversized = {"strategy": "late_market", "total_cost": 100.0}  # > max 75
        is_valid, reason = await guard.validate_trade(oversized)
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_max_concurrent_positions(self, arb_signal, patch_db, patch_settings):
        from risk_guard import RiskGuard

        patch_db.count_open_positions.return_value = 10  # At limit
        guard = RiskGuard()
        is_valid, reason = await guard.validate_trade(arb_signal)
        assert is_valid is False
        assert "concurrent" in reason.lower()

    @pytest.mark.asyncio
    async def test_daily_exposure_limit(self, arb_signal, patch_db, patch_settings):
        from risk_guard import RiskGuard

        patch_db.get_total_exposure.return_value = 1230.0  # Near limit of 1250
        arb_signal["total_cost"] = 50.0  # Would push to 1280 > 1250
        guard = RiskGuard()
        is_valid, reason = await guard.validate_trade(arb_signal)
        assert is_valid is False
        assert "exposure" in reason.lower()

    @pytest.mark.asyncio
    async def test_daily_loss_halt(self, arb_signal, patch_db, patch_settings):
        from risk_guard import RiskGuard

        # Today's PnL is -$300, beyond -$250 halt threshold
        patch_db.get_daily_pnl.return_value = {"realized_pnl": -300.0}
        guard = RiskGuard()
        is_valid, reason = await guard.validate_trade(arb_signal)
        assert is_valid is False
        assert guard.trading_halted is True

    @pytest.mark.asyncio
    async def test_trading_halted_rejects(self, arb_signal, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        guard.halt_trading("Manual halt")
        is_valid, reason = await guard.validate_trade(arb_signal)
        assert is_valid is False
        assert "halted" in reason.lower()


class TestConsecutiveFails:

    @pytest.mark.asyncio
    async def test_consecutive_fails_halt(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.record_trade_result("pos1", False)
        await guard.record_trade_result("pos2", False)
        assert guard.trading_halted is False

        await guard.record_trade_result("pos3", False)
        assert guard.trading_halted is True
        assert guard.consecutive_fails == 3

    @pytest.mark.asyncio
    async def test_success_resets_counter(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        await guard.record_trade_result("pos1", False)
        await guard.record_trade_result("pos2", False)
        assert guard.consecutive_fails == 2

        await guard.record_trade_result("pos3", True)
        assert guard.consecutive_fails == 0

    @pytest.mark.asyncio
    async def test_resume_trading(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        guard.halt_trading("Test halt")
        assert guard.trading_halted is True

        guard.resume_trading()
        assert guard.trading_halted is False
        assert guard.consecutive_fails == 0


class TestRiskStatus:

    def test_get_risk_status(self, patch_settings):
        from risk_guard import RiskGuard

        guard = RiskGuard()
        status = guard.get_risk_status()

        assert "trading_halted" in status
        assert "consecutive_fails" in status
        assert status["trading_halted"] is False
        assert status["consecutive_fails"] == 0
