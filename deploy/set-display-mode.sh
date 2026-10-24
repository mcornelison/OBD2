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

# The ONE cmdline.txt token editor every boot-line writer shares (US-885-a):
# set-boot-screen.sh edits the same line, and neither may clobber the other.
CMDLINE_TOKENS_LIB="$(dirname "${BASH_SOURCE[0]}")/lib/cmdline-tokens.sh"
if [ ! -r "$CMDLINE_TOKENS_LIB" ]; then
    echo "ERROR: shared cmdline helper not found at '${CMDLINE_TOKENS_LIB}'." >&2
    echo "       Nothing was written." >&2
    exit 1
fi
# shellcheck source=lib/cmdline-tokens.sh
. "$CMDLINE_TOKENS_LIB"

# ---- 1. validate the target mode BEFORE reading anything else ----

if ! printf '%s' "$TARGET_MODE" | grep -qE '^[0-9]+x[0-9]+$'; then
    echo "ERROR: ECLIPSE_DISPLAY_MODE='${TARGET_MODE}' is not a WxH mode string." >&2
    echo "       Expected e.g. 480x320. Nothing was written." >&2
    exit 1
fi

# ---- 2. the boot cmdline must exist and be a boot cmdline ----
#
# The checks themselves (present, readable, exactly ONE non-blank line, carries
# `root=`) live in the shared token helper (US-885-a), so every boot-line writer
# refuses the same malformed file for the same reasons.

if ! cmdline_check "$CMDLINE"; then
    exit 1
fi

cmdLine="$(cmdline_read_line "$CMDLINE")"

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
existingToken="$(cmdline_named_token "$CMDLINE" video)"

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
#
# The shared helper backs up ONCE (first-write-wins, so the preserved copy is
# the pristine pre-Eclipse original), verifies the COMPOSED line before it is
# installed -- every original token, `root=` included, must survive, since this
# file is the one surface on the Pi with no local recovery path -- installs it
# via a temp file + mv, re-reads and re-verifies it, and restores the backup on
# a post-write mismatch.

if ! cmdline_add_token "$CMDLINE" "$wantedToken" "$BACKUP"; then
    exit 2
fi

installedLine="$(cmdline_read_line "$CMDLINE")"

echo "Pinned the output mode to the panel's native ${TARGET_MODE}:"
echo "  ${installedLine}"
echo "REBOOT REQUIRED: the Pi keeps scanning out ${observedMode} until it reboots."
echo "  Confirm after reboot with: cat ${FB_SIZE_FILE}   (expect $(printf '%s' "$TARGET_MODE" | tr 'x' ','))"
exit 0
