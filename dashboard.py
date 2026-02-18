"""
Dashboard backend for Polymarket Arbitrage Bot.
Serves real-time data to the "Money Printing Machine" frontend.
"""
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from config import settings
from db import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await db.connect()
    except Exception as e:
        print(f"WARNING: DB connection failed: {e}. Dashboard will show empty data.")
    asyncio.create_task(broadcast_updates())
    yield
    # Shutdown
    await db.disconnect()


app = FastAPI(title="Money Printing Machine API", lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================
# MODELS
# ========================================

class PositionOut(BaseModel):
    position_id: str
    market_id: str
    question: str = ""
    strategy: str = ""
    status: str = "open"
    total_cost: float = 0.0
    expected_edge: float = 0.0
    opened_at: Optional[str] = None
    actual_edge: Optional[float] = None
    realized_pnl: Optional[float] = None

class Stats(BaseModel):
    total_pnl: float
    daily_pnl: float
    bankroll: float
    active_positions: int
    win_rate: float
    total_trades: int
    winning_trades: int
    status: str
    dry_run: bool

class EventOut(BaseModel):
    timestamp: str
    event_type: str
    level: str
    details: Dict[str, Any] = {}

class PnlDay(BaseModel):
    date: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades: int = 0

# ========================================
# WEBSOCKET MANAGER
# ========================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

# ========================================
# DB CONNECTION (handled by lifespan)
# ========================================

# ========================================
# HELPER: Build stats dict
# ========================================

async def _build_stats() -> Dict[str, Any]:
    """Build stats from DB. Returns a plain dict."""
    motor_db = db.db

    total_pnl = 0.0
    daily_pnl = 0.0
    active_count = 0
    total_trades = 0
    winning_trades = 0
    win_rate = 0.0

    if motor_db is not None:
        # 1. Total PnL + win rate from closed positions
        pipeline = [
            {"$match": {"status": "closed"}},
            {
                "$group": {
                    "_id": None,
                    "total_pnl": {"$sum": "$realized_pnl"},
                    "total_trades": {"$sum": 1},
                    "winning_trades": {
                        "$sum": {"$cond": [{"$gt": ["$realized_pnl", 0]}, 1, 0]}
                    },
                }
            },
        ]
        cursor = motor_db.positions.aggregate(pipeline)
        result = await cursor.to_list(length=1)
        if result:
            total_pnl = result[0].get("total_pnl", 0.0) or 0.0
            total_trades = result[0].get("total_trades", 0)
            winning_trades = result[0].get("winning_trades", 0)
            if total_trades > 0:
                win_rate = round((winning_trades / total_trades) * 100, 1)

        # 2. Daily PnL — db stores date as "YYYY-MM-DD" string
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_rec = await motor_db.pnl_daily.find_one({"date": today_str})
        if daily_rec:
            daily_pnl = daily_rec.get("realized_pnl", 0.0) or 0.0

        # 3. Active positions count
        active_count = await motor_db.positions.count_documents({"status": "open"})

    current_bankroll = settings.bankroll + total_pnl

    return {
        "total_pnl": round(total_pnl, 4),
        "daily_pnl": round(daily_pnl, 4),
        "bankroll": round(current_bankroll, 2),
        "active_positions": active_count,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "status": "ONLINE",
        "dry_run": settings.dry_run,
    }


# ========================================
# ENDPOINTS
# ========================================

@app.get("/api/stats")
async def get_stats():
    """Get high-level statistics."""
    return await _build_stats()


@app.get("/api/positions")
async def get_positions(limit: int = 50, status: Optional[str] = None):
    """Get recent positions, optionally filtered by status."""
    if db.db is None:
        return []

    query: Dict[str, Any] = {}
    if status:
        query["status"] = status

    cursor = (
        db.db.positions.find(query, {"_id": 0})
        .sort("opened_at", -1)
        .limit(limit)
    )
    positions = await cursor.to_list(length=limit)

    # Normalize fields for frontend
    for pos in positions:
        if "opened_at" in pos and isinstance(pos["opened_at"], datetime):
            pos["opened_at"] = pos["opened_at"].isoformat()

    return positions


@app.get("/api/events")
async def get_events(limit: int = 100, level: Optional[str] = None):
    """Get recent system events for the log panel."""
    if db.db is None:
        return []

    query: Dict[str, Any] = {}
    if level:
        query["level"] = level.upper()

    cursor = (
        db.db.events_log.find(query, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
    events = await cursor.to_list(length=limit)

    for ev in events:
        if "timestamp" in ev and isinstance(ev["timestamp"], datetime):
            ev["timestamp"] = ev["timestamp"].isoformat()

    return events


@app.get("/api/pnl-history")
async def get_pnl_history(days: int = 30):
    """Get daily PnL history for the chart."""
    if db.db is None:
        return []

    cursor = (
        db.db.pnl_daily.find({}, {"_id": 0})
        .sort("date", -1)
        .limit(days)
    )
    records = await cursor.to_list(length=days)
    # Return chronological order
    records.reverse()
    return records


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "db_connected": db._connected,
        "dry_run": settings.dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ========================================
# WEBSOCKET
# ========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ========================================
# BACKGROUND BROADCASTER (started by lifespan)
# ========================================

async def broadcast_updates():
    """Periodically push stats + positions + recent events to frontend."""
    while True:
        await asyncio.sleep(2)

        if not manager.active_connections:
            continue

        try:
            stats = await _build_stats()

            # Fetch recent positions
            positions = []
            if db.db is not None:
                cursor = (
                    db.db.positions.find({}, {"_id": 0})
                    .sort("opened_at", -1)
                    .limit(20)
                )
                positions = await cursor.to_list(length=20)
                for pos in positions:
                    if "opened_at" in pos and isinstance(pos["opened_at"], datetime):
                        pos["opened_at"] = pos["opened_at"].isoformat()

            # Fetch last 10 events
            events = []
            if db.db is not None:
                cursor = (
                    db.db.events_log.find({}, {"_id": 0})
                    .sort("timestamp", -1)
                    .limit(10)
                )
                events = await cursor.to_list(length=10)
                for ev in events:
                    if "timestamp" in ev and isinstance(ev["timestamp"], datetime):
                        ev["timestamp"] = ev["timestamp"].isoformat()

            await manager.broadcast({
                "type": "full_update",
                "data": {
                    "stats": stats,
                    "positions": positions,
                    "events": events,
                },
            })
        except Exception as e:
            print(f"Broadcast error: {e}")
