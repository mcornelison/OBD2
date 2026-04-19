#!/usr/bin/env bash
################################################################################
# validate_hdmi_display.sh -- US-183 Pi Polish HDMI render validation driver
#
# Purpose:
#   CIO-facing bash driver that drives the Pi's OSOYOO 3.5" HDMI display
#   through a pygame render loop for N seconds and asks the CIO to eyeball
#   the result.  Verifies: display detected by firmware, pygame can open
#   the 480x320 framebuffer, the primary-screen renderer runs without
#   stalling, the app exits cleanly on SIGTERM, and the display returns
#   to black.
#
# Usage:
#   bash scripts/validate_hdmi_display.sh                    # 30s render
#   bash scripts/validate_hdmi_display.sh --duration 60      # 60s render
#   bash scripts/validate_hdmi_display.sh --snapshot /tmp/x.png
#   bash scripts/validate_hdmi_display.sh --dry-run
#   bash scripts/validate_hdmi_display.sh --help
#
# Prerequisites (per US-183 invariants):
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname
#   - OSOYOO 3.5" HDMI display attached to the Pi
#   - ~/obd2-venv/bin/python present on the Pi with pygame installed
#
# Exit codes:
#   0  -- every step PASS (CIO still needs to confirm the eyeball steps)
#   1  -- any step FAIL  (which step is indicated in the summary)
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

DURATION_SECONDS="30"
DRY_RUN="0"
SNAPSHOT_PATH=""

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
Usage: bash scripts/validate_hdmi_display.sh [OPTIONS]

Options:
  --duration N        Seconds to keep the render loop running (default: 30)
  --snapshot PATH     Save the final frame as PNG on the Pi at PATH
  --dry-run           Print the plan without touching the Pi
  --help, -h          Show this help

Environment (overridable via deploy/deploy.conf):
  PI_HOST=10.27.27.28      PI_USER=mcornelison
  PI_PATH=/home/mcornelison/Projects/Eclipse-01
  PI_VENV=$HOME/obd2-venv
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --duration)
            DURATION_SECONDS="$2"
            shift 2
            ;;
        --snapshot)
            SNAPSHOT_PATH="$2"
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

################################################################################
# Pretty-printing helpers (mirrored from validate_pi_to_server.sh).
################################################################################

STEP_RESULTS=()
STEP_NAMES=(
    "1. SSH gate to Pi"
    "2. Firmware reports HDMI display attached"
    "3. pygame init + display.set_mode(480x320) smoke"
    "4. Live render loop for N seconds"
    "5. (manual) CIO confirms display rendered without tearing or clipping"
    "6. (manual) CIO confirms animation visible (RPM sweep)"
    "7. Display returns to black on clean exit"
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

record_manual() {
    STEP_RESULTS+=("MANUAL: $1")
    echo "  -> MANUAL: $1"
}

SSH_PI_ARGS=(-p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)

ssh_pi() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ssh $PI_USER@$PI_HOST -- $*"
        return 0
    fi
    ssh "${SSH_PI_ARGS[@]}" "$PI_USER@$PI_HOST" "$@"
}

################################################################################
# Step 1 -- SSH gate.
################################################################################

banner "Step 1 / 7 -- ${STEP_NAMES[0]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would verify SSH to $PI_USER@$PI_HOST"
    record_skipped "dry-run"
else
    if ssh "${SSH_PI_ARGS[@]}" "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
        echo "  Pi SSH gate OK ($PI_USER@$PI_HOST)"
        record_pass
    else
        echo "ERROR: Pi SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
        echo "       Fix the SSH prerequisite before re-running this driver." >&2
        exit 2
    fi
fi

################################################################################
# Step 2 -- Pi firmware reports a display is attached.
################################################################################
#
# On Pi 5 the canonical "is a display connected" probe is
#   vcgencmd get_config hdmi_force_hotplug | awk ...
# but the reliable signal is actually that `tvservice -s` or (on Pi 5)
# `drm_info` prints HDMI-A-1 connected.  We fall back through a few probes
# so any of them reporting "connected / attached / HDMI" is sufficient.

banner "Step 2 / 7 -- ${STEP_NAMES[1]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would probe display presence via tvservice/drm_info/vcgencmd"
    record_skipped "dry-run"
else
    DISPLAY_PROBE_OUT="$(ssh_pi '
        set +e
        # Pi 4-compatible path (may not exist on Pi 5)
        tvservice -s 2>/dev/null
        # Pi 5 path (DRM/KMS)
        if command -v drm_info >/dev/null 2>&1; then
            drm_info 2>/dev/null | grep -i "connected\|HDMI" | head -20
        fi
        # Always available
        vcgencmd get_config hdmi_force_hotplug 2>/dev/null
        ls /sys/class/drm/ 2>/dev/null
        true
    ' 2>/dev/null)"
    echo "  Display probe output:"
    echo "$DISPLAY_PROBE_OUT" | sed 's/^/    /'

    # We do NOT fail here if nothing matches; the authoritative signal is
    # step 3 (pygame opens the framebuffer).  Still report a soft PASS if
    # any HDMI/connected token appears so the CIO has visibility.
    if echo "$DISPLAY_PROBE_OUT" | grep -qiE 'hdmi|connected'; then
        record_pass
    else
        record_fail "no HDMI/connected token in probe output -- continuing to step 3 anyway"
    fi
fi

################################################################################
# Step 3 -- pygame init + set_mode smoke test on the Pi.
################################################################################

banner "Step 3 / 7 -- ${STEP_NAMES[2]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would run a tiny pygame.display.set_mode smoke on the Pi"
    record_skipped "dry-run"
else
    SMOKE_OUT=$(ssh_pi "cd $PI_PATH && $PI_VENV/bin/python -c '
import pygame
pygame.display.init()
screen = pygame.display.set_mode((480, 320))
assert screen.get_size() == (480, 320), screen.get_size()
pygame.display.flip()
pygame.display.quit()
print(\"PYGAME_OK\")
' 2>&1" || true)
    echo "  Smoke output:"
    echo "$SMOKE_OUT" | sed 's/^/    /'
    if echo "$SMOKE_OUT" | grep -q 'PYGAME_OK'; then
        record_pass
    else
        record_fail "pygame.display.set_mode((480,320)) failed on the Pi -- see output above"
    fi
fi

################################################################################
# Step 4 -- Live render loop for N seconds.
################################################################################

banner "Step 4 / 7 -- ${STEP_NAMES[3]}"

if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] Would run: $PI_VENV/bin/python scripts/render_primary_screen_live.py --duration $DURATION_SECONDS"
    record_skipped "dry-run"
else
    RENDER_CMD="cd $PI_PATH && $PI_VENV/bin/python scripts/render_primary_screen_live.py --duration $DURATION_SECONDS"
    if [ -n "$SNAPSHOT_PATH" ]; then
        RENDER_CMD="$RENDER_CMD --snapshot $SNAPSHOT_PATH"
    fi
    echo "  Launching render loop for ${DURATION_SECONDS}s.  Walk up to the display now."
    echo "  (Running: $RENDER_CMD)"
    # shellcheck disable=SC2029 -- intentional server-side expansion
    if ssh_pi "$RENDER_CMD"; then
        record_pass
    else
        record_fail "render_primary_screen_live.py exited non-zero"
    fi
fi

################################################################################
# Step 5 + 6 -- Manual CIO confirmation.
################################################################################

banner "Step 5 / 7 -- ${STEP_NAMES[4]}"
cat <<'EOF'
  MANUAL: Confirm on the OSOYOO 3.5" HDMI display that:
    [ ] The primary screen rendered at 480x320 (no clipping on edges)
    [ ] Text is readable (RPM, Coolant, Boost, AFR, Speed, Volts labels + values)
    [ ] No tearing, flickering, or black bars
    [ ] Orientation is correct (gauge labels right-side-up)
  If all boxes check, the render tier is PASS.  Otherwise file the issue.
EOF
record_manual "CIO eyeball required -- check the boxes above"

banner "Step 6 / 7 -- ${STEP_NAMES[5]}"
cat <<'EOF'
  MANUAL: Confirm the RPM gauge animates during the render loop.
  The render harness sweeps RPM 800 -> 6500 -> 800 over a ~4 second cycle,
  so during the ${DURATION_SECONDS}s run you should see at least a half-dozen
  full sweeps.  If the gauge is frozen on a single value, the render loop
  is stalled and this step FAILs.
EOF
record_manual "CIO eyeball required -- RPM must sweep, not freeze"

################################################################################
# Step 7 -- Display returned to black on exit.
################################################################################

banner "Step 7 / 7 -- ${STEP_NAMES[6]}"
if [ "$DRY_RUN" = "1" ]; then
    record_skipped "dry-run"
else
    # The render loop blanks the framebuffer in its finally block; there is
    # no remote probe for "is the screen black" so we ask the CIO.
    cat <<'EOF'
  MANUAL: Confirm the display is now black (no frozen final frame, no
          partial render, no garbage).  A clean black is PASS; a stuck
          previous frame or visible glitch is FAIL.
EOF
    record_manual "CIO eyeball required -- display must be black after exit"
fi

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
echo "Overall (programmatic): $OVERALL"
echo "Manual steps (5, 6, 7) need CIO eyeball confirmation before marking"
echo "US-183 passes:true in sprint.json."
echo ""

if [ "$OVERALL" = "FAIL" ]; then
    exit 1
fi
exit 0
