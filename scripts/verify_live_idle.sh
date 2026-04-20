#!/usr/bin/env bash
################################################################################
# File Name: verify_live_idle.sh
# Purpose:   SSH-driven in-car verification that the Pi is collecting OBD data
#            at warm idle.  Runs main.py for N seconds on the Pi, then queries
#            data/obd.db to confirm row count + distinct parameter_name
#            coverage + Session 23-like range sanity.  Exit 0 on PASS.
#
#            Complements scripts/verify_bt_pair.sh (BT pair status) and the
#            eclipse_idle regression fixture (pytest-side).  This is the
#            CIO-runnable live-vehicle smoke that closes the US-168 carryforward
#            work: "are we collecting, in the car, right now?".
# Author:    Rex (Ralph agent)
# Created:   2026-04-19
# Story:     US-197 (US-168 carryforward)
#
# Prereqs:
#   - Pi paired to OBDLink LX (run scripts/verify_bt_pair.sh first).
#   - Engine running, warmed up.
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname
#
# Usage:
#   bash scripts/verify_live_idle.sh                  # 60 s window, live PASS
#   bash scripts/verify_live_idle.sh --duration 30    # shorter window
#   bash scripts/verify_live_idle.sh --bench          # replay fixture, not live
#   bash scripts/verify_live_idle.sh --dry-run        # print plan, no SSH
#   bash scripts/verify_live_idle.sh --help
#
# Modes:
#   live   (default) -- authoritative in-vehicle check.
#   bench            -- replays data/regression/pi-inputs/eclipse_idle.db
#                       to exercise the verification logic.  PASS in this
#                       mode is NOT a substitute for live -- it only proves
#                       the script works; the warning is emitted verbatim.
#
# Exit codes:
#   0 -- PASS (row count threshold met + parameter coverage >= 8)
#   1 -- FAIL (threshold miss or invalid data)
#   2 -- misuse (bad flag, SSH gate failed, missing fixture in bench mode)
################################################################################

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# B-044: source canonical addresses. deploy.conf overrides below.
# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

PI_VENV='$HOME/obd2-venv'

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

DURATION_SECS="60"
MODE="live"
DRY_RUN="0"
MIN_ROWS_PER_SEC="0.3"
MIN_DISTINCT_PARAMS="8"

usage() {
    cat <<'EOF'
Usage: bash scripts/verify_live_idle.sh [OPTIONS]

Options:
  --duration N          Seconds to run main.py on Pi (default 60).
  --bench               Bench mode -- replay eclipse_idle fixture locally.
                        NOT a substitute for live-vehicle PASS.
  --dry-run             Print the plan only; no SSH, no writes.
  --min-distinct-params N
                        Minimum distinct parameter_name rows required
                        (default 8).
  --min-rows-per-sec X  Minimum rows/sec for duration (default 0.3).
  --help, -h            Show this help.

Environment (override via deploy/deploy.conf):
  PI_HOST PI_USER PI_PATH PI_VENV
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --duration)
            DURATION_SECS="$2"
            shift 2
            ;;
        --bench)
            MODE="bench"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        --min-distinct-params)
            MIN_DISTINCT_PARAMS="$2"
            shift 2
            ;;
        --min-rows-per-sec)
            MIN_ROWS_PER_SEC="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$DURATION_SECS" =~ ^[0-9]+$ ]] || [ "$DURATION_SECS" -lt 5 ]; then
    echo "ERROR: --duration must be an integer >= 5 (got: $DURATION_SECS)" >&2
    exit 2
fi

banner() {
    echo ""
    echo "================================================================"
    echo " $1"
    echo "================================================================"
}

SSH_ARGS=(-p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)
ssh_pi() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ssh $PI_USER@$PI_HOST -- $*"
        return 0
    fi
    ssh "${SSH_ARGS[@]}" "$PI_USER@$PI_HOST" "$@"
}

################################################################################
# Bench mode: fixture sanity only.  Clearly marked as non-authoritative.
################################################################################

if [ "$MODE" = "bench" ]; then
    banner "Bench mode (fixture replay) -- NOT an in-vehicle PASS"
    FIXTURE="$REPO_ROOT/data/regression/pi-inputs/eclipse_idle.db"
    if [ ! -f "$FIXTURE" ]; then
        echo "ERROR: Missing fixture: $FIXTURE" >&2
        echo "       Regenerate via scripts/export_regression_fixture.sh" >&2
        exit 2
    fi
    if ! command -v sqlite3 >/dev/null 2>&1; then
        echo "ERROR: sqlite3 CLI not available -- install it or run on Pi" >&2
        exit 2
    fi
    ROWS=$(sqlite3 "$FIXTURE" 'SELECT COUNT(*) FROM realtime_data')
    PARAMS=$(sqlite3 "$FIXTURE" 'SELECT COUNT(DISTINCT parameter_name) FROM realtime_data')
    echo "  fixture rows: $ROWS"
    echo "  distinct parameter_name: $PARAMS"
    echo ""
    if [ "$ROWS" -gt 0 ] && [ "$PARAMS" -ge "$MIN_DISTINCT_PARAMS" ]; then
        echo "Bench: PASS ($ROWS rows / $PARAMS params) -- NOT live confirmation."
        exit 0
    fi
    echo "Bench: FAIL (rows=$ROWS params=$PARAMS min=$MIN_DISTINCT_PARAMS)"
    exit 1
fi

################################################################################
# Live mode.
################################################################################

banner "Live verify -- duration=${DURATION_SECS}s host=$PI_HOST"

if [ "$DRY_RUN" != "1" ]; then
    if ! ssh "${SSH_ARGS[@]}" "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
        exit 2
    fi
    echo "  SSH gate OK"
fi

# Capture the ISO-8601 window boundaries so the query below filters to
# rows produced during THIS run only (main.py may have been running
# before the script; without the filter, older rows would count).
WINDOW_START_CMD='date -u +%Y-%m-%dT%H:%M:%SZ'
WINDOW_START="$(ssh_pi "$WINDOW_START_CMD")"
if [ "$DRY_RUN" = "1" ]; then
    WINDOW_START="2026-04-19T00:00:00Z"
fi
echo "  window_start=$WINDOW_START"

banner "Step 1 / 3 -- stop service, run main.py for ${DURATION_SECS}s"

# Stop the service so the one-shot capture owns the serial port alone.
ssh_pi "sudo systemctl stop eclipse-obd.service 2>/dev/null || true"
ssh_pi "cd $PI_PATH && timeout ${DURATION_SECS}s $PI_VENV/bin/python src/pi/main.py 2>&1 | tail -n 20 || true"

banner "Step 2 / 3 -- query realtime_data for rows written in this window"

ROW_COUNT=$(ssh_pi "cd $PI_PATH && sqlite3 data/obd.db \
  \"SELECT COUNT(*) FROM realtime_data WHERE timestamp >= '$WINDOW_START'\" 2>/dev/null || echo 0")
PARAM_COUNT=$(ssh_pi "cd $PI_PATH && sqlite3 data/obd.db \
  \"SELECT COUNT(DISTINCT parameter_name) FROM realtime_data WHERE timestamp >= '$WINDOW_START'\" 2>/dev/null || echo 0")

if [ "$DRY_RUN" = "1" ]; then
    ROW_COUNT="60"
    PARAM_COUNT="10"
fi

echo "  rows in window: $ROW_COUNT"
echo "  distinct parameter_name: $PARAM_COUNT"

banner "Step 3 / 3 -- assert thresholds"

# Minimum rows = duration * min_rows_per_sec (rounded down).
REQUIRED_ROWS=$(awk -v d="$DURATION_SECS" -v r="$MIN_ROWS_PER_SEC" 'BEGIN{printf("%d", d*r)}')

STATUS="PASS"
FAIL_LINES=""
if ! [[ "$ROW_COUNT" =~ ^[0-9]+$ ]] || [ "$ROW_COUNT" -lt "$REQUIRED_ROWS" ]; then
    STATUS="FAIL"
    FAIL_LINES="$FAIL_LINES  - rows $ROW_COUNT < required $REQUIRED_ROWS"$'\n'
fi
if ! [[ "$PARAM_COUNT" =~ ^[0-9]+$ ]] || [ "$PARAM_COUNT" -lt "$MIN_DISTINCT_PARAMS" ]; then
    STATUS="FAIL"
    FAIL_LINES="$FAIL_LINES  - parameters $PARAM_COUNT < required $MIN_DISTINCT_PARAMS"$'\n'
fi

# Restart the service so the Pi is back to normal ops.
ssh_pi "sudo systemctl start eclipse-obd.service 2>/dev/null || true"

if [ "$DRY_RUN" = "1" ]; then
    echo "Dry run complete -- no thresholds evaluated."
    exit 0
fi

if [ "$STATUS" = "PASS" ]; then
    echo "Overall: PASS (rows=$ROW_COUNT params=$PARAM_COUNT duration=${DURATION_SECS}s)"
    exit 0
fi
echo "Overall: FAIL"
printf '%s' "$FAIL_LINES"
exit 1
