#!/usr/bin/env bash
################################################################################
# validate_pi_to_server.sh -- Walk-phase sprint-exit driver for B-037
#
# DEPRECATED (US-191 / B-045, Sprint 13):
#   The physics-simulator launch path that this driver's Step 1 used has been
#   retired in favor of the deterministic flat-file replay harness at
#   ``scripts/replay_pi_fixture.sh``.  Step 1 here now DELEGATES to the replay
#   harness: it SCPs a known fixture from ``data/regression/pi-inputs/`` to
#   the Pi and runs sync_now.py, producing EXACT per-table row-count deltas
#   (replacing this driver's prior "delta > 0" sloppy assertion).  The report
#   + display steps (5-7) still run here, so this file remains the one-stop
#   "full walk-phase validation" driver.  For data ingest only (and tighter
#   exact-delta assertions), prefer ``replay_pi_fixture.sh`` directly.
#
# Purpose:
#   CIO-facing bash driver that executes the 7-step end-to-end validation
#   from docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md
#   section 2.5 against the live Pi (chi-eclipse-01) and server (Chi-Srv-01).
#   Prints PASS/FAIL after each step and an overall PASS/FAIL at the end.
#
# Usage:
#   bash scripts/validate_pi_to_server.sh                      # default run
#   bash scripts/validate_pi_to_server.sh --fixture local_loop # pick replay
#   bash scripts/validate_pi_to_server.sh --skip-simulator     # just sync+report
#   bash scripts/validate_pi_to_server.sh --dry-run            # print plan only
#   bash scripts/validate_pi_to_server.sh --help
#
# Prerequisites (per spec 2.5):
#   - Key-based SSH works: ssh mcornelison@10.27.27.28 hostname
#   - Key-based SSH works: ssh mcornelison@10.27.27.10 hostname
#   - COMPANION_API_KEY matches between Pi .env and server .env
#   - Chi-Srv-01:8000 reachable from the Pi
#   - Fixture file exists under data/regression/pi-inputs/ (regenerate via
#     ``python scripts/seed_pi_fixture.py --all \
#         --output-dir data/regression/pi-inputs``)
#
# Exit codes:
#   0  -- every step PASS
#   1  -- any step FAIL (which step is indicated in the summary)
#   2  -- misuse (bad flag, missing prerequisite, SSH gate fails)
################################################################################

set -e
set -o pipefail

################################################################################
# Configuration -- B-044: sourced from deploy/addresses.sh, overridable via
# deploy/deploy.conf or per-invocation env vars.
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

PI_VENV='$HOME/obd2-venv'
SERVER_PATH="${SERVER_PATH:-${SERVER_PROJECT_PATH}}"
SERVER_VENV='$HOME/obd2-server-venv'
# Note: SERVER_PORT from addresses.sh is the HTTP API port (8000). The SSH
# port to the server is 22 -- independent of the app port.
SERVER_SSH_PORT="${SERVER_SSH_PORT:-22}"

SIM_DURATION_SECONDS="60"  # retained for backward-compat; ignored post-B-045
FIXTURE_NAME="cold_start"  # default replay fixture; --fixture overrides
SKIP_SIMULATOR="0"
DRY_RUN="0"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

################################################################################
# CLI flag parsing.
################################################################################

show_help() {
    # Defaults flow from deploy/addresses.sh; help text expands them live.
    cat <<EOF
Usage: bash scripts/validate_pi_to_server.sh [OPTIONS]

Options:
  --fixture NAME      Replay fixture name (default: cold_start).  Must be a
                      basename present under data/regression/pi-inputs/.
  --duration N        Retained for backward compat; NO-OP since B-045.
                      (Physics-sim launch replaced by flat-file replay.)
  --skip-simulator    Skip step 1-2 (use whatever is already in the Pi DB)
  --dry-run           Print the plan without touching the Pi or server
  --help, -h          Show this help

Environment (overridable via deploy/deploy.conf or env vars):
  PI_HOST=$PI_HOST      PI_USER=$PI_USER
  SERVER_HOST=$SERVER_HOST SERVER_USER=$SERVER_USER
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --fixture)
            FIXTURE_NAME="$2"
            shift 2
            ;;
        --duration)
            # Accepted for backward compat; value ignored since B-045
            # replaced the timed-simulator launch with flat-file replay.
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
    "1. Replay fixture to Pi (delegates to replay_pi_fixture.sh)"
    "2. Verify local Pi SQLite row counts"
    "3. Run sync_now.py on Pi (covered by step 1 delegation)"
    "4. Verify MariaDB row counts on ${SERVER_HOSTNAME}"
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
SSH_SERVER_ARGS=(-p "$SERVER_SSH_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)

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
# Steps 1-3 -- Delegate to replay_pi_fixture.sh (B-045 replacement for the
#              physics-simulator launch + sync_now.py steps).
#
# The replay harness handles:
#   * stopping eclipse-obd.service on the Pi (Pi producer guard)
#   * SCPing a deterministic fixture into the Pi's obd.db
#   * running sync_now.py
#   * asserting EXACT per-table delta == fixture row count
#
# Physical-tier steps unique to this walk-phase driver (report.py + display)
# continue below in steps 4-7.
################################################################################

banner "Step 1-3 / 7 -- ${STEP_NAMES[0]}"

REPLAY_SH="$SCRIPT_DIR/replay_pi_fixture.sh"
REPLAY_ARGS=("--keep-service-stopped" "$FIXTURE_NAME")
if [ "$DRY_RUN" = "1" ]; then
    REPLAY_ARGS=("--dry-run" "${REPLAY_ARGS[@]}")
fi

if [ "$SKIP_SIMULATOR" = "1" ]; then
    echo "  --skip-simulator set; leaving Pi DB as-is and proceeding to server checks"
    record_skipped "--skip-simulator"
    record_skipped "inherited from --skip-simulator"
    record_skipped "inherited from --skip-simulator"
elif [ ! -x "$REPLAY_SH" ] && [ ! -f "$REPLAY_SH" ]; then
    record_fail "replay driver not found: $REPLAY_SH (regenerate via US-191)"
    record_fail "inherited"
    record_fail "inherited"
else
    echo "  Delegating to $REPLAY_SH ${REPLAY_ARGS[*]}"
    if bash "$REPLAY_SH" "${REPLAY_ARGS[@]}"; then
        record_pass      # step 1 (replay)
        record_pass      # step 2 (local Pi row count proven by replay assertion)
        record_pass      # step 3 (sync_now.py -- ran inside replay harness)
    else
        record_fail "replay_pi_fixture.sh exited non-zero"
        record_fail "inherited from step 1"
        record_fail "inherited from step 1"
    fi
fi

# Post-replay DB state -- used by step 4 for the "server >= Pi" sanity check.
PI_REALTIME_AFTER=0
PI_CONNLOG_AFTER=0
if [ "$DRY_RUN" != "1" ]; then
    PI_REALTIME_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM realtime_data' 2>/dev/null || echo 0")"
    PI_CONNLOG_AFTER="$(ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM connection_log' 2>/dev/null || echo 0")"
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
cur.execute(\\\"SELECT COUNT(*) FROM realtime_data WHERE source_device='${PI_DEVICE_ID}'\\\")
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
cur.execute(\\\"SELECT COUNT(*) FROM connection_log WHERE source_device='${PI_DEVICE_ID}'\\\")
print(cur.fetchone()[0])
\" 2>/dev/null || echo SERVER_QUERY_FAIL")

    echo "  MariaDB counts (source_device=${PI_DEVICE_ID}):"
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
