#!/usr/bin/env python3
"""
Quick status check script for the trading bot.
Run this to check bot health, positions, and daily PnL.
"""
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "polymarket_bot")


async def main():
    """Print bot status."""
    print("=" * 60)
    print("📊 Polymarket Bot Status Check")
    print("=" * 60)
    
    # Connect to MongoDB
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    
    # Get open positions
    open_positions = await db.positions.count_documents({"status": "open"})
    
    # Get today's trades
    today = datetime.utcnow()
    start_of_day = datetime(today.year, today.month, today.day)
    today_trades = await db.positions.count_documents({
        "opened_at": {"$gte": start_of_day}
    })
    
    # Get today's PnL
    date_str = today.strftime("%Y-%m-%d")
    pnl_record = await db.pnl_daily.find_one({"date": date_str})
    
    if pnl_record:
        pnl = pnl_record.get("realized_pnl", 0)
        return_pct = pnl_record.get("return_pct", 0)
    else:
        pnl = 0
        return_pct = 0
    
    # Get total exposure
    pipeline = [
        {"$match": {"status": "open"}},
        {"$group": {"_id": None, "total": {"$sum": "$total_cost"}}}
    ]
    result = list(await db.positions.aggregate(pipeline).to_list(length=1))
    exposure = result[0]["total"] if result else 0
    
    # Get recent errors
    recent_errors = await db.events_log.count_documents({
        "level": "ERROR",
        "timestamp": {"$gte": start_of_day}
    })
    
    # Print status
    print(f"\n📈 Open Positions: {open_positions}")
    print(f"💼 Total Exposure: ${exposure:.2f}")
    print(f"📊 Today's Trades: {today_trades}")
    print(f"💰 Today's PnL: ${pnl:+.2f} ({return_pct:+.2f}%)")
    print(f"❌ Errors Today: {recent_errors}")
    
    # Get latest positions
    print(f"\n📋 Latest Positions:")
    cursor = db.positions.find().sort("opened_at", -1).limit(5)
    positions = await cursor.to_list(length=5)
    
    for pos in positions:
        status_emoji = {
            "open": "🟢",
            "closed": "✅",
            "failed": "❌"
        }.get(pos.get("status", ""), "⚪")
        
        print(f"  {status_emoji} {pos.get('strategy')} - {pos.get('question', '')[:50]}...")
        print(f"     Edge: {pos.get('expected_edge', 0):.2f}% | Cost: ${pos.get('total_cost', 0):.2f}")
    
    print("\n" + "=" * 60)
    
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
