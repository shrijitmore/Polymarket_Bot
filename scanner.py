"""
Market scanner for Polymarket arbitrage bot.
Continuously scans active markets using Gamma API and CLOB orderbook data.
"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config import settings
from db import db
from logger import get_logger
from utils.helpers import (
    calculate_spread,
    validate_orderbook_depth,
    time_to_close,
    safe_float,
    safe_int
)

logger = get_logger("scanner")


class MarketScanner:
    """Scans Polymarket markets and fetches orderbook data."""
    
    def __init__(self, market_queue: asyncio.Queue):
        """
        Initialize scanner.
        
        Args:
            market_queue: Queue to send market updates to signal engine
        """
        self.market_queue = market_queue
        self.gamma_api_url = "https://gamma-api.polymarket.com"
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
    
    async def start(self) -> None:
        """Start the market scanner."""
        self.running = True
        
        # Configure connector with proper settings
        connector = aiohttp.TCPConnector(
            limit=10,  # Connection pool limit
            ttl_dns_cache=300,  # DNS cache TTL
            ssl=False if self.gamma_api_url.startswith('http://') else None  # Use default SSL
        )
        
        self.session = aiohttp.ClientSession(connector=connector)
        logger.info("Market scanner started")
        
        while self.running:
            try:
                await self._scan_markets()
                await asyncio.sleep(settings.scanner_interval_seconds)
            except Exception as e:
                logger.error(f"Scanner error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Brief pause on error
    
    async def stop(self) -> None:
        """Stop the market scanner."""
        self.running = False
        if self.session:
            await self.session.close()
        logger.info("Market scanner stopped")
    
    async def _scan_markets(self) -> None:
        """Scan active markets from Gamma API."""
        try:
            # Fetch active markets with volume filter
            markets = await self._fetch_gamma_markets()
            logger.info(f"📊 Fetched {len(markets)} markets from Gamma API")
            
            # Filter and enrich markets
            passed_count = 0
            for market in markets:
                try:
                    # Basic filters
                    if not self._passes_basic_filters(market):
                        continue
                    
                    passed_count += 1
                    
                    # Fetch orderbook data for each outcome
                    enriched_market = await self._enrich_with_orderbook(market)
                    
                    if enriched_market:
                        # Store in database
                        await self._store_market(enriched_market)
                        
                        # Send to signal engine
                        await self.market_queue.put(enriched_market)
                
                except Exception as e:
                    logger.warning(f"Error processing market {market.get('id')}: {e}")
                    continue
            
            logger.info(f"✅ Processed {passed_count} markets (passed filters)")
        
        except Exception as e:
            logger.error(f"Error scanning markets: {e}", exc_info=True)
    
    async def _fetch_gamma_markets(self) -> List[Dict[str, Any]]:
        """
        Fetch active markets from Gamma API.
        
        Returns:
            List of market dictionaries
        """
        url = f"{self.gamma_api_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "volume_num_min": settings.min_market_volume,
            "limit": 100,  # Fetch up to 100 markets per scan
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
        """
        Apply basic filters to market.
        
        Args:
            market: Market data from Gamma API
        
        Returns:
            True if market passes filters
        """
        # Check if market is active
        if not market.get("active", False):
            return False
        
        # Check volume
        volume = safe_float(market.get("volume", 0))
        if volume < settings.min_market_volume:
            return False
        
        # Check time to close
        end_date_iso = market.get("end_date_iso")
        if end_date_iso:
            try:
                expires_at = datetime.fromisoformat(end_date_iso.replace('Z', '+00:00'))
                seconds_to_close = time_to_close(expires_at)
                min_seconds = settings.min_time_to_close_minutes * 60
                
                # Must have minimum time remaining
                if seconds_to_close < min_seconds:
                    return False
            except Exception as e:
                logger.debug(f"Error parsing end_date_iso: {e}")
                return False
        else:
            # No expiration date, skip
            return False
        
        # Check outcomes exist
        outcomes = market.get("outcomes", [])
        if not outcomes or len(outcomes) < 2:
            return False
        
        return True
    
    async def _enrich_with_orderbook(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Enrich market with orderbook data for each outcome.
        
        Note: In production, this would use the py-clob-client library.
        For now, we'll create a placeholder structure.
        
        Args:
            market: Market data from Gamma API
        
        Returns:
            Enriched market dict or None if data unavailable
        """
        market_id = market.get("id") or market.get("condition_id")
        outcomes = market.get("outcomes", [])
        
        if not market_id or not outcomes:
            return None
        
        enriched_outcomes = []
        
        for outcome in outcomes:
            # In production: fetch real orderbook using py-clob-client
            # For now: placeholder orderbook structure
            outcome_enriched = {
                "outcome": outcome,
                "orderbook": {
                    "asks": [],  # Will be populated by CLOB client
                    "bids": [],  # Will be populated by CLOB client
                    "best_ask": None,
                    "best_bid": None,
                    "spread_pct": None,
                    "depth_usd": 0
                }
            }
            enriched_outcomes.append(outcome_enriched)
        
        # Construct enriched market
        enriched = {
            "market_id": market_id,
            "question": market.get("question", ""),
            "description": market.get("description", ""),
            "volume": safe_float(market.get("volume", 0)),
            "liquidity": safe_float(market.get("liquidity", 0)),
            "expires_at": market.get("end_date_iso"),
            "outcomes": enriched_outcomes,
            "active": market.get("active", True),
            "last_scanned_at": datetime.utcnow(),
        }
        
        return enriched
    
    async def _store_market(self, market: Dict[str, Any]) -> None:
        """
        Store market in MongoDB.
        
        Args:
            market: Enriched market data
        """
        try:
            await db.upsert_market(market)
        except Exception as e:
            logger.warning(f"Error storing market {market.get('market_id')}: {e}")


async def start_scanner(market_queue: asyncio.Queue) -> MarketScanner:
    """
    Start the market scanner.
    
    Args:
        market_queue: Queue for market updates
    
    Returns:
        Scanner instance
    """
    scanner = MarketScanner(market_queue)
    asyncio.create_task(scanner.start())
    return scanner
