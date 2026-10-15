#!/usr/bin/env bash
################################################################################
# os-trim.sh — reversible OS trim: mask/disable services a car never uses
#              (US-866 / US-859 / F-157)
#
# Applies, or reverts, every entry of deploy/os-trim.manifest. The Pi runs a
# full desktop image; cloud-init sits on the boot critical chain and cups,
# wait-online, the apt timers, udisks2, ModemManager and e2scrub cost boot time
# for nothing in a car (Atlas, boot 7c6aafaa). The evidence for each entry is in
# the manifest beside it.
#
# MASK OR DISABLE, NEVER PURGE. The car has no network at key-on, so a purged
# package could not be reinstalled there. Every action here is undone offline,
# from the SAME manifest, by `revert`.
#
# Usage (run on the Pi):
#   sudo bash deploy/os-trim.sh apply  [--dry-run]
#   sudo bash deploy/os-trim.sh revert [--dry-run]
#
# apply:
#   - The FIRST apply records each entry's pre-state (`systemctl is-enabled`
#     output, or whether the flag file exists) in ${STATE_FILE}, written to a
#     temp file and renamed. A later apply NEVER overwrites it: step_os_trim
#     re-asserts on every deploy, and a pre-state recorded after the first trim
#     would record the trimmed state and restore nothing (Atlas G3).
#   - Then performs each entry's action, idempotently: mask / disable / create
#     the flag file. Nothing is stopped now; it takes effect at the next boot.
# revert:
#   - Restores each entry to its recorded pre-state, then deletes the state
#     file. A unit that was already disabled or masked before the first apply
#     stays that way.
#   - With no state file: applies the fixed inverse (unmask / enable / delete
#     the flag file) and prints one WARN.
# --dry-run prints exactly one line per entry and changes nothing.
#
# FAIL LOUD (one ERROR line naming the path, non-zero exit, no systemctl call):
#   - the manifest is missing or does not parse -- a missing manifest is never
#     "nothing to trim";
#   - the state dir /var/lib/eclipse-obd is absent. deploy-pi.sh provisions it
#     (US-667, step_install_persistent_state_dir); a silent mkdir here would
#     hide a deploy that never ran that step.
#
# Test seams (production leaves them unset):
#   $OS_TRIM_MANIFEST   manifest path        (default: beside this script)
#   $OS_TRIM_STATE_DIR  pre-state directory  (default: /var/lib/eclipse-obd)
#   $OS_TRIM_ROOT       prefix for flag-file paths (default: empty, i.e. /)
#   $SYSTEMCTL_BIN      systemctl to call    (default: systemctl)
#
# Exit codes:
#   0  success (including every no-op)
#   1  manifest missing, unreadable or unparseable (nothing done)
#   2  usage error (nothing done)
#   3  state dir absent, or the pre-state file could not be written (nothing done)
#   4  one or more entries failed to apply/revert (the others were still done;
#      on revert the state file is kept so a retry can still restore)
################################################################################

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${OS_TRIM_MANIFEST:-${SCRIPT_DIR}/os-trim.manifest}"
STATE_DIR="${OS_TRIM_STATE_DIR:-/var/lib/eclipse-obd}"
STATE_FILE="${STATE_DIR}/os-trim.state"
ROOT="${OS_TRIM_ROOT:-}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"

# MUST NOT GO (Atlas, same ruling as the manifest). The car needs every one of
# these: BlueZ for the OBDLink, NetworkManager + netplan for home WiFi sync,
# polkit for deploy/polkit-rules, lightdm + accounts-daemon for the X11 kiosk
# autologin (until the DRM story removes them together), rpi-eeprom-update for
# enforce-eeprom-power-off-on-halt.sh, timesyncd for the clock, plymouth for
# US-885, journald for the persistent journal. avahi-daemon is unverified, so it
# stays. A manifest naming any of them is refused before anything is done.
NEVER_UNITS="bluetooth NetworkManager dbus polkit lightdm accounts-daemon avahi-daemon rpi-eeprom-update netplan systemd-timesyncd plymouth systemd-journald"

usage() {
    echo "Usage: sudo bash deploy/os-trim.sh apply|revert [--dry-run]" >&2
}

MODE=""
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        apply|revert)
            if [ -n "$MODE" ]; then usage; exit 2; fi
            MODE="$arg"
            ;;
        --dry-run) DRY_RUN=true ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "ERROR: unknown argument '${arg}'" >&2
            usage
            exit 2
            ;;
    esac
done
if [ -z "$MODE" ]; then
    usage
    exit 2
fi

################################################################################
# Manifest
################################################################################

UNITS=()
ACTIONS=()
ARGS=()
REASONS=()

# Both assign into the variable NAMED by $1 instead of printing: a $(...)
# subshell per field is a fork, and forks are what make this slow on a bench.
trimInto() {
    local s="$2"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf -v "$1" '%s' "$s"
}

baseNameInto() {
    local u="$2" sfx
    for sfx in .service .socket .timer .path .target; do
        u="${u%"$sfx"}"
    done
    printf -v "$1" '%s' "$u"
}

manifestError() {
    echo "ERROR: os-trim manifest ${MANIFEST}: $1 -- nothing was changed." >&2
    exit 1
}

parseManifest() {
    if [ ! -f "$MANIFEST" ]; then
        echo "ERROR: os-trim manifest not found: ${MANIFEST} -- a missing manifest is never 'nothing to trim'; nothing was changed." >&2
        exit 1
    fi
    if [ ! -r "$MANIFEST" ]; then
        echo "ERROR: os-trim manifest not readable: ${MANIFEST} -- nothing was changed." >&2
        exit 1
    fi

    local n=0 raw line pipes unit action reason evidence actionWord actionArg base never seen
    while IFS= read -r raw || [ -n "$raw" ]; do
        n=$((n + 1))
        trimInto line "${raw%$'\r'}"
        [ -z "$line" ] && continue
        case "$line" in \#*) continue ;; esac

        pipes="${line//[^|]/}"
        [ "${#pipes}" -eq 3 ] \
            || manifestError "line ${n}: expected 4 '|'-separated fields (unit | action | reason | evidence)"
        IFS='|' read -r unit action reason evidence <<< "$line"
        trimInto unit "$unit"
        trimInto action "$action"
        trimInto reason "$reason"
        trimInto evidence "$evidence"
        if [ -z "$unit" ] || [ -z "$action" ] || [ -z "$reason" ] || [ -z "$evidence" ]; then
            manifestError "line ${n}: every field (unit, action, reason, evidence) must be non-empty"
        fi
        case "$unit" in *[[:space:]]*) manifestError "line ${n}: unit '${unit}' contains whitespace" ;; esac

        actionWord="${action%%[[:space:]]*}"
        trimInto actionArg "${action#"$actionWord"}"
        case "$actionWord" in
            mask|disable)
                [ -z "$actionArg" ] || manifestError "line ${n}: '${actionWord}' takes no argument"
                ;;
            flagfile)
                case "$actionArg" in
                    /*[[:space:]]*|"") manifestError "line ${n}: flagfile needs one absolute path" ;;
                    /*) ;;
                    *) manifestError "line ${n}: flagfile needs one absolute path" ;;
                esac
                ;;
            *)
                manifestError "line ${n}: unknown action '${actionWord}' (mask | disable | flagfile)"
                ;;
        esac

        baseNameInto base "$unit"
        for never in $NEVER_UNITS; do
            if [ "$unit" = "$never" ] || [ "$base" = "$never" ]; then
                manifestError "line ${n}: '${unit}' is on the NEVER list"
            fi
        done
        for seen in "${UNITS[@]+"${UNITS[@]}"}"; do
            [ "$seen" = "$unit" ] && manifestError "line ${n}: '${unit}' is listed twice"
        done

        UNITS+=("$unit")
        ACTIONS+=("$actionWord")
        ARGS+=("$actionArg")
        REASONS+=("$reason")
    done < "$MANIFEST"

    [ "${#UNITS[@]}" -gt 0 ] \
        || manifestError "no entries -- an empty manifest is never 'nothing to trim'"
}

################################################################################
# Helpers
################################################################################

FAILED=0

# `systemctl is-enabled` prints the state and exits non-zero for disabled /
# masked, so the exit code is not a failure here. A unit systemd has never
# heard of prints nothing on older releases; call that not-found.
unitState() {
    local out
    out="$("$SYSTEMCTL_BIN" is-enabled "$1" 2>/dev/null)"
    out="${out%%$'\n'*}"
    [ -z "$out" ] && out="not-found"
    printf '%s' "$out"
}

systemctlOrFail() {
    if ! "$SYSTEMCTL_BIN" "$@"; then
        echo "ERROR: systemctl $* failed." >&2
        FAILED=1
        return 1
    fi
    return 0
}

requireStateDir() {
    if [ ! -d "$STATE_DIR" ]; then
        echo "ERROR: os-trim state dir ${STATE_DIR} does not exist -- deploy-pi.sh provisions it (US-667); os-trim will not create it. Nothing was changed." >&2
        exit 3
    fi
}

################################################################################
# apply
################################################################################

recordPreState() {
    if [ -f "$STATE_FILE" ]; then
        echo "Pre-state already recorded in ${STATE_FILE} (kept: a later apply never overwrites it)."
        return 0
    fi
    local tmp="${STATE_FILE}.tmp.$$" i state
    {
        echo "# os-trim pre-state, recorded by the FIRST apply $(date -Iseconds 2>/dev/null)"
        echo "# unit|state  (systemctl is-enabled, or flag file present/absent)"
        for i in "${!UNITS[@]}"; do
            if [ "${ACTIONS[$i]}" = "flagfile" ]; then
                state=absent
                [ -e "${ROOT}${ARGS[$i]}" ] && state=present
            else
                state="$(unitState "${UNITS[$i]}")"
            fi
            echo "${UNITS[$i]}|${state}"
        done
    } > "$tmp" || {
        rm -f "$tmp"
        echo "ERROR: could not write the os-trim pre-state to ${tmp}; nothing was changed." >&2
        exit 3
    }
    if ! mv "$tmp" "$STATE_FILE"; then
        rm -f "$tmp"
        echo "ERROR: could not install the os-trim pre-state at ${STATE_FILE}; nothing was changed." >&2
        exit 3
    fi
    echo "Recorded pre-state of ${#UNITS[@]} entries in ${STATE_FILE}."
}

applyEntry() {
    local i="$1" unit="${UNITS[$1]}" action="${ACTIONS[$1]}" arg="${ARGS[$1]}" current path
    case "$action" in
        mask)
            current="$(unitState "$unit")"
            if [ "$current" = "masked" ]; then
                echo "  ${unit}: already masked"
            elif systemctlOrFail mask "$unit"; then
                echo "  ${unit}: masked (was ${current})"
            fi
            ;;
        disable)
            current="$(unitState "$unit")"
            case "$current" in
                enabled|enabled-runtime)
                    systemctlOrFail disable "$unit" && echo "  ${unit}: disabled (was ${current})"
                    ;;
                *)
                    echo "  ${unit}: left as ${current}"
                    ;;
            esac
            ;;
        flagfile)
            path="${ROOT}${arg}"
            if [ -e "$path" ]; then
                echo "  ${unit}: ${arg} already present"
            elif [ ! -d "${path%/*}/" ]; then
                echo "  ${unit}: ${arg%/*}/ absent (${unit} not installed) -- nothing to switch off"
            elif : > "$path"; then
                echo "  ${unit}: created ${arg}"
            else
                echo "ERROR: could not create ${arg}." >&2
                FAILED=1
            fi
            ;;
    esac
}

doApply() {
    local i
    if $DRY_RUN; then
        for i in "${!UNITS[@]}"; do
            if [ "${ACTIONS[$i]}" = "flagfile" ]; then
                echo "DRY-RUN apply ${UNITS[$i]}: create ${ARGS[$i]} (${REASONS[$i]})"
            else
                echo "DRY-RUN apply ${UNITS[$i]}: ${ACTIONS[$i]} (${REASONS[$i]})"
            fi
        done
        return 0
    fi

    requireStateDir
    recordPreState
    echo "Applying ${#UNITS[@]} os-trim entries from ${MANIFEST}:"
    for i in "${!UNITS[@]}"; do
        applyEntry "$i"
    done
    if [ "$FAILED" -ne 0 ]; then
        echo "ERROR: os-trim apply finished with failures (see above)." >&2
        exit 4
    fi
    echo "os-trim applied. Takes effect at the next boot (nothing was stopped now)."
    echo "  Undo offline: sudo bash deploy/os-trim.sh revert   (or deploy-pi.sh --os-trim-revert)"
}

################################################################################
# revert
################################################################################

declare -A RECORDED=()
HAVE_STATE=false

loadPreState() {
    local line
    [ -f "$STATE_FILE" ] || return 0
    HAVE_STATE=true
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in ''|\#*) continue ;; esac
        RECORDED["${line%%|*}"]="${line#*|}"
    done < "$STATE_FILE"
}

# Set INVERSE to the inverse for entry $1 as "<verb> <detail>": verb is unmask,
# enable, delete or keep. Uses the recorded pre-state when there is one,
# otherwise the fixed inverse.
INVERSE=""
inverseFor() {
    local i="$1" unit="${UNITS[$1]}" action="${ACTIONS[$1]}" recorded=""
    if $HAVE_STATE && [ -n "${RECORDED[$unit]+set}" ]; then
        recorded="${RECORDED[$unit]}"
    fi
    case "$action" in
        mask)
            case "$recorded" in
                masked|masked-runtime) INVERSE="keep masked (recorded pre-state: ${recorded})" ;;
                "") INVERSE="unmask (fixed inverse)" ;;
                *) INVERSE="unmask (recorded pre-state: ${recorded})" ;;
            esac
            ;;
        disable)
            case "$recorded" in
                "") INVERSE="enable (fixed inverse)" ;;
                enabled|enabled-runtime) INVERSE="enable (recorded pre-state: ${recorded})" ;;
                *) INVERSE="keep ${recorded} (recorded pre-state: ${recorded})" ;;
            esac
            ;;
        flagfile)
            case "$recorded" in
                present) INVERSE="keep ${ARGS[$i]} (recorded pre-state: present)" ;;
                "") INVERSE="delete ${ARGS[$i]} (fixed inverse)" ;;
                *) INVERSE="delete ${ARGS[$i]} (recorded pre-state: ${recorded})" ;;
            esac
            ;;
    esac
}

revertEntry() {
    local i="$1" unit="${UNITS[$1]}" inverse
    inverseFor "$i"
    inverse="$INVERSE"
    case "${inverse%% *}" in
        unmask) systemctlOrFail unmask "$unit" && echo "  ${unit}: ${inverse}" ;;
        enable) systemctlOrFail enable "$unit" && echo "  ${unit}: ${inverse}" ;;
        delete)
            if rm -f "${ROOT}${ARGS[$i]}"; then
                echo "  ${unit}: ${inverse}"
            else
                echo "ERROR: could not delete ${ARGS[$i]}." >&2
                FAILED=1
            fi
            ;;
        keep) echo "  ${unit}: ${inverse}" ;;
    esac
}

doRevert() {
    local i missing=()
    $DRY_RUN || requireStateDir
    loadPreState

    if ! $HAVE_STATE; then
        echo "WARN: no os-trim pre-state at ${STATE_FILE} -- applying the fixed inverse (unmask / enable / delete flag file)." >&2
    else
        for i in "${!UNITS[@]}"; do
            [ -n "${RECORDED[${UNITS[$i]}]+set}" ] || missing+=("${UNITS[$i]}")
        done
        if [ "${#missing[@]}" -gt 0 ]; then
            echo "WARN: not in the os-trim pre-state (added to the manifest after the first apply), fixed inverse used: ${missing[*]}" >&2
        fi
    fi

    if $DRY_RUN; then
        for i in "${!UNITS[@]}"; do
            inverseFor "$i"
            echo "DRY-RUN revert ${UNITS[$i]}: ${INVERSE}"
        done
        return 0
    fi

    echo "Reverting ${#UNITS[@]} os-trim entries from ${MANIFEST}:"
    for i in "${!UNITS[@]}"; do
        revertEntry "$i"
    done
    if [ "$FAILED" -ne 0 ]; then
        echo "ERROR: os-trim revert finished with failures (see above); ${STATE_FILE} kept for a retry." >&2
        exit 4
    fi
    rm -f "$STATE_FILE"
    echo "os-trim reverted; pre-state file removed. Takes effect at the next boot."
}

################################################################################
# Main
################################################################################

parseManifest
case "$MODE" in
    apply) doApply ;;
    revert) doRevert ;;
esac
exit 0
