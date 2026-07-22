#!/usr/bin/env bash
################################################################################
# File Name: verify_pre_drive.sh
# Purpose:   US-479 (F-117) ONE CIO-runnable pre-drive OBD green-light. Composes
#            scripts/verify_bt_pair.sh (BT bond/link + /dev/rfcomm0 bind) with the
#            scripts/pre_drive_greenlight.py capture probe (which exercises the
#            A-17 connect-edge: a KOEO/idle DTC read co-occurring with the realtime
#            logger on ONE connection) and reports, in order:
#              1. BT bond/link to the OBDLink LX present
#              2. /dev/rfcomm0 bound
#              3. KOEO (engine-off) sub-check -- link + one read (driveway signal)
#              4. N seconds live capture -> realtime_data rows + core-PID coverage
#              5. final CAPTURE: PASS/FAIL + reason
#            Plus (US-487) a POST-RESTART production check: after the probe restarts
#            eclipse-obd, confirm the PRODUCTION service is active AND landing NEW
#            realtime_data rows in data/obd.db -- steps 1-4 probe a throwaway temp db,
#            so this is the only step that proves the real collector is alive. A
#            GREEN can never coexist with a dead production service.
#            So a weekend of drives can never again capture zero rows unnoticed.
# Author:    Rex (Ralph agent)
# Created:   2026-07-20 (US-479); hardened 2026-07-22 (US-487).
# Story:     US-479 (F-117 pre-drive green-light); US-487 (production-path verify +
#            non-authoritative exit codes + DoD honesty note).
#
# Modes:
#   live   (default) -- SSH to the Pi; authoritative in-vehicle gate.
#   bench            -- run the probe against SimulatedObdConnection locally.
#                       PASS in bench is NOT a substitute for a live PASS.
#
# Usage:
#   bash scripts/verify_pre_drive.sh                 # full live gate, 30s window
#   bash scripts/verify_pre_drive.sh --duration 60
#   bash scripts/verify_pre_drive.sh --koeo-only     # driveway (engine off)
#   bash scripts/verify_pre_drive.sh --bench         # off-Pi logic check
#   bash scripts/verify_pre_drive.sh --dry-run       # print plan, no SSH
#   bash scripts/verify_pre_drive.sh --help
#
# Exit codes:
#   0 -- CAPTURE: PASS (full authoritative gate -- green-light the drive)
#   1 -- CAPTURE: FAIL (do NOT drive blind -- see the reason)
#   2 -- misuse (bad flag/MAC, SSH gate failed)
#   3 -- NON-AUTHORITATIVE PASS: --bench (simulator) or --koeo-only (skips the
#        sustained-capture floor) succeeded, but this is NOT the drive green-light.
#        A distinct non-green exit so a distracted operator can't mistake it for the
#        real full-mode gate (exit 0). (US-487 FOLLOW-UP 2.)
#
# Honesty note (US-487 FOLLOW-UP 3): this gate does NOT detect the A-17 read/write
# race live. The probe's interleave detector reads a test-fake-only attribute
# (connection.obd.interleaved) that is inert outside pytest. A live green rests on
# (a) the orchestrator's single-connection _ioLock being correct and (b) the
# row-count + core-PID coverage floors -- if the race were to starve capture, no
# rows land and the floor fails. The interleave readout is belt-and-suspenders, not
# the live signal, and is never asserted as live race detection.
################################################################################

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# B-044: source canonical addresses (OBD_BT_MAC + PI_HOST/PI_USER/PI_PORT/PI_PATH).
# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

PI_VENV='$HOME/obd2-venv'

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
DURATION_SECS="30"
MODE="live"
DRY_RUN="0"
KOEO_ONLY="0"
MAC="${OBD_BT_MAC:-}"

# US-487 FOLLOW-UP 2: a distinct non-green exit for non-authoritative passes
# (--bench / --koeo-only) so they are never mistaken for the full-mode green (exit 0).
EXIT_NONAUTH=3

# US-487 FOLLOW-UP 1: post-restart PRODUCTION-capture check timing. Sourced from
# deploy.conf above if the operator overrode PRE_DRIVE_PROD_*; defaults otherwise.
#   settle -- seconds to let eclipse-obd reconnect BT + resume logging after restart
#   growth -- seconds between the two realtime_data row samples that must increase
PROD_SETTLE_SECS="${PRE_DRIVE_PROD_SETTLE_SECS:-15}"
PROD_GROWTH_SECS="${PRE_DRIVE_PROD_GROWTH_SECS:-10}"

usage() {
    cat <<'EOF'
Usage: bash scripts/verify_pre_drive.sh [OPTIONS]

The ONE pre-drive green-light: proves the Pi is BT-linked to the OBDLink LX,
rfcomm-bound, and actually landing realtime_data rows WHILE the A-17 connect-edge
(a KOEO/idle DTC read co-occurring with the realtime logger on the one
connection) is exercised -- so a green can't happen while the race kills capture.

Options:
  --duration N     Live capture window seconds (default 30).
  --koeo-only      Engine-off driveway check only (BT + link + one read); skips
                   the authoritative live-idle window.
  --bench          Run the probe against the simulator locally. NOT a live PASS.
  --dry-run        Print the plan only; no SSH, no writes.
  --mac ADDR       Override the OBDLink MAC (default $OBD_BT_MAC, canonical).
  --help, -h       Show this help.

Exit: 0 CAPTURE PASS / 1 CAPTURE FAIL / 2 misuse
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --duration) DURATION_SECS="$2"; shift 2 ;;
        --koeo-only) KOEO_ONLY="1"; shift ;;
        --bench) MODE="bench"; shift ;;
        --dry-run) DRY_RUN="1"; shift ;;
        --mac) MAC="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown argument: $1" >&2; usage >&2; exit 2 ;;
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

OVERALL_OK=true
report() {
    local label="$1" ok="$2" detail="${3:-}" mark
    case "$ok" in
        yes)  mark='[ OK ]' ;;
        no)   mark='[FAIL]'; OVERALL_OK=false ;;
        info) mark='[INFO]' ;;
        *)    mark='[ ?? ]' ;;
    esac
    if [ -n "$detail" ]; then
        printf '%s %s -- %s\n' "$mark" "$label" "$detail"
    else
        printf '%s %s\n' "$mark" "$label"
    fi
}

################################################################################
# Bench mode -- local simulator probe. Clearly non-authoritative.
################################################################################
if [ "$MODE" = "bench" ]; then
    banner "Bench mode (simulator) -- NOT an in-vehicle PASS"
    koeoFlag=""
    [ "$KOEO_ONLY" = "1" ] && koeoFlag="--koeo-only"
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] python3 scripts/pre_drive_greenlight.py --bench --duration $DURATION_SECS $koeoFlag"
        exit 0
    fi
    benchRc=0
    # shellcheck disable=SC2086
    python3 "$REPO_ROOT/scripts/pre_drive_greenlight.py" --bench --duration "$DURATION_SECS" $koeoFlag || benchRc=$?
    if [ "$benchRc" = "0" ]; then
        # US-487 FOLLOW-UP 2: a bench PASS is the simulator, NOT the drive green-light.
        # Return the distinct non-green exit so it can't be mistaken for the real gate.
        echo ""
        echo "CAPTURE: NON-AUTHORITATIVE PASS (--bench) -- simulator only; NOT a drive green-light. Run the live gate (no --bench) before driving."
        exit "$EXIT_NONAUTH"
    fi
    exit "$benchRc"
fi

################################################################################
# Live mode -- SSH to the Pi.
################################################################################
SSH_ARGS=(-p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10)
ssh_pi() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] ssh $PI_USER@$PI_HOST -- $*"
        return 0
    fi
    ssh "${SSH_ARGS[@]}" "$PI_USER@$PI_HOST" "$@"
}

# US-487 FOLLOW-UP 1: the PRODUCTION collector writes realtime_data to data/obd.db
# (config.json database.path default ${DB_PATH:./data/obd.db}); the probe used a
# throwaway temp db, so this is the only path that reflects the real service.
PROD_DB="$PI_PATH/data/obd.db"
# prod_row_count -- echo the production realtime_data row count from data/obd.db on
# the Pi. Non-numeric / empty output means the query failed (missing db or table)
# and the caller treats that as "not capturing" (fail closed, never a false green).
prod_row_count() {
    ssh_pi "$PI_VENV/bin/python -c \"import sqlite3; print(sqlite3.connect('$PROD_DB').execute('SELECT COUNT(*) FROM realtime_data').fetchone()[0])\"" 2>/dev/null
}

if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "ERROR: '$MAC' is not a valid MAC (set OBD_BT_MAC or pass --mac)" >&2
    exit 2
fi

banner "Pre-drive green-light -- host=$PI_HOST mac=$MAC window=${DURATION_SECS}s"

if [ "$DRY_RUN" != "1" ]; then
    if ! ssh "${SSH_ARGS[@]}" "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
        echo "ERROR: SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
        exit 2
    fi
    report "SSH gate" yes "$PI_USER@$PI_HOST reachable"
fi

# ---- Steps 1 + 2: BT bond/link + /dev/rfcomm0 bound (verify_bt_pair.sh on Pi) ---
banner "Steps 1-2 / 5 -- BT bond/link + /dev/rfcomm0 bind"
if ssh_pi "cd $PI_PATH && bash scripts/verify_bt_pair.sh $MAC"; then
    report "BT pair + rfcomm bind" yes "OBDLink LX $MAC"
else
    report "BT pair + rfcomm bind" no "verify_bt_pair.sh reported a failure (see above)"
fi

# Stop the collector service so the probe owns /dev/rfcomm0 alone; restart after.
ssh_pi "sudo systemctl stop eclipse-obd.service 2>/dev/null || true"

# ---- Step 3: KOEO (engine-off) sub-check -- earliest driveway signal ----
banner "Step 3 / 5 -- KOEO (engine-off) sub-check: link + one read"
KOEO_CMD="cd $PI_PATH && $PI_VENV/bin/python scripts/pre_drive_greenlight.py --live --koeo-only"
if ssh_pi "$KOEO_CMD"; then
    report "KOEO link + one read" yes "earliest signal green (driveway OK)"
else
    report "KOEO link + one read" no "link or first read failed -- do not drive"
fi

# ---- Step 4: authoritative live-idle capture window (skipped for --koeo-only) ----
CAPTURE_RC=0
PROD_RC=0  # US-487: production-path capture result (0 until proven dead)
if [ "$KOEO_ONLY" = "1" ]; then
    banner "Step 4 / 5 -- live-idle window SKIPPED (--koeo-only)"
    report "Live-idle capture" info "skipped -- KOEO is a driveway pre-check, not the gate"
else
    banner "Step 4 / 5 -- ${DURATION_SECS}s live capture (connect-edge exercised)"
    LIVE_CMD="cd $PI_PATH && $PI_VENV/bin/python scripts/pre_drive_greenlight.py --live --duration $DURATION_SECS"
    if ssh_pi "$LIVE_CMD"; then
        report "Live capture window" yes "realtime_data rows landing + connect-edge exercised"
    else
        CAPTURE_RC=1
        report "Live capture window" no "CAPTURE FAIL (see the probe's reason above)"
    fi
fi

# Restart the collector so the Pi returns to normal ops.
ssh_pi "sudo systemctl start eclipse-obd.service 2>/dev/null || true"

# ---- Post-restart: PRODUCTION capture verification (US-487 FOLLOW-UP 1) ----
# Steps 1-4 probe a THROWAWAY temp db -- a green there says nothing about the real
# service. The probe stops eclipse-obd, and the restart above is best-effort
# (|| true) with no check. Prove the PRODUCTION path is actually capturing after the
# restart: the unit is active AND new rows land in data/obd.db -- so a GREEN can
# never coexist with a dead production collector. Full-mode only: KOEO is engine-off
# (production cannot capture) and bench never reaches this live path.
if [ "$KOEO_ONLY" != "1" ] && [ "$DRY_RUN" != "1" ]; then
    banner "Post-restart -- PRODUCTION eclipse-obd capturing? (data/obd.db)"
    if ssh_pi "systemctl is-active --quiet eclipse-obd.service"; then
        report "eclipse-obd active" yes "unit running after restart"
    else
        PROD_RC=1
        report "eclipse-obd active" no "unit NOT active after restart -- production path down"
    fi
    echo "  (settling ${PROD_SETTLE_SECS}s for reconnect, then sampling ${PROD_GROWTH_SECS}s of capture...)"
    sleep "$PROD_SETTLE_SECS"
    prodBefore="$(prod_row_count || true)"
    sleep "$PROD_GROWTH_SECS"
    prodAfter="$(prod_row_count || true)"
    if [[ "$prodBefore" =~ ^[0-9]+$ ]] && [[ "$prodAfter" =~ ^[0-9]+$ ]] && [ "$prodAfter" -gt "$prodBefore" ]; then
        report "production capture" yes "realtime_data grew ${prodBefore} -> ${prodAfter} rows in data/obd.db"
    else
        PROD_RC=1
        report "production capture" no "realtime_data did not grow (${prodBefore:-?} -> ${prodAfter:-?}) -- eclipse-obd not landing rows in data/obd.db"
    fi
fi

# ---- Step 5: final verdict ----
banner "Step 5 / 5 -- verdict"
if [ "$DRY_RUN" = "1" ]; then
    echo "Dry run complete -- no checks evaluated."
    exit 0
fi

if $OVERALL_OK && [ "$CAPTURE_RC" = "0" ] && [ "$PROD_RC" = "0" ]; then
    if [ "$KOEO_ONLY" = "1" ]; then
        # US-487 FOLLOW-UP 2: KOEO skips the sustained-capture floor -> non-authoritative.
        echo "CAPTURE: NON-AUTHORITATIVE PASS (--koeo-only) -- KOEO driveway pre-check green, but the sustained-capture floor was skipped. This is NOT the drive green-light: run the full gate (no --koeo-only) at warm idle before driving."
        exit "$EXIT_NONAUTH"
    fi
    echo "CAPTURE: PASS -- green-light the drive."
    exit 0
fi
echo "CAPTURE: FAIL -- do NOT drive blind. Fix the failing step(s) above and re-run."
exit 1
