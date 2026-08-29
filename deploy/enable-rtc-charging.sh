#!/usr/bin/env bash
################################################################################
# enable-rtc-charging.sh — Pi 5 RTC backup-battery trickle charge (US-620 / F-138)
#
# Idempotently ensures /boot/firmware/config.txt carries an EFFECTIVE
# `dtparam=rtc_bbat_vchg=<uV>` (default 3000000 = 3.000 V), which enables the
# Pi 5's RTC backup-battery charger so the on-board RTC keeps real time across
# a power-off.
#
# **The defect this fixes.** Measured on chi-eclipse-01 2026-08-28:
#   /sys/class/rtc/rtc0/battery_voltage      = 0
#   /sys/class/rtc/rtc0/charging_voltage     = 0
#   /sys/class/rtc/rtc0/charging_voltage_max = 4400000      (4.4 V)
#   /boot/firmware/config.txt                 no rtc/bbat line at all
#   kernel, every boot: "setting system clock to 1970-01-01T00:00:13 UTC"
#
# The Pi 5 ships with RTC battery charging DISABLED, and the cell it takes is
# RECHARGEABLE. So a battery that IS fitted and WAS new still reads 0 -- it was
# never charged, and an uncharged rechargeable cell simply drains. This is why
# `battery_voltage` alone is a misleading instrument: it reads 0 both for a
# missing/dead cell and for a healthy cell that was never charged.
# `charging_voltage` is a SEPARATE register, and reading BOTH is what tells
# those two apart.
#
# **Why this matters in the car specifically.** fake-hwclock is not installed,
# so systemd falls back to the mtime of /var/lib/systemd/timesync/clock -- the
# last NTP sync. In the car there is no WiFi, so the clock STAYS at that stale
# value for the whole drive and every row captured is stamped against it.
#
# **Why this is deploy-managed and not typed on the Pi.** That is the A-18
# lesson: the live eclipse-rfkill-unblock fix was repo-unmanaged, and a reflash
# would have lost it. config.txt is OS-shipped and can be rewritten
# out-of-band by `rpi-update`, an OS image upgrade, or raspi-config, so this
# script is idempotent and re-asserted on EVERY deploy -- drift self-heals.
#
# **fake-hwclock is deliberately NOT installed here.** It was raised as
# defence-in-depth (a flat cell would degrade to "last known time" rather than
# 1970), and it is worth doing -- but not in this script, for a measurement
# reason: it introduces a SECOND clock authority that can restore a saved time
# at boot, which would mask whether the RTC itself is now holding time. The
# story's decisive validation ("power-cycle with NO network, boot again, is the
# clock right?") could then pass with the RTC still dead. Fix one clock, prove
# it, then add the fallback. Tracked separately in
# offices/pm/tech_debt/TD-us620-fake-hwclock-defence-in-depth.md.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/enable-rtc-charging.sh
#
# Behavior:
#   - Finds the EFFECTIVE `dtparam=...rtc_bbat_vchg=<uV>...`: uncommented, and
#     in a section that applies to this board (top-level, [all], or [pi5]).
#     A line inside e.g. [cm4] is NOT effective on a Pi 5, so it is neither
#     read as "already configured" nor appended to -- either would report
#     success while the charger stayed off.
#   - Already at the requested value -> no-op.
#   - A DIFFERENT non-zero value -> left alone with a loud WARN. Someone else
#     owns that number and it still charges the cell.
#   - An explicit `=0` -> left alone with a loud WARN that names it as CHARGING
#     DISABLED. An operator who wrote 0 may have fitted a NON-rechargeable
#     cell, and force-charging one of those is a genuine hazard -- so this
#     script will not overwrite that decision. It refuses to be silent about it
#     instead: 0 means this defect is still live on that Pi.
#   - Otherwise -> back up config.txt once, append the param under a section
#     that actually applies, verify by re-reading, and announce REBOOT REQUIRED.
#
# The change takes effect ONLY on the next boot. This script never reboots and
# never claims the charger is on -- /sys/class/rtc/rtc0/charging_voltage still
# reads 0 until then, and saying otherwise would be a confident lie.
#
# Test override:
#   - $PI_CONFIG_TXT retargets the file (test harness points it at a fixture).
#     Production callers leave it unset and the real boot config is used.
#     Same seam as deploy/set-gpu-cma.sh, which edits the same file.
#   - $ECLIPSE_RTC_BBAT_VCHG_UV overrides the charge voltage, in microvolts.
#
# Exit codes:
#   0  success (applied, already correct, or a foreign value left alone)
#   1  configuration error (target file missing/unreadable, invalid voltage)
#   2  write or post-write verification failed
################################################################################

set -u

TARGET="${PI_CONFIG_TXT:-/boot/firmware/config.txt}"
VCHG_UV="${ECLIPSE_RTC_BBAT_VCHG_UV:-3000000}"

# Shared with deploy/set-gpu-cma.sh ON PURPOSE. Both scripts edit the same
# /boot/firmware/config.txt, and both back up first-write-wins, so whichever
# runs first preserves the genuinely pristine pre-Eclipse original and the
# second keeps it. A per-script backup would mean the second script's "backup"
# already contained the first script's edit.
BACKUP="${TARGET}.eclipse-bak"

# The ONLY grounded bound available. Read from the Pi's own
# /sys/class/rtc/rtc0/charging_voltage_max on chi-eclipse-01 2026-08-28. A
# request above what the hardware itself reports as its maximum is refused
# BEFORE anything is written.
#
# No lower bound is asserted, deliberately: nothing measured or cited gives one,
# and inventing a floor here would be an ungrounded number in a file whose whole
# job is to carry a grounded one. 0 is refused on its own terms below -- not as
# a range check, but because 0 IS the disabled state this script exists to end.
MEASURED_CHARGING_VOLTAGE_MAX_UV=4400000

# ---- validate the requested voltage BEFORE touching anything ----

case "$VCHG_UV" in
    ''|*[!0-9]*)
        echo "ERROR: rtc_bbat_vchg must be an integer number of MICROVOLTS." >&2
        echo "       Got: '${VCHG_UV}'" >&2
        echo "       Example: 3000000 (= 3.000 V). Nothing was written." >&2
        exit 1
        ;;
esac

vchgNumeric=$((10#$VCHG_UV))

if [ "$vchgNumeric" -eq 0 ]; then
    echo "ERROR: rtc_bbat_vchg=0 means the RTC backup-battery charger is OFF." >&2
    echo "       That is precisely the state US-620 exists to end -- writing it" >&2
    echo "       would install a config line that LOOKS applied and charges" >&2
    echo "       nothing. Nothing was written." >&2
    exit 1
fi

if [ "$vchgNumeric" -gt "$MEASURED_CHARGING_VOLTAGE_MAX_UV" ]; then
    echo "ERROR: rtc_bbat_vchg=${VCHG_UV} uV exceeds this hardware's own stated" >&2
    echo "       maximum of ${MEASURED_CHARGING_VOLTAGE_MAX_UV} uV" >&2
    echo "       (/sys/class/rtc/rtc0/charging_voltage_max, chi-eclipse-01)." >&2
    echo "       Nothing was written." >&2
    exit 1
fi

# ---- validate the target ----

if [ ! -f "$TARGET" ]; then
    echo "ERROR: boot config.txt not found at '${TARGET}'." >&2
    echo "       On Raspberry Pi OS (bookworm) this lives at /boot/firmware/config.txt." >&2
    exit 1
fi

if [ ! -r "$TARGET" ]; then
    echo "ERROR: '${TARGET}' is not readable. Run this script with sudo." >&2
    exit 1
fi

# Locate the EFFECTIVE rtc_bbat_vchg param and print "<lineNo> <value>".
#
# config.txt is section-scoped: a `[cm4]` / `[pi4]` / `[HDMI:0]` header makes
# every following line conditional until the next header. Only the implicit
# top-level section, `[all]` and `[pi5]` reach this board, so only those count.
# Reading a `[cm4]` line as "already configured" would leave the charger off
# while this script reported success.
#
# The value is token-matched inside the dtparam list (`dtparam=a=1,b=2` is
# legal), never by matching the raw line, so a comment or an unrelated param
# cannot be mistaken for the setting.
findRtcParam() {
    awk '
        {
            t = $0
            sub(/^[ \t]+/, "", t)
            sub(/[ \t]+$/, "", t)
        }
        t ~ /^\[/ { section = tolower(t); next }
        (section == "" || section == "[all]" || section == "[pi5]") &&
        t ~ /^dtparam[ \t]*=/ && t ~ /(=|,)[ \t]*rtc_bbat_vchg[ \t]*=/ {
            v = t
            sub(/.*rtc_bbat_vchg[ \t]*=[ \t]*/, "", v)
            sub(/[,[:space:]].*$/, "", v)
            print NR " " v
            exit
        }
    ' "$1"
}

# Print the conditional-filter section in effect at END of file, lowercased
# ("" = the implicit top-level section). This decides whether a line appended
# at EOF would actually apply to a Pi 5.
sectionAtEof() {
    awk '
        {
            t = $0
            sub(/^[ \t]+/, "", t)
            sub(/[ \t]+$/, "", t)
        }
        t ~ /^\[/ { section = tolower(t) }
        END { print section }
    ' "$1"
}

existing="$(findRtcParam "$TARGET")"

if [ -n "$existing" ]; then
    existingLineNo="${existing%% *}"
    existingValue="${existing#* }"

    if [ "$existingValue" = "$VCHG_UV" ]; then
        echo "rtc_bbat_vchg=${VCHG_UV} already set and effective (line ${existingLineNo}) -- no change."
        echo "  $(sed -n "${existingLineNo}p" "$TARGET")"
        exit 0
    fi

    if [ "$existingValue" = "0" ]; then
        echo "WARN: config.txt sets rtc_bbat_vchg=0 (line ${existingLineNo}) -- RTC battery" >&2
        echo "WARN: charging is explicitly DISABLED on this Pi." >&2
        echo "WARN: leaving it alone: a deliberate 0 can mean a NON-rechargeable cell is" >&2
        echo "WARN: fitted, and force-charging one of those is a hazard, not a fix." >&2
        echo "WARN: BUT BE CLEAR -- while this reads 0 the US-620 defect is STILL LIVE:" >&2
        echo "WARN: the RTC will not hold time, and every off-network drive is stamped" >&2
        echo "WARN: against a stale clock." >&2
        echo "WARN: To enable, set rtc_bbat_vchg=${VCHG_UV} in ${TARGET} and reboot." >&2
        echo "  $(sed -n "${existingLineNo}p" "$TARGET")"
        exit 0
    fi

    echo "WARN: config.txt already carries rtc_bbat_vchg=${existingValue} (line ${existingLineNo})." >&2
    echo "WARN: leaving it alone -- US-620 will not clobber an explicitly-set charge" >&2
    echo "WARN: voltage. It is non-zero, so the charger is enabled." >&2
    echo "WARN: to move to ${VCHG_UV}, edit ${TARGET} by hand and reboot." >&2
    echo "  $(sed -n "${existingLineNo}p" "$TARGET")"
    exit 0
fi

# ---- apply ----

# Back up ONCE, first-write-wins, so the preserved copy is the pristine
# pre-Eclipse original rather than whatever a previous run (or set-gpu-cma.sh)
# left behind.
if [ ! -f "$BACKUP" ]; then
    if ! cp "$TARGET" "$BACKUP"; then
        echo "ERROR: could not write backup ${BACKUP}; refusing to modify boot config." >&2
        exit 2
    fi
    echo "Backed up ${TARGET} -> ${BACKUP} (pristine original)."
else
    echo "Backup ${BACKUP} already exists (kept -- it holds the pristine original)."
fi

# Decide whether appending at EOF lands somewhere a Pi 5 actually reads. If the
# file ends inside e.g. [cm4], open an explicit [all] first -- that is exactly
# what [all] is for (it resets the conditional filter). Appending without it
# would write a line the firmware ignores and then report success.
eofSection="$(sectionAtEof "$TARGET")"
headerLine=""
case "$eofSection" in
    ''|'[all]'|'[pi5]')
        ;;
    *)
        headerLine="[all]"
        echo "Note: config.txt ends inside the ${eofSection} section, which does not apply"
        echo "      to a Pi 5. Opening an [all] section so the param actually takes effect."
        ;;
esac

paramLine="dtparam=rtc_bbat_vchg=${VCHG_UV}"

# Write beside the target and rename, so an interrupted write can never leave a
# truncated config.txt on the boot partition. A distinct tmp name from
# set-gpu-cma.sh's so the two can never collide.
tmp="$(dirname "$TARGET")/.config.txt.eclipse-rtc-tmp.$$"
trap 'rm -f "$tmp"' EXIT

if ! awk -v hdr="$headerLine" -v param="$paramLine" \
        '{ print } END { if (hdr != "") print hdr; print param }' \
        "$TARGET" > "$tmp"; then
    echo "ERROR: failed to compose the updated config.txt; ${TARGET} unchanged." >&2
    exit 2
fi

if ! mv "$tmp" "$TARGET"; then
    echo "ERROR: failed to install the updated ${TARGET}." >&2
    echo "       The pristine copy is still at ${BACKUP}." >&2
    exit 2
fi

# Verify by re-reading the file we just wrote -- not by trusting the variable,
# and through the same section-aware finder, so "effective" is what is checked
# rather than "present somewhere".
verify="$(findRtcParam "$TARGET")"
verifyValue=""
[ -n "$verify" ] && verifyValue="${verify#* }"

if [ "$verifyValue" != "$VCHG_UV" ]; then
    echo "ERROR: post-write verification failed -- no EFFECTIVE rtc_bbat_vchg=${VCHG_UV}" >&2
    echo "       in ${TARGET}." >&2
    echo "       Restore with: sudo cp ${BACKUP} ${TARGET}" >&2
    exit 2
fi

verifyLineNo="${verify%% *}"
echo "Applied ${paramLine} (line ${verifyLineNo}):"
echo "  $(sed -n "${verifyLineNo}p" "$TARGET")"
echo "REBOOT REQUIRED: the RTC charger is still off until the Pi reboots."
echo "  After reboot, read BOTH registers -- they mean different things:"
echo "    cat /sys/class/rtc/rtc0/charging_voltage   (expect ~${VCHG_UV}, was 0)"
echo "    cat /sys/class/rtc/rtc0/battery_voltage    (expect NON-ZERO once charged)"
echo "  A charged cell needs time; battery_voltage may lag charging_voltage."
echo "  THE REAL TEST IS NOT A NETWORKED REBOOT: NTP would hide the defect."
echo "  Power-cycle with NO network, wait, boot again, and check the clock is"
echo "  still right and the log carries no 'setting system clock to 1970' line."
exit 0
