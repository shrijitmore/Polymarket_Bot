"""
Logging infrastructure for Polymarket arbitrage bot.
Combines console logging with MongoDB persistence.
"""
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from rich.console import Console
from rich.logging import RichHandler
from config import settings


# Rich console for beautiful CLI output
console = Console()


class MongoDBHandler(logging.Handler):
    """Custom logging handler that writes to MongoDB."""
    
    def __init__(self, db_instance=None):
        super().__init__()
        self.db = db_instance
    
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to MongoDB."""
        if not self.db:
            return
        
        try:
            # Prepare metadata
            metadata = {
                "module": record.name,
                "function": record.funcName,
                "line": record.lineno,
                "thread": record.threadName,
            }
            # Add any custom metadata attached to the record
            if hasattr(record, 'metadata'):
                metadata.update(record.metadata)

            # Asyncio-safe: schedule the coroutine
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Create task to log to MongoDB with new signature
                    asyncio.create_task(self.db.log_event(
                        event_type="log_message",
                        details={
                            "module": record.name,
                            "message": record.getMessage(),
                            "metadata": metadata
                        },
                        level=record.levelname
                    ))
            except RuntimeError:
                # No event loop running, skip DB logging
                pass
                
        except Exception:
            self.handleError(record)


def setup_logging(db_instance=None) -> logging.Logger:
    """
    Set up logging infrastructure.
    
    Args:
        db_instance: MongoDB instance for database logging
    
    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger("polymarket_bot")
    logger.setLevel(getattr(logging, settings.log_level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Console handler with Rich formatting
    console_handler = RichHandler(
        rich_tracebacks=True,
        console=console,
        show_time=True,
        show_path=False
    )
    console_handler.setLevel(getattr(logging, settings.log_level.upper()))
    console_format = logging.Formatter(
        "%(message)s",
        datefmt="[%X]"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # MongoDB handler if database is provided
    if db_instance:
        mongo_handler = MongoDBHandler(db_instance)
        mongo_handler.setLevel(logging.INFO)  # Only log INFO and above to DB
        logger.addHandler(mongo_handler)
    
    return logger


def log_with_metadata(
    logger: logging.Logger,
    level: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log message with additional metadata.
    
    Args:
        logger: Logger instance
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        message: Log message
        metadata: Additional structured data
    """
    # Create a LogRecord with metadata
    log_func = getattr(logger, level.lower())
    
    # Attach metadata to the log record
    extra = {'metadata': metadata or {}}
    log_func(message, extra=extra)


# Module-level loggers for different components
def get_logger(module_name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(f"polymarket_bot.{module_name}")
