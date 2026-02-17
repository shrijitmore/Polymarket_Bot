"""
Order execution engine for Polymarket arbitrage bot.
Handles multi-leg order placement, timeout, cancellation, and DRY_RUN simulation.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from config import settings
from db import db
from logger import get_logger
from risk_guard import get_risk_guard
from clob_client import clob_client
from utils.helpers import calculate_slippage, format_usd, generate_position_id

logger = get_logger("executor")


class OrderExecutor:
    """Executes multi-leg arbitrage orders."""
    
    def __init__(self, signal_queue: asyncio.Queue):
        """
        Initialize executor.
        
        Args:
            signal_queue: Queue receiving trade signals
        """
        self.signal_queue = signal_queue
        self.running = False
        self.risk_guard = get_risk_guard()
    
    async def start(self) -> None:
        """Start the executor."""
        self.running = True
        logger.info(f"Order executor started (DRY_RUN={settings.dry_run})")
        
        while self.running:
            try:
                # Wait for trade signal
                signal = await self.signal_queue.get()
                
                # Execute trade
                await self._execute_signal(signal)
            
            except Exception as e:
                logger.error(f"Executor error: {e}", exc_info=True)
                await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the executor."""
        self.running = False
        logger.info("Order executor stopped")
    
    async def _execute_signal(self, signal: Dict[str, Any]) -> None:
        """
        Execute a trade signal.
        
        Args:
            signal: Trade signal from signal engine
        """
        strategy = signal.get("strategy")
        position_id = signal.get("position_id")
        
        logger.info(f"🎯 Executing {strategy} signal: {position_id}")
        
        # Validate with risk guard
        is_valid, reason = await self.risk_guard.validate_trade(signal)
        
        if not is_valid:
            logger.warning(f"❌ Trade rejected by risk guard: {reason}")
            await self._record_failed_trade(signal, f"Risk check failed: {reason}")
            return
        
        # Create position record
        position = self._create_position_record(signal)
        await db.create_position(position)
        
        # Execute based on mode
        if settings.dry_run:
            success = await self._execute_dry_run(signal, position)
        else:
            success = await self._execute_live(signal, position)
        
        # Record result with risk guard
        pnl = position.get("realized_pnl")
        await self.risk_guard.record_trade_result(position_id, success, pnl)
    
    def _create_position_record(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Create position record for database."""
        return {
            "position_id": signal.get("position_id"),
            "market_id": signal.get("market_id"),
            "question": signal.get("question"),
            "strategy": signal.get("strategy"),
            "status": "pending",
            "legs": signal.get("legs"),
            "total_cost": signal.get("total_cost"),
            "expected_payout": signal.get("expected_payout", 1.0),
            "expected_edge": signal.get("expected_edge"),
            "opened_at": datetime.utcnow(),
            "closed_at": None,
            "realized_pnl": None,
            "orders": []
        }
    
    async def _execute_dry_run(self, signal: Dict[str, Any], position: Dict[str, Any]) -> bool:
        """
        Execute trade in DRY_RUN mode (simulation).
        
        Args:
            signal: Trade signal
            position: Position record
        
        Returns:
            True if simulated execution successful
        """
        position_id = signal.get("position_id")
        legs = signal.get("legs", [])
        
        logger.info(f"💡 DRY_RUN: Simulating {len(legs)} legs for {position_id}")
        
        # Simulate order placement
        await asyncio.sleep(0.1)  # Simulate network delay
        
        # Calculate simulated fills
        simulated_orders = []
        actual_total_cost = 0.0
        
        for leg in legs:
            # Simulate fill at best_ask
            fill_price = leg["price"]
            fill_size = leg["size_tokens"]
            fill_cost = fill_price * fill_size
            
            actual_total_cost += fill_cost
            
            simulated_orders.append({
                "outcome": leg["outcome"],
                "order_id": f"DRY_RUN_{position_id}_{leg['outcome']}",
                "side": "BUY",
                "price": fill_price,
                "size": fill_size,
                "filled": fill_size,
                "status": "filled",
                "fill_price": fill_price,
                "slippage_pct": 0.0  # No slippage in simulation
            })
        
        # Update position
        position["status"] = "open"
        position["orders"] = simulated_orders
        position["actual_total_cost"] = actual_total_cost
        
        await db.update_position(position_id, position)
        
        # Calculate and log expected edge
        expected_edge = signal.get("expected_edge")
        logger.info(
            f"✅ DRY_RUN: {position_id} opened - "
            f"Cost: {format_usd(actual_total_cost)}, "
            f"Expected Edge: {expected_edge:.2f}%"
        )
        
        # Log to database
        await db.log_event(
            event_type="dry_run_trade_executed",
            details={
                "module": "executor",
                "message": f"DRY_RUN trade executed: {signal.get('strategy')}",
                "position_id": position_id,
                "strategy": signal.get("strategy"),
                "expected_edge": expected_edge,
                "total_cost": actual_total_cost
            },
            level="INFO"
        )
        
        return True
    
    async def _execute_live(self, signal: Dict[str, Any], position: Dict[str, Any]) -> bool:
        """
        Execute trade in LIVE mode (real orders).
        
        Args:
            signal: Trade signal
            position: Position record
        
        Returns:
            True if execution successful
        """
        position_id = signal.get("position_id")
        legs = signal.get("legs", [])
        market_id = signal.get("market_id")
        
        logger.info(f"🔴 LIVE: Executing {len(legs)} orders for {position_id}")
        
        try:
            # Place all orders concurrently
            order_tasks = []
            for leg in legs:
                task = self._place_order(market_id, leg)
                order_tasks.append(task)
            
            # Wait for all orders with timeout
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*order_tasks, return_exceptions=True),
                    timeout=settings.order_timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error(f"⏰ Timeout placing orders for {position_id}")
                await self._cancel_all_orders(results)
                await self._record_failed_trade(signal, "Order timeout")
                return False
            
            # Check for any failures
            failed_orders = [r for r in results if isinstance(r, Exception) or not r]
            
            if failed_orders:
                logger.error(f"❌ Failed to place some orders for {position_id}")
                await self._cancel_all_orders(results)
                await self._record_failed_trade(signal, "Partial fill")
                return False
            
            # Verify fills and slippage
            all_filled = True
            total_slippage = 0.0
            orders = []
            
            for i, order_result in enumerate(results):
                leg = legs[i]
                expected_price = leg["price"]
                
                # Check if order was filled
                if order_result.get("status") != "filled":
                    all_filled = False
                    break
                
                fill_price = float(order_result.get("fill_price", expected_price))
                slippage = calculate_slippage(expected_price, fill_price)
                total_slippage += slippage
                
                # Check slippage tolerance
                if abs(slippage) > settings.max_slippage_pct:
                    logger.warning(
                        f"⚠️ Excessive slippage on {leg['outcome']}: {slippage:.2f}%"
                    )
                    all_filled = False
                    break
                
                orders.append({
                    **order_result,
                    "outcome": leg["outcome"],
                    "slippage_pct": slippage
                })
            
            # If not all filled or slippage too high, cancel and fail
            if not all_filled:
                logger.error(f"❌ Execution failed for {position_id}")
                await self._cancel_all_orders(results)
                await self._record_failed_trade(signal, "Fill verification failed")
                return False
            
            # Success! Update position
            actual_cost = sum(o["fill_price"] * o["size"] for o in orders)
            actual_edge = (signal.get("expected_payout", 1.0) - actual_cost) * 100.0
            
            position["status"] = "open"
            position["orders"] = orders
            position["actual_total_cost"] = actual_cost
            position["actual_edge"] = actual_edge
            position["avg_slippage"] = total_slippage / len(orders) if orders else 0
            
            await db.update_position(position_id, position)
            
            logger.info(
                f"✅ LIVE: {position_id} filled - "
                f"Cost: {format_usd(actual_cost)}, "
                f"Edge: {actual_edge:.2f}%, "
                f"Avg Slippage: {position['avg_slippage']:.3f}%"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Execution error for {position_id}: {e}", exc_info=True)
            await self._record_failed_trade(signal, f"Exception: {str(e)}")
            return False
    
    async def _place_order(self, market_id: str, leg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Place a single order.
        
        Args:
            market_id: Market ID
            leg: Leg specification
        
        Returns:
            Order result or None
        """
        token_id = leg.get("token_id")
        if not token_id:
            logger.error(f"Missing token_id for leg: {leg.get('outcome')}")
            return None

        neg_risk = leg.get("neg_risk", False)

        result = await clob_client.place_order(
            token_id=token_id,
            side="BUY",
            price=leg["price"],
            size=leg["size_tokens"],
            neg_risk=neg_risk,
        )

        return result
    
    async def _cancel_all_orders(self, order_results: List[Any]) -> None:
        """Cancel all orders from failed execution."""
        for result in order_results:
            if isinstance(result, dict) and result.get("order_id"):
                try:
                    await clob_client.cancel_order(result["order_id"])
                except Exception as e:
                    logger.warning(f"Failed to cancel order: {e}")
    
    async def _record_failed_trade(self, signal: Dict[str, Any], reason: str) -> None:
        """Record failed trade in database."""
        position_id = signal.get("position_id")
        
        failed_position = self._create_position_record(signal)
        failed_position["status"] = "failed"
        failed_position["failure_reason"] = reason
        failed_position["closed_at"] = datetime.utcnow()
        
        await db.update_position(position_id, failed_position)
        
        await db.log_event(
            event_type="trade_failed",
            details={
                "module": "executor",
                "message": f"Trade failed: {reason}",
                "position_id": position_id,
                "strategy": signal.get("strategy"),
                "reason": reason
            },
            level="ERROR"
        )


async def start_executor(signal_queue: asyncio.Queue) -> OrderExecutor:
    """
    Start the order executor.
    
    Args:
        signal_queue: Queue receiving trade signals
    
    Returns:
        Executor instance
    """
    executor = OrderExecutor(signal_queue)
    asyncio.create_task(executor.start())
    return executor
