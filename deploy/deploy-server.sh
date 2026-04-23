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
#   3.5 (--init only) API_KEY bake-in
#   4. (--init only) Creates MariaDB tables via SQLAlchemy create_all
#   4.5 Applies pending schema migrations via apply_server_migrations.py --run-all
#       (US-213 / TD-029: runs on --init AND default flow; idempotent; hard-fails
#       deploy under `set -e` if any migration fails)
#   5. Stops any running uvicorn on port 8000
#   6. Starts uvicorn in background with nohup
#   7. Waits 3 seconds and checks /health endpoint
################################################################################

set -e

# B-044: source canonical bash-side addresses. Operators may override by
# pre-setting SERVER_HOST / SERVER_USER / SERVER_PROJECT_PATH / SERVER_PORT
# in the environment.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=addresses.sh
. "$SCRIPT_DIR/addresses.sh"

HOST="${SERVER_USER}@${SERVER_HOSTNAME}"
PROJECT="${SERVER_PROJECT_PATH}"
VENV="$HOME/obd2-server-venv"
REMOTE_VENV="/home/${SERVER_USER}/obd2-server-venv"
PORT="${SERVER_PORT}"
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
echo "Host: ${SERVER_HOSTNAME}"
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

# Step 3.5: API_KEY bake-in (--init only) -- US-201.
# Ensures /etc/eclipse-obd-server/.env (or $PROJECT/.env, the default)
# has API_KEY. Idempotent: never overwrites an existing value (rotating
# would break the already-paired Pi).
if [ "$INIT" = true ]; then
    echo "--- Step 3.5: Ensuring server .env has API_KEY (US-201) ---"
    SERVER_ENV="$PROJECT/.env"
    KEY_PRESENT=$(ssh "$HOST" \
        "grep -E '^API_KEY=.+' '$SERVER_ENV' >/dev/null 2>&1 && echo yes || echo no")
    if [ "$KEY_PRESENT" = "yes" ]; then
        echo "API_KEY already present in server .env -- no change (idempotent)."
    else
        echo "API_KEY missing or empty in server .env."
        echo "Choose:"
        echo "  [g] Generate a fresh 64-hex key"
        echo "  [p] Paste an existing key (when pairing with a pre-configured Pi)"
        echo "  [s] Skip"
        read -r -p "Choice [g/p/s]: " CHOICE
        NEW_KEY=""
        case "$CHOICE" in
            g|G)
                SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
                NEW_KEY=$(bash "$SCRIPT_ROOT/scripts/generate_api_key.sh")
                echo "Generated fresh key (not echoed). Writing..."
                ;;
            p|P)
                read -r -s -p "Paste API key (input hidden): " NEW_KEY
                echo ""
                [ -z "$NEW_KEY" ] && { echo "Empty paste -- aborting."; exit 1; }
                ;;
            *)
                echo "Skipped. Wire API_KEY into $SERVER_ENV manually later."
                NEW_KEY=""
                ;;
        esac
        if [ -n "$NEW_KEY" ]; then
            printf 'API_KEY=%s\n' "$NEW_KEY" | \
                ssh "$HOST" "cat >> '$SERVER_ENV' && chmod 600 '$SERVER_ENV'"
            echo "API_KEY written to $SERVER_ENV on $HOST (chmod 600)."
        fi
    fi
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

# Step 4.5: Apply pending schema migrations (US-213 / TD-029 closure).
# Runs on --init AND the default deploy flow; skipped when --restart.  `set -e`
# at top of script + non-zero rc from apply_server_migrations.py --run-all
# halts the deploy before the service restart -- no partially-migrated state.
# The runner is idempotent; a fully-migrated server emits a single
# "0 applied" line and exits 0.  US-209 manual-migrated servers will record
# version='0001' on first run (scan returns empty plan, so no DDL emitted).
if [ "$RESTART_ONLY" = false ]; then
    echo "--- Step 4.5: Applying pending schema migrations ---"
    # Runs LOCALLY (not via SSH on server) because apply_server_migrations.py
    # is designed to SSH to the server itself; running it server-side
    # attempts a self-SSH that fails host-key verification.
    LOCAL_REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
    PYTHONPATH="$LOCAL_REPO_ROOT" python "$LOCAL_REPO_ROOT/scripts/apply_server_migrations.py" --run-all --addresses "$LOCAL_REPO_ROOT/deploy/addresses.sh"
    echo ""
fi

# Step 5: Stop any running server
# Pattern uses [u]vicorn bracket trick so pkill's own shell (whose cmdline
# contains the literal pattern) does not self-match and kill the SSH session.
echo "--- Step 5: Stopping existing server ---"
ssh $HOST "pkill -f '[u]vicorn src.server.main:app' 2>/dev/null && echo 'Stopped.' || echo 'No server was running.'"
sleep 1
echo ""

# Step 6: Start server
# ssh -f forks the local ssh to background after auth (implies -n).
# Combined with remote nohup + redirected stdin/stdout/stderr, this lets
# ssh return immediately instead of hanging on the channel to a daemonized
# child that never closes its fds.
echo "--- Step 6: Starting server on port $PORT ---"
ssh -f $HOST "cd $PROJECT && PYTHONPATH=$PROJECT nohup $REMOTE_VENV/bin/uvicorn src.server.main:app --host 0.0.0.0 --port $PORT > $LOG 2>&1 < /dev/null &"
echo "Server starting... (log: $LOG)"
echo ""

# Step 7: Health check
echo "--- Step 7: Health check ---"
sleep 3
HEALTH=$(curl -s "http://${SERVER_HOSTNAME}:${PORT}/api/v1/health" 2>/dev/null)
if [ $? -eq 0 ] && echo "$HEALTH" | python -c "import sys,json; d=json.load(sys.stdin); print(f'Status: {d[\"status\"]}, Drives: {d[\"driveCount\"]}, Uptime: {d[\"uptime\"]}')" 2>/dev/null; then
    echo "Server is healthy."
else
    echo "HEALTH CHECK FAILED. Check log:"
    ssh $HOST "tail -20 $LOG"
    exit 1
fi

echo ""
echo "=== Deployment complete ==="
