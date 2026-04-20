#!/usr/bin/env bash
################################################################################
# File Name: pair_obdlink.sh
# Purpose:   One-time pexpect-driven pair of an OBDLink LX (SSP passkey auto-yes)
# Author:    Ralph Agent (Rex)
# Created:   2026-04-19
# Story:     US-196 — lift + generalise from Pi ~/Projects/Eclipse-01/scripts/
#
# Why this script exists
# ----------------------
# The OBDLink LX Bluetooth adapter uses Secure Simple Pairing (SSP) with
# passkey confirmation, not the legacy "PIN 1234" flow. bluez's default
# NoInputNoOutput agent handles most SSP "Just Works" devices, but the LX
# firmware sends an actual numeric passkey and bluez prompts:
#
#     Confirm passkey N (yes/no):
#
# bt-agent, the stock non-interactive agent, does not intercept this —
# bt-device's internal agent grabs the callback first and asks to its own
# stdin. So non-interactive pairing needs pexpect to drive bluetoothctl
# directly, spot the "Confirm passkey" prompt, and send "yes".
#
# Usage
# -----
#   scripts/pair_obdlink.sh <MAC>              # do the pair
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
MAC=""

# ------------------------------------------------------------------------------
# Usage / help
# ------------------------------------------------------------------------------
show_help() {
    cat <<'EOF'
pair_obdlink.sh — one-time pair of an OBDLink LX via bluetoothctl + pexpect.

USAGE
    scripts/pair_obdlink.sh <MAC> [--dry-run]
    scripts/pair_obdlink.sh --dry-run <MAC>
    scripts/pair_obdlink.sh --help

ARGUMENTS
    MAC            Bluetooth MAC of the dongle (AA:BB:CC:DD:EE:FF).
                   Falls back to $OBD_BT_MAC if no positional arg.

OPTIONS
    --dry-run      Print what would be done; do not touch the BT stack.
    --help, -h     Show this help and exit.

EXAMPLES
    scripts/pair_obdlink.sh AA:BB:CC:DD:EE:FF
    OBD_BT_MAC=AA:BB:CC:DD:EE:FF scripts/pair_obdlink.sh
    scripts/pair_obdlink.sh --dry-run AA:BB:CC:DD:EE:FF

EXIT CODES
    0   pair succeeded (or dry-run previewed successfully)
    1   pair attempt failed — dongle may not be in pair mode
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
DRY-RUN: would pair MAC ${MAC} via bluetoothctl+pexpect.
    1. scan on
    2. agent NoInputNoOutput; default-agent
    3. pair ${MAC}       (auto-'yes' to SSP passkey prompt)
    4. trust ${MAC}      (survives reboot, allows auto-reconnect)
    5. scan off
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
# The pexpect driver — embedded Python that understands the SSP prompt
# ------------------------------------------------------------------------------
# MAC is exported so the python block can read it without string-interpolation
# risks (a MAC can't contain anything exotic, but keeping interpolation out of
# the embedded script makes it easier to audit and keeps this shellcheck-clean).
export MAC

"$PYTHON_BIN" - <<'PYEOF'
"""Embedded pexpect driver — spawns bluetoothctl and auto-confirms SSP passkey."""
import os
import sys
import time

try:
    import pexpect  # type: ignore[import-not-found]
except ImportError:
    sys.stderr.write("pexpect missing — see pair_obdlink.sh pre-flight message\n")
    sys.exit(1)

mac = os.environ["MAC"]
timeoutSeconds = int(os.environ.get("PAIR_TIMEOUT_S", "60"))

# pexpect.spawn does not invoke a shell; bluetoothctl itself is the REPL.
child = pexpect.spawn("bluetoothctl", encoding="utf-8", timeout=timeoutSeconds)
child.logfile_read = sys.stdout  # stream bluetoothctl output live for operator visibility

def send(line: str) -> None:
    child.sendline(line)
    # Wait for the prompt to return before the next command.
    child.expect(r"\[.+\]#", timeout=10)

try:
    # Wait for first prompt.
    child.expect(r"\[.+\]#", timeout=10)

    send("agent NoInputNoOutput")
    send("default-agent")
    send("scan on")

    # Give the dongle a moment to appear in the scan results. LX needs to be
    # in pair mode (solid blue LED). If the scan never finds it, the `pair`
    # command below will time out — we surface that clearly.
    time.sleep(5)

    child.sendline(f"pair {mac}")

    # The SSP passkey prompt is the critical dance. Possible endings:
    #   - "Confirm passkey NNNNNN (yes/no):"          -> send 'yes'
    #   - "Pairing successful"                         -> done
    #   - "Failed to pair: org.bluez.Error.*"          -> fatal
    #   - timeout                                      -> fatal (probably not in pair mode)
    while True:
        index = child.expect(
            [
                r"Confirm passkey \d+ \(yes/no\):",
                r"Pairing successful",
                r"Failed to pair[^\r\n]*",
                pexpect.TIMEOUT,
                pexpect.EOF,
            ],
            timeout=timeoutSeconds,
        )
        if index == 0:
            child.sendline("yes")
            continue
        if index == 1:
            break
        if index == 2:
            raise SystemExit(f"pair failed: {child.after!s}")
        if index == 3:
            raise SystemExit(
                "pair timed out — is the LX in pair mode (solid blue LED)?"
            )
        if index == 4:
            raise SystemExit("bluetoothctl exited before pair completed")

    # Back to the prompt now that pairing finished.
    child.expect(r"\[.+\]#", timeout=10)

    send(f"trust {mac}")   # auto-reconnect on future sessions
    send("scan off")
    send("quit")
    child.expect(pexpect.EOF, timeout=5)

    sys.stdout.write(f"\n--- pair + trust successful for {mac} ---\n")
except SystemExit as exc:
    sys.stderr.write(f"\n{exc}\n")
    child.close(force=True)
    sys.exit(1)
PYEOF

echo ""
echo "--- post-pair check: run scripts/verify_bt_pair.sh to confirm ---"
