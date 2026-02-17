"""
Binance WebSocket client for real-time crypto price feed.
Used for late-market strategy signal detection.
"""
import asyncio
import json
from typing import Dict, Optional, List
from datetime import datetime
import websockets
from config import settings
from logger import get_logger
from utils.helpers import calculate_volatility

logger = get_logger("binance_feed")


class BinanceFeed:
    """Real-time cryptocurrency price feed via Binance WebSocket."""
    
    def __init__(self):
        """Initialize Binance feed."""
        self.symbols = ["btcusdt", "ethusdt", "solusdt", "xrpusdt"]
        self.prices: Dict[str, float] = {}
        self.price_history: Dict[str, List[float]] = {symbol: [] for symbol in self.symbols}
        self.running = False
        self.ws = None
    
    async def start(self) -> None:
        """Start the WebSocket feed."""
        self.running = True
        logger.info("Starting Binance WebSocket feed...")
        
        while self.running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(f"Binance feed error: {e}")
                if self.running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the WebSocket feed."""
        self.running = False
        if self.ws:
            await self.ws.close()
        logger.info("Binance feed stopped")
    
    async def _connect_and_listen(self) -> None:
        """Connect to Binance WebSocket and listen for price updates."""
        # Build combined stream URL
        streams = "/".join([f"{symbol}@ticker" for symbol in self.symbols])
        url = f"{settings.binance_ws_url}/{streams}"
        
        logger.info(f"Connecting to Binance: {url}")
        
        async with websockets.connect(url) as websocket:
            self.ws = websocket
            logger.info("✅ Connected to Binance WebSocket")
            
            while self.running:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                    await self._process_message(message)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.ping()
                except Exception as e:
                    logger.warning(f"Error receiving message: {e}")
                    break
    
    async def _process_message(self, message: str) -> None:
        """Process WebSocket message."""
        try:
            data = json.loads(message)
            
            # Handle combined stream format
            if "stream" in data:
                stream_data = data.get("data", {})
            else:
                stream_data = data
            
            symbol = stream_data.get("s", "").lower()
            price = float(stream_data.get("c", 0))  # Current price
            
            if symbol in self.symbols and price > 0:
                # Update current price
                self.prices[symbol] = price
                
                # Add to price history (keep last 60 data points for volatility calc)
                history = self.price_history[symbol]
                history.append(price)
                if len(history) > 60:
                    history.pop(0)
                
                logger.debug(f"{symbol.upper()}: ${price:,.2f}")
        
        except Exception as e:
            logger.warning(f"Error processing Binance message: {e}")
    
    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for symbol.
        
        Args:
            symbol: Symbol (e.g., "btcusdt")
        
        Returns:
            Current price or None
        """
        return self.prices.get(symbol.lower())
    
    def get_volatility(self, symbol: str, window: int = 30) -> float:
        """
        Calculate rolling volatility for symbol.
        
        Args:
            symbol: Symbol (e.g., "btcusdt")
            window: Number of data points to use
        
        Returns:
            Volatility percentage
        """
        history = self.price_history.get(symbol.lower(), [])
        
        if len(history) < 2:
            return 0.0
        
        recent_prices = history[-window:] if len(history) >= window else history
        return calculate_volatility(recent_prices)
    
    def is_connected(self) -> bool:
        """Check if feed is connected."""
        return self.running and bool(self.prices)


# Global feed instance
binance_feed = BinanceFeed()


async def start_binance_feed() -> BinanceFeed:
    """Start the Binance feed."""
    asyncio.create_task(binance_feed.start())
    
    # Wait for first price update
    max_wait = 10
    for _ in range(max_wait):
        if binance_feed.prices:
            break
        await asyncio.sleep(1)
    
    return binance_feed
