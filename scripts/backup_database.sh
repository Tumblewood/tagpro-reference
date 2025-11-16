#!/bin/bash

# Database backup script for tagpro-reference
# Runs weekly on Fridays, keeping:
# - Last 2 weekly backups
# - First backup of each month for the last 3 months

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Configuration
DB_PATH="$SCRIPT_DIR/../db.sqlite3"
BACKUP_DIR="$SCRIPT_DIR/../backups"
DATE=$(date +%Y-%m-%d)
DAY_OF_MONTH=$(date +%d)
BACKUP_FILE="$BACKUP_DIR/db_$DATE.sqlite3"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Create the backup
echo "Creating backup: $BACKUP_FILE"
cp "$DB_PATH" "$BACKUP_FILE"
echo "✓ Backup created successfully"

# Tag first backup of the month
if [ "$DAY_OF_MONTH" -le 7 ]; then
    MONTH_TAG="$BACKUP_DIR/db_$(date +%Y-%m)_FIRST.sqlite3"
    cp "$BACKUP_FILE" "$MONTH_TAG"
    echo "✓ Tagged as first backup of the month: $MONTH_TAG"
fi

# Cleanup old backups
echo ""
echo "Cleaning up old backups..."

# Keep last 2 weekly backups (non-tagged files)
ls -t "$BACKUP_DIR"/db_[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].sqlite3 2>/dev/null | tail -n +3 | while read file; do
    echo "  Removing old weekly backup: $file"
    rm "$file"
done

# Keep only first-of-month backups from last 3 months
THREE_MONTHS_AGO=$(date -v-3m +%Y-%m 2>/dev/null || date -d "-3 months" +%Y-%m)
ls "$BACKUP_DIR"/db_*_FIRST.sqlite3 2>/dev/null | while read file; do
    FILE_MONTH=$(echo "$file" | sed -E 's/.*db_([0-9]{4}-[0-9]{2})_FIRST.*/\1/')
    if [[ "$FILE_MONTH" < "$THREE_MONTHS_AGO" ]]; then
        echo "  Removing old monthly backup: $file"
        rm "$file"
    fi
done

echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"/*.sqlite3 2>/dev/null || echo "  No backups found"

echo ""
echo "✓ Backup complete!"
