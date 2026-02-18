"""Tests for dashboard.py FastAPI backend."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


@pytest.fixture
def mock_db():
    """Mock the db module."""
    with patch("dashboard.db") as mock:
        mock.db = MagicMock()
        mock._connected = True
        mock.disconnect = AsyncMock()
        mock.connect = AsyncMock()
        yield mock


@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("dashboard.settings") as mock:
        mock.bankroll = 5000.0
        mock.dry_run = True
        yield mock


class TestBuildStats:
    @pytest.mark.asyncio
    async def test_returns_correct_structure(self, mock_db, mock_settings):
        from dashboard import _build_stats

        # Mock aggregate for closed positions
        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[{
            "total_pnl": 150.0,
            "total_trades": 10,
            "winning_trades": 7,
        }])
        mock_db.db.positions.aggregate = MagicMock(return_value=agg_cursor)

        # Mock daily pnl
        mock_db.db.pnl_daily.find_one = AsyncMock(return_value={
            "date": "2026-02-18",
            "realized_pnl": 25.50,
        })

        # Mock active count
        mock_db.db.positions.count_documents = AsyncMock(return_value=3)

        stats = await _build_stats()

        assert stats["total_pnl"] == 150.0
        assert stats["daily_pnl"] == 25.50
        assert stats["bankroll"] == 5150.0
        assert stats["active_positions"] == 3
        assert stats["win_rate"] == 70.0
        assert stats["total_trades"] == 10
        assert stats["winning_trades"] == 7
        assert stats["status"] == "ONLINE"
        assert stats["dry_run"] is True

    @pytest.mark.asyncio
    async def test_handles_empty_db(self, mock_db, mock_settings):
        from dashboard import _build_stats

        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[])
        mock_db.db.positions.aggregate = MagicMock(return_value=agg_cursor)
        mock_db.db.pnl_daily.find_one = AsyncMock(return_value=None)
        mock_db.db.positions.count_documents = AsyncMock(return_value=0)

        stats = await _build_stats()

        assert stats["total_pnl"] == 0.0
        assert stats["daily_pnl"] == 0.0
        assert stats["active_positions"] == 0
        assert stats["win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_no_db(self, mock_settings):
        """When DB is None, returns defaults."""
        with patch("dashboard.db") as mock:
            mock.db = None
            mock._connected = False

            from dashboard import _build_stats
            stats = await _build_stats()

            assert stats["total_pnl"] == 0.0
            assert stats["active_positions"] == 0
            assert stats["bankroll"] == 5000.0


class TestWinRateCalculation:
    @pytest.mark.asyncio
    async def test_zero_trades_zero_winrate(self, mock_db, mock_settings):
        from dashboard import _build_stats

        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[{
            "total_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
        }])
        mock_db.db.positions.aggregate = MagicMock(return_value=agg_cursor)
        mock_db.db.pnl_daily.find_one = AsyncMock(return_value=None)
        mock_db.db.positions.count_documents = AsyncMock(return_value=0)

        stats = await _build_stats()
        assert stats["win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_all_wins(self, mock_db, mock_settings):
        from dashboard import _build_stats

        agg_cursor = AsyncMock()
        agg_cursor.to_list = AsyncMock(return_value=[{
            "total_pnl": 500.0,
            "total_trades": 5,
            "winning_trades": 5,
        }])
        mock_db.db.positions.aggregate = MagicMock(return_value=agg_cursor)
        mock_db.db.pnl_daily.find_one = AsyncMock(return_value=None)
        mock_db.db.positions.count_documents = AsyncMock(return_value=0)

        stats = await _build_stats()
        assert stats["win_rate"] == 100.0


class TestConnectionManager:
    def test_disconnect_handles_missing_connection(self):
        from dashboard import ConnectionManager
        mgr = ConnectionManager()
        fake_ws = MagicMock()
        # Should not raise even if not in list
        mgr.disconnect(fake_ws)
