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
        # Hot-loop watchlist: market_id → enriched market snapshot
        self._watchlist: Dict[str, Dict[str, Any]] = {}

    async def start(self) -> None:
        """Start the market scanner with dual-mode scan loops."""
        self.running = True

        connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(connector=connector)
        logger.info("Market scanner started")

        tasks = [asyncio.create_task(self._arb_scan_loop())]
        if settings.enable_late_market:
            # Two-stage late-market pipeline:
            # 1. Watchlist feeder — polls Gamma every 10s to find candidates
            # 2. Hot-loop — polls orderbooks every 0.5s for watchlist markets only
            tasks.append(asyncio.create_task(self._watchlist_feeder_loop()))
            tasks.append(asyncio.create_task(self._hot_loop()))

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
    # LATE-MARKET HOT-LOOP WATCHLIST
    # ================================================================

    # ── Stage 1: Watchlist feeder (runs every 10s) ──────────────────

    async def _watchlist_feeder_loop(self) -> None:
        """
        Polls Gamma API every 10s to find BTC 5m markets closing within
        the watchlist horizon (default: 5 min). Adds them to self._watchlist
        so the hot-loop can monitor them without hitting Gamma again.
        """
        horizon = settings.watchlist_horizon_seconds  # e.g. 300s = 5 min
        logger.info(
            f"Watchlist feeder started — horizon={horizon}s, "
            f"hot-loop interval={settings.hot_loop_interval_ms}ms"
        )
        while self.running:
            try:
                await self._refresh_watchlist(horizon)
            except Exception as e:
                logger.error(f"Watchlist feeder error: {e}", exc_info=True)
            await asyncio.sleep(settings.watchlist_feeder_interval_seconds)

    async def _refresh_watchlist(self, horizon: int) -> None:
        """Fetch BTC 5m markets from Gamma and update the watchlist."""
        markets = await self._fetch_btc_5m_markets()
        now_candidates: set = set()

        for market in markets:
            question = market.get("question", "")
            if not is_btc_5m_market(question):
                continue
            if not market.get("active", False):
                continue
            if not market.get("acceptingOrders", True):
                continue

            end_date = market.get("endDate") or market.get("end_date_iso")
            if not end_date:
                continue

            try:
                expires_at = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                secs = time_to_close(expires_at)
            except Exception:
                continue

            # Add to watchlist if closing within horizon
            if 0 < secs <= horizon:
                market_id = market.get("id") or market.get("condition_id") or market.get("conditionId")
                if not market_id:
                    continue
                now_candidates.add(market_id)

                if market_id not in self._watchlist:
                    # First time seeing this market — do a full enrich
                    enriched = await self._enrich_with_orderbook(market)
                    if enriched:
                        enriched["is_btc_5m"] = True
                        self._watchlist[market_id] = enriched
                        logger.info(
                            f"📋 Watchlist +ADD: {question[:60]} | {secs:.0f}s to close"
                        )

        # Prune markets that have closed or left the horizon
        stale = [mid for mid in self._watchlist if mid not in now_candidates]
        for mid in stale:
            q = self._watchlist[mid].get("question", mid)[:50]
            logger.debug(f"Watchlist -REMOVE: {q}")
            del self._watchlist[mid]

        if self._watchlist:
            logger.debug(f"Watchlist: {len(self._watchlist)} active candidates")

    # ── Stage 2: Hot-loop (runs every 0.5s) ─────────────────────────

    async def _hot_loop(self) -> None:
        """
        Runs every hot_loop_interval_ms milliseconds.
        For each market in the watchlist:
          - Refreshes orderbooks only (no Gamma API call)
          - Checks if the market is now inside the 30s entry window
          - Pushes to the signal queue if so
        """
        interval = settings.hot_loop_interval_ms / 1000.0  # convert ms → seconds
        logger.info(f"Hot-loop started — interval={settings.hot_loop_interval_ms}ms")
        while self.running:
            try:
                await self._hot_loop_tick()
            except Exception as e:
                logger.error(f"Hot-loop error: {e}", exc_info=True)
            await asyncio.sleep(interval)

    async def _hot_loop_tick(self) -> None:
        """Single hot-loop tick — refresh orderbooks and push candidates."""
        if not self._watchlist:
            return

        for market_id, market in list(self._watchlist.items()):
            try:
                expires_at_str = market.get("expires_at")
                if not expires_at_str:
                    continue

                expires_at = datetime.fromisoformat(
                    expires_at_str.replace('Z', '+00:00')
                )
                secs = time_to_close(expires_at)

                # Drop from watchlist if expired
                if secs <= 0:
                    logger.debug(f"Hot-loop: market {market_id} expired, removing")
                    self._watchlist.pop(market_id, None)
                    continue

                # Only refresh orderbooks + push when inside the entry window
                if not is_within_late_window(
                    expires_at,
                    settings.late_market_window_start,
                    settings.late_market_window_end,
                ):
                    continue

                # Refresh orderbooks in-place (cheap — no Gamma API call)
                refreshed = await self._refresh_orderbooks(market)
                if refreshed:
                    self._watchlist[market_id] = refreshed
                    logger.debug(
                        f"🔥 Hot-loop: pushing {market.get('question','')[:50]} | {secs:.1f}s left"
                    )
                    await self.market_queue.put(refreshed)

            except Exception as e:
                logger.warning(f"Hot-loop tick error for {market_id}: {e}")

    async def _refresh_orderbooks(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Re-fetch only the orderbooks for each outcome in a watchlist market.
        Returns the updated market dict, or None on failure.
        """
        outcomes = market.get("outcomes", [])
        if not outcomes:
            return None

        refreshed_outcomes = []
        for outcome in outcomes:
            token_id = outcome.get("token_id")
            if not token_id:
                refreshed_outcomes.append(outcome)
                continue

            orderbook = await clob_client.get_orderbook(token_id)
            if orderbook is None:
                orderbook = outcome.get("orderbook", {
                    "asks": [], "bids": [],
                    "best_ask": None, "best_bid": None,
                    "spread_pct": None, "asks_depth": 0, "bids_depth": 0
                })

            refreshed_outcomes.append({**outcome, "orderbook": orderbook})

        return {**market, "outcomes": refreshed_outcomes}

    # ── Legacy BTC 5m loop (kept for reference, replaced by hot-loop) ─

    async def _btc_5m_scan_loop(self) -> None:
        """[DEPRECATED] Old BTC 5m scan loop — replaced by watchlist + hot-loop."""
        pass


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
