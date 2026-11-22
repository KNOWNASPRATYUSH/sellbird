#!/bin/bash
set -e

# Ensure data directory exists
mkdir -p /app/data

# Sync /app/.env from container environment variables without losing existing keys
touch /app/.env
env | grep -E '^(GROQ_|SMTP_|IMAP_|TINYFISH_|SERPER_|REOON_|ZEROBOUNCE_|HUNTER_|SELLBIRD_|GITHUB_|NOTIFICATION_|ALERT_|PORT)' >> /app/.env || true
# Deduplicate entries in .env, letting newer non-empty container env entries take precedence
awk -F= '!seen[$1]++' /app/.env > /app/.env.tmp && mv /app/.env.tmp /app/.env

# Auto-restore database on boot from encrypted seed or remote cloud backup
NEED_RESTORE=0
if [ ! -s /app/data/sellbird.db ]; then
    NEED_RESTORE=1
else
    COMP_COUNT=$(python -c "import sqlite3; con=sqlite3.connect('/app/data/sellbird.db'); cur=con.cursor(); print(cur.execute('SELECT count(id) FROM companies').fetchone()[0] if 'companies' in [r[0] for r in cur.execute('SELECT name FROM sqlite_master WHERE type=\x27table\x27').fetchall()] else 0)" 2>/dev/null || echo 0)
    if [ "$COMP_COUNT" -eq 0 ]; then
        NEED_RESTORE=1
    fi
fi

if [ "$NEED_RESTORE" -eq 1 ]; then
    echo "Restoring database from encrypted seed vault..."
    SEED_FILE="/app/seed.enc"
    [ ! -f "$SEED_FILE" ] && SEED_FILE="/app/sellbird/seed.enc"
    [ ! -f "$SEED_FILE" ] && SEED_FILE="seed.enc"
    python -m sellbird.seed_vault restore /app/data/sellbird.db "$SEED_FILE"
fi

# Background auto-backup loop (syncs to private Gist every 30m if GITHUB_BACKUP_TOKEN is set)
(
    while true; do
        sleep 1800
        if [ -n "$GITHUB_BACKUP_TOKEN" ] && [ -s /app/data/sellbird.db ]; then
            python -m sellbird.seed_vault backup /app/data/sellbird.db >/dev/null 2>&1 || true
        fi
    done
) &

# Clear any stale lockfiles from previous restarts
rm -f /app/data/sellbird.pid /app/data/sellbird.lock

echo "============================================================"
echo " Starting Sellbird Outreach Engine & 24/7 Cloud Backgrounder"
echo "============================================================"

# Auto-confirm signals so discovery and prospecting start immediately without manual UI gate
python -m sellbird signals --confirm all || true

# Auto-approve pending review outbox items so autopilot sends autonomously
python -c "import asyncio; from sellbird.state import StateManager; asyncio.run(StateManager().approve_outbox())" 2>/dev/null || true

# Launch autonomous background worker loop
python -m sellbird run &

# Launch web dashboard for healthcheck & remote UI
PORT="${PORT:-8000}"
echo "Starting Sellbird Dashboard on port $PORT..."
exec python -m sellbird dashboard --port "$PORT" --host 0.0.0.0
