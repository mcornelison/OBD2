#!/usr/bin/env bash
################################################################################
# eclipse-display-mode.sh -- choose the kiosk's display stack: X11 or Wayland
#                            (US-649-a / F-139)
#
# /etc/eclipse/display-mode holds exactly `x11` or `wayland` and is the ONLY
# authority for which kiosk variants are installed. An ABSENT file means x11.
# The deploy and both kit installers read it; nothing chooses by detecting the
# running session any more (a deploy run while X11 was up used to re-install
# X11 over a Wayland choice -- Atlas, measured trap).
#
# NAME CLASH, not the same thing: deploy/set-display-mode.sh pins the HDMI
# RESOLUTION in cmdline.txt (US-552). This command never reads or sets that.
#
# Installed by deploy-pi.sh as /usr/local/sbin/eclipse-display-mode, a wrapper
# that runs THIS file from the deployed tree, so it works offline.
#
# Usage (on the Pi):
#   sudo eclipse-display-mode x11|wayland [--no-reboot]
#   sudo eclipse-display-mode status
#
# x11|wayland, in order:
#   1. writes the mode file;
#   2. runs BOTH kit installers from the deployed tree, forced to that mode;
#   3. swaps the display manager -- wayland: disable lightdm, enable
#      eclipse-compositor; x11: the reverse. The outgoing one goes first: both
#      claim display-manager.service. lightdm is DISABLED only, never removed --
#      this command is its only owner, and the one-command revert depends on it;
#   4. daemon-reload, then reboots unless --no-reboot.
# status prints the file's mode, the enabled display manager and the installed
# dashboard variant, and exits 1 on any mismatch.
# An unknown mode or flag exits 2 and changes nothing.
#
# Overrides (desk tests only):
#   KIOSK_MODE_FILE     the mode file          (default /etc/eclipse/display-mode)
#   KIOSK_TREE          the deployed repo tree (default: this script's ../)
#   KIOSK_SYSTEMD_DIR   where the kiosk units are installed (default /etc/systemd/system)
#   KIOSK_USER          the kiosk user forced into the kit installers (the
#                       installed wrapper sets it; unset => the kits' own V-1)
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
MODE_FILE="${KIOSK_MODE_FILE:-/etc/eclipse/display-mode}"
TREE="${KIOSK_TREE:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
SYSTEMD_DIR="${KIOSK_SYSTEMD_DIR:-/etc/systemd/system}"
DASH_UNIT="eclipse-dashboard.service"
LIGHTDM="lightdm.service"
COMPOSITOR="eclipse-compositor.service"

usage() {
    echo "usage: eclipse-display-mode x11|wayland|status [--no-reboot]" >&2
    exit 2
}

# The mode the file declares. Absent => x11; any other content is printed
# as-is so the caller can reject it rather than default it.
read_mode() {
    if [ -f "$MODE_FILE" ]; then
        tr -d '[:space:]' < "$MODE_FILE"
    else
        printf 'x11'
    fi
}

# The enabled display manager(s): one name, `a+b` if both, `none` if neither.
enabled_display_manager() {
    local found=()
    local unit
    for unit in "$LIGHTDM" "$COMPOSITOR"; do
        if systemctl is-enabled "$unit" >/dev/null 2>&1; then
            found+=("$unit")
        fi
    done
    if [ "${#found[@]}" -eq 0 ]; then
        printf 'none'
    else
        (IFS=+; printf '%s' "${found[*]}")
    fi
}

# The installed dashboard variant, read from the unit's own Environment= lines:
# only the .wayland variant sets WAYLAND_DISPLAY, only the .x11 one DISPLAY.
installed_dashboard_variant() {
    local unit="$SYSTEMD_DIR/$DASH_UNIT"
    if [ ! -f "$unit" ]; then
        printf 'none'
    elif grep -q '^Environment=WAYLAND_DISPLAY=' "$unit"; then
        printf 'wayland'
    elif grep -q '^Environment=DISPLAY=' "$unit"; then
        printf 'x11'
    else
        printf 'unknown'
    fi
}

cmd_status() {
    local mode dm variant expectedDm problems=()
    mode="$(read_mode)"
    dm="$(enabled_display_manager)"
    variant="$(installed_dashboard_variant)"
    case "$mode" in
        x11)     expectedDm="$LIGHTDM" ;;
        wayland) expectedDm="$COMPOSITOR" ;;
        *)
            echo "mode file: ${mode:-<empty>} | MISMATCH: $MODE_FILE must hold x11 or wayland"
            return 1
            ;;
    esac
    [ "$dm" = "$expectedDm" ] || problems+=("display-manager is $dm, mode $mode needs $expectedDm")
    [ "$variant" = "$mode" ] || problems+=("dashboard variant is $variant, mode is $mode")

    local line="mode file: $mode | display-manager: $dm | dashboard variant: $variant"
    if [ "${#problems[@]}" -eq 0 ]; then
        echo "$line | OK"
        return 0
    fi
    local joined
    joined="$(IFS=';'; printf '%s' "${problems[*]}")"
    echo "$line | MISMATCH: ${joined//;/; }"
    return 1
}

# Run one kit installer from the deployed tree, forced to $1. The env is set
# INSIDE the call so nothing depends on sudo preserving it.
run_kit() {
    local mode="$1" prefix="$2" kit="$TREE/$3"
    if [ ! -f "$kit" ]; then
        echo "ERROR: kit installer missing: $kit" >&2
        return 1
    fi
    if [ -n "${KIOSK_USER:-}" ]; then
        env "${prefix}_FORCE_SESSION=$mode" "${prefix}_FORCE_USER=$KIOSK_USER" bash "$kit"
    else
        env "${prefix}_FORCE_SESSION=$mode" bash "$kit"
    fi
}

cmd_switch() {
    local mode="$1" reboot="$2" outgoing incoming
    if [ "$mode" = wayland ]; then
        outgoing="$LIGHTDM"; incoming="$COMPOSITOR"
    else
        outgoing="$COMPOSITOR"; incoming="$LIGHTDM"
    fi
    # Pre-flight BEFORE anything changes: the display manager we switch TO must
    # exist, or the box would reboot with no display manager at all.
    if ! systemctl cat "$incoming" >/dev/null 2>&1; then
        echo "ERROR: $incoming is not installed -- nothing changed." >&2
        return 1
    fi

    echo "==> display mode -> $mode ($MODE_FILE)"
    mkdir -p "$(dirname -- "$MODE_FILE")"
    printf '%s\n' "$mode" > "$MODE_FILE"

    echo "==> installing the $mode kiosk units from $TREE"
    run_kit "$mode" SPLASH src/pi/ui/splash/install.sh
    run_kit "$mode" DASHBOARD src/pi/ui/dashboard/install.sh

    echo "==> display manager: $outgoing -> $incoming"
    # The outgoing unit may not exist (the compositor before it is deployed):
    # then there is nothing to disable.
    if systemctl cat "$outgoing" >/dev/null 2>&1; then
        systemctl disable "$outgoing"
    fi
    systemctl enable "$incoming"
    systemctl daemon-reload

    if [ "$reboot" = yes ]; then
        echo "==> rebooting into $mode"
        systemctl reboot
    else
        echo "==> --no-reboot: $mode takes effect at the next boot"
    fi
}

main() {
    local verb="" reboot=yes arg
    for arg in "$@"; do
        case "$arg" in
            --no-reboot) reboot=no ;;
            x11|wayland|status)
                [ -z "$verb" ] || usage
                verb="$arg"
                ;;
            *)
                echo "ERROR: unknown mode or flag: $arg" >&2
                usage
                ;;
        esac
    done
    case "$verb" in
        status)      cmd_status ;;
        x11|wayland) cmd_switch "$verb" "$reboot" ;;
        *)           usage ;;
    esac
}

main "$@"
