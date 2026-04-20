#!/usr/bin/env bash
################################################################################
# File Name: connect_obdlink.sh
# Purpose:   Idempotently bind the paired OBDLink LX dongle to /dev/rfcommN.
# Author:    Ralph Agent (Rex)
# Created:   2026-04-19
# Story:     US-193 / TD-023 — lift from Pi ~/Projects/Eclipse-01/scripts/
#
# This script is a thin operational companion to src/pi/obdii/bluetooth_helper.py.
# The Python helper is the production path (called inside ObdConnection.connect);
# this shell script is for:
#   - manual smoke-testing on the Pi without starting the orchestrator
#   - systemd / boot-time rfcomm binding when the orchestrator does not own
#     the device lifecycle (see specs/architecture.md Bluetooth section).
#
# Requires sudoers NOPASSWD for /usr/sbin/rfcomm if this script is run by a
# non-root user. See specs/architecture.md for the recommended sudoers entry.
#
# Usage:
#   connect_obdlink.sh <MAC>              # bind rfcomm0 to MAC on channel 1
#   connect_obdlink.sh <MAC> <DEVICE> <CHANNEL>
#   connect_obdlink.sh --release          # release rfcomm0
#   connect_obdlink.sh --release <DEVICE>
################################################################################

set -euo pipefail

MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'

usage() {
    cat <<'EOF'
Usage:
  connect_obdlink.sh <MAC> [DEVICE] [CHANNEL]
  connect_obdlink.sh --release [DEVICE]

Defaults: DEVICE=0, CHANNEL=1 (SPP on OBDLink LX).
EOF
}

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 2
fi

if [[ "$1" == "--release" ]]; then
    DEVICE="${2:-0}"
    if rfcomm show "$DEVICE" >/dev/null 2>&1; then
        sudo rfcomm release "$DEVICE"
        echo "released /dev/rfcomm${DEVICE}"
    else
        echo "/dev/rfcomm${DEVICE} not bound — nothing to do"
    fi
    exit 0
fi

MAC="$1"
DEVICE="${2:-0}"
CHANNEL="${3:-1}"

if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "error: '$MAC' is not a valid Bluetooth MAC (expected AA:BB:CC:DD:EE:FF)" >&2
    exit 2
fi

# Idempotent: if already bound to the same MAC, no-op.
if rfcomm show "$DEVICE" 2>/dev/null | grep -qi "$MAC"; then
    echo "/dev/rfcomm${DEVICE} already bound to ${MAC}"
    exit 0
fi

# If bound to something else, release first (lets operators re-target the device).
if rfcomm show "$DEVICE" >/dev/null 2>&1; then
    echo "/dev/rfcomm${DEVICE} bound to a different MAC — releasing"
    sudo rfcomm release "$DEVICE"
fi

sudo rfcomm bind "$DEVICE" "$MAC" "$CHANNEL"
echo "bound /dev/rfcomm${DEVICE} -> ${MAC} channel ${CHANNEL}"
