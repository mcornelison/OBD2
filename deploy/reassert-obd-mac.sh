#!/usr/bin/env bash
################################################################################
# File Name: reassert-obd-mac.sh
# Purpose:   Idempotently re-assert the canonical OBDLink LX MAC into the Pi's
#            /etc/default/obdlink so a drifted device address self-heals on the
#            next deploy (US-477 / F-120).
# Author:    Rex (Ralph Agent)
# Created:   2026-07-20 — US-477
#
# ORIGIN (why this exists): on 2026-07-17 the Pi's /etc/default/obdlink was
# repointed to a PHANTOM MAC (00:04:3C:84:15:6B — a mis-identified stranger's
# device). A Bluetooth MAC is burned-in and does NOT change on factory reset,
# so the OBDLink LX's real address (00:04:3E:85:0D:FB) never moved. rfcomm then
# bound a nonexistent device -> no connection -> a weekend of drives captured
# ZERO rows. This script makes the deploy RE-ASSERT the repo-canonical MAC on
# every run so that class of drift can never persist silently.
#
# SURGICAL by design (acceptance #3): it corrects ONLY the OBD_BT_MAC line and
# leaves OBD_BT_CHANNEL (and every other line/comment) untouched, so a
# legitimately different channel/device setting is never clobbered.
#
# Idempotent: a no-op (exit 0, "already canonical") when the file already holds
# the canonical MAC. The canonical MAC is the SSOT in deploy/addresses.sh
# (OBD_BT_MAC default) mirrored into config.json pi.bluetooth.macAddress.
#
# Usage (run directly on the Pi, or against a fixture on the bench):
#   sudo bash deploy/reassert-obd-mac.sh --mac 00:04:3E:85:0D:FB
#   sudo bash deploy/reassert-obd-mac.sh --mac "$OBD_BT_MAC" --env-file /etc/default/obdlink
#   bash deploy/reassert-obd-mac.sh --mac "$OBD_BT_MAC" --env-file ./fixture --dry-run
#   OBD_BT_MAC=00:04:3E:85:0D:FB bash deploy/reassert-obd-mac.sh   # MAC from env
#
# Flags:
#   --mac <MAC>        Canonical MAC to assert (default: $OBD_BT_MAC). Required
#                      (via flag or env) — this script never guesses the MAC.
#   --env-file <path>  Target env file (default: /etc/default/obdlink).
#   --dry-run          Report the decision (no-op / correct / append) without
#                      writing. Reports do NOT mutate the file.
#   --help, -h         Show this header.
#
# Behavior:
#   - OBD_BT_MAC line present and == canonical:   no-op, exit 0.
#   - OBD_BT_MAC line present and != canonical:   rewrite ONLY that line, exit 0.
#   - OBD_BT_MAC line absent (file exists):       append the canonical line, exit 0.
#   - env file missing:                           log + exit 0 (install-rfcomm-
#                                                  bind.sh owns file creation).
#
# Exit codes:
#   0  success (no-op, corrected, appended, or nothing-to-do)
#   2  usage / invalid or missing MAC
################################################################################

set -euo pipefail

MAC_REGEX='^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$'
ENV_FILE="/etc/default/obdlink"
MAC="${OBD_BT_MAC:-}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mac)
            MAC="${2:-}"
            shift 2
            ;;
        --env-file)
            ENV_FILE="${2:-}"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "error: unknown argument '$1'" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$MAC" ]]; then
    echo "error: canonical MAC required (--mac <MAC> or \$OBD_BT_MAC)" >&2
    exit 2
fi
if ! [[ "$MAC" =~ $MAC_REGEX ]]; then
    echo "error: '$MAC' is not a valid Bluetooth MAC" >&2
    exit 2
fi
if [[ -z "$ENV_FILE" ]]; then
    echo "error: --env-file requires a path" >&2
    exit 2
fi

LABEL="OBDLink LX"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "OBD MAC re-assert: ${ENV_FILE} not present -- nothing to re-assert (install-rfcomm-bind.sh creates it)."
    exit 0
fi

# The current effective OBD_BT_MAC line (first non-comment assignment).
existing=$(grep -E '^[[:space:]]*OBD_BT_MAC[[:space:]]*=' "$ENV_FILE" | head -1 || true)
currentMac=""
if [[ -n "$existing" ]]; then
    currentMac=$(echo "$existing" | cut -d= -f2- | tr -d '[:space:]"'"'")
fi

# ---- case: already canonical -> idempotent no-op --------------------------
if [[ "$currentMac" == "$MAC" ]]; then
    echo "OBD MAC re-assert: ${ENV_FILE} already canonical (${MAC}, ${LABEL}) -- no-op."
    exit 0
fi

# ---- case: line absent -> append the canonical assignment -----------------
if [[ -z "$existing" ]]; then
    if $DRY_RUN; then
        echo "DRY-RUN: would append OBD_BT_MAC=${MAC} (${LABEL}) to ${ENV_FILE} (no OBD_BT_MAC line present)."
        exit 0
    fi
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    # Preserve every existing line, then append the canonical MAC.
    printf '%s\nOBD_BT_MAC=%s\n' "$(cat "$ENV_FILE")" "$MAC" > "$tmp"
    cat "$tmp" > "$ENV_FILE"
    echo "OBD MAC re-assert: appended OBD_BT_MAC=${MAC} (${LABEL}) to ${ENV_FILE} (line was absent)."
    exit 0
fi

# ---- case: present but drifted -> correct ONLY the MAC line ----------------
if $DRY_RUN; then
    echo "DRY-RUN: would correct OBD_BT_MAC ${currentMac} -> ${MAC} (${LABEL}) in ${ENV_FILE} (channel/other lines preserved)."
    exit 0
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
# sed touches ONLY the OBD_BT_MAC assignment; OBD_BT_CHANNEL and every comment/
# other line pass through verbatim -> surgical, non-clobbering (acceptance #3).
sed -E "s|^[[:space:]]*OBD_BT_MAC[[:space:]]*=.*|OBD_BT_MAC=${MAC}|" "$ENV_FILE" > "$tmp"
cat "$tmp" > "$ENV_FILE"
echo "OBD MAC re-assert: corrected OBD_BT_MAC ${currentMac} -> ${MAC} (${LABEL}) in ${ENV_FILE} (self-heal; channel preserved)."
exit 0
