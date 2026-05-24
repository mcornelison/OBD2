#!/usr/bin/env bash
################################################################################
# enforce-eeprom-power-off-on-halt.sh — Pi 5 + X1209-HAT wake-on-power EEPROM
#
# Idempotently enforces POWER_OFF_ON_HALT=1 in the Pi 5 bootloader EEPROM. On
# this hardware topology (Pi 5 + Geekworm X1209 UPS HAT), =1 is the load-bearing
# setting for unattended wake on external-power-return.
#
# **Topology-specific rationale (the F-6 fix).** With the X1209 holding the Pi
# 5 V rail up off its battery, `=0` leaves the PMIC active after `poweroff`
# and the PMIC NEVER sees a power-cycle edge when external power returns
# → no unattended auto-boot. This is Finding B, observed empirically on the
# Pi 2026-05-17. `=1` powers the PMIC fully off so a USB-C power-return is a
# real boot event → clean unattended restore.
#
# Provenance (do not weaken without re-validating both):
#   - CIO decision 2026-05-18: `POWER_OFF_ON_HALT=1` locked for this topology.
#   - Bench Check B (Atlas-gated 2026-05-18): empirically confirmed `=1` →
#     unattended auto-boot on this physical Pi 5 + X1209-HAT, 1 cycle. Spec
#     definitive corrections: offices/architect/findings/2026-05-18-
#     architecture-md-corrections-definitive.md §11.
#   - The previously documented "`=0` ⇒ auto-boots / `=1` ⇒ needs button"
#     table was FALSE for this topology (it described a bare Pi 5 with no HAT)
#     and was the documentation root of the V0.27.x chain blocker (finding
#     F-6). The empirical bench drill is the sole arbiter.
#
# History note: prior to SS-T8 (2026-05-19) this script enforced =0 and was
# the defect that reverted the correct setting on every deploy. SS-T8
# inverts the target value.  Full IRL confirmation (5 consecutive clean
# unattended cycles) is still pending — `=1` is designed-for and
# empirically supported at 1 cycle, never asserted beyond evidence.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/enforce-eeprom-power-off-on-halt.sh
#
# Behavior:
#   - Reads current EEPROM config via `rpi-eeprom-config`
#   - If POWER_OFF_ON_HALT=1: no-op (already correct)
#   - If POWER_OFF_ON_HALT line is absent: rewrite the config block to add an
#     explicit POWER_OFF_ON_HALT=1 (the bootloader default 0 is WRONG on this
#     HAT topology; do not rely on it)
#   - If POWER_OFF_ON_HALT=<anything-other-than-1>: rewrite to set
#     POWER_OFF_ON_HALT=1 via `rpi-eeprom-config --apply <tmpfile>`
#   - If `rpi-eeprom-config` is missing or fails: exit non-zero with a clear error
#
# Test override:
#   - Set $RPI_EEPROM_CONFIG to a different binary path (test harness uses a
#     PATH-mocked stub). Production callers leave it unset and the script falls
#     back to the real `rpi-eeprom-config` from PATH.
#
# Exit codes:
#   0  success (no-op or successful rewrite)
#   1  rpi-eeprom-config tool missing
#   2  rpi-eeprom-config read or apply failed
################################################################################

set -e
set -o pipefail

# Allow override of the binary for tests; default to the system binary.
TOOL="${RPI_EEPROM_CONFIG:-rpi-eeprom-config}"

if ! command -v "$TOOL" >/dev/null 2>&1; then
    echo "ERROR: '$TOOL' not found on PATH. POWER_OFF_ON_HALT=1 cannot be enforced." >&2
    echo "       This script targets Pi 5 bootloaders. Verify rpi-eeprom is installed." >&2
    exit 1
fi

# Read the current config block. rpi-eeprom-config writes the active config to
# stdout as plain key=value lines (plus comments and blank lines).
current=$("$TOOL" 2>/dev/null) || {
    echo "ERROR: '$TOOL' failed to read current EEPROM config." >&2
    exit 2
}

# Locate an explicit POWER_OFF_ON_HALT assignment. Comments (#) are ignored.
# Multiple matches would be unusual but we only consider the first effective
# (last-wins-in-config-but-grep-takes-first-non-comment-here is fine because
# rpi-eeprom-config emits at most one canonical line per key on read-back).
existing=$(echo "$current" | grep -E '^[[:space:]]*POWER_OFF_ON_HALT[[:space:]]*=' || true)

if [ -z "$existing" ]; then
    # The bootloader default (0) is wrong for the Pi 5 + X1209-HAT topology.
    # Rewrite to add an explicit =1 line; relying on the default would silently
    # ship Finding B (no unattended wake) on any future bootloader rev.
    echo "POWER_OFF_ON_HALT not present in EEPROM config -- rewriting to 1 (Pi 5 + X1209-HAT requires =1; default 0 is WRONG on this topology)."
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    # Append the missing line at the end of the current config.
    printf '%s\nPOWER_OFF_ON_HALT=1\n' "$current" > "$tmp"
    if ! "$TOOL" --apply "$tmp" >/dev/null 2>&1; then
        echo "ERROR: '$TOOL --apply' failed; EEPROM config unchanged." >&2
        echo "       Inspect with: sudo $TOOL" >&2
        exit 2
    fi
    echo "POWER_OFF_ON_HALT=1 applied. Effect persists across reboots."
    exit 0
fi

value=$(echo "$existing" | head -1 | cut -d= -f2 | tr -d '[:space:]')
if [ "$value" = "1" ]; then
    echo "POWER_OFF_ON_HALT=1 already set (wake-on-power OK)."
    exit 0
fi

echo "POWER_OFF_ON_HALT=${value} -- rewriting to 1 (Pi 5 + X1209-HAT wake-on-power requires =1; SS-T8 / CIO decision 2026-05-18)."

# Rewrite the line in a tempfile copy of the current config, then apply
# atomically. `rpi-eeprom-config --apply <file>` validates and replaces the
# whole config block; partial writes never reach the EEPROM.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

echo "$current" | sed -E 's/^[[:space:]]*POWER_OFF_ON_HALT[[:space:]]*=.*/POWER_OFF_ON_HALT=1/' > "$tmp"

if ! "$TOOL" --apply "$tmp" >/dev/null 2>&1; then
    echo "ERROR: '$TOOL --apply' failed; EEPROM config unchanged." >&2
    echo "       Inspect with: sudo $TOOL" >&2
    exit 2
fi

echo "POWER_OFF_ON_HALT=1 applied. Effect persists across reboots."
