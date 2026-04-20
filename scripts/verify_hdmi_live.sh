#!/usr/bin/env bash
################################################################################
# verify_hdmi_live.sh -- US-192 HDMI live-data display verification driver
#
# Purpose:
#   CIO-runnable bash driver that proves the 6-gauge primary screen updates
#   live on the Pi's OSOYOO 3.5" HDMI display while data is flowing into
#   realtime_data.  Orchestrates: start main.py --simulate in the background,
#   wait for it to write rows, run the render harness in --from-db mode so
#   each frame reads the latest value per gauge from SQLite, then ask the CIO
#   to eyeball that the six gauges are refreshing with non-zero values.
#
# Differences from US-183's validate_hdmi_display.sh:
#   validate_hdmi_display.sh -- proves pygame can paint the 480x320 buffer,
#                               hardcoded scripted values, RPM sweep heartbeat.
#   verify_hdmi_live.sh      -- proves LIVE DATA reaches the display: main.py
#                               writes rows -> render harness polls SQLite ->
#                               screen updates.  Engine not required
#                               (simulator path is the valid acceptance path
#                               per US-192 invariant).
#
# Usage:
#   bash scripts/verify_hdmi_live.sh                    # 30s live render
#   bash scripts/verify_hdmi_live.sh --duration 60      # 60s live render
#   bash scripts/verify_hdmi_live.sh --dry-run          # print plan only
#   bash scripts/verify_hdmi_live.sh --help
#
# Prerequisites:
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname
#   - OSOYOO 3.5" HDMI display attached to the Pi
#   - ~/obd2-venv/bin/python present on the Pi with pygame installed
#   - DISPLAY=:0 + XAUTHORITY available on the Pi's interactive session
#     (matches eclipse-obd.service Environment= block post US-192)
#
# Exit codes:
#   0  -- every step PASS; CIO eyeball confirmation prompted at Step 4
#   1  -- any automated step FAIL (which step is indicated in the summary)
#   2  -- misuse (bad flag, missing prerequisite, SSH gate fails)
################################################################################

set -e
set -o pipefail

################################################################################
# Configuration -- B-044: sourced from deploy/addresses.sh.
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

PI_VENV='$HOME/obd2-venv'

DURATION_SECONDS="30"
DRY_RUN="0"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

################################################################################
# CLI flag parsing.
################################################################################

show_help() {
    cat <<EOF
Usage: bash scripts/verify_hdmi_live.sh [OPTIONS]

Options:
  --duration N        Seconds to keep the live render loop running (default: 30)
  --dry-run           Print the plan without touching the Pi
  --help, -h          Show this help

Environment (overridable via deploy/deploy.conf or env vars):
  PI_HOST=$PI_HOST      PI_USER=$PI_USER
  PI_PATH=$PI_PATH
  PI_VENV=\$HOME/obd2-venv
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --duration)
            DURATION_SECONDS="$2"
            shift 2
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

if ! [[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || [ "$DURATION_SECONDS" -lt 1 ]; then
    echo "ERROR: --duration must be a positive integer, got: $DURATION_SECONDS" >&2
    exit 2
fi

################################################################################
# Helpers.
################################################################################

ssh_pi() {
    ssh -p "$PI_PORT" -o BatchMode=yes -o ConnectTimeout=10 \
        "$PI_USER@$PI_HOST" "$@"
}

step_banner() {
    echo ""
    echo "===================================================================="
    echo "$1"
    echo "===================================================================="
}

PASS_COUNT=0
FAIL_COUNT=0

record_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  PASS: $1"
}

record_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: $1" >&2
}

################################################################################
# Dry-run short-circuit: print plan, exit 0.
################################################################################

if [ "$DRY_RUN" = "1" ]; then
    cat <<EOF
DRY RUN -- US-192 HDMI Live Display Verification

Configuration:
  PI_HOST=$PI_HOST  PI_USER=$PI_USER  PI_PORT=$PI_PORT
  PI_PATH=$PI_PATH  PI_VENV=$PI_VENV
  DURATION_SECONDS=$DURATION_SECONDS

Planned steps:
  Step 1  SSH gate: ssh $PI_USER@$PI_HOST hostname
  Step 2  Stop any running eclipse-obd.service on the Pi.
  Step 3  Start 'python src/pi/main.py --simulate' in the background on the Pi.
          It writes realtime_data rows into $PI_PATH/data/obd.db.
  Step 4  After 5s warm-up, launch scripts/render_primary_screen_live.py
          --duration $DURATION_SECONDS --from-db $PI_PATH/data/obd.db
          on the Pi with DISPLAY + XAUTHORITY + SDL_VIDEODRIVER=x11 set.
          CIO eyeballs the OSOYOO for 6 gauges refreshing with non-zero values.
  Step 5  Kill the background main.py, optionally restart the service.

No Pi-side commands will be executed in this dry run.
EOF
    exit 0
fi

################################################################################
# Step 1 -- SSH gate.
################################################################################

step_banner "Step 1 -- SSH gate (ssh $PI_USER@$PI_HOST)"
if ssh_pi "hostname" > /tmp/us192_step1.out 2>&1; then
    record_pass "SSH reachable ($(cat /tmp/us192_step1.out))"
else
    record_fail "SSH unreachable -- check key-based auth for $PI_USER@$PI_HOST"
    echo ""
    echo "SUMMARY: 0 pass / 1 fail (SSH gate)"
    exit 2
fi

################################################################################
# Step 2 -- Stop eclipse-obd.service if running (we start our own main.py).
################################################################################

step_banner "Step 2 -- Stop eclipse-obd.service on the Pi (if active)"
if ssh_pi "sudo systemctl stop eclipse-obd 2>/dev/null || true" \
        > /tmp/us192_step2.out 2>&1; then
    record_pass "eclipse-obd.service stopped (or already inactive)"
else
    record_fail "systemctl stop failed -- check sudoers + service name"
fi

################################################################################
# Step 3 -- Start main.py --simulate in the background on the Pi.
################################################################################

step_banner "Step 3 -- Start 'python src/pi/main.py --simulate' in background"
# Launch in background; redirect stdout+stderr to a log the CIO can tail.
REMOTE_LOG="/tmp/us192_main.log"
REMOTE_PID="/tmp/us192_main.pid"

if ssh_pi "cd $PI_PATH && nohup $PI_VENV/bin/python src/pi/main.py --simulate \
    > $REMOTE_LOG 2>&1 & echo \$! > $REMOTE_PID"; then
    record_pass "main.py --simulate launched"
else
    record_fail "main.py launch failed -- see $REMOTE_LOG on Pi"
    exit 1
fi

# Warm up: give orchestrator + simulator time to write the first realtime
# rows.  Session 22 showed ~0.6s to runLoop entry; 5s is a safety margin.
echo "  waiting 5s for first realtime_data rows..."
sleep 5

# Sanity check: did realtime_data gain at least one row?
if ssh_pi "sqlite3 $PI_PATH/data/obd.db 'SELECT COUNT(*) FROM realtime_data' \
        2>/dev/null" > /tmp/us192_row_count.out 2>&1; then
    ROW_COUNT=$(cat /tmp/us192_row_count.out | tr -d '[:space:]')
    if [ -n "$ROW_COUNT" ] && [ "$ROW_COUNT" -gt 0 ] 2>/dev/null; then
        record_pass "realtime_data has $ROW_COUNT rows after warm-up"
    else
        record_fail "realtime_data is empty after 5s -- main.py may have crashed"
    fi
else
    record_fail "Could not query realtime_data row count"
fi

################################################################################
# Step 4 -- Run the live render harness in --from-db mode.
#           CIO eyeball verification.
################################################################################

step_banner "Step 4 -- Live render for ${DURATION_SECONDS}s (CIO: eyeball the HDMI!)"
cat <<EOF
  CIO checklist (while the render runs):
    [ ] All 6 gauges visible: RPM, Coolant, Boost, AFR, Speed, Volts
    [ ] Values are NOT '---' placeholders
    [ ] Values change over the window (RPM, SPEED at minimum)
    [ ] No flicker, no black screen, no GL errors in log

EOF

# DISPLAY / XAUTHORITY / SDL_VIDEODRIVER must already be set in the
# interactive SSH session (installed by eclipse-obd.service Environment=
# block, honored by the user's login shell too).  We force them here
# defensively for the ssh_pi invocation so the harness runs under X11
# regardless of PAM environment.
RENDER_CMD="DISPLAY=:0 XAUTHORITY=\$HOME/.Xauthority SDL_VIDEODRIVER=x11 \
    $PI_VENV/bin/python scripts/render_primary_screen_live.py \
    --duration $DURATION_SECONDS --from-db $PI_PATH/data/obd.db"

if ssh_pi "cd $PI_PATH && $RENDER_CMD"; then
    record_pass "render harness exited cleanly after ${DURATION_SECONDS}s"
else
    record_fail "render harness failed -- check $REMOTE_LOG + DISPLAY vars"
fi

echo ""
read -p "CIO: did the 6 gauges show live non-zero values? [y/N] " CIO_CONFIRM
if [ "${CIO_CONFIRM:-N}" = "y" ] || [ "${CIO_CONFIRM:-N}" = "Y" ]; then
    record_pass "CIO eyeball confirmation: live HDMI display"
else
    record_fail "CIO eyeball confirmation: NOT confirmed"
fi

################################################################################
# Step 5 -- Cleanup: kill background main.py.
################################################################################

step_banner "Step 5 -- Cleanup (kill background main.py)"
if ssh_pi "if [ -f $REMOTE_PID ]; then kill \$(cat $REMOTE_PID) 2>/dev/null || \
        true; rm -f $REMOTE_PID; fi"; then
    record_pass "background main.py terminated"
else
    record_fail "cleanup failed -- may need manual 'kill $(cat $REMOTE_PID)' on Pi"
fi

################################################################################
# Summary.
################################################################################

echo ""
echo "===================================================================="
echo "SUMMARY: $PASS_COUNT pass / $FAIL_COUNT fail"
echo "===================================================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
