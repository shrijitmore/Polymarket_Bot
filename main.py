"""
Main entry point for Polymarket arbitrage bot.
Orchestrates all modules: scanner, signal engine, executor, risk guard.
"""
import asyncio
import signal as sys_signal
from datetime import datetime
from config import settings
from db import init_db, close_db
from logger import setup_logging, get_logger
from scanner import start_scanner
from signal_engine import start_signal_engine
from executor import start_executor
from binance_feed import start_binance_feed
from risk_guard import get_risk_guard
from clob_client import init_clob_client

logger = get_logger("main")


class TradingBot:
    """Main trading bot orchestrator."""
    
    def __init__(self):
        """Initialize bot."""
        self.market_queue = asyncio.Queue(maxsize=1000)
        self.signal_queue = asyncio.Queue(maxsize=100)
        self.scanner = None
        self.signal_engine = None
        self.executor = None
        self.binance_feed = None
        self.running = False
    
    async def start(self) -> None:
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info("🚀 Polymarket Arbitrage Bot Starting...")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY_RUN (Paper Trading)' if settings.dry_run else '🔴 LIVE TRADING'}")
        logger.info(f"Bankroll: ${settings.bankroll:,.2f}")
        logger.info(f"Max Arb Position: ${settings.max_arb_position_size:,.2f}")
        logger.info(f"Max Late Position: ${settings.max_late_position_size:,.2f}")
        logger.info(f"Daily Loss Halt: ${settings.daily_loss_halt_amount:,.2f}")
        logger.info("")
        logger.info("Enabled Strategies:")
        if settings.enable_one_of_many:
            logger.info("  ✅ One-of-Many Arbitrage")
        if settings.enable_yes_no:
            logger.info("  ✅ YES/NO Arbitrage")
        if settings.enable_late_market:
            logger.info("  ✅ Late-Market Sure Side")
        logger.info("=" * 60)
        
        try:
            # Initialize database
            logger.info("Initializing database...")
            await init_db()
            
            # Initialize CLOB client (needed for orderbook reads, even in DRY_RUN)
            logger.info("Initializing CLOB client...")
            try:
                await init_clob_client()
            except Exception as e:
                if not settings.dry_run:
                    raise
                logger.warning(f"CLOB client init failed (DRY_RUN, orderbook reads may fail): {e}")
            
            # Start Binance feed if late-market enabled
            if settings.enable_late_market:
                logger.info("Starting Binance price feed...")
                self.binance_feed = await start_binance_feed()
            
            # Start scanner
            logger.info("Starting market scanner...")
            self.scanner = await start_scanner(self.market_queue)
            
            # Start signal engine
            logger.info("Starting signal engine...")
            self.signal_engine = await start_signal_engine(
                self.market_queue,
                self.signal_queue
            )
            
            # Start executor
            logger.info("Starting order executor...")
            self.executor = await start_executor(self.signal_queue)
            
            logger.info("")
            logger.info("✅ All systems operational!")
            logger.info("=" * 60)
            
            self.running = True
            
            # Keep running until stopped
            while self.running:
                await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Fatal error during startup: {e}", exc_info=True)
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """Stop the trading bot."""
        logger.info("")
        logger.info("=" * 60)
        logger.info("🛑 Shutting down bot...")
        logger.info("=" * 60)
        
        self.running = False
        
        # Stop components
        if self.scanner:
            await self.scanner.stop()
        
        if self.signal_engine:
            await self.signal_engine.stop()
        
        if self.executor:
            await self.executor.stop()
        
        if self.binance_feed:
            await self.binance_feed.stop()
        
        # Close database
        await close_db()
        
        logger.info("✅ Shutdown complete")
    
    def get_status(self) -> dict:
        """Get bot status."""
        risk_guard = get_risk_guard()
        
        return {
            "running": self.running,
            "dry_run": settings.dry_run,
            "risk_status": risk_guard.get_risk_status(),
            "binance_connected": self.binance_feed.is_connected() if self.binance_feed else False
        }


# Global bot instance
bot = TradingBot()


async def main():
    """Main entry point."""
    # Setup logging
    db_instance = None
    try:
        from db import db as db_instance
    except:
        pass
    
    setup_logging(db_instance)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(bot.stop())
    
    for sig in (sys_signal.SIGINT, sys_signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Start bot
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        if bot.running:
            await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
