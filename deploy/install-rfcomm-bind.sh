#!/usr/bin/env bash
################################################################################
# File Name: install-rfcomm-bind.sh
# Purpose:   Install + enable rfcomm-bind.service (reboot-survival for rfcomm)
# Author:    Ralph Agent (Rex)
# Created:   2026-04-19 — US-196
#
# Runs ON the Pi as an operator. Idempotent: safe to re-run.
#
# Usage:
#   sudo bash deploy/install-rfcomm-bind.sh <MAC>
#   sudo bash deploy/install-rfcomm-bind.sh           # uses $OBD_BT_MAC
#   sudo bash deploy/install-rfcomm-bind.sh --uninstall
################################################################################

set -euo pipefail

MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
SERVICE_NAME="rfcomm-bind.service"
ENV_FILE="/etc/default/obdlink"
UNIT_DIR="/etc/systemd/system"
UNIT_SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="${UNIT_SRC_DIR}/${SERVICE_NAME}"

UNINSTALL=false
MAC=""

for arg in "$@"; do
    case "$arg" in
        --uninstall) UNINSTALL=true ;;
        --help|-h)
            grep -E '^#( |$)' "$0" | head -20 | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            if [[ -n "$MAC" ]]; then
                echo "error: multiple MAC arguments supplied" >&2
                exit 2
            fi
            MAC="$arg"
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "error: must run as root (rfcomm + systemctl need privilege)" >&2
    echo "  try: sudo bash deploy/install-rfcomm-bind.sh $*" >&2
    exit 1
fi

if $UNINSTALL; then
    echo "--- uninstalling ${SERVICE_NAME} ---"
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "${UNIT_DIR}/${SERVICE_NAME}"
    systemctl daemon-reload
    echo "${SERVICE_NAME} uninstalled. ${ENV_FILE} left in place (remove manually if desired)."
    exit 0
fi

if [[ -z "$MAC" ]]; then
    MAC="${OBD_BT_MAC:-}"
fi
if [[ -z "$MAC" ]]; then
    # Fall back to whatever is already in the env file — useful for re-runs.
    if [[ -r "$ENV_FILE" ]]; then
        # shellcheck disable=SC1090
        . "$ENV_FILE"
        MAC="${OBD_BT_MAC:-}"
    fi
fi
if [[ -z "$MAC" ]]; then
    echo "error: MAC required (argv, \$OBD_BT_MAC, or pre-existing ${ENV_FILE})" >&2
    exit 2
fi
if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "error: '$MAC' is not a valid Bluetooth MAC" >&2
    exit 2
fi

if [[ ! -f "$UNIT_SRC" ]]; then
    echo "error: systemd unit source not found at ${UNIT_SRC}" >&2
    echo "  did you rsync deploy/ to the Pi?" >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# 1. Write /etc/default/obdlink — sourced by the unit at start time
# ------------------------------------------------------------------------------
echo "--- writing ${ENV_FILE} ---"
umask 0022
cat > "$ENV_FILE" <<EOF
# Managed by deploy/install-rfcomm-bind.sh — edit MAC here then restart the unit:
#   sudo systemctl restart ${SERVICE_NAME}
OBD_BT_MAC=${MAC}
OBD_BT_CHANNEL=1
EOF
chmod 0644 "$ENV_FILE"

# ------------------------------------------------------------------------------
# 2. Install the unit file
# ------------------------------------------------------------------------------
echo "--- installing ${SERVICE_NAME} to ${UNIT_DIR} ---"
install -m 0644 "$UNIT_SRC" "${UNIT_DIR}/${SERVICE_NAME}"

# ------------------------------------------------------------------------------
# 3. Reload + enable
# ------------------------------------------------------------------------------
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
echo "--- starting ${SERVICE_NAME} now (simulates post-reboot bind) ---"
systemctl restart "$SERVICE_NAME" || {
    echo "warn: initial start failed; check: journalctl -u ${SERVICE_NAME} -n 20" >&2
    exit 1
}

# ------------------------------------------------------------------------------
# 4. Report
# ------------------------------------------------------------------------------
echo ""
echo "=== rfcomm-bind install OK ==="
echo "  enabled: $(systemctl is-enabled "$SERVICE_NAME")"
echo "  active:  $(systemctl is-active "$SERVICE_NAME")"
rfcomm show 0 2>/dev/null || echo "  rfcomm show 0: (not bound yet — check 'journalctl -u ${SERVICE_NAME}')"
