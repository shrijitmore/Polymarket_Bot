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
            from py_clob_client.client import ClobClient

            loop = asyncio.get_running_loop()

            def _init_client():
                if settings.polymarket_api_key and settings.polymarket_api_secret:
                    from py_clob_client.clob_types import ApiCreds
                    logger.info("Initializing CLOB client with API key authentication")
                    creds = ApiCreds(
                        api_key=settings.polymarket_api_key,
                        api_secret=settings.polymarket_api_secret,
                        api_passphrase=settings.polymarket_api_passphrase,
                    )
                    return ClobClient(
                        host=settings.polymarket_api_url,
                        key=settings.polymarket_private_key or "",
                        creds=creds,
                        chain_id=settings.polymarket_chain_id
                    )
                elif settings.polymarket_private_key:
                    logger.info("Initializing CLOB client with private key authentication")
                    return ClobClient(
                        host=settings.polymarket_api_url,
                        key=settings.polymarket_private_key,
                        chain_id=settings.polymarket_chain_id
                    )
                else:
                    # Read-only mode — no signing capability, can still fetch orderbooks
                    logger.warning("Initializing CLOB client in READ-ONLY mode (no credentials)")
                    return ClobClient(
                        host=settings.polymarket_api_url,
                        chain_id=settings.polymarket_chain_id
                    )

            self.client = await loop.run_in_executor(None, _init_client)
            self._initialized = True
            logger.info("CLOB client initialized successfully")

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
            loop = asyncio.get_running_loop()

            def _fetch_orderbook():
                return self.client.get_order_book(token_id)

            raw_orderbook = await loop.run_in_executor(None, _fetch_orderbook)

            # Parse orderbook
            return self._parse_orderbook(raw_orderbook)

        except Exception as e:
            logger.warning(f"Error fetching orderbook for {token_id[:16]}...: {e}")
            return None

    def _parse_orderbook(self, raw_book) -> Dict[str, Any]:
        """
        Parse raw orderbook into standardized format.

        Args:
            raw_book: Raw orderbook from CLOB API

        Returns:
            Parsed orderbook dictionary
        """
        # Handle both dict and object responses from py-clob-client
        if hasattr(raw_book, "asks"):
            raw_asks = raw_book.asks or []
            raw_bids = raw_book.bids or []
        elif isinstance(raw_book, dict):
            raw_asks = raw_book.get("asks", [])
            raw_bids = raw_book.get("bids", [])
        else:
            raw_asks = []
            raw_bids = []

        # Normalize to list of dicts and sort
        asks = sorted(
            [self._parse_order_level(a) for a in raw_asks],
            key=lambda x: x["price"]
        )
        bids = sorted(
            [self._parse_order_level(b) for b in raw_bids],
            key=lambda x: x["price"],
            reverse=True
        )

        # Extract best prices
        best_ask = asks[0]["price"] if asks else None
        best_bid = bids[0]["price"] if bids else None

        # Calculate spread
        spread_pct = None
        if best_ask and best_bid:
            spread_pct = calculate_spread(best_bid, best_ask)

        # Calculate depth (top 10 levels)
        asks_depth = sum(level["size"] for level in asks[:10])
        bids_depth = sum(level["size"] for level in bids[:10])

        return {
            "asks": asks[:20],
            "bids": bids[:20],
            "best_ask": best_ask,
            "best_bid": best_bid,
            "spread_pct": spread_pct,
            "asks_depth": asks_depth,
            "bids_depth": bids_depth,
        }

    def _parse_order_level(self, level) -> Dict[str, float]:
        """Parse a single order level from either dict or object."""
        if isinstance(level, dict):
            return {
                "price": safe_float(level.get("price", 0)),
                "size": safe_float(level.get("size", 0)),
            }
        else:
            return {
                "price": safe_float(getattr(level, "price", 0)),
                "size": safe_float(getattr(level, "size", 0)),
            }

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        neg_risk: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Place a limit order.

        Args:
            token_id: Outcome token ID
            side: "BUY" or "SELL"
            price: Limit price (0-1)
            size: Order size in outcome tokens
            neg_risk: Whether market uses negative risk (BTC 5m markets do)

        Returns:
            Order response or None if failed
        """
        if not self._initialized:
            await self.initialize()

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL

            loop = asyncio.get_running_loop()

            def _create_and_post_order():
                order_args = OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=order_side,
                )
                signed_order = self.client.create_order(order_args)
                response = self.client.post_order(signed_order, OrderType.GTC)
                return response

            order_response = await loop.run_in_executor(None, _create_and_post_order)
            logger.info(f"Placed {side} order: {token_id[:16]}... @ {price} x {size}")
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
            loop = asyncio.get_running_loop()

            def _cancel_order():
                return self.client.cancel(order_id)

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
            loop = asyncio.get_running_loop()

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
