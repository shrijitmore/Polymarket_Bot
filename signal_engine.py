"""
Signal engine for detecting arbitrage and late-market trading opportunities.
Implements three strategies:
1. One-of-Many Arbitrage
2. Base YES/NO Arbitrage
3. Late-Market Sure Side (BTC 5m)
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from config import settings
from db import db
from logger import get_logger
from binance_feed import binance_feed
from utils.helpers import (
    calculate_spread,
    validate_orderbook_depth,
    validate_binary_market,
    time_to_close,
    is_within_late_window,
    is_btc_5m_market,
    safe_float,
    generate_position_id
)

logger = get_logger("signal_engine")


class SignalEngine:
    """Detects trading signals from market data."""

    def __init__(self, market_queue: asyncio.Queue, signal_queue: asyncio.Queue):
        self.market_queue = market_queue
        self.signal_queue = signal_queue
        self.running = False
        self._recently_signaled: set = set()

    async def start(self) -> None:
        """Start the signal engine."""
        self.running = True
        logger.info("Signal engine started")
        cleanup_counter = 0

        while self.running:
            try:
                # Wait for market update with timeout for cleanup
                try:
                    market = await asyncio.wait_for(self.market_queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    self._recently_signaled.clear()
                    continue

                # Gate: if btc_5m_only is set, skip non-BTC-5m markets entirely
                if settings.btc_5m_only:
                    question = market.get("question", "")
                    if not is_btc_5m_market(question) and not market.get("is_btc_5m", False):
                        self.market_queue.task_done() if hasattr(self.market_queue, 'task_done') else None
                        continue

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

                # Periodic cleanup of dedup set
                cleanup_counter += 1
                if cleanup_counter % 200 == 0:
                    self._recently_signaled.clear()

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
        """
        outcomes = market.get("outcomes", [])

        # Must have 3+ outcomes
        if len(outcomes) < 3:
            return None

        # Check time to close
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
                return None

            # Check spread per outcome
            spread = orderbook.get("spread_pct", 100)
            if spread is not None and spread > settings.max_spread_one_of_many:
                return None

            # Calculate required size
            position_size_usd = settings.max_arb_position_size / len(outcomes)
            required_tokens = position_size_usd / best_ask if best_ask > 0 else 0

            # Validate liquidity
            asks = orderbook.get("asks", [])
            if not validate_orderbook_depth(asks, required_tokens, "asks"):
                return None

            total_cost += best_ask
            legs.append({
                "outcome": outcome.get("outcome"),
                "token_id": outcome.get("token_id"),
                "neg_risk": market.get("neg_risk", False),
                "price": best_ask,
                "size_usd": position_size_usd,
                "size_tokens": required_tokens,
                "spread_pct": spread
            })

        # Calculate edge
        edge = (1.0 - total_cost) * 100.0

        # Check minimum edge
        if edge < settings.min_arb_edge_pct:
            return None

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
            f"One-of-Many ARB detected: {market.get('question', '')[:50]}... "
            f"Edge: {edge:.2f}%, Cost: ${total_cost:.3f}"
        )

        return signal

    async def _check_yes_no_arb(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check for Base YES/NO (or Up/Down) arbitrage opportunity.
        Strategy: Buy both sides when sum of asks < 0.97
        """
        outcomes = market.get("outcomes", [])

        # Must be binary market
        if not validate_binary_market(outcomes):
            return None

        # Check time to close
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

        # Find the two sides (YES/NO or Up/Down)
        side_a = None
        side_b = None

        for outcome in outcomes:
            outcome_name = outcome.get("outcome", "").upper()
            if outcome_name in ("YES", "UP"):
                side_a = outcome
            elif outcome_name in ("NO", "DOWN"):
                side_b = outcome

        if not side_a or not side_b:
            return None

        # Get orderbook data
        book_a = side_a.get("orderbook", {})
        book_b = side_b.get("orderbook", {})

        ask_a = book_a.get("best_ask")
        ask_b = book_b.get("best_ask")

        if ask_a is None or ask_b is None:
            return None

        # Check spreads
        spread_a = book_a.get("spread_pct", 100)
        spread_b = book_b.get("spread_pct", 100)

        if (spread_a is not None and spread_a > settings.max_spread_yes_no) or \
           (spread_b is not None and spread_b > settings.max_spread_yes_no):
            return None

        # Calculate total cost and edge
        total_cost = ask_a + ask_b
        edge = (1.0 - total_cost) * 100.0

        if edge < settings.min_arb_edge_pct:
            return None

        # Calculate position sizes
        position_size_per_side = settings.max_arb_position_size / 2.0
        tokens_a = position_size_per_side / ask_a if ask_a > 0 else 0
        tokens_b = position_size_per_side / ask_b if ask_b > 0 else 0

        # Validate liquidity
        asks_a = book_a.get("asks", [])
        asks_b = book_b.get("asks", [])

        if not validate_orderbook_depth(asks_a, tokens_a, "asks"):
            return None
        if not validate_orderbook_depth(asks_b, tokens_b, "asks"):
            return None

        signal = {
            "strategy": "yes_no",
            "market_id": market.get("market_id"),
            "question": market.get("question", ""),
            "legs": [
                {
                    "outcome": side_a.get("outcome"),
                    "token_id": side_a.get("token_id"),
                    "neg_risk": market.get("neg_risk", False),
                    "price": ask_a,
                    "size_usd": position_size_per_side,
                    "size_tokens": tokens_a,
                    "spread_pct": spread_a
                },
                {
                    "outcome": side_b.get("outcome"),
                    "token_id": side_b.get("token_id"),
                    "neg_risk": market.get("neg_risk", False),
                    "price": ask_b,
                    "size_usd": position_size_per_side,
                    "size_tokens": tokens_b,
                    "spread_pct": spread_b
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
            f"YES/NO ARB detected: {market.get('question', '')[:50]}... "
            f"Edge: {edge:.2f}%, Cost: ${total_cost:.3f}"
        )

        return signal

    async def _check_late_market(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Late-Market Sure Side strategy for BTC 5m markets.

        Logic:
        1. Detect BTC 5m market closing in 60-180 seconds
        2. Get current BTC price from Binance feed
        3. Market resolves "Up" if end_price >= start_price, "Down" otherwise
        4. If BTC has moved sufficiently, buy the winning side
        """
        question = market.get("question", "")
        if not market.get("is_btc_5m", False) and not is_btc_5m_market(question):
            return None

        market_id = market.get("market_id")

        # Avoid duplicate signals for the same market
        if market_id in self._recently_signaled:
            return None

        # Validate expiration is within late-market window
        expires_at_str = market.get("expires_at")
        if not expires_at_str:
            return None

        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            seconds_left = time_to_close(expires_at)
        except Exception:
            return None

        if not is_within_late_window(
            expires_at,
            settings.late_market_window_start,
            settings.late_market_window_end,
        ):
            return None

        # Get current BTC price from Binance
        btc_price = binance_feed.get_price("btcusdt")
        if btc_price is None:
            logger.warning("No BTC price available from Binance feed")
            return None

        # Check BTC volatility — too volatile means outcome is uncertain
        btc_volatility = binance_feed.get_volatility("btcusdt", window=30)
        if btc_volatility > settings.late_market_max_volatility_pct:
            logger.debug(f"BTC volatility too high: {btc_volatility:.2f}%")
            return None

        # Find Up and Down outcomes with their token IDs
        outcomes = market.get("outcomes", [])
        up_outcome = None
        down_outcome = None

        for outcome in outcomes:
            name = outcome.get("outcome", "").upper()
            if name == "UP":
                up_outcome = outcome
            elif name == "DOWN":
                down_outcome = outcome

        if not up_outcome or not down_outcome:
            return None

        up_ask = up_outcome.get("orderbook", {}).get("best_ask")
        down_ask = down_outcome.get("orderbook", {}).get("best_ask")

        if up_ask is None or down_ask is None:
            return None

        # Use Binance price history to gauge BTC direction
        btc_history = binance_feed.price_history.get("btcusdt", [])
        if len(btc_history) < 5:
            return None

        # Opening price approximation: earliest price in the history window
        opening_price = btc_history[0]
        current_price = btc_history[-1]

        if opening_price is None or current_price is None or opening_price == 0:
            return None

        price_change_pct = ((current_price - opening_price) / opening_price) * 100.0

        # Determine winning side
        if price_change_pct >= 0:
            winning_side = "Up"
            winning_outcome = up_outcome
            entry_price = up_ask
        else:
            winning_side = "Down"
            winning_outcome = down_outcome
            entry_price = down_ask

        # Check minimum deviation — need sufficient price movement to be confident
        if abs(price_change_pct) < settings.late_market_min_deviation_pct:
            logger.debug(
                f"BTC price change {price_change_pct:.3f}% below threshold "
                f"{settings.late_market_min_deviation_pct}%"
            )
            return None

        # Check entry price — don't buy if already priced in
        if entry_price > settings.late_market_max_price:
            logger.debug(f"Entry price {entry_price} too high (max {settings.late_market_max_price})")
            return None

        # Calculate position size
        position_size_usd = settings.max_late_position_size
        size_tokens = position_size_usd / entry_price if entry_price > 0 else 0

        # Validate orderbook depth
        winning_asks = winning_outcome.get("orderbook", {}).get("asks", [])
        if not validate_orderbook_depth(winning_asks, size_tokens, "asks"):
            logger.debug("Insufficient orderbook depth for late-market trade")
            return None

        # Check spread
        winning_spread = winning_outcome.get("orderbook", {}).get("spread_pct", 100)
        if winning_spread is not None and winning_spread > settings.max_spread_late_market:
            return None

        # Mark as signaled to avoid duplicates
        self._recently_signaled.add(market_id)

        # Calculate expected edge
        expected_edge = (1.0 - entry_price) * 100.0
        total_cost = entry_price * size_tokens
        expected_payout = 1.0 * size_tokens

        signal = {
            "strategy": "late_market",
            "market_id": market_id,
            "question": question,
            "legs": [
                {
                    "outcome": winning_side,
                    "token_id": winning_outcome.get("token_id"),
                    "neg_risk": market.get("neg_risk", False),
                    "price": entry_price,
                    "size_usd": position_size_usd,
                    "size_tokens": size_tokens,
                    "spread_pct": winning_spread,
                }
            ],
            "total_cost": total_cost,
            "expected_payout": expected_payout,
            "expected_edge": expected_edge,
            "expires_at": expires_at_str,
            "seconds_to_close": seconds_left,
            "btc_price": current_price,
            "btc_opening_price": opening_price,
            "btc_change_pct": price_change_pct,
            "btc_volatility": btc_volatility,
            "position_id": generate_position_id(market_id, "late_market"),
            "detected_at": datetime.utcnow().isoformat(),
        }

        logger.info(
            f"LATE-MARKET signal: {winning_side} @ ${entry_price:.3f} | "
            f"BTC {price_change_pct:+.3f}% | Edge: {expected_edge:.1f}% | "
            f"{seconds_left}s to close"
        )

        return signal


async def start_signal_engine(
    market_queue: asyncio.Queue,
    signal_queue: asyncio.Queue
) -> SignalEngine:
    """Start the signal engine."""
    engine = SignalEngine(market_queue, signal_queue)
    asyncio.create_task(engine.start())
    return engine
