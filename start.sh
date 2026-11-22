#!/bin/bash
set -e

# Ensure data directory exists
mkdir -p /app/data

# Always sync /app/.env from container environment variables
echo "Syncing /app/.env from container environment variables..."
env | grep -E '^(GROQ_|SMTP_|IMAP_|TINYFISH_|SERPER_|REOON_|ZEROBOUNCE_|HUNTER_|SELLBIRD_|PORT)' > /app/.env || true

# Clear any stale lockfiles from previous restarts
rm -f /app/data/sellbird.pid /app/data/sellbird.lock

echo "============================================================"
echo " Starting Sellbird Outreach Engine & 24/7 Cloud Backgrounder"
echo "============================================================"

# Auto-confirm signals so discovery and prospecting start immediately without manual UI gate
python -m sellbird signals --confirm all || true

# Launch autonomous background worker loop
python -m sellbird run &

# Launch web dashboard for healthcheck & remote UI
PORT="${PORT:-8000}"
echo "Starting Sellbird Dashboard on port $PORT..."
exec python -m sellbird dashboard --port "$PORT" --host 0.0.0.0
