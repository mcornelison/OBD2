#!/usr/bin/env bash
################################################################################
# validate_pi_to_server.sh -- Walk-phase sprint-exit driver for B-037
#
# Purpose:
#   CIO-facing bash driver that executes the 7-step end-to-end validation
#   from docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md
#   section 2.5 against the live Pi (chi-eclipse-01) and server (Chi-Srv-01).
#   Prints PASS/FAIL after each step and an overall PASS/FAIL at the end.
#
# Usage:
#   bash scripts/validate_pi_to_server.sh                      # default run
#   bash scripts/validate_pi_to_server.sh --duration 45        # tune sim run
#   bash scripts/validate_pi_to_server.sh --skip-simulator     # just sync+report
#   bash scripts/validate_pi_to_server.sh --dry-run            # print plan only
#   bash scripts/validate_pi_to_server.sh --help
#
# Prerequisites (per spec 2.5):
#   - Key-based SSH works: ssh mcornelison@10.27.27.28 hostname
#   - Key-based SSH works: ssh mcornelison@10.27.27.10 hostname
#   - COMPANION_API_KEY matches between Pi .env and server .env
#   - Chi-Srv-01:8000 reachable from the Pi
#
# Exit codes:
#   0  -- every step PASS
#   1  -- any step FAIL (which step is indicated in the summary)
#   2  -- misuse (bad flag, missing prerequisite, SSH gate fails)
################################################################################

set -e
set -o pipefail

################################################################################
# Configuration (overridable via deploy/deploy.conf if present).
################################################################################

PI_HOST="10.27.27.28"
PI_USER="mcornelison"
PI_PATH="/home/mcornelison/Projects/Eclipse-01"
PI_VENV='$HOME/obd2-venv'
PI_PORT="22"

SERVER_HOST="10.27.27.10"
SERVER_USER="mcornelison"
SERVER_PATH="/home/mcornelison/Projects/Eclipse-01"
SERVER_VENV='$HOME/obd2-server-venv'
SERVER_PORT="22"

SIM_DURATION_SECONDS="60"
SKIP_SIMULATOR="0"
DRY_RUN="0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

################################################################################
# CLI flag parsing.
################################################################################

show_help() {
    cat <<'EOF'
Usage: bash scripts/validate_pi_to_server.sh [OPTIONS]

Options:
  --duration N        Seconds to run the simulator on the Pi (default: 60)
  --skip-simulator    Skip step 1-2 (use whatever is already in the Pi DB)
  --dry-run           Print the plan without touching the Pi or server
  --help, -h          Show this help

Environment (overridable via deploy/deploy.conf):
  PI_HOST=10.27.27.28      PI_USER=mcornelison
  SERVER_HOST=10.27.27.10 SERVER_USER=mcornelison
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --duration)
            SIM_DURATION_SECONDS="$2"
            shift 2
            ;;
        --skip-simulator)
            SKIP_SIMULATOR="1"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            echo "ERROR: Unknown flag: $1" >&2
            show_help >&2
            exit 2
            ;;
    esac
done

################################################################################
# Pretty-printing helpers.
################################################################################

STEP_RESULTS=()      # indexed 0..6 -- "PASS" or "FAIL: <reason>"
STEP_NAMES=(
    "1. Run simulator on Pi"
    "2. Verify local Pi SQLite row counts"
    "3. Run sync_now.py on Pi"
    "4. Verify MariaDB row counts on Chi-Srv-01"
    "5. Run scripts/report.py --drive latest on server"
    "6. Confirm report output non-empty + drive present"
    "7. (manual) Display Sync indicator flipped green"
)

banner() {
    echo ""
    echo "================================================================"
    echo " $1"
    echo "================================================================"
}

record_pass() {
    STEP_RESULTS+=("PASS")
    echo "  -> PASS"
}

record_fail() {
    STEP_RESULTS+=("FAIL: $1")
    echo "  -> FAIL: $1" >&2
}

record_skipped() {
    STEP_RESULTS+=("SKIPPED: $1")
    echo "  -> SKIPPED: $1"
}

# Shared SSH args -- StrictHostKeyChecking no is intentional for IoT tier where
# keys get rotated freely; this is a CIO-run driver against known hosts.
SSH_PI_ARGS=(-p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)
SSH_SERVER_ARGS=(-p "$SERVER_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)

ssh_pi() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ssh $PI_USER@$PI_HOST -- $*"
        return 0
    fi
    ssh "${SSH_PI_ARGS[@]}" "$PI_USER@$PI_HOST" "$@"
}

ssh_server() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ssh $SERVER_USER@$SERVER_HOST -- $*"
        return 0
    fi
    ssh "${SSH_SERVER_ARGS[@]}" "$SERVER_USER@$SERVER_HOST" "$@"
}

################################################################################
# Pre-flight: SSH gates to Pi and server.
################################################################################

banner "Pre-flight: SSH gates"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would verify SSH to $PI_USER@$PI_HOST and $SERVER_USER@$SERVER_HOST"
else
    if ! ssh "${SSH_PI_ARGS[@]}" "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: Pi SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
        echo "       Fix the SSH prerequisite before re-running this driver." >&2
        exit 2
    fi
    echo "  Pi SSH gate OK ($PI_USER@$PI_HOST)"

    if ! ssh "${SSH_SERVER_ARGS[@]}" "$SERVER_USER@$SERVER_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: Server SSH gate failed -- cannot reach $SERVER_USER@$SERVER_HOST" >&2
        echo "       Fix the SSH prerequisite before re-running this driver." >&2
        exit 2
    fi
    echo "  Server SSH gate OK ($SERVER_USER@$SERVER_HOST)"
fi

################################################################################
# Step 1 -- Run simulator on the Pi for SIM_DURATION_SECONDS, then terminate.
################################################################################

banner "Step 1 / 7 -- ${STEP_NAMES[0]}"

# Cache pre-run row counts so step 2 can compute the delta cleanly.
PI_REALTIME_BEFORE=0
PI_CONNLOG_BEFORE=0

if [ "$SKIP_SIMULATOR" = "1" ]; then
    record_skipped "--skip-simulator set; using existing Pi DB state"
else
    # Pre-run counts (step 2 deltas from these).
    if [ "$DRY_RUN" != "1" ]; then
        PI_REALTIME_BEFORE="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM realtime_data' 2>/dev/null || echo 0")"
        PI_CONNLOG_BEFORE="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM connection_log' 2>/dev/null || echo 0")"
        echo "  Pre-run counts: realtime_data=$PI_REALTIME_BEFORE, connection_log=$PI_CONNLOG_BEFORE"
    fi

    # Start the simulator in the background and SIGTERM after the duration.
    # --simulate triggers the simulator path; --verbose gives us actionable
    # log output in case the run goes sideways.
    # `< /dev/null` is load-bearing: without it, the local SSH session inherits
    # the python's stdin and the SSH channel never closes (even though stdout/
    # stderr are redirected to a file). Same class of bug as I-013 fixed in
    # deploy-server.sh Session 19 -- absent it, this script hangs indefinitely
    # at step 1 with the simulator running fine on the Pi but local bash never
    # advancing past the PID-capture line.
    SIM_CMD="cd $PI_PATH && nohup $PI_VENV/bin/python src/pi/main.py --simulate --verbose >/tmp/eclipse-obd-sim.log 2>&1 </dev/null & echo \$!"
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] Would run simulator for $SIM_DURATION_SECONDS seconds on the Pi."
        record_skipped "dry-run"
    else
        # shellcheck disable=SC2029 -- intentional server-side expansion
        SIM_PID="$(ssh_pi "$SIM_CMD" || echo "")"
        if [ -z "$SIM_PID" ] || ! [[ "$SIM_PID" =~ ^[0-9]+$ ]]; then
            record_fail "could not start simulator on Pi (SIM_PID=$SIM_PID)"
        else
            echo "  Simulator started on Pi (PID=$SIM_PID); running for ${SIM_DURATION_SECONDS}s..."
            sleep "$SIM_DURATION_SECONDS"

            # Graceful stop first, then KILL if the process is stuck.
            # shellcheck disable=SC2029 -- intentional server-side expansion
            ssh_pi "kill -TERM $SIM_PID 2>/dev/null || true; sleep 3; kill -KILL $SIM_PID 2>/dev/null || true"
            echo "  Simulator stopped."
            record_pass
        fi
    fi
fi

################################################################################
# Step 2 -- Verify the Pi SQLite gained rows in the expected tables.
################################################################################

banner "Step 2 / 7 -- ${STEP_NAMES[1]}"

PI_REALTIME_AFTER=0
PI_CONNLOG_AFTER=0

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would sqlite3-count realtime_data + connection_log on Pi"
    record_skipped "dry-run"
elif [ "$SKIP_SIMULATOR" = "1" ]; then
    PI_REALTIME_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM realtime_data' 2>/dev/null || echo 0")"
    PI_CONNLOG_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM connection_log' 2>/dev/null || echo 0")"
    echo "  Existing Pi counts: realtime_data=$PI_REALTIME_AFTER, connection_log=$PI_CONNLOG_AFTER"
    record_pass
else
    PI_REALTIME_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM realtime_data' 2>/dev/null || echo 0")"
    PI_CONNLOG_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM connection_log' 2>/dev/null || echo 0")"

    DELTA_REALTIME=$(( PI_REALTIME_AFTER - PI_REALTIME_BEFORE ))
    DELTA_CONNLOG=$(( PI_CONNLOG_AFTER - PI_CONNLOG_BEFORE ))
    echo "  After-run counts: realtime_data=$PI_REALTIME_AFTER (delta +$DELTA_REALTIME)"
    echo "                    connection_log=$PI_CONNLOG_AFTER (delta +$DELTA_CONNLOG)"

    if [ "$DELTA_REALTIME" -le 0 ] && [ "$DELTA_CONNLOG" -le 0 ]; then
        record_fail "simulator added no rows to either realtime_data or connection_log"
    else
        record_pass
    fi
fi

################################################################################
# Step 3 -- Run scripts/sync_now.py on the Pi (pushes to Chi-Srv-01).
################################################################################

banner "Step 3 / 7 -- ${STEP_NAMES[2]}"

SYNC_OUT_FILE="/tmp/eclipse-obd-sync.out"
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would: ssh Pi && $PI_VENV/bin/python scripts/sync_now.py"
    record_skipped "dry-run"
else
    if ssh_pi "cd $PI_PATH && $PI_VENV/bin/python scripts/sync_now.py" | tee "$SYNC_OUT_FILE"; then
        if grep -qE '^Status: (OK|DISABLED)' "$SYNC_OUT_FILE"; then
            record_pass
        elif grep -q '^Status: FAILED' "$SYNC_OUT_FILE"; then
            record_fail "sync_now.py reported Status: FAILED -- see output above"
        else
            record_fail "sync_now.py output did not contain a Status: line"
        fi
    else
        record_fail "sync_now.py exited non-zero on Pi"
    fi
fi

################################################################################
# Step 4 -- Verify MariaDB row counts on Chi-Srv-01 match (or exceed) the Pi.
################################################################################

banner "Step 4 / 7 -- ${STEP_NAMES[3]}"

# We read DB credentials off the server's .env via a tiny Python snippet to
# avoid keying them into this driver.  Requires server-side .env to exist.

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would query MariaDB for realtime_data + connection_log counts"
    record_skipped "dry-run"
else
    SERVER_REALTIME=$(ssh_server "cd $SERVER_PATH && $SERVER_VENV/bin/python -c \"
import os, sys
sys.path.insert(0, '.')
from src.common.config.secrets_loader import loadEnvFile
loadEnvFile('.env')
try:
    import mysql.connector as m
except ImportError:
    import sys; print('NO_MYSQL_CONNECTOR'); sys.exit(0)
conn = m.connect(
    host=os.environ.get('MYSQL_HOST','localhost'),
    user=os.environ.get('MYSQL_USER','obd2'),
    password=os.environ.get('MYSQL_PASSWORD',''),
    database=os.environ.get('MYSQL_DATABASE','obd2db'),
)
cur = conn.cursor()
cur.execute(\\\"SELECT COUNT(*) FROM realtime_data WHERE source_device='chi-eclipse-01'\\\")
print(cur.fetchone()[0])
\" 2>/dev/null || echo SERVER_QUERY_FAIL")

    SERVER_CONNLOG=$(ssh_server "cd $SERVER_PATH && $SERVER_VENV/bin/python -c \"
import os, sys
sys.path.insert(0, '.')
from src.common.config.secrets_loader import loadEnvFile
loadEnvFile('.env')
try:
    import mysql.connector as m
except ImportError:
    import sys; print('NO_MYSQL_CONNECTOR'); sys.exit(0)
conn = m.connect(
    host=os.environ.get('MYSQL_HOST','localhost'),
    user=os.environ.get('MYSQL_USER','obd2'),
    password=os.environ.get('MYSQL_PASSWORD',''),
    database=os.environ.get('MYSQL_DATABASE','obd2db'),
)
cur = conn.cursor()
cur.execute(\\\"SELECT COUNT(*) FROM connection_log WHERE source_device='chi-eclipse-01'\\\")
print(cur.fetchone()[0])
\" 2>/dev/null || echo SERVER_QUERY_FAIL")

    echo "  MariaDB counts (source_device=chi-eclipse-01):"
    echo "    realtime_data   : $SERVER_REALTIME"
    echo "    connection_log  : $SERVER_CONNLOG"

    if [ "$SERVER_REALTIME" = "SERVER_QUERY_FAIL" ] || [ "$SERVER_CONNLOG" = "SERVER_QUERY_FAIL" ]; then
        record_fail "could not query MariaDB (check server .env DB credentials)"
    elif [ "$SERVER_REALTIME" = "NO_MYSQL_CONNECTOR" ]; then
        record_fail "mysql.connector not installed in server venv -- pip install mysql-connector-python"
    elif [ "$PI_REALTIME_AFTER" = "0" ] && [ "$PI_CONNLOG_AFTER" = "0" ]; then
        # If Pi was empty, we can only confirm server is at zero or above.
        record_pass
    elif [ "$SERVER_REALTIME" -ge "$PI_REALTIME_AFTER" ] && \
         [ "$SERVER_CONNLOG" -ge "$PI_CONNLOG_AFTER" ]; then
        # Server should have at LEAST as many rows as the Pi (older drives +
        # this one).  Any shortfall means the sync didn't land correctly.
        record_pass
    else
        record_fail "server row counts ($SERVER_REALTIME / $SERVER_CONNLOG) are below Pi ($PI_REALTIME_AFTER / $PI_CONNLOG_AFTER) -- sync mismatch"
    fi
fi

################################################################################
# Step 5 -- Run scripts/report.py --drive latest on the server.
################################################################################

banner "Step 5 / 7 -- ${STEP_NAMES[4]}"

REPORT_OUT_FILE="/tmp/eclipse-obd-report.out"
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would: ssh server && $SERVER_VENV/bin/python scripts/report.py --drive latest"
    record_skipped "dry-run"
else
    if ssh_server "cd $SERVER_PATH && $SERVER_VENV/bin/python scripts/report.py --drive latest" | tee "$REPORT_OUT_FILE"; then
        record_pass
    else
        record_fail "report.py --drive latest exited non-zero"
    fi
fi

################################################################################
# Step 6 -- Confirm the report output is non-empty and references a drive.
################################################################################

banner "Step 6 / 7 -- ${STEP_NAMES[5]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would grep the report for drive + statistics markers"
    record_skipped "dry-run"
elif [ ! -s "$REPORT_OUT_FILE" ]; then
    record_fail "report.py produced empty output (file: $REPORT_OUT_FILE)"
else
    # Lean sanity check -- the report must at least name a drive and emit
    # some metrics.  Not trying to re-implement report schema validation
    # here; step 5 already proved the command succeeded.
    if grep -qiE 'drive|realtime|statistic' "$REPORT_OUT_FILE"; then
        record_pass
    else
        record_fail "report output has no drive/realtime/statistic markers"
    fi
fi

################################################################################
# Step 7 -- (manual) Display Sync indicator flipped green.
################################################################################

banner "Step 7 / 7 -- ${STEP_NAMES[6]}"
echo "  MANUAL: walk up to the OSOYOO display and verify the 'Sync' dot is"
echo "          green in the header.  This driver cannot observe it remotely."
echo "          Mark PASS only after visual confirmation."
record_skipped "manual step -- CIO observes display directly"

################################################################################
# Summary.
################################################################################

banner "Summary"

OVERALL="PASS"
for i in "${!STEP_RESULTS[@]}"; do
    name="${STEP_NAMES[$i]}"
    status="${STEP_RESULTS[$i]}"
    echo "  $name : $status"
    if [[ "$status" == FAIL:* ]]; then
        OVERALL="FAIL"
    fi
done

echo ""
echo "Overall: $OVERALL"
echo ""

if [ "$OVERALL" = "FAIL" ]; then
    exit 1
fi
exit 0
