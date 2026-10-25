#!/usr/bin/env bash
################################################################################
# eclipse-display-mode.sh -- choose the kiosk's display stack: X11 or Wayland
#                            (US-649-a / F-139)
#
# /etc/eclipse/display-mode holds exactly `x11` or `wayland` and is the ONLY
# authority for which kiosk variants are installed. An ABSENT file means
# $DISPLAY_MODE_DEFAULT, defined ONLY in deploy/lib/display-mode-default.sh
# (x11 today; US-652-a). The deploy and both kit installers read it; nothing chooses by detecting the
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
#   sudo eclipse-display-mode trigger
#   sudo eclipse-display-mode status
#
# lightdm is the display manager in BOTH modes (design A, CIO 2026-10-16,
# US-649-e): Wayland is lightdm's own autologin session `eclipse-kiosk`
# (deploy/wayland-sessions/eclipse-kiosk.desktop -> labwc), X11 is the
# session the car had before the first switch.
#
# x11|wayland, in order:
#   1. pre-flight -- lightdm.service is known to systemctl; for wayland also
#      the session file and labwc exist; lightdm.conf exists with a [Seat:*]
#      section; the state dir exists (never created here, the os-trim
#      requireStateDir rule). Any failure exits non-zero, nothing changed;
#   2. wayland: records the prior autologin-session / user-session values in
#      display-mode.state -- once, never rewritten (the os-trim G3 pattern) --
#      BEFORE the lightdm.conf edit (os-trim order, Atlas G2);
#   3. edits the two keys inside [Seat:*] of lightdm.conf by temp file +
#      rename (same mode and owner, never an in-place edit). wayland: eclipse-kiosk;
#      x11: the recorded priors, then the state file is deleted. An unrecorded
#      key still reading eclipse-kiosk falls back to rpd-x with ONE WARN;
#   4. writes the mode file and runs BOTH kit installers, forced to that mode;
#   5. applies the kiosk start trigger for the mode (the `trigger` verb below);
#   6. retires the old eclipse-compositor unit (disable if enabled, delete the
#      unit file), enables lightdm (never masked or purged), daemon-reload,
#      then reboots unless --no-reboot.
# trigger (US-651-a; deploy-pi.sh runs it every deploy) applies the CURRENT
# mode's kiosk start trigger and nothing else -- no lightdm edit, no kit run,
# no reboot: installs the latch eclipse-kiosk-start.target and BOTH .path
# units (rendered with the kiosk uid) every time, enables only the mode's
# .path (wayland: eclipse-kiosk-socket.path; x11: eclipse-x-ready.path plus the
# eclipse-x-ready.desktop autostart entry, which wayland removes) and disables
# the other .path only when `systemctl is-enabled` says it is enabled. Nothing
# is started: the .path takes effect at the next boot, so a deploy never
# re-shows the splash over a live dashboard.
# status prints the file's mode, the enabled display manager, lightdm's
# autologin session and the installed dashboard variant, and exits 1 on any
# mismatch.
# An unknown mode or flag exits 2 and changes nothing.
#
# Overrides (desk tests only):
#   KIOSK_MODE_FILE     the mode file          (default /etc/eclipse/display-mode)
#   KIOSK_TREE          the deployed repo tree (default: this script's ../)
#   KIOSK_SYSTEMD_DIR   where the kiosk units are installed (default /etc/systemd/system)
#   KIOSK_USER          the kiosk user forced into the kit installers (the
#                       installed wrapper sets it; unset => the kits' own V-1)
#   KIOSK_UID           the kiosk uid (desk tests only). ONE uid source: unset,
#                       it is `id -u $KIOSK_USER`, the kit installers' own
#                       derivation; set, it is forced into the kits too, so the
#                       .path units and the kiosk units name one /run/user/<uid>
#   KIOSK_AUTOSTART_DIR the XDG autostart dir (default /etc/xdg/autostart)
#   KIOSK_LIGHTDM_CONF  lightdm's config       (default /etc/lightdm/lightdm.conf)
#   KIOSK_SESSION_FILE  the kiosk session file (default
#                       /usr/share/wayland-sessions/eclipse-kiosk.desktop)
#   KIOSK_LABWC_BIN     the compositor binary  (default /usr/bin/labwc)
#   KIOSK_STATE_DIR     holds display-mode.state (default /var/lib/eclipse-obd)
################################################################################
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

# US-652-a: what an absent mode file means lives in ONE file, beside this one
# in the deployed tree (deploy/lib/display-mode-default.sh). Missing => every
# verb refuses before anything is read or changed; never a silent x11.
DISPLAY_MODE_DEFAULT_LIB="$SCRIPT_DIR/lib/display-mode-default.sh"
if [ ! -r "$DISPLAY_MODE_DEFAULT_LIB" ]; then
    echo "ERROR: display-mode default lib not found at '$DISPLAY_MODE_DEFAULT_LIB' -- nothing changed." >&2
    exit 1
fi
# shellcheck source=lib/display-mode-default.sh
. "$DISPLAY_MODE_DEFAULT_LIB"

MODE_FILE="${KIOSK_MODE_FILE:-/etc/eclipse/display-mode}"
TREE="${KIOSK_TREE:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
SYSTEMD_DIR="${KIOSK_SYSTEMD_DIR:-/etc/systemd/system}"
AUTOSTART_DIR="${KIOSK_AUTOSTART_DIR:-/etc/xdg/autostart}"
DASH_UNIT="eclipse-dashboard.service"
# US-651-a: the kiosk start trigger. Each mode's .path starts the latch, which
# Wants= splash-boot; in x11 the autostart entry writes the .path's marker.
LATCH_UNIT="eclipse-kiosk-start.target"
SOCKET_PATH_UNIT="eclipse-kiosk-socket.path"
X_READY_PATH_UNIT="eclipse-x-ready.path"
X_READY_DESKTOP="eclipse-x-ready.desktop"
TRIGGER_FILES=("$LATCH_UNIT" "$SOCKET_PATH_UNIT" "$X_READY_PATH_UNIT" "$X_READY_DESKTOP")
LIGHTDM="lightdm.service"
# Retired by design A; still on cars switched to Wayland before US-649-e.
COMPOSITOR="eclipse-compositor.service"
LIGHTDM_CONF="${KIOSK_LIGHTDM_CONF:-/etc/lightdm/lightdm.conf}"
SESSION_FILE="${KIOSK_SESSION_FILE:-/usr/share/wayland-sessions/eclipse-kiosk.desktop}"
LABWC_BIN="${KIOSK_LABWC_BIN:-/usr/bin/labwc}"
# Same dir as os-trim.state; deploy-pi.sh provisions it (US-667).
STATE_DIR="${KIOSK_STATE_DIR:-/var/lib/eclipse-obd}"
STATE_FILE="$STATE_DIR/display-mode.state"
# lightdm names a session by its .desktop file's basename.
KIOSK_SESSION="eclipse-kiosk"
# Raspberry Pi OS's X11 desktop session, what lightdm.conf holds on today's car
# (US-649-e acceptance: the fixed inverse when no prior was recorded).
X11_SESSION="rpd-x"
SESSION_KEYS=(autologin-session user-session)

usage() {
    echo "usage: eclipse-display-mode x11|wayland|trigger|status [--no-reboot]" >&2
    exit 2
}

# The mode the file declares. Absent => $DISPLAY_MODE_DEFAULT (the lib); any
# other content is printed as-is so the caller can reject it rather than
# default it.
read_mode() {
    if [ -f "$MODE_FILE" ]; then
        tr -d '[:space:]' < "$MODE_FILE"
    else
        printf '%s' "$DISPLAY_MODE_DEFAULT"
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

# The value of key $1 in lightdm.conf's [Seat:*] section (the last one wins,
# as in lightdm). Commented lines and other sections are ignored. Exits 1
# when the key is not set there.
seat_value() {
    awk -v want="$1" '
        /^[[:space:]]*\[/ { inseat = ($0 ~ /^[[:space:]]*\[Seat:\*\][[:space:]]*$/); next }
        inseat && /^[[:space:]]*[^#;[:space:]][^=]*=/ {
            key = $0; sub(/^[[:space:]]*/, "", key); sub(/[[:space:]]*=.*$/, "", key)
            if (key == want) {
                v = $0; sub(/^[^=]*=[[:space:]]*/, "", v); sub(/[[:space:]]*$/, "", v)
                found = 1
            }
        }
        END { if (found) print v; exit !found }
    ' "$LIGHTDM_CONF"
}

has_seat_section() {
    grep -q '^[[:space:]]*\[Seat:\*\][[:space:]]*$' "$LIGHTDM_CONF"
}

cmd_status() {
    local mode dm variant session problems=()
    mode="$(read_mode)"
    case "$mode" in
        x11|wayland) ;;
        *)
            echo "mode file: ${mode:-<empty>} | MISMATCH: $MODE_FILE must hold x11 or wayland"
            return 1
            ;;
    esac
    dm="$(enabled_display_manager)"
    variant="$(installed_dashboard_variant)"

    if [ ! -f "$LIGHTDM_CONF" ]; then
        session="<missing>"
        problems+=("lightdm.conf missing")
    elif session="$(seat_value autologin-session)" && [ -n "$session" ]; then
        if [ "$mode" = wayland ] && [ "$session" != "$KIOSK_SESSION" ]; then
            problems+=("lightdm session is $session, mode wayland needs $KIOSK_SESSION")
        elif [ "$mode" = x11 ] && [ "$session" = "$KIOSK_SESSION" ]; then
            problems+=("lightdm session is $KIOSK_SESSION, mode x11 needs an X11 session")
        fi
    else
        session="<unset>"
        problems+=("autologin-session unset")
    fi
    [ "$variant" = "$mode" ] || problems+=("dashboard variant is $variant, mode is $mode")
    systemctl is-enabled "$LIGHTDM" >/dev/null 2>&1 || problems+=("$LIGHTDM not enabled")
    if systemctl is-enabled "$COMPOSITOR" >/dev/null 2>&1; then
        problems+=("$COMPOSITOR still enabled")
    fi

    local line="mode file: $mode | display-manager: $dm | lightdm session: $session | dashboard variant: $variant"
    if [ "${#problems[@]}" -eq 0 ]; then
        echo "$line | OK"
        return 0
    fi
    local joined
    joined="$(IFS=';'; printf '%s' "${problems[*]}")"
    echo "$line | MISMATCH: ${joined//;/, }"
    return 1
}

# Pre-flight for a switch to $1: everything the switch needs, checked before
# anything changes.
preflight() {
    local mode="$1"
    if ! systemctl cat "$LIGHTDM" >/dev/null 2>&1; then
        echo "ERROR: $LIGHTDM is not installed -- nothing changed." >&2
        return 1
    fi
    if [ "$mode" = wayland ]; then
        if [ ! -f "$SESSION_FILE" ]; then
            echo "ERROR: kiosk session file $SESSION_FILE missing (deploy-pi.sh installs it) -- nothing changed." >&2
            return 1
        fi
        if [ ! -x "$LABWC_BIN" ]; then
            echo "ERROR: $LABWC_BIN missing -- nothing changed." >&2
            return 1
        fi
    fi
    if [ ! -f "$LIGHTDM_CONF" ]; then
        echo "ERROR: $LIGHTDM_CONF missing -- nothing changed." >&2
        return 1
    fi
    if ! has_seat_section; then
        echo "ERROR: $LIGHTDM_CONF has no [Seat:*] section -- nothing changed." >&2
        return 1
    fi
    if [ ! -d "$STATE_DIR" ]; then
        echo "ERROR: state dir $STATE_DIR does not exist -- deploy-pi.sh provisions it (US-667); this command will not create it. Nothing changed." >&2
        return 1
    fi
    trigger_preflight
}

# The kiosk uid: KIOSK_UID if set (desk override), else `id -u $KIOSK_USER` --
# the derivation the kit installers use for the units' /run/user/<uid>. Prints
# nothing unless that is a number.
kiosk_uid() {
    local uid=""
    if [ -n "${KIOSK_UID:-}" ]; then
        uid="$KIOSK_UID"
    elif [ -n "${KIOSK_USER:-}" ]; then
        uid="$(id -u "$KIOSK_USER" 2>/dev/null || true)"
    fi
    case "$uid" in
        ''|*[!0-9]*) return 0 ;;
    esac
    printf '%s' "$uid"
}

# What the trigger needs, checked before anything changes: a numeric kiosk uid
# (never a /run/user/0 fallback, I-044) and its four source files in the tree.
trigger_preflight() {
    local f
    if [ -z "$(kiosk_uid)" ]; then
        echo "ERROR: cannot resolve the kiosk uid (KIOSK_USER='${KIOSK_USER:-}', KIOSK_UID='${KIOSK_UID:-}') -- nothing changed." >&2
        return 1
    fi
    for f in "${TRIGGER_FILES[@]}"; do
        if [ ! -f "$TREE/deploy/$f" ]; then
            echo "ERROR: $TREE/deploy/$f missing -- nothing changed." >&2
            return 1
        fi
    done
}

# Install deploy/$1 as $2 with __PI_UID__ rendered as $3, by temp file + rename.
install_rendered() {
    local src="$TREE/deploy/$1" dest="$2" uid="$3" tmp
    tmp="$dest.tmp.$$"
    if ! sed -e "s/__PI_UID__/$uid/g" "$src" > "$tmp" || ! chmod 0644 "$tmp" \
            || ! mv -f "$tmp" "$dest"; then
        rm -f "$tmp"
        echo "ERROR: could not install $dest" >&2
        return 1
    fi
}

# Apply mode $1's kiosk start trigger (see `trigger` in the header).
apply_trigger() {
    local mode="$1" uid on off
    uid="$(kiosk_uid)"
    if [ "$mode" = wayland ]; then
        on="$SOCKET_PATH_UNIT"; off="$X_READY_PATH_UNIT"
    else
        on="$X_READY_PATH_UNIT"; off="$SOCKET_PATH_UNIT"
    fi
    echo "==> kiosk start trigger for $mode (uid $uid): $on"
    mkdir -p "$SYSTEMD_DIR"
    install_rendered "$LATCH_UNIT" "$SYSTEMD_DIR/$LATCH_UNIT" "$uid" || return 1
    install_rendered "$SOCKET_PATH_UNIT" "$SYSTEMD_DIR/$SOCKET_PATH_UNIT" "$uid" || return 1
    install_rendered "$X_READY_PATH_UNIT" "$SYSTEMD_DIR/$X_READY_PATH_UNIT" "$uid" || return 1
    if [ "$mode" = x11 ]; then
        mkdir -p "$AUTOSTART_DIR"
        install_rendered "$X_READY_DESKTOP" "$AUTOSTART_DIR/$X_READY_DESKTOP" "$uid" || return 1
    else
        rm -f "$AUTOSTART_DIR/$X_READY_DESKTOP"
    fi
    systemctl daemon-reload
    if systemctl is-enabled "$off" >/dev/null 2>&1; then
        systemctl disable "$off"
    fi
    systemctl enable "$on"
}

cmd_trigger() {
    local mode
    mode="$(read_mode)"
    case "$mode" in
        x11|wayland) ;;
        *)
            echo "ERROR: $MODE_FILE holds '${mode:-<empty>}', not x11|wayland -- nothing changed." >&2
            return 1
            ;;
    esac
    trigger_preflight || return 1
    apply_trigger "$mode"
}

# The prior value of key $1 recorded by the first switch to wayland
# ('absent' = the key was not set). Exits 1 when nothing is recorded.
recorded_prior() {
    local line
    [ -f "$STATE_FILE" ] || return 1
    line="$(grep -m1 -E "^$1=" "$STATE_FILE")" || return 1
    printf '%s' "${line#*=}"
}

# Record each key's value as it is NOW, before the lightdm.conf edit. Lines
# already recorded are never rewritten (os-trim recordPreState, Atlas G3); a
# value that is already eclipse-kiosk is not a prior and is never recorded.
record_priors() {
    local tmp="$STATE_FILE.tmp.$$" key cur added=()
    for key in "${SESSION_KEYS[@]}"; do
        recorded_prior "$key" >/dev/null && continue
        if cur="$(seat_value "$key")"; then
            [ "$cur" = "$KIOSK_SESSION" ] && continue
            added+=("$key=$cur")
        else
            added+=("$key=absent")
        fi
    done
    if [ "${#added[@]}" -eq 0 ]; then
        echo "==> lightdm priors: nothing new to record"
        return 0
    fi
    {
        if [ -f "$STATE_FILE" ]; then cat "$STATE_FILE"; fi
        printf '%s\n' "${added[@]}"
    } > "$tmp" || {
        rm -f "$tmp"
        echo "ERROR: could not write $tmp -- nothing changed." >&2
        return 1
    }
    if ! mv "$tmp" "$STATE_FILE"; then
        rm -f "$tmp"
        echo "ERROR: could not install $STATE_FILE -- nothing changed." >&2
        return 1
    fi
    echo "==> lightdm priors recorded in $STATE_FILE: ${added[*]}"
}

# Point [Seat:*]'s two session keys at mode $1, by temp file + rename. Only
# those two key lines change; comments and other sections are byte-identical.
edit_lightdm_conf() {
    local mode="$1" key cur present target prior edits="" fallback=() tmp
    for key in "${SESSION_KEYS[@]}"; do
        present=yes
        cur="$(seat_value "$key")" || { present=no; cur=""; }
        if [ "$mode" = wayland ]; then
            target="$KIOSK_SESSION"
        elif prior="$(recorded_prior "$key")"; then
            if [ "$prior" = absent ]; then
                [ "$present" = yes ] && edits+="del"$'\t'"$key"$'\n'
                continue
            fi
            target="$prior"
        elif [ "$present" = yes ] && [ "$cur" = "$KIOSK_SESSION" ]; then
            target="$X11_SESSION"
            fallback+=("$key")
        else
            # No prior and not ours: someone else's value, left alone.
            continue
        fi
        if [ "$present" = no ]; then
            edits+="add"$'\t'"$key"$'\t'"$target"$'\n'
        elif [ "$cur" != "$target" ]; then
            edits+="set"$'\t'"$key"$'\t'"$target"$'\n'
        fi
    done
    if [ "${#fallback[@]}" -gt 0 ]; then
        echo "WARN: no recorded lightdm prior for ${fallback[*]} in $STATE_FILE -- set to $X11_SESSION (fixed inverse)." >&2
    fi
    if [ -z "$edits" ]; then
        echo "==> $LIGHTDM_CONF already set for $mode"
        return 0
    fi
    # Root may rename over any file; a read-only lightdm.conf is a refusal.
    if [ ! -w "$LIGHTDM_CONF" ]; then
        echo "ERROR: $LIGHTDM_CONF is not writable -- lightdm.conf unchanged." >&2
        return 1
    fi
    tmp="$LIGHTDM_CONF.tmp.$$"
    DM_EDITS="$edits" awk '
        BEGIN {
            n = split(ENVIRON["DM_EDITS"], rows, "\n")
            for (i = 1; i <= n; i++) {
                if (rows[i] == "") continue
                split(rows[i], f, "\t")
                op[f[2]] = f[1]; val[f[2]] = f[3]
                if (f[1] == "add") adds[++na] = f[2]
            }
        }
        /^[[:space:]]*\[/ {
            inseat = ($0 ~ /^[[:space:]]*\[Seat:\*\][[:space:]]*$/)
            print
            # A key missing from [Seat:*] goes directly under its header.
            if (inseat && !addedKeys) {
                for (j = 1; j <= na; j++) print adds[j] "=" val[adds[j]]
                addedKeys = 1
            }
            next
        }
        inseat && /^[[:space:]]*[^#;[:space:]][^=]*=/ {
            key = $0; sub(/^[[:space:]]*/, "", key); sub(/[[:space:]]*=.*$/, "", key)
            if (op[key] == "del") next
            if (op[key] == "set") { print key "=" val[key]; next }
        }
        { print }
    ' "$LIGHTDM_CONF" > "$tmp" || {
        rm -f "$tmp"
        echo "ERROR: could not write $tmp -- lightdm.conf unchanged." >&2
        return 1
    }
    if ! chmod --reference="$LIGHTDM_CONF" "$tmp" || ! chown --reference="$LIGHTDM_CONF" "$tmp"; then
        rm -f "$tmp"
        echo "ERROR: could not copy the mode/owner of $LIGHTDM_CONF -- lightdm.conf unchanged." >&2
        return 1
    fi
    if ! mv -f "$tmp" "$LIGHTDM_CONF"; then
        rm -f "$tmp"
        echo "ERROR: could not rename $tmp over $LIGHTDM_CONF -- lightdm.conf unchanged." >&2
        return 1
    fi
    echo "==> $LIGHTDM_CONF [Seat:*] set for $mode"
}

# Run one kit installer from the deployed tree, forced to $1. The env is set
# INSIDE the call so nothing depends on sudo preserving it.
run_kit() {
    local mode="$1" prefix="$2" kit="$TREE/$3"
    local forced=("${prefix}_FORCE_SESSION=$mode")
    if [ ! -f "$kit" ]; then
        echo "ERROR: kit installer missing: $kit" >&2
        return 1
    fi
    if [ -n "${KIOSK_USER:-}" ]; then
        forced+=("${prefix}_FORCE_USER=$KIOSK_USER")
    fi
    # A desk KIOSK_UID reaches the units' rendering too: one uid source.
    if [ -n "${KIOSK_UID:-}" ]; then
        forced+=("${prefix}_FORCE_UID=$(kiosk_uid)")
    fi
    env "${forced[@]}" bash "$kit"
}

cmd_switch() {
    local mode="$1" reboot="$2"
    # (1) Pre-flight BEFORE anything changes.
    preflight "$mode" || return 1

    # (2) Priors first, then (3) the edit: a failed edit still leaves the
    # values the revert needs (os-trim order, Atlas G2).
    if [ "$mode" = wayland ]; then
        record_priors || return 1
    fi
    edit_lightdm_conf "$mode" || return 1
    if [ "$mode" = x11 ] && [ -f "$STATE_FILE" ]; then
        # Reverted: the priors are back in lightdm.conf (os-trim revert, Atlas Q29).
        rm -f "$STATE_FILE"
    fi

    # (4) The mode file and both kits.
    echo "==> display mode -> $mode ($MODE_FILE)"
    mkdir -p "$(dirname -- "$MODE_FILE")"
    printf '%s\n' "$mode" > "$MODE_FILE"

    echo "==> installing the $mode kiosk units from $TREE"
    run_kit "$mode" SPLASH src/pi/ui/splash/install.sh
    run_kit "$mode" DASHBOARD src/pi/ui/dashboard/install.sh

    # (5) The kiosk start trigger for the new mode (US-651-a).
    apply_trigger "$mode" || return 1

    # (6) lightdm in both modes. The old compositor goes first: both claim
    # display-manager.service.
    echo "==> display manager: $LIGHTDM (retiring $COMPOSITOR)"
    if systemctl is-enabled "$COMPOSITOR" >/dev/null 2>&1; then
        systemctl disable "$COMPOSITOR"
    fi
    if [ -f "$SYSTEMD_DIR/$COMPOSITOR" ]; then
        rm -f "$SYSTEMD_DIR/$COMPOSITOR"
    fi
    systemctl enable "$LIGHTDM"
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
            x11|wayland|trigger|status)
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
        trigger)     cmd_trigger ;;
        x11|wayland) cmd_switch "$verb" "$reboot" ;;
        *)           usage ;;
    esac
}

main "$@"
