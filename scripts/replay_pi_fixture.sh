#!/usr/bin/env bash
################################################################################
# replay_pi_fixture.sh -- Flat-file replay test harness for Pi -> Server sync
#                         (B-045 / US-191 fulfillment).
#
# Purpose:
#   Deterministic test driver: SCP a known SQLite fixture to the Pi, run
#   sync_now.py, and assert that the server received EXACTLY the number of
#   rows present in the fixture (per-table).  Replaces the physics-sim
#   launch path in validate_pi_to_server.sh, which was non-deterministic
#   and produced only "delta > 0" assertions.
#
# Why:
#   Session 21 sprint exit exposed that the physics simulator drifts (noise
#   enabled, non-repeatable row counts) and violates tier isolation (second
#   --simulate process while the systemd service already had one).  The
#   CIO directive (B-045) replaces physics-based generation with flat-file
#   replay.  This driver is the canonical Pi -> Server validation; the
#   walk-phase ``validate_pi_to_server.sh`` is deprecated.
#
# Usage:
#   bash scripts/replay_pi_fixture.sh cold_start         # default fixture
#   bash scripts/replay_pi_fixture.sh local_loop         # 10-param / 900 rows
#   bash scripts/replay_pi_fixture.sh errand_day         # 3 drives / 2400 rows
#   bash scripts/replay_pi_fixture.sh --fixture cold_start
#   bash scripts/replay_pi_fixture.sh --dry-run cold_start
#   bash scripts/replay_pi_fixture.sh --keep-service-stopped cold_start
#   bash scripts/replay_pi_fixture.sh --help
#
# Prerequisites:
#   - data/regression/pi-inputs/<fixture>.db exists locally (git-checked).
#     Regenerate with ``python scripts/seed_pi_fixture.py --all
#                      --output-dir data/regression/pi-inputs``.
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname
#   - Key-based SSH: ssh mcornelison@10.27.27.10 hostname
#   - COMPANION_API_KEY in Pi .env matches server .env API_KEY.
#   - Chi-Srv-01:8000 reachable from the Pi.
#
# Invariants (from US-191):
#   * Row-count assertions are EXACT.  ``fixture has N realtime_data rows,
#     server delta == N``, not ``delta > 0``.
#   * No producer process on the Pi during the test -- eclipse-obd.service
#     is stopped before SCP and optionally restarted at the end.
#   * Fixture files live under data/regression/pi-inputs/ checked into
#     git.  Regenerate via seed_pi_fixture.py only when schema changes.
#
# Exit codes:
#   0  -- PASS (server delta matched fixture per-table)
#   1  -- FAIL (any per-table assertion failed)
#   2  -- misuse (bad flag, missing fixture, SSH gate fails)
################################################################################

set -e
set -o pipefail

################################################################################
# Configuration (overridable via deploy/deploy.conf).
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

DRY_RUN="0"
KEEP_SERVICE_STOPPED="0"
FIXTURE_NAME=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"
FIXTURE_DIR="$REPO_ROOT/data/regression/pi-inputs"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

################################################################################
# CLI flag parsing.
################################################################################

show_help() {
    cat <<'EOF'
Usage: bash scripts/replay_pi_fixture.sh [OPTIONS] FIXTURE

Positional:
  FIXTURE              One of: cold_start, local_loop, errand_day
                       (i.e. any basename present in data/regression/pi-inputs/)

Options:
  --fixture NAME       Alternative to the positional argument.
  --dry-run            Print the plan without touching the Pi or server.
  --keep-service-stopped
                       Do NOT restart eclipse-obd.service at the end.  Leave
                       the Pi in "bench" mode for back-to-back replays.
  --help, -h           Show this help.

Environment (overridable via deploy/deploy.conf):
  PI_HOST=10.27.27.28       PI_USER=mcornelison
  SERVER_HOST=10.27.27.10   SERVER_USER=mcornelison
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --fixture)
            FIXTURE_NAME="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        --keep-service-stopped)
            KEEP_SERVICE_STOPPED="1"
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        --*)
            echo "ERROR: Unknown flag: $1" >&2
            show_help >&2
            exit 2
            ;;
        *)
            if [ -n "$FIXTURE_NAME" ]; then
                echo "ERROR: Fixture specified twice ($FIXTURE_NAME, $1)" >&2
                exit 2
            fi
            FIXTURE_NAME="$1"
            shift
            ;;
    esac
done

if [ -z "$FIXTURE_NAME" ]; then
    echo "ERROR: Fixture name is required." >&2
    show_help >&2
    exit 2
fi

FIXTURE_PATH="$FIXTURE_DIR/${FIXTURE_NAME}.db"
if [ ! -f "$FIXTURE_PATH" ] && [ "$DRY_RUN" != "1" ]; then
    echo "ERROR: Fixture not found: $FIXTURE_PATH" >&2
    echo "       Regenerate via: python scripts/seed_pi_fixture.py --all \\" >&2
    echo "         --output-dir data/regression/pi-inputs" >&2
    exit 2
fi

################################################################################
# Pretty-printing helpers.
################################################################################

banner() {
    echo ""
    echo "================================================================"
    echo " $1"
    echo "================================================================"
}

# Shared SSH args.  StrictHostKeyChecking=no keeps this a one-command run
# on a freshly-wiped Pi / server.  ConnectTimeout prevents the driver from
# hanging forever when one host is down.
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

scp_to_pi() {
    local src="$1"
    local dst="$2"
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] scp $src $PI_USER@$PI_HOST:$dst"
        return 0
    fi
    scp -P "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "$src" "$PI_USER@$PI_HOST:$dst"
}

################################################################################
# Fixture-side row counts -- authoritative expected deltas.
################################################################################

# Read per-table row counts from the local fixture with sqlite3.  The Pi's
# assertion step compares server deltas against these.  Tables absent from
# the fixture simply emit 0 -- matches the "empty placeholder table" shape.
readLocalFixtureCount() {
    local table="$1"
    if [ "$DRY_RUN" = "1" ]; then
        echo "0"
        return 0
    fi
    sqlite3 "$FIXTURE_PATH" "SELECT COUNT(*) FROM $table" 2>/dev/null || echo 0
}

# In-scope tables per src/pi/data/sync_log.py::IN_SCOPE_TABLES -- same set
# the Pi SyncClient iterates and the server /api/v1/sync accepts.
IN_SCOPE_TABLES=(
    "realtime_data"
    "statistics"
    "profiles"
    "vehicle_info"
    "ai_recommendations"
    "connection_log"
    "alert_log"
    "calibration_sessions"
)

################################################################################
# Pre-flight: SSH gates.
################################################################################

banner "Pre-flight: SSH gates (fixture=$FIXTURE_NAME)"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would verify SSH to $PI_USER@$PI_HOST and $SERVER_USER@$SERVER_HOST"
else
    if ! ssh "${SSH_PI_ARGS[@]}" "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: Pi SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
        exit 2
    fi
    echo "  Pi SSH gate OK"

    if ! ssh "${SSH_SERVER_ARGS[@]}" "$SERVER_USER@$SERVER_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: Server SSH gate failed -- cannot reach $SERVER_USER@$SERVER_HOST" >&2
        exit 2
    fi
    echo "  Server SSH gate OK"
fi

################################################################################
# Step 1 -- Stop the Pi producer so no other writes hit obd.db during replay.
################################################################################

banner "Step 1 / 8 -- Stop eclipse-obd.service on Pi"

# Tolerate "service was already stopped" via `|| true`.  The assertion we
# care about is "no producer running AFTER this step", not "the stop was
# a no-op vs an actual transition".
ssh_pi "sudo systemctl stop eclipse-obd 2>/dev/null || true"
echo "  eclipse-obd.service stopped (or was already)"

################################################################################
# Step 2 -- Read local fixture row counts (authoritative expected deltas).
################################################################################

banner "Step 2 / 8 -- Read fixture row counts locally"

declare -A FIXTURE_COUNTS
TOTAL_FIXTURE_ROWS=0
for table in "${IN_SCOPE_TABLES[@]}"; do
    count="$(readLocalFixtureCount "$table")"
    FIXTURE_COUNTS["$table"]="$count"
    TOTAL_FIXTURE_ROWS=$(( TOTAL_FIXTURE_ROWS + count ))
    printf '  %-22s %6d expected rows\n' "$table" "$count"
done
echo "  -------"
echo "  Total fixture rows: $TOTAL_FIXTURE_ROWS"

################################################################################
# Step 3 -- Capture pre-sync server row counts (baseline for delta math).
################################################################################

banner "Step 3 / 8 -- Capture pre-sync server row counts"

# Read counts via a Python one-liner on the server that uses the same
# mysql-connector bridge validate_pi_to_server.sh already relies on.
# This avoids keying DB credentials into this driver.
readServerCount() {
    local table="$1"
    if [ "$DRY_RUN" = "1" ]; then
        echo "0"
        return 0
    fi
    ssh_server "cd $SERVER_PATH && $SERVER_VENV/bin/python -c \"
import os, sys
sys.path.insert(0, '.')
from src.common.config.secrets_loader import loadEnvFile
loadEnvFile('.env')
try:
    import mysql.connector as m
except ImportError:
    print('NO_MYSQL_CONNECTOR'); sys.exit(0)
conn = m.connect(
    host=os.environ.get('MYSQL_HOST','localhost'),
    user=os.environ.get('MYSQL_USER','obd2'),
    password=os.environ.get('MYSQL_PASSWORD',''),
    database=os.environ.get('MYSQL_DATABASE','obd2db'),
)
cur = conn.cursor()
try:
    cur.execute(\\\"SELECT COUNT(*) FROM $table WHERE source_device='chi-eclipse-01'\\\")
    print(cur.fetchone()[0])
except Exception as exc:
    print(f'TABLE_ERROR:{exc}')
\" 2>/dev/null || echo SERVER_QUERY_FAIL"
}

declare -A SERVER_COUNT_BEFORE
for table in "${IN_SCOPE_TABLES[@]}"; do
    count="$(readServerCount "$table")"
    SERVER_COUNT_BEFORE["$table"]="$count"
    printf '  %-22s %s\n' "$table" "$count"
done

################################################################################
# Step 4 -- SCP the fixture to the Pi, overwriting obd.db.
################################################################################

banner "Step 4 / 8 -- SCP fixture to Pi (overwrite obd.db)"

REMOTE_DB="$PI_PATH/data/obd.db"
scp_to_pi "$FIXTURE_PATH" "$REMOTE_DB"
# Remove any stale WAL / SHM sidecars -- fixture is a single plain DB file
# and leftover journal bytes from a crashed systemd run would corrupt the
# replay (SyncClient opens the DB and reads committed rows via COUNT(*)).
ssh_pi "rm -f $REMOTE_DB-shm $REMOTE_DB-wal 2>/dev/null || true"
echo "  Fixture installed: $REMOTE_DB"

################################################################################
# Step 5 -- Run sync_now.py on the Pi.
################################################################################

banner "Step 5 / 8 -- Run sync_now.py on Pi"

SYNC_OUT_FILE="/tmp/replay-${FIXTURE_NAME}-sync.out"
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would: ssh Pi && $PI_VENV/bin/python scripts/sync_now.py"
elif ssh_pi "cd $PI_PATH && $PI_VENV/bin/python scripts/sync_now.py" \
        | tee "$SYNC_OUT_FILE"; then
    if grep -q '^Status: FAILED' "$SYNC_OUT_FILE"; then
        echo "  ERROR: sync_now.py reported Status: FAILED" >&2
        exit 1
    fi
    if ! grep -qE '^Status: (OK|DISABLED)' "$SYNC_OUT_FILE"; then
        echo "  ERROR: sync_now.py output missing Status: OK/DISABLED line" >&2
        exit 1
    fi
    echo "  sync_now.py exit OK"
else
    echo "  ERROR: sync_now.py exited non-zero on Pi" >&2
    exit 1
fi

################################################################################
# Step 6 -- Capture post-sync server row counts.
################################################################################

banner "Step 6 / 8 -- Capture post-sync server row counts"

declare -A SERVER_COUNT_AFTER
for table in "${IN_SCOPE_TABLES[@]}"; do
    count="$(readServerCount "$table")"
    SERVER_COUNT_AFTER["$table"]="$count"
    printf '  %-22s %s\n' "$table" "$count"
done

################################################################################
# Step 7 -- Assert per-table delta == fixture row count EXACTLY.
################################################################################

banner "Step 7 / 8 -- Assert per-table deltas"

FAIL_COUNT=0
declare -a FAIL_LINES
printf '  %-22s %10s %10s %10s %10s %s\n' \
    "table" "before" "after" "delta" "expected" "status"
printf '  %-22s %10s %10s %10s %10s %s\n' \
    "-----" "------" "-----" "-----" "--------" "------"

for table in "${IN_SCOPE_TABLES[@]}"; do
    before="${SERVER_COUNT_BEFORE[$table]:-0}"
    after="${SERVER_COUNT_AFTER[$table]:-0}"
    expected="${FIXTURE_COUNTS[$table]:-0}"

    # Short-circuit the arithmetic branch when either readServerCount
    # returned an error sentinel ("SERVER_QUERY_FAIL", "NO_MYSQL_CONNECTOR",
    # "TABLE_ERROR:..").  Treat those as non-numeric -> FAIL without trying
    # to compute a delta.
    if ! [[ "$before" =~ ^[0-9]+$ ]] || ! [[ "$after" =~ ^[0-9]+$ ]]; then
        status="FAIL (non-numeric server count: before=$before after=$after)"
        FAIL_COUNT=$(( FAIL_COUNT + 1 ))
        FAIL_LINES+=("$table: $status")
        printf '  %-22s %10s %10s %10s %10s %s\n' \
            "$table" "$before" "$after" "?" "$expected" "$status"
        continue
    fi

    delta=$(( after - before ))
    if [ "$delta" -eq "$expected" ]; then
        status="PASS"
    else
        status="FAIL"
        FAIL_COUNT=$(( FAIL_COUNT + 1 ))
        FAIL_LINES+=("$table: expected +$expected, got +$delta")
    fi
    printf '  %-22s %10d %10d %10d %10d %s\n' \
        "$table" "$before" "$after" "$delta" "$expected" "$status"
done

################################################################################
# Step 8 -- Summary + optional service restart.
################################################################################

banner "Step 8 / 8 -- Summary"

if [ "$KEEP_SERVICE_STOPPED" != "1" ]; then
    echo "  Restarting eclipse-obd.service on Pi (use --keep-service-stopped to skip)"
    ssh_pi "sudo systemctl start eclipse-obd 2>/dev/null || true"
else
    echo "  eclipse-obd.service left stopped (--keep-service-stopped)"
fi

if [ "$DRY_RUN" = "1" ]; then
    echo ""
    echo "Dry run complete -- no assertions evaluated."
    exit 0
fi

if [ "$FAIL_COUNT" -eq 0 ]; then
    echo ""
    echo "Overall: PASS ($TOTAL_FIXTURE_ROWS rows replayed from $FIXTURE_NAME.db)"
    exit 0
fi

echo ""
echo "Overall: FAIL ($FAIL_COUNT tables off-delta)"
for line in "${FAIL_LINES[@]}"; do
    echo "  - $line"
done
exit 1
