"""
MongoDB connection and schema management for Polymarket arbitrage bot.
Uses Motor for async MongoDB operations.
"""
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo import IndexModel, ASCENDING, DESCENDING
from config import settings
import logging

logger = logging.getLogger(__name__)


class MongoDB:
    """MongoDB connection manager."""
    
    def __init__(self, db_manager=None):
        """Initialize MongoDB connection manager."""
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[Any] = None
        self.collections: Dict[str, Any] = {}  # Initialize empty dict immediately
        self._connected = False
        self.db_manager = db_manager
    
    async def connect(self) -> None:
        """Establish MongoDB connection and initialize collections."""
        try:
            logger.info(f"Connecting to MongoDB at {settings.mongo_uri}")
            self.client = AsyncIOMotorClient(settings.mongo_uri)
            self.db = self.client[settings.mongo_db_name]
            
            # Ping to verify connection
            await self.client.admin.command('ping')
            logger.info(f"Successfully connected to MongoDB database: {settings.mongo_db_name}")
            
            # Initialize collections
            self.collections = {
                "markets": self.db.markets,
                "positions": self.db.positions,
                "pnl_daily": self.db.pnl_daily,
                "events_log": self.db.events_log,
            }
            
            # Create indexes
            await self._create_indexes()
            
            # Mark as connected
            self._connected = True
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")
    
    async def _create_indexes(self) -> None:
        """Create database indexes for efficient queries."""
        logger.info("Creating database indexes...")
        
        # Markets collection indexes
        markets_indexes = [
            IndexModel([("market_id", ASCENDING)], unique=True),
            IndexModel([("active", ASCENDING)]),
            IndexModel([("last_scanned_at", DESCENDING)]),
            IndexModel([("expires_at", ASCENDING)]),
        ]
        await self.collections["markets"].create_indexes(markets_indexes)
        
        # Positions collection indexes
        positions_indexes = [
            IndexModel([("position_id", ASCENDING)], unique=True),
            IndexModel([("market_id", ASCENDING)]),
            IndexModel([("strategy", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("opened_at", DESCENDING)]),
            IndexModel([("closed_at", DESCENDING)]),
            IndexModel([("status", ASCENDING), ("opened_at", DESCENDING)]),
        ]
        await self.collections["positions"].create_indexes(positions_indexes)
        
        # PnL daily collection indexes
        pnl_indexes = [
            IndexModel([("date", DESCENDING)], unique=True),
        ]
        await self.collections["pnl_daily"].create_indexes(pnl_indexes)
        
        # Events log collection indexes
        events_indexes = [
            IndexModel([("timestamp", DESCENDING)]),
            IndexModel([("level", ASCENDING)]),
            IndexModel([("module", ASCENDING)]),
            IndexModel([("timestamp", DESCENDING), ("level", ASCENDING)]),
        ]
        await self.collections["events_log"].create_indexes(events_indexes)
        
        logger.info("Database indexes created successfully")
    
    # ========================================
    # MARKETS COLLECTION HELPERS
    # ========================================
    async def upsert_market(self, market_data: Dict[str, Any]) -> None:
        """Insert or update market data."""
        await self.collections["markets"].update_one(
            {"market_id": market_data["market_id"]},
            {"$set": market_data},
            upsert=True
        )
    
    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get market by ID."""
        return await self.collections["markets"].find_one({"market_id": market_id})
    
    async def get_active_markets(self, min_volume: float = 0) -> List[Dict[str, Any]]:
        """Get all active markets above minimum volume."""
        cursor = self.collections["markets"].find({
            "active": True,
            "volume": {"$gte": min_volume}
        }).sort("last_scanned_at", DESCENDING)
        return await cursor.to_list(length=None)
    
    # ========================================
    # POSITIONS COLLECTION HELPERS
    # ========================================
    async def create_position(self, position_data: Dict[str, Any]) -> str:
        """Create new position record."""
        result = await self.collections["positions"].insert_one(position_data)
        return str(result.inserted_id)
    
    async def update_position(self, position_id: str, update_data: Dict[str, Any]) -> None:
        """Update position record."""
        await self.collections["positions"].update_one(
            {"position_id": position_id},
            {"$set": update_data}
        )
    
    async def get_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Get position by ID."""
        return await self.collections["positions"].find_one({"position_id": position_id})
    
    async def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        cursor = self.collections["positions"].find(
            {"status": "open"}
        ).sort("opened_at", DESCENDING)
        return await cursor.to_list(length=None)
    
    async def get_positions_by_strategy(self, strategy: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get positions by strategy and optional status."""
        query = {"strategy": strategy}
        if status:
            query["status"] = status
        
        cursor = self.collections["positions"].find(query).sort("opened_at", DESCENDING)
        return await cursor.to_list(length=None)
    
    async def count_open_positions(self) -> int:
        """Count currently open positions."""
        return await self.collections["positions"].count_documents({"status": "open"})
    
    async def get_today_positions(self, date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get positions opened today."""
        if date is None:
            date = datetime.utcnow()
        
        start_of_day = datetime(date.year, date.month, date.day, 0, 0, 0)
        end_of_day = datetime(date.year, date.month, date.day, 23, 59, 59)
        
        cursor = self.collections["positions"].find({
            "opened_at": {"$gte": start_of_day, "$lte": end_of_day}
        }).sort("opened_at", DESCENDING)
        return await cursor.to_list(length=None)
    
    # ========================================
    # PNL DAILY COLLECTION HELPERS
    # ========================================
    async def upsert_daily_pnl(self, date: datetime, pnl_data: Dict[str, Any]) -> None:
        """Insert or update daily PnL record."""
        date_str = date.strftime("%Y-%m-%d")
        await self.collections["pnl_daily"].update_one(
            {"date": date_str},
            {"$set": {**pnl_data, "date": date_str, "updated_at": datetime.utcnow()}},
            upsert=True
        )
    
    async def get_daily_pnl(self, date: datetime) -> Optional[Dict[str, Any]]:
        """Get PnL for specific date."""
        date_str = date.strftime("%Y-%m-%d")
        return await self.collections["pnl_daily"].find_one({"date": date_str})
    
    async def get_recent_pnl(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get PnL for recent days."""
        cursor = self.collections["pnl_daily"].find().sort("date", DESCENDING).limit(days)
        return await cursor.to_list(length=days)
    
    # ========================================
    # EVENTS LOG COLLECTION HELPERS
    # ========================================
    async def log_event(self, event_type: str, details: Dict[str, Any], level: str = "INFO") -> None:
        """
        Log an event to MongoDB.
        
        Args:
            event_type: Type of event (e.g., "trade_executed", "risk_halt")
            details: Event details
            level: Log level (INFO, WARNING, ERROR)
        """
        # Skip if not connected yet
        if not self._connected or not self.collections or "events_log" not in self.collections:
            return
            
        event = {
            "timestamp": datetime.utcnow(),
            "event_type": event_type,
            "level": level,
            "details": details
        }
        
        try:
            await self.collections["events_log"].insert_one(event)
        except Exception as e:
            logger.error(f"Failed to log event to MongoDB: {e}")
    
    async def get_recent_events(
        self,
        limit: int = 100,
        level: Optional[str] = None,
        module: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get recent events with optional filtering."""
        query = {}
        if level:
            query["level"] = level.upper()
        if module:
            query["module"] = module
        
        cursor = self.collections["events_log"].find(query).sort("timestamp", DESCENDING).limit(limit)
        return await cursor.to_list(length=limit)
    
    # ========================================
    # AGGREGATION HELPERS
    # ========================================
    async def get_total_exposure(self) -> float:
        """Calculate total exposure from open positions."""
        pipeline = [
            {"$match": {"status": "open"}},
            {"$group": {"_id": None, "total": {"$sum": "$total_cost"}}}
        ]
        result = await self.collections["positions"].aggregate(pipeline).to_list(length=1)
        return result[0]["total"] if result else 0.0
    
    async def get_strategy_stats(self, strategy: str) -> Dict[str, Any]:
        """Get statistics for a specific strategy."""
        pipeline = [
            {"$match": {"strategy": strategy, "status": "closed"}},
            {
                "$group": {
                    "_id": None,
                    "total_trades": {"$sum": 1},
                    "winning_trades": {
                        "$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}
                    },
                    "total_pnl": {"$sum": "$realized_pnl"},
                    "avg_edge": {"$avg": "$expected_edge"}
                }
            }
        ]
        result = await self.collections["positions"].aggregate(pipeline).to_list(length=1)
        
        if result:
            stats = result[0]
            stats["win_rate"] = (
                stats["winning_trades"] / stats["total_trades"] * 100
                if stats["total_trades"] > 0 else 0
            )
            return stats
        
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "total_pnl": 0.0,
            "avg_edge": 0.0,
            "win_rate": 0.0
        }


# Global database instance
db = MongoDB()


async def init_db() -> MongoDB:
    """Initialize database connection."""
    await db.connect()
    return db


async def close_db() -> None:
    """Close database connection."""
    await db.disconnect()
