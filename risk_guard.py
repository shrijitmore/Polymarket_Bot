"""
Risk management guard for trade validation and position tracking.
Enforces strict risk limits before trade execution.
"""
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from config import settings
from db import db
from logger import get_logger

logger = get_logger("risk_guard")


class RiskGuard:
    """Validates trades against risk limits and tracks exposure."""
    
    def __init__(self):
        """Initialize risk guard."""
        self.consecutive_fails = 0
        self.trading_halted = False
        self.halt_reason = ""
    
    async def validate_trade(self, signal: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate trade signal against all risk limits.
        
        Args:
            signal: Trade signal from signal engine
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Check if trading is halted
        if self.trading_halted:
            return False, f"Trading halted: {self.halt_reason}"
        
        strategy = signal.get("strategy", "unknown")
        total_cost = signal.get("total_cost", 0)
        
        # Validate 1: Position size limit
        max_size = self._get_max_position_size(strategy)
        if total_cost > max_size:
            logger.warning(
                f"Trade rejected: Position size ${total_cost:.2f} exceeds "
                f"max ${max_size:.2f} for {strategy}"
            )
            return False, f"Position size exceeds limit ({max_size})"
        
        # Validate 2: Concurrent positions limit
        open_count = await db.count_open_positions()
        if open_count >= settings.max_concurrent_positions:
            logger.warning(
                f"Trade rejected: Max concurrent positions ({settings.max_concurrent_positions}) reached"
            )
            return False, f"Max concurrent positions reached ({settings.max_concurrent_positions})"
        
        # Validate 3: Daily exposure limit
        current_exposure = await db.get_total_exposure()
        new_exposure = current_exposure + total_cost
        
        if new_exposure > settings.max_daily_exposure:
            logger.warning(
                f"Trade rejected: Total exposure ${new_exposure:.2f} would exceed "
                f"max ${settings.max_daily_exposure:.2f}"
            )
            return False, f"Daily exposure limit would be exceeded"
        
        # Validate 4: Daily loss check
        today_pnl = await self._get_today_pnl()
        if today_pnl < -settings.daily_loss_halt_amount:
            self.halt_trading(f"Daily loss limit exceeded: ${today_pnl:.2f}")
            return False, self.halt_reason
        
        # All validations passed
        logger.debug(f"Trade validated: {strategy} - ${total_cost:.2f}")
        return True, "OK"
    
    def _get_max_position_size(self, strategy: str) -> float:
        """Get maximum position size for strategy."""
        if strategy == "late_market":
            return settings.max_late_position_size
        else:
            # Arbitrage strategies
            return settings.max_arb_position_size
    
    async def _get_today_pnl(self) -> float:
        """Get today's realized PnL."""
        today = datetime.utcnow()
        pnl_record = await db.get_daily_pnl(today)
        
        if pnl_record:
            return pnl_record.get("realized_pnl", 0.0)
        
        return 0.0
    
    async def record_trade_result(
        self,
        position_id: str,
        success: bool,
        pnl: Optional[float] = None
    ) -> None:
        """
        Record trade result and update consecutive fails counter.
        
        Args:
            position_id: Position ID
            success: Whether trade was successful
            pnl: Realized PnL (if closed)
        """
        if success:
            # Reset consecutive fails counter
            self.consecutive_fails = 0
            logger.info(f"Trade successful: {position_id}")
        else:
            # Increment consecutive fails
            self.consecutive_fails += 1
            logger.warning(
                f"Trade failed: {position_id} "
                f"(consecutive fails: {self.consecutive_fails})"
            )
            
            # Check if we should pause trading
            if self.consecutive_fails >= settings.max_consecutive_fails:
                self.halt_trading(
                    f"{settings.max_consecutive_fails} consecutive failed trades"
                )
        
        # Update daily PnL if provided
        if pnl is not None:
            await self._update_daily_pnl(pnl)
    
    async def _update_daily_pnl(self, pnl: float) -> None:
        """Update today's PnL record."""
        today = datetime.utcnow()
        current_pnl = await db.get_daily_pnl(today)
        
        if current_pnl:
            new_total = current_pnl.get("realized_pnl", 0.0) + pnl
        else:
            new_total = pnl
        
        # Calculate return percentage
        return_pct = (new_total / settings.bankroll) * 100.0
        
        await db.upsert_daily_pnl(today, {
            "realized_pnl": new_total,
            "return_pct": return_pct,
            "trades_count": (current_pnl.get("trades_count", 0) + 1) if current_pnl else 1
        })
    
    def halt_trading(self, reason: str) -> None:
        """
        Halt all trading.
        
        Args:
            reason: Reason for halt
        """
        self.trading_halted = True
        self.halt_reason = reason
        logger.error(f"🛑 TRADING HALTED: {reason}")
    
    def resume_trading(self) -> None:
        """Resume trading (manual intervention only)."""
        self.trading_halted = False
        self.halt_reason = ""
        self.consecutive_fails = 0
        logger.info("✅ Trading resumed")
    
    def get_risk_status(self) -> Dict[str, Any]:
        """
        Get current risk status.
        
        Returns:
            Risk status dictionary
        """
        return {
            "trading_halted": self.trading_halted,
            "halt_reason": self.halt_reason,
            "consecutive_fails": self.consecutive_fails,
            "max_consecutive_fails": settings.max_consecutive_fails,
        }


# Global risk guard instance
risk_guard = RiskGuard()


def get_risk_guard() -> RiskGuard:
    """Get global risk guard instance."""
    return risk_guard
