#!/usr/bin/env bash
################################################################################
# eclipse-capture-panel.sh -- screenshot the running panel in either display
#                             mode (US-650 / F-139)
#
# Reads /etc/eclipse/display-mode (absent => $DISPLAY_MODE_DEFAULT from
# deploy/lib/display-mode-default.sh, wayland since US-652-b; US-649-a, US-652-a)
# and captures with
# the tool for that stack, run as the kiosk user:
#   wayland -> grim  with XDG_RUNTIME_DIR=/run/user/<uid> WAYLAND_DISPLAY=wayland-0
#              (labwc's wlr-screencopy; scrot cannot see a Wayland panel)
#   x11     -> scrot with DISPLAY=:0
# Writes /tmp/eclipse-panel-<utc>.png and prints that path on stdout.
#
# READ-ONLY: it never writes the mode file or touches a unit. It reads the
# mode file, never the running session -- the same authority the deploy uses.
#
# Installed by deploy-pi.sh as /usr/local/bin/eclipse-capture-panel, a wrapper
# that runs THIS file from the deployed tree with KIOSK_USER baked in.
#
# On failure: exit 1 and one `ERROR: <reason> -- ...` line on stderr, reason one of
#   no_mode_tool    the mode has no capture tool, or its tool is not installed
#   no_socket       wayland mode but /run/user/<uid>/wayland-0 does not exist
#   capture_failed  the tool failed, or left no non-empty image behind
#   no_default_lib  deploy/lib/display-mode-default.sh is missing beside this file
#
# Overrides (desk tests only):
#   KIOSK_MODE_FILE     the mode file   (default /etc/eclipse/display-mode)
#   KIOSK_USER          the kiosk user  (default mcornelison, the Pi user the kiosk session runs as)
#   KIOSK_UID           its uid         (default: id -u "$KIOSK_USER")
#   KIOSK_RUNTIME_ROOT  runtime dirs    (default /run/user)
################################################################################
set -euo pipefail

MODE_FILE="${KIOSK_MODE_FILE:-/etc/eclipse/display-mode}"
KIOSK_USER="${KIOSK_USER:-mcornelison}"
RUNTIME_ROOT="${KIOSK_RUNTIME_ROOT:-/run/user}"

fail() {
    echo "ERROR: $1 -- $2" >&2
    exit 1
}

# US-652-a: what an absent mode file means lives in ONE file, beside this one
# in the deployed tree. Missing => refuse before reading anything.
DISPLAY_MODE_DEFAULT_LIB="$(dirname -- "${BASH_SOURCE[0]}")/lib/display-mode-default.sh"
[ -r "$DISPLAY_MODE_DEFAULT_LIB" ] \
    || fail no_default_lib "display-mode default lib not found at '$DISPLAY_MODE_DEFAULT_LIB' (deploy/lib/display-mode-default.sh) -- nothing captured"
# shellcheck source=lib/display-mode-default.sh
. "$DISPLAY_MODE_DEFAULT_LIB"

# Same reading as eclipse-display-mode: absent => $DISPLAY_MODE_DEFAULT (the
# lib), anything else as-is.
read_mode() {
    if [ -f "$MODE_FILE" ]; then
        tr -d '[:space:]' < "$MODE_FILE"
    else
        printf '%s' "$DISPLAY_MODE_DEFAULT"
    fi
}

kiosk_uid() {
    if [ -n "${KIOSK_UID:-}" ]; then
        printf '%s' "$KIOSK_UID"
    else
        id -u "$KIOSK_USER" 2>/dev/null \
            || fail capture_failed "kiosk user '$KIOSK_USER' does not exist"
    fi
}

# Run "$@" as the kiosk user: directly if we already are, else through sudo.
as_kiosk_user() {
    if [ "$(id -u)" = "$uid" ]; then
        "$@"
    else
        sudo -u "$KIOSK_USER" "$@"
    fi
}

mode="$(read_mode)"
case "$mode" in
    wayland) tool=grim ;;
    x11)     tool=scrot ;;
    *)       fail no_mode_tool "$MODE_FILE holds '${mode:-<empty>}', not x11|wayland -- no capture tool for it" ;;
esac
command -v "$tool" >/dev/null 2>&1 \
    || fail no_mode_tool "$tool is not installed (needed for $mode mode)"

uid="$(kiosk_uid)"
out="/tmp/eclipse-panel-$(date -u +%Y%m%dT%H%M%SZ).png"

if [ "$mode" = wayland ]; then
    runtimeDir="$RUNTIME_ROOT/$uid"
    # -e, not -S: a stale non-socket here makes grim fail -> capture_failed.
    [ -e "$runtimeDir/wayland-0" ] \
        || fail no_socket "$runtimeDir/wayland-0 does not exist -- is the kiosk session running (lightdm, eclipse-kiosk)?"
    as_kiosk_user env XDG_RUNTIME_DIR="$runtimeDir" WAYLAND_DISPLAY=wayland-0 grim "$out" >&2 \
        || fail capture_failed "grim exited non-zero"
else
    as_kiosk_user env -u WAYLAND_DISPLAY DISPLAY=:0 scrot "$out" >&2 \
        || fail capture_failed "scrot exited non-zero"
fi

[ -s "$out" ] || fail capture_failed "$tool left no image at $out"
echo "$out"
