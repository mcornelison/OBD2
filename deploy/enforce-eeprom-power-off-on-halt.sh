#!/usr/bin/env bash
################################################################################
# enforce-eeprom-power-off-on-halt.sh — Pi 5 bootloader EEPROM key enforcer
#
# Idempotently enforces ONE table of EEPROM keys (EEPROM_KEY_TABLE below):
# POWER_OFF_ON_HALT=1 for wake-on-power, and since US-926-a the boot-speed
# keys NET_INSTALL_AT_POWER_ON=0, NET_INSTALL_ENABLED=0 and BOOT_UART=0.
#
# POWER_OFF_ON_HALT=1 in the Pi 5 bootloader EEPROM: on
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
# US-926-a (Atlas MEASURED 2026-10-24; RPi WP-1 2026-06-01): firmware reached
# 'Starting OS' at 13.5 s against a ~7 s floor. The network-install probe and
# the bootloader UART log are the keys this car still pays for.
#
# MERGE, never rebuild (Atlas MEASURED Q3, Spool 2026-10-24): `--apply` takes
# a WHOLE config, and a second apply reads the unchanged running config and
# drops the first one's staged change. So there is ONE read, every table key
# compared, and ONE apply of the running config as read with ONLY the table
# keys rewritten in place (or appended when absent). Every other line --
# WAKE_ON_GPIO, the boot order, PSU_MAX_CURRENT, comments, blank lines,
# section headers -- reaches the apply byte-identical and in order.
#
# Never in the table and never written: PSU_MAX_CURRENT (Atlas MEASURED:
# usb_pd_init costs 6 ms, nothing to win; 5 A is unrated for the car buck --
# Spool), max_framebuffers (never 0: WP-1 p.10), and the boot order key.
#
# The bootloader image moves with the config (Atlas MEASURED Q5, ruled: accept
# and name it): `--apply` writes the config into the LATEST packaged image, so
# the first real apply also moves this car's bootloader 2026/05/11 ->
# 2026/05/26. The image is logged (`rpi-eeprom-update -l`) before the apply.
# This script never runs `rpi-eeprom-update` with its apply-update flag.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/enforce-eeprom-power-off-on-halt.sh
#
# Behavior:
#   - Reads the current EEPROM config ONCE via `rpi-eeprom-config`
#   - Compares every table key; logs one line per key:
#       already set / <old> -> <new> / absent -> <new>
#     (POWER_OFF_ON_HALT keeps its pre-US-926-a wording)
#   - All keys right: no-op, no apply, no image probe
#   - Otherwise: logs the image the apply will install, then ONE
#     `rpi-eeprom-config --apply <tmpfile>` of the merged config
#   - If `rpi-eeprom-config` is missing or fails: exit non-zero with a clear error
#
# Test overrides:
#   - $RPI_EEPROM_CONFIG: a different rpi-eeprom-config binary (the test
#     harness uses a stub). Production callers leave it unset.
#   - $RPI_EEPROM_UPDATE: a different rpi-eeprom-update binary for the image
#     probe. Production callers leave it unset.
#
# Exit codes:
#   0  success (no-op or successful apply)
#   1  rpi-eeprom-config tool missing
#   2  rpi-eeprom-config read or apply failed
################################################################################

set -e
set -o pipefail

# >>> EEPROM_KEY_TABLE -- the ONE table of required KEY=VALUE pairs, each with
# its source. Tests read this block; the never-keys above stay out of it.
EEPROM_KEY_TABLE=(
    # CIO 2026-05-18 (Finding-B fix, SS-T8): Pi 5 + X1209-HAT wake-on-power.
    "POWER_OFF_ON_HALT=1"
    # Atlas 2026-10-24 + RPi WP-1: no network-install probe at power-on.
    "NET_INSTALL_AT_POWER_ON=0"
    # Atlas 2026-10-24 + RPi WP-1: network install disabled outright.
    "NET_INSTALL_ENABLED=0"
    # Atlas 2026-10-24 + RPi WP-1: no bootloader UART log on the boot path.
    "BOOT_UART=0"
)
# <<< EEPROM_KEY_TABLE

# Allow override of the binaries for tests; default to the system binaries.
TOOL="${RPI_EEPROM_CONFIG:-rpi-eeprom-config}"
UPDATE_TOOL="${RPI_EEPROM_UPDATE:-rpi-eeprom-update}"

if ! command -v "$TOOL" >/dev/null 2>&1; then
    echo "ERROR: '$TOOL' not found on PATH. POWER_OFF_ON_HALT=1 cannot be enforced." >&2
    echo "       This script targets Pi 5 bootloaders. Verify rpi-eeprom is installed." >&2
    exit 1
fi

current=$(mktemp)
tmp=$(mktemp)
trap 'rm -f "$current" "$tmp"' EXIT

# Read the current config block ONCE, into a file so every line -- trailing
# blank lines included -- survives to the apply exactly as read.
if ! "$TOOL" > "$current" 2>/dev/null; then
    echo "ERROR: '$TOOL' failed to read current EEPROM config." >&2
    exit 2
fi

# Print the first effective (non-comment) value of key $1; fail when absent.
# rpi-eeprom-config emits at most one canonical line per key on read-back.
read_value() {
    local line
    line=$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$current" | head -1 || true)
    [ -n "$line" ] || return 1
    echo "$line" | cut -d= -f2 | tr -d '[:space:]'
}

changed=()
for entry in "${EEPROM_KEY_TABLE[@]}"; do
    key="${entry%%=*}"
    want="${entry#*=}"
    if ! have=$(read_value "$key"); then
        if [ "$key" = "POWER_OFF_ON_HALT" ]; then
            # The bootloader default (0) is wrong for the Pi 5 + X1209-HAT
            # topology; relying on it would silently ship Finding B.
            echo "POWER_OFF_ON_HALT not present in EEPROM config -- rewriting to 1 (Pi 5 + X1209-HAT requires =1; default 0 is WRONG on this topology)."
        else
            echo "${key} absent -> ${want}"
        fi
        changed+=("$key")
    elif [ "$have" = "$want" ]; then
        if [ "$key" = "POWER_OFF_ON_HALT" ]; then
            echo "POWER_OFF_ON_HALT=1 already set (wake-on-power OK)."
        else
            echo "${key}=${want} already set."
        fi
    else
        if [ "$key" = "POWER_OFF_ON_HALT" ]; then
            echo "POWER_OFF_ON_HALT=${have} -- rewriting to 1 (Pi 5 + X1209-HAT wake-on-power requires =1; SS-T8 / CIO decision 2026-05-18)."
        else
            echo "${key} ${have} -> ${want}"
        fi
        changed+=("$key")
    fi
done

if [ "${#changed[@]}" -eq 0 ]; then
    exit 0
fi

# Merge: the running config as read, each table key's line rewritten in
# place, any absent table key appended at the end. Nothing else is touched.
awk -v table="${EEPROM_KEY_TABLE[*]}" '
BEGIN {
    n = split(table, entries, " ")
    for (i = 1; i <= n; i++) {
        key = entries[i]; sub(/=.*/, "", key)
        want[key] = entries[i]; order[i] = key
    }
}
{
    for (key in want) {
        if ($0 ~ ("^[[:space:]]*" key "[[:space:]]*=")) {
            print want[key]; seen[key] = 1; next
        }
    }
    print
}
END {
    for (i = 1; i <= n; i++) if (!(order[i] in seen)) print want[order[i]]
}' "$current" > "$tmp"

# Name the image the apply will install: --apply writes this config into the
# LATEST packaged bootloader, so the apply moves the bootloader to it.
if image=$("$UPDATE_TOOL" -l 2>/dev/null) && [ -n "$image" ]; then
    echo "applying onto $(basename "$image") (${image}): --apply installs the latest packaged bootloader image with this config."
else
    echo "WARNING: could not read the bootloader image --apply will install ('$UPDATE_TOOL -l' failed); applying anyway."
fi

# `rpi-eeprom-config --apply <file>` validates and replaces the whole config
# block; partial writes never reach the EEPROM.
if ! "$TOOL" --apply "$tmp" >/dev/null 2>&1; then
    echo "ERROR: '$TOOL --apply' failed; EEPROM config unchanged." >&2
    echo "       Inspect with: sudo $TOOL" >&2
    exit 2
fi

for key in "${changed[@]}"; do
    if [ "$key" = "POWER_OFF_ON_HALT" ]; then
        echo "POWER_OFF_ON_HALT=1 applied. Effect persists across reboots."
    fi
done
echo "EEPROM config applied (${changed[*]}). Effect persists across reboots."
