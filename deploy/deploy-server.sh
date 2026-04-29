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
#   4.7 Installs/updates obd-server.service systemd unit (US-231; sync-if-changed)
#   5. Cutover: kills any orphan nohup uvicorn (one-time pre-systemd cleanup)
#   6. Restarts via `sudo systemctl restart obd-server` (US-231; replaces nohup)
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

# Step 4.7 (US-231): Install/update obd-server.service systemd unit.
# Mirror of deploy-pi.sh step_install_eclipse_obd_unit -- sync-if-changed via
# cmp -s so re-deploys are no-ops when the unit content matches the installed
# copy. Runs on every default deploy AND on --restart (so a sprint that only
# tweaks the unit can ship via `bash deploy/deploy-server.sh --restart` if
# the operator prefers).
#
# Idempotency: the cmp -s gate skips daemon-reload when nothing changed --
# important because daemon-reload triggers a brief unit re-evaluation that
# can stall systemd-analyze on a busy box.
#
# sudo prompts: `sudo install` + `sudo systemctl daemon-reload` +
# `sudo systemctl enable` will prompt for the operator's password unless
# /etc/sudoers grants NOPASSWD for these systemctl operations. Pre-US-231
# scout (Session 105) confirmed sudo REQUIRES password on chi-srv-01;
# operator handles the prompt during deploy.
echo "--- Step 4.7: Installing obd-server.service systemd unit (US-231) ---"
ssh $HOST "
    SRC='${PROJECT}/deploy/obd-server.service'
    DST='/etc/systemd/system/obd-server.service'
    if [ ! -f \"\$SRC\" ]; then
        echo 'WARN: \$SRC not present on chi-srv-01 -- skipping unit install.'
        exit 0
    fi
    if sudo test -f \"\$DST\" && sudo cmp -s \"\$SRC\" \"\$DST\"; then
        echo 'obd-server.service already up-to-date; no install needed.'
    else
        echo 'Installing new obd-server.service -> /etc/systemd/system/'
        sudo install -m 644 \"\$SRC\" \"\$DST\"
        sudo systemctl daemon-reload
        sudo systemctl enable obd-server.service
        echo 'Unit installed + daemon-reload + enabled.'
    fi
"
echo ""

# Step 5 (US-231 cutover): kill any orphan pre-systemd uvicorn.
# The pre-US-231 deploy launched uvicorn via `ssh -f ... nohup`; that process
# is NOT systemd-managed and will conflict on port 8000 if left running when
# we switch to the systemd unit. The pkill is a one-time-needed safety net;
# on subsequent deploys (post-cutover) it's a no-op because the systemd-managed
# uvicorn is owned by systemd and won't be matched by the cmdline pattern
# (systemd's exec sets the cmdline differently from the nohup wrapper). The
# [u]vicorn bracket trick prevents the SSH shell hosting the pkill from
# self-matching and killing the SSH session.
echo "--- Step 5: Cutover -- killing any orphan pre-systemd uvicorn ---"
ssh $HOST "pkill -f 'nohup .*[u]vicorn src.server.main:app' 2>/dev/null && echo 'Orphan stopped.' || echo 'No orphan running (post-cutover state -- expected).'"
sleep 1
echo ""

# Step 6 (US-231): restart the systemd-managed server.
# Replaces the pre-US-231 `ssh -f nohup` pattern. systemctl restart handles
# both the start-from-stopped case (post-step-5 cutover) and the restart case
# (subsequent deploys). is-active check + 2s settle window catches a unit
# that fails to come up (DB connection rejected, port already bound by something
# else, etc.) before the health check runs.
echo "--- Step 6: Restarting obd-server.service ---"
ssh $HOST "sudo systemctl restart obd-server.service"
sleep 2
ACTIVE=$(ssh $HOST "systemctl is-active obd-server.service" 2>/dev/null)
if [ "$ACTIVE" = "active" ]; then
    echo "obd-server.service active."
else
    echo "ERROR: obd-server.service not active after restart (state=$ACTIVE)."
    echo "  Check: ssh $HOST 'sudo journalctl -u obd-server.service -n 50 --no-pager'"
    exit 1
fi
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
