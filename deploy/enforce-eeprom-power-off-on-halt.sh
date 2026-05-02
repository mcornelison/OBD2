#!/usr/bin/env bash
################################################################################
# enforce-eeprom-power-off-on-halt.sh — Pi 5 wake-on-power EEPROM enforcement
#
# Idempotently enforces POWER_OFF_ON_HALT=0 in the Pi 5 bootloader EEPROM. With
# this setting (which is the bootloader default), `systemctl poweroff` halts
# the SoC but leaves the PMIC awake watching the power rails. When wall power
# returns the PMIC kicks the SoC back on -- no operator button press required.
# A non-zero value puts the board in deep sleep on poweroff, requiring a
# physical button or full power-cycle to boot.
#
# Background (US-253, paired with US-216 staged shutdown / US-252 firing fix):
# In the post-B-043 in-car wiring scenario, key-OFF cuts wall power, the UPS
# sustains the Pi long enough for US-216's staged ladder to fire a graceful
# `systemctl poweroff`, and key-ON returns wall power. The Pi MUST auto-wake at
# that point -- there's no operator at the car. POWER_OFF_ON_HALT=0 is the
# load-bearing setting that makes that loop work.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/enforce-eeprom-power-off-on-halt.sh
#
# Behavior:
#   - Reads current EEPROM config via `rpi-eeprom-config`
#   - If POWER_OFF_ON_HALT line is absent: no-op (defaults to 0; correct)
#   - If POWER_OFF_ON_HALT=0: no-op (already correct)
#   - If POWER_OFF_ON_HALT=<non-zero>: rewrite the config block in-place to set
#     POWER_OFF_ON_HALT=0, apply via `rpi-eeprom-config --apply <tmpfile>`
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
    echo "ERROR: '$TOOL' not found on PATH. POWER_OFF_ON_HALT=0 cannot be enforced." >&2
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
    echo "POWER_OFF_ON_HALT not present in EEPROM config (defaults to 0; wake-on-power OK)."
    exit 0
fi

value=$(echo "$existing" | head -1 | cut -d= -f2 | tr -d '[:space:]')
if [ "$value" = "0" ]; then
    echo "POWER_OFF_ON_HALT=0 already set (wake-on-power OK)."
    exit 0
fi

echo "POWER_OFF_ON_HALT=${value} -- rewriting to 0 to enable wake-on-power (US-253)."

# Rewrite the line in a tempfile copy of the current config, then apply
# atomically. `rpi-eeprom-config --apply <file>` validates and replaces the
# whole config block; partial writes never reach the EEPROM.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

echo "$current" | sed -E 's/^[[:space:]]*POWER_OFF_ON_HALT[[:space:]]*=.*/POWER_OFF_ON_HALT=0/' > "$tmp"

if ! "$TOOL" --apply "$tmp" >/dev/null 2>&1; then
    echo "ERROR: '$TOOL --apply' failed; EEPROM config unchanged." >&2
    echo "       Inspect with: sudo $TOOL" >&2
    exit 2
fi

echo "POWER_OFF_ON_HALT=0 applied. Effect persists across reboots."
