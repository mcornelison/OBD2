#!/usr/bin/env bash
################################################################################
# deploy-server.sh — Deploy/update the OBD2v2 server on Chi-Srv-01
#
# Usage:
#   bash deploy/deploy-server.sh              # Deploy from current branch
#   bash deploy/deploy-server.sh --init       # First-time setup (venv + DB tables)
#   bash deploy/deploy-server.sh --restart    # Just restart the service
#
# Prerequisites:
#   - SSH access to chi-srv-01 as mcornelison
#   - Project cloned at /mnt/projects/O/OBD2v2
#   - .env file configured at /mnt/projects/O/OBD2v2/.env
#   - MariaDB running with obd2db database and obd2 user created
#
# What this script does:
#   1. Pulls latest code from origin on the server
#   2. Creates/updates venv in ~/obd2-server-venv (avoids NAS symlink issues)
#   3. Installs/updates server + base dependencies
#   4. (--init only) Creates MariaDB tables via SQLAlchemy create_all
#   5. Stops any running uvicorn on port 8000
#   6. Starts uvicorn in background with nohup
#   7. Waits 3 seconds and checks /health endpoint
################################################################################

set -e

HOST="mcornelison@chi-srv-01"
PROJECT="/mnt/projects/O/OBD2v2"
VENV="$HOME/obd2-server-venv"
REMOTE_VENV="/home/mcornelison/obd2-server-venv"
PORT=8000
LOG="/tmp/obd2-server.log"

# Parse flags
INIT=false
RESTART_ONLY=false
for arg in "$@"; do
    case $arg in
        --init) INIT=true ;;
        --restart) RESTART_ONLY=true ;;
        --help|-h)
            echo "Usage: bash deploy/deploy-server.sh [--init|--restart]"
            echo "  --init     First-time setup: create venv, install deps, create DB tables"
            echo "  --restart  Skip pull/install, just restart the server"
            echo "  (no flag)  Pull latest, install deps, restart server"
            exit 0
            ;;
    esac
done

echo "=== OBD2v2 Server Deployment ==="
echo "Host: chi-srv-01"
echo "Project: $PROJECT"
echo ""

# Step 1: Pull latest code
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 1: Pulling latest code ---"
    ssh $HOST "cd $PROJECT && git pull 2>&1"
    echo ""
fi

# Step 2: Create venv if needed (--init or first run)
if [ "$INIT" = true ] || ! ssh $HOST "test -f $REMOTE_VENV/bin/python3" 2>/dev/null; then
    echo "--- Step 2: Creating venv at $REMOTE_VENV ---"
    ssh $HOST "python3 -m venv $REMOTE_VENV"
    echo "Venv created."
    echo ""
fi

# Step 3: Install/update dependencies
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 3: Installing dependencies ---"
    ssh $HOST "$REMOTE_VENV/bin/pip install -q -r $PROJECT/requirements.txt -r $PROJECT/requirements-server.txt 2>&1 | tail -5"
    echo ""
fi

# Step 4: Create DB tables (--init only)
if [ "$INIT" = true ]; then
    echo "--- Step 4: Creating MariaDB tables ---"
    ssh $HOST "cd $PROJECT && PYTHONPATH=$PROJECT $REMOTE_VENV/bin/python -c \"
from src.server.db.models import Base
from sqlalchemy import create_engine
from src.server.config import Settings
s = Settings(_env_file='$PROJECT/.env')
url = str(s.DATABASE_URL).replace('aiomysql', 'pymysql')
e = create_engine(url)
Base.metadata.create_all(e)
print('Tables:', list(Base.metadata.tables.keys()))
\" 2>&1"
    echo ""
fi

# Step 5: Stop any running server
echo "--- Step 5: Stopping existing server ---"
ssh $HOST "pkill -f 'uvicorn src.server.main:app' 2>/dev/null && echo 'Stopped.' || echo 'No server was running.'"
sleep 1
echo ""

# Step 6: Start server
echo "--- Step 6: Starting server on port $PORT ---"
ssh $HOST "cd $PROJECT && PYTHONPATH=$PROJECT nohup $REMOTE_VENV/bin/uvicorn src.server.main:app --host 0.0.0.0 --port $PORT > $LOG 2>&1 &"
echo "Server starting... (log: $LOG)"
echo ""

# Step 7: Health check
echo "--- Step 7: Health check ---"
sleep 3
HEALTH=$(curl -s http://chi-srv-01:$PORT/api/v1/health 2>/dev/null)
if [ $? -eq 0 ] && echo "$HEALTH" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Status: {d[\"status\"]}, Drives: {d[\"driveCount\"]}, Uptime: {d[\"uptime\"]}')" 2>/dev/null; then
    echo "Server is healthy."
else
    echo "HEALTH CHECK FAILED. Check log:"
    ssh $HOST "tail -20 $LOG"
    exit 1
fi

echo ""
echo "=== Deployment complete ==="
