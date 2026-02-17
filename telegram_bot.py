"""
Telegram bot for sending alerts and notifications.
"""
import asyncio
from typing import Optional
from datetime import datetime
from config import settings
from logger import get_logger

logger = get_logger("telegram")


class TelegramBot:
    """Send alerts via Telegram."""
    
    def __init__(self):
        """Initialize Telegram bot."""
        self.enabled = settings.telegram_enabled
        self.bot = None
        self.chat_id = settings.telegram_chat_id
        
        if not self.enabled:
            logger.info("Telegram alerts disabled (no credentials)")
    
    async def initialize(self) -> None:
        """Initialize Telegram bot client."""
        if not self.enabled:
            return
        
        try:
            from telegram import Bot
            self.bot = Bot(token=settings.telegram_bot_token)
            
            # Test connection
            me = await self.bot.get_me()
            logger.info(f"Telegram bot initialized: @{me.username}")
        
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            self.enabled = False
    
    async def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message via Telegram.
        
        Args:
            message: Message text
            parse_mode: Parse mode (Markdown or HTML)
        
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.bot:
            return False
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        
        except Exception as e:
            logger.warning(f"Failed to send Telegram message: {e}")
            return False
    
    async def alert_arb_executed(
        self,
        strategy: str,
        question: str,
        edge: float,
        cost: float
    ) -> None:
        """Alert when arbitrage is executed."""
        message = (
            f"🎯 *Arbitrage Executed*\n\n"
            f"*Strategy:* {strategy}\n"
            f"*Market:* {question[:100]}\n"
            f"*Edge:* {edge:.2f}%\n"
            f"*Cost:* ${cost:.2f}\n"
            f"*Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        await self.send_message(message)
    
    async def alert_trade_failed(
        self,
        strategy: str,
        question: str,
        reason: str
    ) -> None:
        """Alert when trade fails."""
        message = (
            f"❌ *Trade Failed*\n\n"
            f"*Strategy:* {strategy}\n"
            f"*Market:* {question[:100]}\n"
            f"*Reason:* {reason}\n"
            f"*Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        await self.send_message(message)
    
    async def alert_risk_halt(self, reason: str) -> None:
        """Alert when trading is halted."""
        message = (
            f"🛑 *TRADING HALTED*\n\n"
            f"*Reason:* {reason}\n"
            f"*Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
            f"Manual intervention required."
        )
        await self.send_message(message)
    
    async def send_daily_summary(
        self,
        pnl: float,
        trades: int,
        win_rate: float,
        max_dd: float
    ) -> None:
        """Send daily summary."""
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        
        message = (
            f"{pnl_emoji} *Daily Summary*\n\n"
            f"*PnL:* ${pnl:+.2f} ({(pnl/settings.bankroll*100):+.2f}%)\n"
            f"*Trades:* {trades}\n"
            f"*Win Rate:* {win_rate:.1f}%\n"
            f"*Max Drawdown:* {max_dd:.2f}%\n"
            f"*Date:* {datetime.utcnow().strftime('%Y-%m-%d')}"
        )
        await self.send_message(message)


# Global instance
telegram_bot = TelegramBot()


async def init_telegram() -> TelegramBot:
    """Initialize Telegram bot."""
    await telegram_bot.initialize()
    return telegram_bot
