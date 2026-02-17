# Polymarket Arbitrage Bot

A fully autonomous Python trading bot that runs 24/7 executing arbitrage strategies on Polymarket.

## Features

- **Three Trading Strategies:**
  - One-of-Many Arbitrage
  - Base YES/NO Arbitrage
  - Late-Market Sure Side (crypto markets)

- **Robust Risk Management:**
  - Position size limits (2% per arb, 1.5% late-market)
  - Daily exposure limits (25% max)
  - Circuit breakers (consecutive fails, daily loss halt)
  - Slippage protection

- **Production-Ready:**
  - Fully async (asyncio-based)
  - MongoDB persistence
  - Real-time logging
  - Telegram alerts
  - Docker deployment
  - DRY_RUN mode for paper trading

## Quick Start

### 1. Prerequisites

- Python 3.11+
- MongoDB (or use Docker Compose)
- Polymarket private key
- (Optional) Telegram bot token

### 2. Installation

```bash
# Clone repository
cd /path/to/arbitrage

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

**Required variables:**
- `POLYMARKET_PRIVATE_KEY` - Your Polymarket wallet private key
- `MONGO_URI` - MongoDB connection string
- `BANKROLL` - Your trading bankroll in USD

**Important:** Keep `DRY_RUN=true` for paper trading initially!

### 4. Run with Docker (Recommended)

```bash
# Start MongoDB and bot
docker-compose up -d

# View logs
docker-compose logs -f bot

# Stop
docker-compose down
```

### 5. Run Locally

```bash
# Ensure MongoDB is running
# mongod --dbpath /path/to/data

# Start bot
python main.py
```

## DRY_RUN Mode

**⚠️ CRITICAL:** Always run in DRY_RUN mode first!

1. Set `DRY_RUN=true` in `.env`
2. Run bot for minimum 7 days
3. Monitor MongoDB for simulated trades
4. Verify risk limits are working
5. Only then consider live trading with minimal capital

## Deployment

See [deployment guide](docs/DEPLOYMENT.md) for VPS setup instructions.

## Project Structure

```
arbitrage/
├── main.py              # Main orchestrator
├── config.py            # Configuration management
├── db.py                # MongoDB connection
├── scanner.py           # Market scanner (Gamma API)
├── clob_client.py       # CLOB API wrapper
├── signal_engine.py     # Arbitrage signal detection
├── executor.py          # Order execution
├── risk_guard.py        # Risk management
├── binance_feed.py      # Binance WebSocket
├── logger.py            # Logging infrastructure
├── telegram_bot.py      # Telegram alerts
├── utils/
│   └── helpers.py       # Utility functions
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Monitoring

- **CLI Logs:** Real-time console output with Rich formatting
- **MongoDB:** Query `positions`, `pnl_daily`, `events_log` collections
- **Telegram:** Receive alerts for trades, failures, daily summaries

## Risk Warnings

⚠️ **Use at your own risk!**

- Polymarket orders are **not atomic** - partial fills can occur
- Market conditions change rapidly
- No strategy guarantees profits
- Start with minimal capital ($100-500)
- Monitor closely for first few weeks
- Never disable risk limits

## License

MIT License - See LICENSE file

## Support

For issues or questions, open a GitHub issue.
