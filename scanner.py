"""
Market scanner for Polymarket arbitrage bot.
Continuously scans active markets using Gamma API and CLOB orderbook data.
Supports dual-mode scanning: standard arb scan + fast BTC 5m scan.
"""
import asyncio
import json
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config import settings
from db import db
from logger import get_logger
from clob_client import clob_client
from utils.helpers import (
    calculate_spread,
    validate_orderbook_depth,
    time_to_close,
    is_within_late_window,
    is_btc_5m_market,
    safe_float,
    safe_int
)

logger = get_logger("scanner")


class MarketScanner:
    """Scans Polymarket markets and fetches orderbook data."""

    def __init__(self, market_queue: asyncio.Queue):
        self.market_queue = market_queue
        self.gamma_api_url = "https://gamma-api.polymarket.com"
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False

    async def start(self) -> None:
        """Start the market scanner with dual-mode scan loops."""
        self.running = True

        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector)
        logger.info("Market scanner started")

        tasks = [asyncio.create_task(self._arb_scan_loop())]
        if settings.enable_late_market:
            tasks.append(asyncio.create_task(self._btc_5m_scan_loop()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the market scanner."""
        self.running = False
        if self.session:
            await self.session.close()
        logger.info("Market scanner stopped")

    # ================================================================
    # STANDARD ARB SCAN LOOP
    # ================================================================

    async def _arb_scan_loop(self) -> None:
        """Standard scan loop for arb strategies."""
        while self.running:
            try:
                await self._scan_markets()
                await asyncio.sleep(settings.scanner_interval_seconds)
            except Exception as e:
                logger.error(f"Arb scan error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _scan_markets(self) -> None:
        """Scan active markets from Gamma API for arb opportunities."""
        try:
            markets = await self._fetch_gamma_markets()
            logger.info(f"Fetched {len(markets)} markets from Gamma API")

            passed_count = 0
            for market in markets:
                try:
                    if not self._passes_basic_filters(market):
                        continue

                    passed_count += 1
                    enriched_market = await self._enrich_with_orderbook(market)

                    if enriched_market:
                        await self._store_market(enriched_market)
                        await self.market_queue.put(enriched_market)

                except Exception as e:
                    logger.warning(f"Error processing market {market.get('id', market.get('condition_id'))}: {e}")
                    continue

            logger.info(f"Processed {passed_count} markets (passed filters)")

        except Exception as e:
            logger.error(f"Error scanning markets: {e}", exc_info=True)

    async def _fetch_gamma_markets(self) -> List[Dict[str, Any]]:
        """Fetch active markets from Gamma API."""
        url = f"{self.gamma_api_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "volume_num_min": settings.min_market_volume,
            "limit": 100,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with self.session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    data = await response.json()
                    return data if isinstance(data, list) else []
                else:
                    logger.warning(f"Gamma API returned status {response.status}")
                    return []

        except asyncio.TimeoutError:
            logger.warning("Gamma API request timed out after 30s")
            return []
        except Exception as e:
            logger.error(f"Error fetching Gamma markets: {e}")
            return []

    def _passes_basic_filters(self, market: Dict[str, Any]) -> bool:
        """Apply basic filters for arb-eligible markets."""
        if not market.get("active", False):
            return False

        volume = safe_float(market.get("volume", 0))
        if volume < settings.min_market_volume:
            return False

        end_date_iso = market.get("endDate") or market.get("end_date_iso")
        if end_date_iso:
            try:
                expires_at = datetime.fromisoformat(end_date_iso.replace('Z', '+00:00'))
                seconds_to_close = time_to_close(expires_at)
                min_seconds = settings.min_time_to_close_minutes * 60

                if seconds_to_close < min_seconds:
                    return False
            except Exception as e:
                logger.debug(f"Error parsing end_date_iso: {e}")
                return False
        else:
            return False

        # Check outcomes — Gamma returns stringified JSON
        outcomes = self._parse_json_field(market.get("outcomes", "[]"))
        if not outcomes or len(outcomes) < 2:
            return False

        return True

    # ================================================================
    # BTC 5M FAST SCAN LOOP
    # ================================================================

    async def _btc_5m_scan_loop(self) -> None:
        """Fast scan loop for BTC 5-minute late-market opportunities."""
        logger.info("BTC 5m fast-scan loop started (interval: 2s)")
        while self.running:
            try:
                await self._scan_btc_5m_markets()
                await asyncio.sleep(settings.btc_5m_scan_interval_seconds)
            except Exception as e:
                logger.error(f"BTC 5m scan error: {e}", exc_info=True)
                await asyncio.sleep(3)

    async def _scan_btc_5m_markets(self) -> None:
        """Scan for BTC 5-minute markets approaching close."""
        try:
            markets = await self._fetch_btc_5m_markets()

            for market in markets:
                try:
                    if not self._passes_btc_5m_filters(market):
                        continue

                    enriched = await self._enrich_with_orderbook(market)
                    if enriched:
                        enriched["is_btc_5m"] = True
                        await self.market_queue.put(enriched)

                except Exception as e:
                    logger.debug(f"Error processing BTC 5m market: {e}")

        except Exception as e:
            logger.error(f"Error scanning BTC 5m markets: {e}", exc_info=True)

    async def _fetch_btc_5m_markets(self) -> List[Dict[str, Any]]:
        """Fetch BTC 5-minute markets from Gamma API."""
        # Try the markets endpoint with text search
        url = f"{self.gamma_api_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": 20,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with self.session.get(url, params=params, timeout=timeout) as response:
                if response.status == 200:
                    all_markets = await response.json()
                    if not isinstance(all_markets, list):
                        return []

                    # Filter client-side for BTC 5m markets
                    btc_markets = []
                    for m in all_markets:
                        question = m.get("question", "")
                        if is_btc_5m_market(question):
                            btc_markets.append(m)

                    if btc_markets:
                        logger.debug(f"Found {len(btc_markets)} BTC 5m markets")
                    return btc_markets
                return []
        except Exception as e:
            logger.warning(f"Error fetching BTC 5m markets: {e}")
            return []

    def _passes_btc_5m_filters(self, market: Dict[str, Any]) -> bool:
        """Filter for BTC 5m markets in the late-market trading window."""
        question = market.get("question", "")
        if not is_btc_5m_market(question):
            return False

        if not market.get("active", False):
            return False

        if not market.get("acceptingOrders", True):
            return False

        end_date = market.get("endDate") or market.get("end_date_iso")
        if not end_date:
            return False

        try:
            expires_at = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            if not is_within_late_window(
                expires_at,
                settings.late_market_window_start,
                settings.late_market_window_end,
            ):
                return False
        except Exception:
            return False

        return True

    # ================================================================
    # SHARED: ORDERBOOK ENRICHMENT
    # ================================================================

    async def _enrich_with_orderbook(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Enrich market with real orderbook data from CLOB API.
        Parses Gamma API's stringified JSON fields and fetches live orderbooks.
        """
        market_id = market.get("id") or market.get("condition_id") or market.get("conditionId")

        # Parse outcomes — Gamma API returns stringified JSON arrays
        outcomes = self._parse_json_field(market.get("outcomes", "[]"))

        # Parse clobTokenIds
        token_ids = self._parse_json_field(market.get("clobTokenIds", "[]"))

        if not market_id or not outcomes:
            return None

        # If token IDs don't match outcomes, try alternative field names
        if len(token_ids) != len(outcomes):
            # Try 'tokens' field which some responses use
            tokens_field = market.get("tokens", [])
            if isinstance(tokens_field, list) and len(tokens_field) == len(outcomes):
                token_ids = [t.get("token_id", t) if isinstance(t, dict) else t for t in tokens_field]

        if len(token_ids) != len(outcomes):
            logger.debug(f"Skipping market {market_id}: outcomes({len(outcomes)}) != tokens({len(token_ids)})")
            return None

        neg_risk = market.get("negRisk", False)
        enriched_outcomes = []

        for i, outcome_name in enumerate(outcomes):
            token_id = token_ids[i]

            # Fetch real orderbook from CLOB
            orderbook = await clob_client.get_orderbook(token_id)

            if orderbook is None:
                orderbook = {
                    "asks": [], "bids": [],
                    "best_ask": None, "best_bid": None,
                    "spread_pct": None, "asks_depth": 0, "bids_depth": 0
                }

            enriched_outcomes.append({
                "outcome": outcome_name,
                "token_id": token_id,
                "orderbook": orderbook,
            })

        # Parse outcomePrices for reference
        outcome_prices = self._parse_json_field(market.get("outcomePrices", "[]"))
        try:
            outcome_prices = [float(p) for p in outcome_prices]
        except (ValueError, TypeError):
            outcome_prices = []

        enriched = {
            "market_id": market_id,
            "condition_id": market.get("conditionId", market_id),
            "question": market.get("question", ""),
            "description": market.get("description", ""),
            "slug": market.get("slug", ""),
            "volume": safe_float(market.get("volume", 0)),
            "liquidity": safe_float(market.get("liquidity", 0)),
            "expires_at": market.get("endDate") or market.get("end_date_iso"),
            "outcomes": enriched_outcomes,
            "outcome_prices": outcome_prices,
            "neg_risk": neg_risk,
            "active": market.get("active", True),
            "accepting_orders": market.get("acceptingOrders", True),
            "last_scanned_at": datetime.utcnow(),
        }

        return enriched

    def _parse_json_field(self, field) -> list:
        """Parse a Gamma API field that may be a stringified JSON array or a list."""
        if isinstance(field, list):
            return field
        if isinstance(field, str):
            try:
                parsed = json.loads(field)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    async def _store_market(self, market: Dict[str, Any]) -> None:
        """Store market in MongoDB."""
        try:
            await db.upsert_market(market)
        except Exception as e:
            logger.warning(f"Error storing market {market.get('market_id')}: {e}")


async def start_scanner(market_queue: asyncio.Queue) -> MarketScanner:
    """Start the market scanner."""
    scanner = MarketScanner(market_queue)
    asyncio.create_task(scanner.start())
    return scanner
