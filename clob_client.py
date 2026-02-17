"""
CLOB (Central Limit Order Book) client for Polymarket.
Wraps py-clob-client with async interface and orderbook fetching.
"""
import asyncio
from typing import Dict, List, Any, Optional
from decimal import Decimal
from config import settings
from logger import get_logger
from utils.helpers import calculate_spread, validate_orderbook_depth, safe_float

logger = get_logger("clob_client")


class CLOBClient:
    """
    Async wrapper for Polymarket CLOB API using py-clob-client.
    
    Note: py-clob-client is primarily synchronous, so we'll run
    blocking calls in an executor to maintain async compatibility.
    """
    
    def __init__(self):
        """Initialize CLOB client."""
        self.client = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the CLOB client connection."""
        try:
            # Import here to avoid issues if library not installed yet
            from py_clob_client.client import ClobClient
            
            loop = asyncio.get_event_loop()
            
            def _init_client():
                # Check if using API key authentication
                if settings.polymarket_api_key and settings.polymarket_api_secret:
                    logger.info("Initializing CLOB client with API key authentication")
                    return ClobClient(
                        host=settings.polymarket_api_url,
                        key=settings.polymarket_private_key or "",  # May not need private key with API auth
                        api_key=settings.polymarket_api_key,
                        api_secret=settings.polymarket_api_secret,
                        api_passphrase=settings.polymarket_api_passphrase,
                        chain_id=settings.polymarket_chain_id
                    )
                else:
                    # Fall back to private key authentication
                    logger.info("Initializing CLOB client with private key authentication")
                    if not settings.polymarket_private_key:
                        raise ValueError("POLYMARKET_PRIVATE_KEY required when not using API keys")
                    return ClobClient(
                        host=settings.polymarket_api_url,
                        key=settings.polymarket_private_key,
                        chain_id=settings.polymarket_chain_id
                    )
            
            self.client = await loop.run_in_executor(None, _init_client)
            self._initialized = True
            logger.info("✅ CLOB client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            raise
    
    async def get_orderbook(self, token_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch orderbook for a specific outcome token.
        
        Args:
            token_id: Polymarket token ID for the outcome
        
        Returns:
            Orderbook dictionary with asks, bids, and best prices
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            loop = asyncio.get_event_loop()
            
            def _fetch_orderbook():
                return self.client.get_order_book(token_id)
            
            raw_orderbook = await loop.run_in_executor(None, _fetch_orderbook)
            
            # Parse orderbook
            return self._parse_orderbook(raw_orderbook)
        
        except Exception as e:
            logger.warning(f"Error fetching orderbook for {token_id}: {e}")
            return None
    
    def _parse_orderbook(self, raw_book: Dict) -> Dict[str, Any]:
        """
        Parse raw orderbook into standardized format.
        
        Args:
            raw_book: Raw orderbook from CLOB API
        
        Returns:
            Parsed orderbook dictionary
        """
        asks = raw_book.get("asks", [])
        bids = raw_book.get("bids", [])
        
        # Extract best prices
        best_ask = safe_float(asks[0]["price"]) if asks else None
        best_bid = safe_float(bids[0]["price"]) if bids else None
        
        # Calculate spread
        spread_pct = None
        if best_ask and best_bid:
            spread_pct = calculate_spread(best_bid, best_ask)
        
        # Calculate depth
        asks_depth = sum(safe_float(level.get("size", 0)) for level in asks[:10])
        bids_depth = sum(safe_float(level.get("size", 0)) for level in bids[:10])
        
        return {
            "asks": [
                {"price": safe_float(a["price"]), "size": safe_float(a["size"])}
                for a in asks[:20]  # Top 20 levels
            ],
            "bids": [
                {"price": safe_float(b["price"]), "size": safe_float(b["size"])}
                for b in bids[:20]
            ],
            "best_ask": best_ask,
            "best_bid": best_bid,
            "spread_pct": spread_pct,
            "asks_depth": asks_depth,
            "bids_depth": bids_depth,
        }
    
    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order.
        
        Args:
            token_id: Outcome token ID
            side: "BUY" or "SELL"
            price: Limit price (0-1)
            size: Order size in outcome tokens
        
        Returns:
            Order response or None if failed
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            loop = asyncio.get_event_loop()
            
            def _place_order():
                return self.client.create_order(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side.upper()
                )
            
            order_response = await loop.run_in_executor(None, _place_order)
            logger.info(f"Placed {side} order: {token_id} @ {price} x {size}")
            return order_response
        
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if successful
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            loop = asyncio.get_event_loop()
            
            def _cancel_order():
                return self.client.cancel_order(order_id)
            
            await loop.run_in_executor(None, _cancel_order)
            logger.info(f"Cancelled order: {order_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False
    
    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get order status.
        
        Args:
            order_id: Order ID
        
        Returns:
            Order status dictionary or None
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            loop = asyncio.get_event_loop()
            
            def _get_order():
                return self.client.get_order(order_id)
            
            order = await loop.run_in_executor(None, _get_order)
            return order
        
        except Exception as e:
            logger.warning(f"Error fetching order status {order_id}: {e}")
            return None


# Global CLOB client instance
clob_client = CLOBClient()


async def init_clob_client() -> CLOBClient:
    """Initialize global CLOB client."""
    await clob_client.initialize()
    return clob_client
