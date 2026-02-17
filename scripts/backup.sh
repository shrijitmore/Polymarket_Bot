#!/bin/bash
# MongoDB backup script
# Run daily via cron: 0 2 * * * /path/to/backup.sh

set -e

# Configuration
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="polymarket_bot_${TIMESTAMP}"
MONGO_URI="${MONGO_URI:-mongodb://localhost:27017}"
DB_NAME="${MONGO_DB_NAME:-polymarket_bot}"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Run mongodump
echo "Creating backup: $BACKUP_NAME"
mongodump --uri="$MONGO_URI" --db="$DB_NAME" --out="$BACKUP_DIR/$BACKUP_NAME"

# Compress backup
echo "Compressing backup..."
cd "$BACKUP_DIR"
tar -czf "${BACKUP_NAME}.tar.gz" "$BACKUP_NAME"
rm -rf "$BACKUP_NAME"

# Keep only last 30 days of backups
echo "Cleaning old backups..."
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "Backup complete: ${BACKUP_NAME}.tar.gz"
