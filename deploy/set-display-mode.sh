#!/usr/bin/env bash
################################################################################
# set-display-mode.sh — Pi 5 HDMI/KMS output-mode pin (US-552 / F-127)
#
# Idempotently pins the kernel's KMS output mode to the panel's native
# resolution (default 480x320, the OSOYOO 3.5" HDMI panel this project ships --
# docs/hardware-reference.md "Display: OSOYOO 3.5\" HDMI Touch Screen"), by
# adding a `video=<connector>:<WxH>` token to /boot/firmware/cmdline.txt.
#
# WHY THIS EXISTS (Atlas A-16 display-pipeline fidelity). The deploy pins no
# output mode at all, so the Pi scans out whatever EDID negotiation lands on --
# on this panel that is very likely 1080p, which the panel then downsamples to
# its own 480x320. Every glyph is scaled up and resampled back down, softening
# the US-540 type scale and RAISING the legibility floor those values were set
# against. Pinning the native mode renders the scale 1:1 -- a legibility lever
# distinct from the font sizes themselves.
#
# **Why cmdline.txt, when US-524 deliberately refused to touch it.** That
# refusal was correct for its job: a CMA size had a config.txt mechanism, and a
# bad overlay param only costs a dark display with SSH alive, whereas a
# corrupted cmdline.txt can break `root=` on a Pi that lives in a car. The
# output mode has NO such alternative on a Pi 5 -- the legacy config.txt
# `hdmi_group` / `hdmi_mode` / `hdmi_cvt` settings are a Pi 4-and-earlier
# firmware path that the Pi 5 does not implement; the KMS `video=` kernel
# argument is the only boot-level mechanism. So the risk is BOUNDED rather than
# avoided, by four interlocks:
#
#   1. The connector is DISCOVERED from /sys/class/drm, never assumed. A Pi 5
#      has two micro-HDMI ports; pinning the empty one is a silent no-op that
#      would still read as "applied".
#   2. Nothing is written unless EXACTLY ONE connector reports `connected`.
#      No panel (bench deploy) or two panels means we cannot know the target,
#      and a guess would be a confident wrong answer.
#   3. The target mode must be one the PANEL ITSELF advertises in its EDID mode
#      list. A forced timing the panel never claimed can scan out black -- in a
#      car, with no local recovery. An unadvertised target is a loud refusal.
#   4. The rewritten line is verified BEFORE it is installed (one line, `root=`
#      and every original token intact) and again after; a post-install
#      mismatch restores the pristine backup automatically.
#
# A pre-existing `video=` token is left strictly alone with a WARN: someone else
# owns that decision, and an optional fidelity tweak must not clobber it.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/set-display-mode.sh
#
# The change takes effect ONLY on the next boot. This script never reboots and
# never claims the mode changed -- the active mode is whatever was negotiated at
# the last boot until then, and saying otherwise would be a confident lie.
#
# Test overrides (the harness points these at fixtures; production leaves unset):
#   $PI_DRM_DIR             -> /sys/class/drm
#   $PI_CMDLINE_TXT         -> /boot/firmware/cmdline.txt
#   $PI_FB_SIZE_FILE        -> /sys/class/graphics/fb0/virtual_size
#   $ECLIPSE_DISPLAY_MODE   -> the target mode (default 480x320)
#
# Exit codes:
#   0  success (pinned, already pinned, or deliberately left alone with a WARN)
#   1  configuration error (target file missing/malformed, bad mode string)
#   2  write or post-write verification failed (backup restored)
################################################################################

set -u

DRM_DIR="${PI_DRM_DIR:-/sys/class/drm}"
CMDLINE="${PI_CMDLINE_TXT:-/boot/firmware/cmdline.txt}"
FB_SIZE_FILE="${PI_FB_SIZE_FILE:-/sys/class/graphics/fb0/virtual_size}"
TARGET_MODE="${ECLIPSE_DISPLAY_MODE:-480x320}"
BACKUP="${CMDLINE}.eclipse-bak"

# ---- 1. validate the target mode BEFORE reading anything else ----

if ! printf '%s' "$TARGET_MODE" | grep -qE '^[0-9]+x[0-9]+$'; then
    echo "ERROR: ECLIPSE_DISPLAY_MODE='${TARGET_MODE}' is not a WxH mode string." >&2
    echo "       Expected e.g. 480x320. Nothing was written." >&2
    exit 1
fi

# ---- 2. the boot cmdline must exist and be a boot cmdline ----

if [ ! -f "$CMDLINE" ]; then
    echo "ERROR: boot cmdline.txt not found at '${CMDLINE}'." >&2
    echo "       On Raspberry Pi OS (bookworm) this lives at /boot/firmware/cmdline.txt." >&2
    exit 1
fi

if [ ! -r "$CMDLINE" ]; then
    echo "ERROR: '${CMDLINE}' is not readable. Run this script with sudo." >&2
    exit 1
fi

# cmdline.txt is ONE line by contract -- the bootloader passes the first line
# and a stray newline silently truncates every argument after it. A file that
# already has two is malformed, and appending to it would bury that fact under
# an "applied" message.
contentLines="$(grep -c '[^[:space:]]' "$CMDLINE")"
if [ "$contentLines" != "1" ]; then
    echo "ERROR: '${CMDLINE}' has ${contentLines} non-blank lines; a boot cmdline is exactly 1." >&2
    echo "       Refusing to edit a malformed boot cmdline. Nothing was written." >&2
    exit 1
fi

cmdLine="$(grep -m1 '[^[:space:]]' "$CMDLINE")"

# `root=` is the token whose loss makes the Pi unbootable and headless. Its
# presence is how we know this file is what we think it is; its survival is
# verified again after the rewrite.
if ! printf '%s' "$cmdLine" | grep -qE '(^|[[:space:]])root='; then
    echo "ERROR: '${CMDLINE}' carries no root= argument -- this is not a boot cmdline." >&2
    echo "       Refusing to edit it. Nothing was written." >&2
    exit 1
fi

# ---- 3. observe the mode currently being scanned out (informational) ----
#
# The framebuffer's virtual_size is the cheapest honest read of what the display
# pipeline actually settled on, and needs no extra package (kmsprint/modetest
# are not installed on this Pi). It is REPORTED, never used to skip the pin: an
# EDID negotiation that happened to land native at this boot is not a guarantee
# for the next one, and the DoD asks the deploy to SET the mode.
observedMode="unknown"
if [ -r "$FB_SIZE_FILE" ]; then
    rawSize="$(tr -d '[:space:]' < "$FB_SIZE_FILE")"
    if printf '%s' "$rawSize" | grep -qE '^[0-9]+,[0-9]+$'; then
        observedMode="$(printf '%s' "$rawSize" | tr ',' 'x')"
    fi
fi

if [ "$observedMode" = "unknown" ]; then
    echo "Observed output mode: unknown (${FB_SIZE_FILE} unreadable or unrecognised)."
else
    echo "Observed output mode: ${observedMode} (from ${FB_SIZE_FILE})."
fi

# ---- 4. discover the connected HDMI connector ----

connected=""
connectedCount=0
allHdmi=""

for connectorDir in "$DRM_DIR"/*-HDMI-*; do
    [ -d "$connectorDir" ] || continue
    connectorName="$(basename "$connectorDir")"
    # /sys/class/drm entries are card<N>-<CONNECTOR>; the kernel's `video=`
    # argument takes the connector part only (e.g. HDMI-A-1).
    connectorName="${connectorName#*-}"
    allHdmi="${allHdmi} ${connectorName}"
    [ -r "$connectorDir/status" ] || continue
    if [ "$(tr -d '[:space:]' < "$connectorDir/status")" = "connected" ]; then
        connected="$connectorName"
        connectedCount=$((connectedCount + 1))
        connectedDir="$connectorDir"
    fi
done

if [ "$connectedCount" -eq 0 ]; then
    echo "WARN: no HDMI connector reports 'connected' under ${DRM_DIR}." >&2
    echo "WARN: seen:${allHdmi:- (none)}" >&2
    echo "WARN: the output mode was NOT pinned -- with no panel attached there is" >&2
    echo "WARN: no connector to name and a guess could pin the wrong port." >&2
    echo "WARN: re-run this deploy with the panel connected." >&2
    exit 0
fi

if [ "$connectedCount" -gt 1 ]; then
    echo "WARN: ${connectedCount} HDMI connectors report 'connected' (${allHdmi# })." >&2
    echo "WARN: the output mode was NOT pinned -- this script will not guess which" >&2
    echo "WARN: one is the dashboard panel. Pin it by hand, or disconnect the other." >&2
    exit 0
fi

echo "Connected panel: ${connected}"

# ---- 5. the panel must advertise the target mode ----

advertised=""
[ -r "$connectedDir/modes" ] && advertised="$(cat "$connectedDir/modes")"

if ! printf '%s\n' "$advertised" | grep -qx "$TARGET_MODE"; then
    echo "WARN: ${connected} does not advertise ${TARGET_MODE} in its EDID mode list." >&2
    echo "WARN: it advertises: $(printf '%s' "$advertised" | tr '\n' ' ')" >&2
    echo "WARN: the output mode was NOT pinned. Forcing a timing the panel never" >&2
    echo "WARN: claimed can scan out black, and this Pi has no local recovery." >&2
    echo "WARN: if ${TARGET_MODE} is genuinely correct for this panel, that is an" >&2
    echo "WARN: EDID finding for Atlas (US-552) -- not something to force here." >&2
    exit 0
fi

# ---- 6. decide against what is already pinned ----

wantedToken="video=${connected}:${TARGET_MODE}"
existingToken="$(printf '%s' "$cmdLine" | grep -oE '(^|[[:space:]])video=[^[:space:]]+' | head -1 | tr -d '[:space:]')"

if [ "$existingToken" = "$wantedToken" ]; then
    echo "${wantedToken} is already pinned in ${CMDLINE} -- no change."
    echo "  ${cmdLine}"
    exit 0
fi

if [ -n "$existingToken" ]; then
    echo "WARN: ${CMDLINE} already carries '${existingToken}'." >&2
    echo "WARN: leaving it alone -- US-552 will not clobber an explicitly-set mode." >&2
    echo "WARN: to move to ${wantedToken}, edit ${CMDLINE} by hand and reboot." >&2
    echo "  ${cmdLine}"
    exit 0
fi

# ---- 7. apply ----

# Back up ONCE, first-write-wins, so the preserved copy is the pristine
# pre-Eclipse original rather than whatever a previous run left behind.
if [ ! -f "$BACKUP" ]; then
    if ! cp "$CMDLINE" "$BACKUP"; then
        echo "ERROR: could not write backup ${BACKUP}; refusing to modify the boot cmdline." >&2
        exit 2
    fi
    echo "Backed up ${CMDLINE} -> ${BACKUP} (pristine original)."
else
    echo "Backup ${BACKUP} already exists (kept -- it holds the pristine original)."
fi

newLine="${cmdLine} ${wantedToken}"

# Verify the COMPOSED line before it is installed, so the live boot cmdline is
# never wrong even for an instant. Every original token must survive: a rewrite
# that dropped `root=` or `rootwait` would boot to nothing, and this file is the
# one surface on the Pi with no local recovery path.
verifyLine() {
    local candidate="$1" token
    for token in $cmdLine; do
        printf '%s\n' "$candidate" | grep -qF -- "$token" || return 1
    done
    printf '%s\n' "$candidate" | grep -qF -- "$wantedToken" || return 1
    return 0
}

if ! verifyLine "$newLine"; then
    echo "ERROR: the composed boot cmdline lost an argument; ${CMDLINE} left unchanged." >&2
    exit 2
fi

tmp="$(dirname "$CMDLINE")/.cmdline.txt.eclipse-tmp.$$"
trap 'rm -f "$tmp"' EXIT

if ! printf '%s\n' "$newLine" > "$tmp"; then
    echo "ERROR: failed to compose the updated cmdline.txt; ${CMDLINE} unchanged." >&2
    exit 2
fi

if ! mv "$tmp" "$CMDLINE"; then
    echo "ERROR: failed to install the updated ${CMDLINE}." >&2
    echo "       The pristine copy is still at ${BACKUP}." >&2
    exit 2
fi

# Re-verify by re-reading the file we just wrote -- not by trusting the variable.
installedLines="$(grep -c '[^[:space:]]' "$CMDLINE")"
installedLine="$(grep -m1 '[^[:space:]]' "$CMDLINE")"

if [ "$installedLines" != "1" ] || ! verifyLine "$installedLine"; then
    echo "ERROR: post-write verification of ${CMDLINE} FAILED. Restoring the backup." >&2
    if cp "$BACKUP" "$CMDLINE"; then
        echo "ERROR: restored the pristine ${CMDLINE} from ${BACKUP}. DO NOT REBOOT" >&2
        echo "ERROR: until this is understood, and verify the file by hand first." >&2
    else
        echo "ERROR: THE RESTORE ALSO FAILED. ${CMDLINE} may be unbootable." >&2
        echo "ERROR: fix it by hand from ${BACKUP} BEFORE rebooting this Pi." >&2
    fi
    exit 2
fi

echo "Pinned the output mode to the panel's native ${TARGET_MODE}:"
echo "  ${installedLine}"
echo "REBOOT REQUIRED: the Pi keeps scanning out ${observedMode} until it reboots."
echo "  Confirm after reboot with: cat ${FB_SIZE_FILE}   (expect $(printf '%s' "$TARGET_MODE" | tr 'x' ','))"
exit 0
