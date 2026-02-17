"""
Signal engine for detecting arbitrage and late-market trading opportunities.
Implements three strategies:
1. One-of-Many Arbitrage
2. Base YES/NO Arbitrage  
3. Late-Market Sure Side
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from config import settings
from db import db
from logger import get_logger
from utils.helpers import (
    calculate_spread,
    validate_orderbook_depth,
    validate_binary_market,
    time_to_close,
    is_within_late_window,
    safe_float,
    generate_position_id
)

logger = get_logger("signal_engine")


class SignalEngine:
    """Detects trading signals from market data."""
    
    def __init__(self, market_queue: asyncio.Queue, signal_queue: asyncio.Queue):
        """
        Initialize signal engine.
        
        Args:
            market_queue: Queue receiving market updates from scanner
            signal_queue: Queue sending trade signals to executor
        """
        self.market_queue = market_queue
        self.signal_queue = signal_queue
        self.running = False
    
    async def start(self) -> None:
        """Start the signal engine."""
        self.running = True
        logger.info("Signal engine started")
        
        while self.running:
            try:
                # Wait for market update
                market = await self.market_queue.get()
                
                # Check all enabled strategies
                signals = []
                
                if settings.enable_one_of_many:
                    signal = await self._check_one_of_many_arb(market)
                    if signal:
                        signals.append(signal)
                
                if settings.enable_yes_no:
                    signal = await self._check_yes_no_arb(market)
                    if signal:
                        signals.append(signal)
                
                if settings.enable_late_market:
                    signal = await self._check_late_market(market)
                    if signal:
                        signals.append(signal)
                
                # Send signals to executor
                for signal in signals:
                    await self.signal_queue.put(signal)
            
            except Exception as e:
                logger.error(f"Signal engine error: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the signal engine."""
        self.running = False
        logger.info("Signal engine stopped")
    
    async def _check_one_of_many_arb(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check for One-of-Many arbitrage opportunity.
        
        Strategy: Buy all outcomes when sum(bestAsk) < 0.97
        
        Args:
            market: Market data with orderbook
        
        Returns:
            Trade signal or None
        """
        outcomes = market.get("outcomes", [])
        
        # Filter 1: Must have 3+ outcomes
        if len(outcomes) < 3:
            return None
        
        # Filter 2: Check time to close
        expires_at_str = market.get("expires_at")
        if not expires_at_str:
            return None
        
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            seconds_left = time_to_close(expires_at)
            if seconds_left < settings.min_time_to_close_minutes * 60:
                return None
        except Exception:
            return None
        
        # Calculate total cost and validate spreads/liquidity
        total_cost = 0.0
        legs = []
        
        for outcome in outcomes:
            orderbook = outcome.get("orderbook", {})
            best_ask = orderbook.get("best_ask")
            
            if best_ask is None:
                return None  # Missing orderbook data
            
            # Filter 3: Check spread per outcome
            spread = orderbook.get("spread_pct", 100)
            if spread > settings.max_spread_one_of_many:
                return None
            
            # Calculate required size (in USD)
            position_size_usd = settings.max_arb_position_size / len(outcomes)
            required_tokens = position_size_usd / best_ask if best_ask > 0 else 0
            
            # Filter 4: Validate liquidity
            asks = orderbook.get("asks", [])
            if not validate_orderbook_depth(asks, required_tokens, "asks"):
                return None
            
            total_cost += best_ask
            legs.append({
                "outcome": outcome.get("outcome"),
                "price": best_ask,
                "size_usd": position_size_usd,
                "size_tokens": required_tokens,
                "spread_pct": spread
            })
        
        # Calculate edge
        edge = (1.0 - total_cost) * 100.0  # Convert to percentage
        
        # Filter 5: Check minimum edge
        if edge < settings.min_arb_edge_pct:
            return None
        
        # Create signal
        signal = {
            "strategy": "one_of_many",
            "market_id": market.get("market_id"),
            "question": market.get("question", ""),
            "legs": legs,
            "total_cost": total_cost,
            "expected_payout": 1.0,
            "expected_edge": edge,
            "expires_at": expires_at_str,
            "position_id": generate_position_id(market.get("market_id"), "one_of_many"),
            "detected_at": datetime.utcnow().isoformat()
        }
        
        logger.info(
            f"🎯 One-of-Many ARB detected: {market.get('question')[:50]}... "
            f"Edge: {edge:.2f}%, Cost: ${total_cost:.3f}"
        )
        
        return signal
    
    async def _check_yes_no_arb(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check for Base YES/NO arbitrage opportunity.
        
        Strategy: Buy YES and NO when YES_ask + NO_ask < 0.97
        
        Args:
            market: Market data with orderbook
        
        Returns:
            Trade signal or None
        """
        outcomes = market.get("outcomes", [])
        
        # Filter 1: Must be binary market
        if not validate_binary_market(outcomes):
            return None
        
        # Filter 2: Check time to close
        expires_at_str = market.get("expires_at")
        if not expires_at_str:
            return None
        
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            seconds_left = time_to_close(expires_at)
            if seconds_left < settings.min_time_to_close_minutes * 60:
                return None
        except Exception:
            return None
        
        # Find YES and NO outcomes
        yes_outcome = None
        no_outcome = None
        
        for outcome in outcomes:
            outcome_name = outcome.get("outcome", "").upper()
            if "YES" in outcome_name:
                yes_outcome = outcome
            elif "NO" in outcome_name:
                no_outcome = outcome
        
        if not yes_outcome or not no_outcome:
            return None
        
        # Get orderbook data
        yes_book = yes_outcome.get("orderbook", {})
        no_book = no_outcome.get("orderbook", {})
        
        yes_ask = yes_book.get("best_ask")
        no_ask = no_book.get("best_ask")
        
        if yes_ask is None or no_ask is None:
            return None
        
        # Filter 3: Check spreads
        yes_spread = yes_book.get("spread_pct", 100)
        no_spread = no_book.get("spread_pct", 100)
        
        if yes_spread > settings.max_spread_yes_no or no_spread > settings.max_spread_yes_no:
            return None
        
        # Calculate total cost
        total_cost = yes_ask + no_ask
        
        # Calculate edge
        edge = (1.0 - total_cost) * 100.0
        
        # Filter 4: Check minimum edge
        if edge < settings.min_arb_edge_pct:
            return None
        
        # Calculate position sizes
        position_size_per_side = settings.max_arb_position_size / 2.0
        yes_tokens = position_size_per_side / yes_ask if yes_ask > 0 else 0
        no_tokens = position_size_per_side / no_ask if no_ask > 0 else 0
        
        # Filter 5: Validate liquidity
        yes_asks = yes_book.get("asks", [])
        no_asks = no_book.get("asks", [])
        
        if not validate_orderbook_depth(yes_asks, yes_tokens, "asks"):
            return None
        if not validate_orderbook_depth(no_asks, no_tokens, "asks"):
            return None
        
        # Create signal
        signal = {
            "strategy": "yes_no",
            "market_id": market.get("market_id"),
            "question": market.get("question", ""),
            "legs": [
                {
                    "outcome": "YES",
                    "price": yes_ask,
                    "size_usd": position_size_per_side,
                    "size_tokens": yes_tokens,
                    "spread_pct": yes_spread
                },
                {
                    "outcome": "NO",
                    "price": no_ask,
                    "size_usd": position_size_per_side,
                    "size_tokens": no_tokens,
                    "spread_pct": no_spread
                }
            ],
            "total_cost": total_cost,
            "expected_payout": 1.0,
            "expected_edge": edge,
            "expires_at": expires_at_str,
            "position_id": generate_position_id(market.get("market_id"), "yes_no"),
            "detected_at": datetime.utcnow().isoformat()
        }
        
        logger.info(
            f"🎯 YES/NO ARB detected: {market.get('question')[:50]}... "
            f"Edge: {edge:.2f}%, Cost: ${total_cost:.3f}"
        )
        
        return signal
    
    async def _check_late_market(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check for Late-Market Sure Side opportunity.
        
        Strategy: Trade winning side in final 60-180s of crypto markets
        
        Args:
            market: Market data with orderbook
        
        Returns:
            Trade signal or None
        """
        # This is a placeholder - requires Binance price feed integration
        # Will be fully implemented in Phase 4
        return None


async def start_signal_engine(
    market_queue: asyncio.Queue,
    signal_queue: asyncio.Queue
) -> SignalEngine:
    """
    Start the signal engine.
    
    Args:
        market_queue: Queue receiving market updates
        signal_queue: Queue sending trade signals
    
    Returns:
        Signal engine instance
    """
    engine = SignalEngine(market_queue, signal_queue)
    asyncio.create_task(engine.start())
    return engine
