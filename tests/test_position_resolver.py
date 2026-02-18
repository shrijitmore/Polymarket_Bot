"""Tests for the position resolver."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_db():
    with patch("position_resolver.db") as mock_db:
        mock_db.get_open_positions = AsyncMock(return_value=[])
        mock_db.update_position = AsyncMock()
        mock_db.log_event = AsyncMock()
        mock_db.get_daily_pnl = AsyncMock(return_value=None)
        mock_db.upsert_daily_pnl = AsyncMock()
        yield mock_db


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("position_resolver.settings") as mock_settings:
        mock_settings.resolver_interval_seconds = 60
        yield mock_settings


def make_position(
    strategy="yes_no",
    legs=None,
    actual_total_cost=0.95,
    position_id="pos_test_001",
    market_id="0xabc123",
):
    if legs is None:
        legs = [
            {"outcome": "Yes", "size_tokens": 111.11, "price": 0.45},
            {"outcome": "No",  "size_tokens": 100.0,  "price": 0.50},
        ]
    return {
        "position_id": position_id,
        "market_id": market_id,
        "strategy": strategy,
        "status": "open",
        "legs": legs,
        "actual_total_cost": actual_total_cost,
        "opened_at": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# _calculate_pnl tests
# ---------------------------------------------------------------------------

class TestCalculatePnl:

    def setup_method(self):
        from position_resolver import PositionResolver
        self.resolver = PositionResolver()

    def test_yes_no_yes_wins(self):
        """YES/NO arb: YES wins → payout from YES tokens minus total cost."""
        position = make_position(
            strategy="yes_no",
            legs=[
                {"outcome": "Yes", "size_tokens": 111.11, "price": 0.45},
                {"outcome": "No",  "size_tokens": 100.0,  "price": 0.50},
            ],
            actual_total_cost=0.95,
        )
        pnl = self.resolver._calculate_pnl(position, "Yes", "yes_no")
        # 111.11 * 1.0 - 0.95
        assert abs(pnl - (111.11 - 0.95)) < 0.001

    def test_yes_no_no_wins(self):
        """YES/NO arb: NO wins → payout from NO tokens minus total cost."""
        position = make_position(
            strategy="yes_no",
            legs=[
                {"outcome": "Yes", "size_tokens": 111.11, "price": 0.45},
                {"outcome": "No",  "size_tokens": 100.0,  "price": 0.50},
            ],
            actual_total_cost=0.95,
        )
        pnl = self.resolver._calculate_pnl(position, "No", "yes_no")
        assert abs(pnl - (100.0 - 0.95)) < 0.001

    def test_one_of_many_arb_winner_found(self):
        """One-of-many: outcome B wins → payout from B tokens minus total cost."""
        position = make_position(
            strategy="one_of_many",
            legs=[
                {"outcome": "A", "size_tokens": 50.0, "price": 0.30},
                {"outcome": "B", "size_tokens": 50.0, "price": 0.30},
                {"outcome": "C", "size_tokens": 50.0, "price": 0.30},
            ],
            actual_total_cost=0.90,
        )
        pnl = self.resolver._calculate_pnl(position, "B", "one_of_many")
        assert abs(pnl - (50.0 - 0.90)) < 0.001

    def test_one_of_many_no_matching_leg(self):
        """One-of-many: winner not in legs → total loss."""
        position = make_position(
            strategy="one_of_many",
            legs=[
                {"outcome": "A", "size_tokens": 50.0, "price": 0.30},
                {"outcome": "B", "size_tokens": 50.0, "price": 0.30},
            ],
            actual_total_cost=0.60,
        )
        pnl = self.resolver._calculate_pnl(position, "X", "one_of_many")
        assert abs(pnl - (-0.60)) < 0.001

    def test_late_market_win(self):
        """Late market: predicted side wins."""
        position = make_position(
            strategy="late_market",
            legs=[{"outcome": "Up", "size_tokens": 200.0, "price": 0.375}],
            actual_total_cost=75.0,
        )
        pnl = self.resolver._calculate_pnl(position, "Up", "late_market")
        assert abs(pnl - (200.0 - 75.0)) < 0.001

    def test_late_market_loss(self):
        """Late market: predicted side loses → total cost lost."""
        position = make_position(
            strategy="late_market",
            legs=[{"outcome": "Up", "size_tokens": 200.0, "price": 0.375}],
            actual_total_cost=75.0,
        )
        pnl = self.resolver._calculate_pnl(position, "Down", "late_market")
        assert abs(pnl - (-75.0)) < 0.001

    def test_case_insensitive_winner_matching(self):
        """Winner matching should be case-insensitive."""
        position = make_position(
            strategy="yes_no",
            legs=[
                {"outcome": "Yes", "size_tokens": 111.11, "price": 0.45},
                {"outcome": "No",  "size_tokens": 100.0,  "price": 0.50},
            ],
            actual_total_cost=0.95,
        )
        # API might return "YES" or "yes" — should still match
        pnl_upper = self.resolver._calculate_pnl(position, "YES", "yes_no")
        pnl_lower = self.resolver._calculate_pnl(position, "yes", "yes_no")
        assert abs(pnl_upper - pnl_lower) < 0.001


# ---------------------------------------------------------------------------
# _extract_winner tests
# ---------------------------------------------------------------------------

class TestExtractWinner:

    def setup_method(self):
        from position_resolver import PositionResolver
        self.resolver = PositionResolver()

    def test_direct_winner_field(self):
        market = {"resolved": True, "winner": "Yes"}
        assert self.resolver._extract_winner(market) == "Yes"

    def test_tokens_array_winner(self):
        market = {
            "resolved": True,
            "tokens": [
                {"outcome": "Yes", "winner": True},
                {"outcome": "No",  "winner": False},
            ]
        }
        assert self.resolver._extract_winner(market) == "Yes"

    def test_outcomes_array_winner(self):
        market = {
            "resolved": True,
            "outcomes": [
                {"outcome": "Up",   "winner": True},
                {"outcome": "Down", "winner": False},
            ]
        }
        assert self.resolver._extract_winner(market) == "Up"

    def test_no_winner_returns_none(self):
        market = {"resolved": True}
        assert self.resolver._extract_winner(market) is None


# ---------------------------------------------------------------------------
# _check_and_resolve integration tests
# ---------------------------------------------------------------------------

class TestCheckAndResolve:

    @pytest.mark.asyncio
    async def test_unresolved_market_skipped(self, patch_db):
        """If market not resolved, position should not be updated."""
        from position_resolver import PositionResolver

        resolver = PositionResolver()
        position = make_position()

        with patch.object(resolver, "_fetch_market", new=AsyncMock(
            return_value={"resolved": False}
        )):
            await resolver._check_and_resolve(position)

        patch_db.update_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolved_market_closes_position(self, patch_db):
        """Resolved market should close position and write PnL."""
        from position_resolver import PositionResolver

        resolver = PositionResolver()
        position = make_position(
            strategy="yes_no",
            legs=[
                {"outcome": "Yes", "size_tokens": 111.11, "price": 0.45},
                {"outcome": "No",  "size_tokens": 100.0,  "price": 0.50},
            ],
            actual_total_cost=0.95,
        )

        with patch.object(resolver, "_fetch_market", new=AsyncMock(
            return_value={"resolved": True, "winner": "Yes"}
        )):
            await resolver._check_and_resolve(position)

        patch_db.update_position.assert_called_once()
        call_args = patch_db.update_position.call_args[0]
        update = call_args[1]
        assert update["status"] == "closed"
        assert update["winner"] == "Yes"
        assert update["realized_pnl"] is not None
        assert update["realized_pnl"] > 0  # arb should always profit

    @pytest.mark.asyncio
    async def test_fetch_failure_skips_gracefully(self, patch_db):
        """If API fetch fails, position should not be touched."""
        from position_resolver import PositionResolver

        resolver = PositionResolver()
        position = make_position()

        with patch.object(resolver, "_fetch_market", new=AsyncMock(return_value=None)):
            await resolver._check_and_resolve(position)

        patch_db.update_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_daily_pnl_upserted_on_resolution(self, patch_db):
        """Daily PnL should be updated when a position resolves."""
        from position_resolver import PositionResolver

        resolver = PositionResolver()
        position = make_position()

        with patch.object(resolver, "_fetch_market", new=AsyncMock(
            return_value={"resolved": True, "winner": "Yes"}
        )):
            await resolver._check_and_resolve(position)

        patch_db.upsert_daily_pnl.assert_called_once()
