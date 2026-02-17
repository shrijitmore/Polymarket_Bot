"""Tests for the market scanner."""
import pytest
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def patch_settings():
    with patch("scanner.settings") as mock_settings:
        mock_settings.min_market_volume = 5000
        mock_settings.min_time_to_close_minutes = 30
        mock_settings.scanner_interval_seconds = 5
        mock_settings.enable_late_market = True
        mock_settings.late_market_window_start = 180
        mock_settings.late_market_window_end = 60
        mock_settings.btc_5m_scan_interval_seconds = 2
        yield mock_settings


@pytest.fixture(autouse=True)
def patch_db():
    with patch("scanner.db") as mock_db:
        mock_db.upsert_market = AsyncMock()
        yield mock_db


@pytest.fixture(autouse=True)
def patch_clob():
    with patch("scanner.clob_client") as mock_clob:
        mock_clob.get_orderbook = AsyncMock(return_value={
            "asks": [{"price": 0.55, "size": 500}],
            "bids": [{"price": 0.54, "size": 400}],
            "best_ask": 0.55,
            "best_bid": 0.54,
            "spread_pct": 0.2,
            "asks_depth": 500,
            "bids_depth": 400,
        })
        yield mock_clob


class TestBasicFilters:
    def test_rejects_inactive_market(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "active": False,
            "volume": 10000,
            "endDate": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "outcomes": '["Yes", "No"]',
        }
        assert scanner._passes_basic_filters(market) is False

    def test_rejects_low_volume(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "active": True,
            "volume": 100,  # Below 5000 threshold
            "endDate": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "outcomes": '["Yes", "No"]',
        }
        assert scanner._passes_basic_filters(market) is False

    def test_rejects_closing_soon(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "active": True,
            "volume": 10000,
            "endDate": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),  # < 30 min
            "outcomes": '["Yes", "No"]',
        }
        assert scanner._passes_basic_filters(market) is False

    def test_accepts_valid_market(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "active": True,
            "volume": 10000,
            "endDate": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "outcomes": '["Yes", "No"]',
        }
        assert scanner._passes_basic_filters(market) is True


class TestBtc5mFilters:
    def test_accepts_btc_5m_in_window(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "question": "Bitcoin Up or Down - February 17, 3:20PM-3:25PM ET",
            "active": True,
            "acceptingOrders": True,
            "endDate": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
        }
        assert scanner._passes_btc_5m_filters(market) is True

    def test_rejects_non_btc(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "question": "Will it rain tomorrow?",
            "active": True,
            "endDate": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
        }
        assert scanner._passes_btc_5m_filters(market) is False

    def test_rejects_outside_window(self, patch_settings):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        market = {
            "question": "Bitcoin Up or Down - February 17, 3:20PM-3:25PM ET",
            "active": True,
            "acceptingOrders": True,
            "endDate": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        }
        assert scanner._passes_btc_5m_filters(market) is False


class TestEnrichWithOrderbook:
    @pytest.mark.asyncio
    async def test_parses_stringified_json_fields(self, patch_clob):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        scanner.session = MagicMock()

        market = {
            "id": "0xmarket123",
            "conditionId": "0xmarket123",
            "question": "Test Market?",
            "volume": "10000",
            "liquidity": "5000",
            "endDate": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["token_yes_123", "token_no_456"]',
            "outcomePrices": '[0.55, 0.45]',
            "negRisk": False,
            "active": True,
        }

        enriched = await scanner._enrich_with_orderbook(market)

        assert enriched is not None
        assert enriched["market_id"] == "0xmarket123"
        assert len(enriched["outcomes"]) == 2
        assert enriched["outcomes"][0]["token_id"] == "token_yes_123"
        assert enriched["outcomes"][1]["token_id"] == "token_no_456"
        assert enriched["outcomes"][0]["orderbook"]["best_ask"] == 0.55

    @pytest.mark.asyncio
    async def test_maps_token_ids_to_outcomes(self, patch_clob):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        scanner.session = MagicMock()

        market = {
            "id": "0xtest",
            "question": "Test?",
            "outcomes": '["Up", "Down"]',
            "clobTokenIds": '["tok_up_abc", "tok_down_def"]',
            "active": True,
        }

        enriched = await scanner._enrich_with_orderbook(market)
        assert enriched is not None
        assert enriched["outcomes"][0]["outcome"] == "Up"
        assert enriched["outcomes"][0]["token_id"] == "tok_up_abc"
        assert enriched["outcomes"][1]["outcome"] == "Down"
        assert enriched["outcomes"][1]["token_id"] == "tok_down_def"

    @pytest.mark.asyncio
    async def test_mismatched_tokens_returns_none(self, patch_clob):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        scanner.session = MagicMock()

        market = {
            "id": "0xbad",
            "question": "Test?",
            "outcomes": '["A", "B", "C"]',
            "clobTokenIds": '["tok1", "tok2"]',  # 3 outcomes but 2 tokens
            "active": True,
        }

        enriched = await scanner._enrich_with_orderbook(market)
        assert enriched is None


class TestParseJsonField:
    def test_parses_string(self):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        assert scanner._parse_json_field('["a", "b"]') == ["a", "b"]

    def test_passes_list_through(self):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        assert scanner._parse_json_field(["a", "b"]) == ["a", "b"]

    def test_invalid_json_returns_empty(self):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        assert scanner._parse_json_field("not json") == []

    def test_none_returns_empty(self):
        import asyncio
        from scanner import MarketScanner

        scanner = MarketScanner(asyncio.Queue())
        assert scanner._parse_json_field(None) == []
