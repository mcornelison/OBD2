#!/usr/bin/env bash
################################################################################
# File Name: pair_obdlink.sh
# Purpose:   One-time pexpect-driven pair of an OBDLink LX (SSP passkey auto-yes)
# Author:    Ralph Agent (Rex)
# Created:   2026-04-19
# Story:     US-196 — lift + generalise from Pi ~/Projects/Eclipse-01/scripts/
#
# Modification History
# --------------------
#   2026-07-31 | Rex | HOTFIX (Atlas CIO-directed P0, BL-025 half 2; supersedes
#              |     | shelved US-475). The embedded pexpect driver could not
#              |     | pair AT ALL: it waited for the legacy `[bluetooth]#`
#              |     | prompt while the Pi's bluez 5.82 prints `[bluetoothctl]>`,
#              |     | so it timed out on the FIRST command; and it registered
#              |     | `agent NoInputNoOutput`, under which the Confirm-passkey
#              |     | branch below it is dead code and SSP can auth-fail.
#              |     | The driver moved OUT of the heredoc into
#              |     | scripts/pair_obdlink_driver.py so it is importable and
#              |     | unit-testable (tests/pi/obdii/test_pair_obdlink_driver.py
#              |     | drives it against a transcript captured live from the Pi).
#
# Why this script exists
# ----------------------
# The OBDLink LX Bluetooth adapter uses Secure Simple Pairing (SSP) with
# passkey confirmation, not the legacy "PIN 1234" flow. The LX firmware sends
# an actual numeric passkey and bluez prompts:
#
#     Confirm passkey N (yes/no):
#
# That prompt only fires under a DISPLAY-CAPABLE agent (DisplayYesNo /
# KeyboardDisplay) — which is why the CIO's phone pairs and this script did
# not. bt-agent, the stock non-interactive agent, does not intercept it either:
# bt-device's internal agent grabs the callback first and asks to its own
# stdin. So non-interactive pairing needs pexpect to drive bluetoothctl
# directly, spot the "Confirm passkey" prompt, and send "yes".
#
# Usage
# -----
#   scripts/pair_obdlink.sh <MAC>              # do the pair
#   scripts/pair_obdlink.sh <MAC> --force      # re-pair even if already bonded
#   scripts/pair_obdlink.sh <MAC> --dry-run    # preview; does not touch BT stack
#   scripts/pair_obdlink.sh --dry-run <MAC>    # flag order interchangeable
#   scripts/pair_obdlink.sh --help             # this text
#
# MAC may also come from $OBD_BT_MAC if no positional arg is given.
#
# Invariants
# ----------
#   - MAC is never hardcoded (B-044) — sourced from argv or environment.
#   - --dry-run must not invoke bluetoothctl or any external BT stack.
#   - sudo inside the bash script only; Python (pexpect) must not call sudo.
#   - Requires pexpect on PATH (pip install pexpect OR apt install python3-pexpect).
#   - Without --force the script is IDEMPOTENT: an existing durable bond is
#     reported and left alone. Re-pairing needs the dongle powered (engine on),
#     so blindly removing a working bond can strand the car.
#   - Success is claimed only after re-reading `bluetoothctl info` and seeing
#     Paired+Bonded+Trusted. "Pairing successful" alone describes the LINK, not
#     a bond that survives a reboot — which is the actual deliverable.
#
# Operator UX notes
# -----------------
#   - OBDLink LX drops out of pair mode ~30s after each failed attempt.
#     Solid blue LED = discoverable. Hold the LX button or power-cycle to
#     re-trigger. Keep within 1-2m of the Pi during pairing.
#   - Once paired/bonded/trusted, the bond is persistent across reboots —
#     re-running this script is unnecessary unless bluez bonds are wiped.
#
# See also
# --------
#   specs/architecture.md §3.4 Bluetooth Connection Resolution
#   docs/testing.md "OBDLink LX re-pair walkthrough"
#   scripts/connect_obdlink.sh (daily-use rfcomm bind; pairs with this)
#   scripts/verify_bt_pair.sh (status snapshot — CIO-runnable)
################################################################################

set -euo pipefail

# ------------------------------------------------------------------------------
# Defaults + regex
# ------------------------------------------------------------------------------
MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
DRY_RUN=false
FORCE=false
MAC=""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVER="${SCRIPT_DIR}/pair_obdlink_driver.py"

# ------------------------------------------------------------------------------
# Usage / help
# ------------------------------------------------------------------------------
show_help() {
    cat <<'EOF'
pair_obdlink.sh — one-time pair of an OBDLink LX via bluetoothctl + pexpect.

USAGE
    scripts/pair_obdlink.sh <MAC> [--force] [--dry-run]
    scripts/pair_obdlink.sh --dry-run <MAC>
    scripts/pair_obdlink.sh --help

ARGUMENTS
    MAC            Bluetooth MAC of the dongle (AA:BB:CC:DD:EE:FF).
                   Falls back to $OBD_BT_MAC if no positional arg.

OPTIONS
    --force        Re-pair even when a durable bond already exists (clears the
                   existing bond first). Without it, an already-bonded dongle
                   is reported and left untouched.
    --dry-run      Print what would be done; do not touch the BT stack.
    --help, -h     Show this help and exit.

ENVIRONMENT
    OBD_BT_MAC     Fallback MAC when no positional arg is given.
    PAIR_TIMEOUT_S Seconds to wait for the pair handshake (default 60).
    PAIR_SCAN_S    Seconds of discovery before pairing (default 7).

EXAMPLES
    scripts/pair_obdlink.sh AA:BB:CC:DD:EE:FF
    OBD_BT_MAC=AA:BB:CC:DD:EE:FF scripts/pair_obdlink.sh
    scripts/pair_obdlink.sh --dry-run AA:BB:CC:DD:EE:FF

EXIT CODES
    0   pair succeeded, or the dongle was already bonded, or dry-run previewed
    1   pair attempt failed — dongle may not be powered / in pair mode, or the
        resulting bond was not durable (Paired+Bonded+Trusted)
    2   usage error (missing/invalid MAC, unknown flag)

See specs/architecture.md §3.4 and docs/testing.md for the full walkthrough.
EOF
}

# ------------------------------------------------------------------------------
# Arg parse — flags in any order, one positional MAC
# ------------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            show_help
            exit 0
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        --force)
            FORCE=true
            ;;
        --*)
            echo "error: unknown flag '$arg'" >&2
            echo "run 'scripts/pair_obdlink.sh --help' for usage" >&2
            exit 2
            ;;
        *)
            if [[ -n "$MAC" ]]; then
                echo "error: multiple MAC arguments supplied ('$MAC' and '$arg')" >&2
                exit 2
            fi
            MAC="$arg"
            ;;
    esac
done

# Fallback to environment
if [[ -z "$MAC" ]]; then
    MAC="${OBD_BT_MAC:-}"
fi

if [[ -z "$MAC" ]]; then
    echo "error: MAC address required (argv or \$OBD_BT_MAC)" >&2
    show_help >&2
    exit 2
fi

if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "error: '$MAC' is not a valid Bluetooth MAC (expected AA:BB:CC:DD:EE:FF)" >&2
    exit 2
fi

# ------------------------------------------------------------------------------
# Dry-run short-circuit — MUST NOT invoke bluetoothctl
# ------------------------------------------------------------------------------
if $DRY_RUN; then
    cat <<EOF
DRY-RUN: would pair MAC ${MAC} via ${DRIVER} (bluetoothctl+pexpect).
    1. info ${MAC}       (already bonded? -> stop, unless --force)
    2. remove ${MAC}     (only if a stale/partial bond exists, or --force)
    3. power on; agent DisplayYesNo; default-agent
    4. scan on -> wait ${PAIR_SCAN_S:-7}s -> scan off
    5. pair ${MAC}       (auto-'yes' to the SSP passkey prompt)
    6. trust ${MAC}      (survives reboot, allows auto-reconnect)
    7. info ${MAC}       (VERIFY Paired+Bonded+Trusted, else fail)
    force re-pair: ${FORCE}
No BT stack commands were invoked.
EOF
    exit 0
fi

# ------------------------------------------------------------------------------
# Pre-flight: ensure bluetoothctl + pexpect are available
# ------------------------------------------------------------------------------
if ! command -v bluetoothctl >/dev/null 2>&1; then
    echo "error: bluetoothctl not found; install bluez (apt install bluez bluez-tools)" >&2
    exit 1
fi

if [[ ! -f "$DRIVER" ]]; then
    echo "error: pairing driver not found at ${DRIVER}" >&2
    echo "  (it lives beside this script — a partial deploy/copy will do this)" >&2
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! "$PYTHON_BIN" -c "import pexpect" >/dev/null 2>&1; then
    echo "error: python3 pexpect module not available" >&2
    echo "  install:  sudo apt install python3-pexpect" >&2
    echo "       or:  ${PYTHON_BIN} -m pip install pexpect" >&2
    exit 1
fi

# Ensure the BT radio is powered. `sudo` lives in the shell; Python does not
# inherit privilege beyond what the runtime needs to talk to bluetoothctl.
if ! bluetoothctl --timeout 3 show 2>/dev/null | grep -q "Powered: yes"; then
    echo "--- bluetooth radio not powered; attempting 'bluetoothctl power on' ---"
    bluetoothctl power on >/dev/null || {
        echo "error: could not power on the BT radio — check 'systemctl status bluetooth'" >&2
        exit 1
    }
fi

echo "--- pairing OBDLink LX at ${MAC} (SSP passkey auto-confirm) ---"

# ------------------------------------------------------------------------------
# Hand off to the pairing driver
# ------------------------------------------------------------------------------
# The driver used to be an embedded `python3 - <<PYEOF` heredoc. Heredoc code
# cannot be imported, so it could not be tested — and it shipped broken for
# months (wrong prompt regex + a non-display agent, see the modification
# history above). It now lives in pair_obdlink_driver.py, covered by
# tests/pi/obdii/test_pair_obdlink_driver.py against a real captured
# bluetoothctl transcript.
#
# MAC is exported rather than interpolated: it keeps operator input out of the
# command line the driver is invoked with, and keeps this shellcheck-clean.
export MAC

DRIVER_ARGS=()
if $FORCE; then
    DRIVER_ARGS+=(--force)
fi

"$PYTHON_BIN" "$DRIVER" "${DRIVER_ARGS[@]+"${DRIVER_ARGS[@]}"}"

echo ""
echo "--- post-pair check: run scripts/verify_bt_pair.sh to confirm ---"
