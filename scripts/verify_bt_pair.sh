#!/usr/bin/env bash
################################################################################
# File Name: verify_bt_pair.sh
# Purpose:   CIO-runnable status snapshot — pair state, rfcomm bind, reboot-survive
# Author:    Ralph Agent (Rex)
# Created:   2026-04-19
# Story:     US-196 — one-shot BT verification after pair/bind/reboot-survive setup
#
# Reports, at a glance:
#   - Is MAC paired? (bluetoothctl info)
#   - Is MAC trusted? (persistence across reboot)
#   - Is /dev/rfcomm0 currently bound? (rfcomm show)
#   - Is rfcomm-bind.service enabled? (systemctl is-enabled)
#   - Last python-obd smoke — PASS / FAIL / UNKNOWN (based on whether obd.OBD
#     opened the rfcomm device without raising; UNKNOWN if no attempt made).
#
# Usage:
#   scripts/verify_bt_pair.sh <MAC>
#   scripts/verify_bt_pair.sh                # uses $OBD_BT_MAC
#   scripts/verify_bt_pair.sh --help
#   scripts/verify_bt_pair.sh --smoke        # also run a python-obd handshake
################################################################################

set -uo pipefail

MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
MAC=""
RUN_SMOKE=false

show_help() {
    cat <<'EOF'
verify_bt_pair.sh — one-shot status snapshot for OBDLink LX pair + rfcomm bind.

USAGE
    scripts/verify_bt_pair.sh <MAC>
    scripts/verify_bt_pair.sh --smoke <MAC>
    scripts/verify_bt_pair.sh --help

ARGUMENTS
    MAC            Bluetooth MAC; falls back to $OBD_BT_MAC if omitted.

OPTIONS
    --smoke        Additionally run a python-obd handshake against /dev/rfcomm0.
                   Expect the dongle to be powered + in range.
    --help, -h     Show this help and exit.

EXIT CODES
    0   all reported checks are green (or informational-only)
    1   one or more checks failed — see output for details
    2   usage error (missing/invalid MAC, unknown flag)
EOF
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            show_help
            exit 0
            ;;
        --smoke)
            RUN_SMOKE=true
            ;;
        --*)
            echo "error: unknown flag '$arg'" >&2
            exit 2
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

if [[ -z "$MAC" ]]; then
    MAC="${OBD_BT_MAC:-}"
fi

if [[ -z "$MAC" ]]; then
    echo "error: MAC address required (argv or \$OBD_BT_MAC)" >&2
    exit 2
fi

if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "error: '$MAC' is not a valid MAC (AA:BB:CC:DD:EE:FF)" >&2
    exit 2
fi

# ------------------------------------------------------------------------------
# Report helper: prints "LABEL: STATUS" and tracks overall pass/fail
# ------------------------------------------------------------------------------
OVERALL_OK=true

report() {
    local label="$1"
    local ok="$2"       # yes | no | info
    local detail="${3:-}"
    local mark
    case "$ok" in
        yes)  mark='[ OK ]' ;;
        no)   mark='[FAIL]'; OVERALL_OK=false ;;
        info) mark='[INFO]' ;;
        *)    mark='[ ?? ]' ;;
    esac
    if [[ -n "$detail" ]]; then
        printf '%s %s — %s\n' "$mark" "$label" "$detail"
    else
        printf '%s %s\n' "$mark" "$label"
    fi
}

echo "=== BT pair + rfcomm verification for ${MAC} ==="
echo ""

# ------------------------------------------------------------------------------
# 1. bluetoothctl info — paired? trusted? bonded?
# ------------------------------------------------------------------------------
if ! command -v bluetoothctl >/dev/null 2>&1; then
    report "bluetoothctl present" no "install bluez (apt install bluez bluez-tools)"
else
    info_out=$(bluetoothctl --timeout 3 info "$MAC" 2>/dev/null || true)
    if [[ -z "$info_out" ]]; then
        report "bluetoothctl info" no "no bond on record for ${MAC}"
    else
        if grep -q "Paired: yes" <<<"$info_out"; then
            report "Paired" yes
        else
            report "Paired" no
        fi
        if grep -q "Trusted: yes" <<<"$info_out"; then
            report "Trusted (reboot-survive)" yes
        else
            report "Trusted (reboot-survive)" no "run: bluetoothctl trust ${MAC}"
        fi
        if grep -q "Bonded: yes" <<<"$info_out"; then
            report "Bonded" yes
        else
            report "Bonded" info "bonded flag not yet set — some BT stacks only set Bonded on first connection"
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 2. rfcomm bind — is /dev/rfcomm0 pointing at our MAC?
# ------------------------------------------------------------------------------
if ! command -v rfcomm >/dev/null 2>&1; then
    report "rfcomm present" no "install bluez-tools"
else
    show_out=$(rfcomm show 0 2>/dev/null || true)
    if [[ -z "$show_out" ]]; then
        report "/dev/rfcomm0 bound" no "run: scripts/connect_obdlink.sh ${MAC}"
    elif grep -qi "$MAC" <<<"$show_out"; then
        report "/dev/rfcomm0 bound" yes "points at ${MAC}"
    else
        bound_mac=$(awk '{print $2}' <<<"$show_out" | head -1)
        report "/dev/rfcomm0 bound" no "bound to ${bound_mac} (not ${MAC}) — release+rebind"
    fi
fi

# ------------------------------------------------------------------------------
# 3. rfcomm-bind.service — systemd reboot-survival unit enabled?
# ------------------------------------------------------------------------------
if ! command -v systemctl >/dev/null 2>&1; then
    report "systemctl present" info "skipping reboot-survive check (non-systemd host)"
elif ! systemctl list-unit-files 2>/dev/null | grep -q '^rfcomm-bind.service'; then
    report "rfcomm-bind.service installed" no "run: deploy/install-rfcomm-bind.sh on Pi"
else
    if systemctl is-enabled rfcomm-bind.service >/dev/null 2>&1; then
        report "rfcomm-bind.service enabled" yes "will re-bind after reboot"
    else
        report "rfcomm-bind.service enabled" no "sudo systemctl enable rfcomm-bind.service"
    fi
    if systemctl is-active rfcomm-bind.service >/dev/null 2>&1 \
        || systemctl status rfcomm-bind.service 2>/dev/null | grep -q "status=0/SUCCESS"; then
        report "rfcomm-bind.service last-run" yes
    else
        report "rfcomm-bind.service last-run" info "oneshot units are normally inactive; check journalctl -u rfcomm-bind"
    fi
fi

# ------------------------------------------------------------------------------
# 4. Optional python-obd smoke
# ------------------------------------------------------------------------------
if $RUN_SMOKE; then
    if ! command -v python3 >/dev/null 2>&1; then
        report "python-obd smoke" no "python3 not on PATH"
    elif ! python3 -c "import obd" >/dev/null 2>&1; then
        report "python-obd smoke" no "python-obd not installed in active env"
    else
        set +e
        smoke_out=$(python3 - <<'PYEOF' 2>&1
import sys
import obd
try:
    conn = obd.OBD("/dev/rfcomm0", baudrate=38400, fast=False, timeout=10)
    ok = conn.is_connected()
    conn.close()
    sys.stdout.write("CONNECTED\n" if ok else "NOT_CONNECTED\n")
    sys.exit(0 if ok else 1)
except Exception as exc:
    sys.stdout.write(f"ERROR {exc}\n")
    sys.exit(2)
PYEOF
        )
        rc=$?
        set -e
        if [[ $rc -eq 0 ]]; then
            report "python-obd smoke" yes "$smoke_out"
        else
            report "python-obd smoke" no "$smoke_out"
        fi
    fi
else
    report "python-obd smoke" info "skipped (pass --smoke to run)"
fi

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo ""
if $OVERALL_OK; then
    echo "=== verify_bt_pair.sh: ALL CHECKS GREEN ==="
    exit 0
else
    echo "=== verify_bt_pair.sh: ONE OR MORE CHECKS FAILED (see above) ==="
    exit 1
fi
