"""
Quick PnL check script — run this anytime to see position status.

Usage:
    python3 scripts/check_pnl.py
"""
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "polymarket_bot"


async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    print("\n" + "=" * 70)
    print("  POLYMARKET BOT — PnL REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ── Positions ──────────────────────────────────────────────────────
    positions = await db.positions.find().sort("opened_at", -1).to_list(length=200)

    open_pos   = [p for p in positions if p.get("status") == "open"]
    closed_pos = [p for p in positions if p.get("status") == "closed"]
    failed_pos = [p for p in positions if p.get("status") == "failed"]

    print(f"\n📊 POSITIONS SUMMARY")
    print(f"   Open:   {len(open_pos)}")
    print(f"   Closed: {len(closed_pos)}")
    print(f"   Failed: {len(failed_pos)}")
    print(f"   Total:  {len(positions)}")

    # ── Closed positions with PnL ──────────────────────────────────────
    if closed_pos:
        print(f"\n✅ CLOSED POSITIONS (most recent first)")
        print(f"   {'Position ID':<30} {'Strategy':<14} {'PnL':>10}  {'Winner'}")
        print("   " + "-" * 65)
        total_pnl = 0.0
        for p in closed_pos:
            pnl = p.get("realized_pnl", 0.0) or 0.0
            total_pnl += pnl
            sign = "+" if pnl >= 0 else ""
            winner = p.get("winner", "?")
            print(
                f"   {p['position_id']:<30} "
                f"{p.get('strategy','?'):<14} "
                f"{sign}${pnl:>8.4f}  {winner}"
            )
        print("   " + "-" * 65)
        wins = sum(1 for p in closed_pos if (p.get("realized_pnl") or 0) > 0)
        win_rate = wins / len(closed_pos) * 100 if closed_pos else 0
        sign = "+" if total_pnl >= 0 else ""
        print(f"   TOTAL PnL: {sign}${total_pnl:.4f}  |  Win rate: {win_rate:.1f}%")

    # ── Open positions ─────────────────────────────────────────────────
    if open_pos:
        print(f"\n⏳ OPEN POSITIONS (awaiting resolution)")
        print(f"   {'Position ID':<30} {'Strategy':<14} {'Cost':>10}  {'Edge':>8}")
        print("   " + "-" * 65)
        for p in open_pos:
            cost = p.get("actual_total_cost") or p.get("total_cost") or 0.0
            edge = p.get("expected_edge") or 0.0
            print(
                f"   {p['position_id']:<30} "
                f"{p.get('strategy','?'):<14} "
                f"${cost:>8.4f}  {edge:>6.2f}%"
            )

    # ── Daily PnL ─────────────────────────────────────────────────────
    daily = await db.pnl_daily.find().sort("date", -1).limit(7).to_list(length=7)
    if daily:
        print(f"\n📅 DAILY PnL (last 7 days)")
        print(f"   {'Date':<12} {'PnL':>10}  {'Trades':>7}  {'Win Rate':>9}")
        print("   " + "-" * 45)
        for d in daily:
            pnl = d.get("total_pnl", 0.0)
            sign = "+" if pnl >= 0 else ""
            print(
                f"   {d['date']:<12} "
                f"{sign}${pnl:>8.4f}  "
                f"{d.get('total_trades', 0):>7}  "
                f"{d.get('win_rate', 0):>8.1f}%"
            )

    print("\n" + "=" * 70 + "\n")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
