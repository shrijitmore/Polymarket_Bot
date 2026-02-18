"""
Position Resolver for DRY_RUN mode.

Periodically checks open positions against the Polymarket API to see if
their markets have resolved. When a market resolves, calculates the
realized PnL and marks the position as closed in MongoDB.

PnL logic:
  - one_of_many / yes_no arb: one leg wins (pays $1/token), rest expire
    worthless. Profit = winning_leg.size_tokens - actual_total_cost
  - late_market: single leg. Win = size_tokens - cost. Loss = -cost.
"""
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, Optional, List
from config import settings
from db import db
from logger import get_logger

logger = get_logger("position_resolver")

# Polymarket CLOB REST endpoint for a single market
MARKET_URL = "https://clob.polymarket.com/markets/{condition_id}"


class PositionResolver:
    """
    Background task that resolves open DRY_RUN positions.

    Polls at `settings.resolver_interval_seconds` intervals.
    """

    def __init__(self):
        self.running = False
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        """Start the resolver loop."""
        self.running = True
        logger.info(
            f"Position resolver started "
            f"(interval={settings.resolver_interval_seconds}s)"
        )
        async with aiohttp.ClientSession() as session:
            self._session = session
            while self.running:
                try:
                    await self._resolve_open_positions()
                except Exception as e:
                    logger.error(f"Resolver error: {e}", exc_info=True)
                await asyncio.sleep(settings.resolver_interval_seconds)

    async def stop(self) -> None:
        """Stop the resolver loop."""
        self.running = False
        logger.info("Position resolver stopped")

    # ------------------------------------------------------------------
    # Core resolution loop
    # ------------------------------------------------------------------

    async def _resolve_open_positions(self) -> None:
        """Check all open positions for market resolution."""
        open_positions = await db.get_open_positions()

        if not open_positions:
            logger.debug("No open positions to resolve")
            return

        logger.debug(f"Checking {len(open_positions)} open position(s) for resolution")

        for position in open_positions:
            try:
                await self._check_and_resolve(position)
            except Exception as e:
                pid = position.get("position_id", "?")
                logger.warning(f"Error resolving position {pid}: {e}")

    async def _check_and_resolve(self, position: Dict[str, Any]) -> None:
        """
        Check a single position and resolve it if the market has settled.

        Args:
            position: Position document from MongoDB
        """
        market_id = position.get("market_id")
        position_id = position.get("position_id")

        if not market_id:
            return

        # Fetch market state from Polymarket
        market_data = await self._fetch_market(market_id)
        if market_data is None:
            return

        # Check if market is resolved
        resolved = market_data.get("resolved", False) or market_data.get("closed", False)
        if not resolved:
            return

        # Determine the winning outcome name
        winner = self._extract_winner(market_data)
        if winner is None:
            logger.debug(f"Market {market_id} resolved but no winner field yet")
            return

        # Calculate realized PnL
        strategy = position.get("strategy", "")
        pnl = self._calculate_pnl(position, winner, strategy)

        # Close the position in DB
        now = datetime.utcnow()
        await db.update_position(position_id, {
            "status": "closed",
            "closed_at": now,
            "realized_pnl": pnl,
            "winner": winner,
        })

        # Update daily PnL rollup
        await self._update_daily_pnl(pnl, strategy, now)

        # Log result
        sign = "+" if pnl >= 0 else ""
        logger.info(
            f"{'✅' if pnl >= 0 else '❌'} RESOLVED: {position_id} | "
            f"Strategy: {strategy} | Winner: {winner} | "
            f"PnL: {sign}${pnl:.4f}"
        )

        await db.log_event(
            event_type="position_resolved",
            details={
                "module": "position_resolver",
                "message": f"Position resolved: {sign}${pnl:.4f}",
                "position_id": position_id,
                "strategy": strategy,
                "winner": winner,
                "realized_pnl": pnl,
            },
            level="INFO" if pnl >= 0 else "WARNING",
        )

    # ------------------------------------------------------------------
    # PnL calculation
    # ------------------------------------------------------------------

    def _calculate_pnl(
        self,
        position: Dict[str, Any],
        winner: str,
        strategy: str,
    ) -> float:
        """
        Calculate realized PnL for a resolved position.

        For arb strategies (one_of_many, yes_no):
          - We bought ALL outcomes. Exactly one pays $1/token.
          - PnL = winning_leg.size_tokens * 1.0 - actual_total_cost

        For late_market:
          - We bought ONE outcome (the predicted winner).
          - Win:  PnL = leg.size_tokens * 1.0 - actual_total_cost
          - Loss: PnL = -actual_total_cost

        Args:
            position: Position document
            winner: Winning outcome name (e.g. "Yes", "No", "Up", "Down")
            strategy: Strategy name

        Returns:
            Realized PnL in USD
        """
        legs: List[Dict[str, Any]] = position.get("legs", [])
        actual_total_cost: float = position.get("actual_total_cost", 0.0)

        if not legs:
            return 0.0

        winner_lower = winner.lower().strip()

        if strategy in ("one_of_many", "yes_no"):
            # Find the winning leg by outcome name
            winning_leg = None
            for leg in legs:
                outcome = leg.get("outcome", "").lower().strip()
                if outcome == winner_lower:
                    winning_leg = leg
                    break

            if winning_leg is None:
                # Fallback: no leg matched winner — all legs expire worthless
                logger.warning(
                    f"No leg matched winner '{winner}' in position "
                    f"{position.get('position_id')} — treating as total loss"
                )
                return -actual_total_cost

            winning_tokens = winning_leg.get("size_tokens", 0.0)
            payout = winning_tokens * 1.0  # $1 per token
            return payout - actual_total_cost

        elif strategy == "late_market":
            # Single leg — did we pick the right side?
            if not legs:
                return -actual_total_cost

            leg = legs[0]
            leg_outcome = leg.get("outcome", "").lower().strip()
            size_tokens = leg.get("size_tokens", 0.0)

            if leg_outcome == winner_lower:
                # Won
                payout = size_tokens * 1.0
                return payout - actual_total_cost
            else:
                # Lost — entire cost is lost
                return -actual_total_cost

        else:
            # Unknown strategy — conservative: return 0
            logger.warning(f"Unknown strategy '{strategy}' in PnL calculation")
            return 0.0

    # ------------------------------------------------------------------
    # Polymarket API helpers
    # ------------------------------------------------------------------

    async def _fetch_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch market data from Polymarket CLOB API.

        Args:
            market_id: Market condition ID (hex string)

        Returns:
            Market data dict or None on error
        """
        url = MARKET_URL.format(condition_id=market_id)
        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 404:
                    logger.debug(f"Market {market_id} not found (404)")
                    return None
                else:
                    logger.warning(
                        f"Unexpected status {resp.status} fetching market {market_id}"
                    )
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching market {market_id}")
            return None
        except Exception as e:
            logger.warning(f"Error fetching market {market_id}: {e}")
            return None

    def _extract_winner(self, market_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract the winning outcome name from market data.

        Polymarket API may return the winner in different fields depending
        on market type. We check several known field names.

        Args:
            market_data: Raw market dict from CLOB API

        Returns:
            Winner name string or None if not determinable
        """
        # Direct winner field
        winner = market_data.get("winner")
        if winner:
            return str(winner)

        # Check tokens array for the one marked as winner
        tokens = market_data.get("tokens", [])
        for token in tokens:
            if token.get("winner", False):
                outcome = token.get("outcome")
                if outcome:
                    return str(outcome)

        # Check outcomes array
        outcomes = market_data.get("outcomes", [])
        for outcome in outcomes:
            if isinstance(outcome, dict) and outcome.get("winner", False):
                name = outcome.get("outcome") or outcome.get("name")
                if name:
                    return str(name)

        return None

    # ------------------------------------------------------------------
    # Daily PnL rollup
    # ------------------------------------------------------------------

    async def _update_daily_pnl(
        self, pnl: float, strategy: str, timestamp: datetime
    ) -> None:
        """
        Upsert the daily PnL record in MongoDB.

        Args:
            pnl: Realized PnL for this trade
            strategy: Strategy name
            timestamp: Resolution timestamp
        """
        date_str = timestamp.strftime("%Y-%m-%d")

        # Fetch existing record
        existing = await db.get_daily_pnl(timestamp)

        if existing:
            new_total = existing.get("total_pnl", 0.0) + pnl
            new_trades = existing.get("total_trades", 0) + 1
            new_wins = existing.get("winning_trades", 0) + (1 if pnl > 0 else 0)

            # Per-strategy breakdown
            strategy_pnl = existing.get("strategy_pnl", {})
            strategy_pnl[strategy] = strategy_pnl.get(strategy, 0.0) + pnl

            pnl_data = {
                "total_pnl": new_total,
                "total_trades": new_trades,
                "winning_trades": new_wins,
                "win_rate": (new_wins / new_trades * 100) if new_trades > 0 else 0.0,
                "strategy_pnl": strategy_pnl,
            }
        else:
            pnl_data = {
                "total_pnl": pnl,
                "total_trades": 1,
                "winning_trades": 1 if pnl > 0 else 0,
                "win_rate": 100.0 if pnl > 0 else 0.0,
                "strategy_pnl": {strategy: pnl},
            }

        await db.upsert_daily_pnl(timestamp, pnl_data)
        logger.debug(
            f"Daily PnL updated for {date_str}: "
            f"total={pnl_data['total_pnl']:.4f}, "
            f"trades={pnl_data['total_trades']}"
        )


# Global resolver instance
position_resolver = PositionResolver()


async def start_position_resolver() -> PositionResolver:
    """Start the global position resolver as a background task."""
    asyncio.create_task(position_resolver.start())
    return position_resolver
