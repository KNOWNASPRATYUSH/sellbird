#!/bin/bash
set -e

# Clear any stale lockfiles from previous restarts
rm -f /app/data/sellbird.pid /app/data/sellbird.lock

echo "============================================================"
echo " Starting Sellbird Outreach Engine & 24/7 Cloud Backgrounder"
echo "============================================================"

# Launch autonomous background worker loop
python -m sellbird run &

# Launch web dashboard for healthcheck & remote UI
PORT="${PORT:-8000}"
echo "Starting Sellbird Dashboard on port $PORT..."
exec python -m sellbird dashboard --port "$PORT" --host 0.0.0.0
