#!/usr/bin/env bash
################################################################################
# set-boot-screen.sh — the power-on WARNING screen and a quiet boot line
#                      (US-885-b / F-139)
#
# At power-on the CIO should see Iris's WARNING image (specs/assets/boot/
# warning-480x320.png, PR #130) from the firmware hand-off until lightdm quits
# Plymouth -- never the firmware rainbow, never kernel text. This script owns
# the four things that make that true, and their revert:
#
#   1. The Plymouth theme deploy/plymouth/eclipse/, installed to
#      /usr/share/plymouth/themes/eclipse/ and made the default with
#      `plymouth-set-default-theme -R eclipse`. Atlas MEASURED 2026-10-23 (boot
#      b4c1f965): config.txt auto_initramfs=1; /boot/firmware/initramfs_2712
#      carries plymouth + the theme; -R rebuilds the initramfs and the
#      z50-raspi-firmware hook copies it to /boot/firmware. The choice survives
#      kernel updates via plymouthd.conf, so no extra hook is needed.
#   2. config.txt `disable_splash=1` (no rainbow), plus `camera_auto_detect=0`
#      and `display_auto_detect=0` (US-926-b: no camera / DSI-panel I2C probe
#      before Starting OS -- this car has neither) -- all through
#      deploy/lib/config-txt-keys.sh, the ONE config.txt key writer, which is
#      section-aware (only the top level, [all] and [pi5] reach a Pi 5) and
#      rewrites an effective line with another value in place.
#   3. cmdline.txt `loglevel=3` and `vt.global_cursor_default=0` added and
#      `console=tty1` removed -- all through deploy/lib/cmdline-tokens.sh, the
#      ONE cmdline editor, so set-display-mode.sh's video= pin and these tokens
#      give their union in either order.
#   4. The revert (`--revert`), independent of display mode.
#
# It applies in BOTH display modes: lightdm quits Plymouth in x11 and wayland
# alike (display-stack ADR 11.3), so deploy-pi.sh runs it on every deploy.
#
# THE INITRAMFS is the one boot-critical file this script writes (through -R).
# Before EITHER rebuild (install or revert) both /boot/firmware/initramfs_2712
# and /boot/firmware/initramfs8 are copied to a dated .bak and cmp-verified; a
# failed copy or cmp aborts with nothing changed. A non-zero exit from -R copies
# both .bak files back (the hook may already have copied a half-built image),
# cmp-verifies them and exits non-zero loudly. Only the NEWEST .bak pair this
# script wrote is kept, and older ones are pruned only after the new pair
# verifies; any other .bak (e.g. a .bak-6.18.29-claude pair) is never touched.
#
# IDEMPOTENT (deploy-pi runs this on every deploy; ~37 MB of .bak per rebuild
# against 404 MB free on /boot/firmware, MEASURED): the backup and -R are
# SKIPPED when all three hold -- plymouthd.conf Theme=eclipse; the installed
# theme files are byte-identical to deploy/plymouth/eclipse/; and
# `lsinitramfs initramfs_2712` lists themes/eclipse. Any one failing (a changed
# asset, a kernel update that rebuilt the initramfs without it) rebuilds.
#
# THE REVERT restores what apply changed and nothing else: the boot-screen
# tokens it added are removed, console=tty1 is put back where it was, the
# config.txt disable_splash block it appended is removed -- or, when apply
# rewrote an existing disable_splash line in place, that line's prior value is
# put back (both files byte-identical to before when nothing else edited them),
# and -R rebuilds with the theme RECORDED before
# the first install (pix if there is no record). It never restores the
# initramfs from a .bak: a kernel update may have happened in between, and -R
# builds a correct one.
#
# The revert leaves camera_auto_detect=0 / display_auto_detect=0 alone (Atlas
# 2026-10-25: one revert per concern -- undoing the boot screen must not slow
# the boot or touch hardware detection). Their undo, needed only if a camera or
# a DSI panel is fitted (the HDMI35 is HDMI and needs neither), is the same
# writer setting each back to 1:
#   . deploy/lib/config-txt-keys.sh
#   config_txt_set_key /boot/firmware/config.txt camera_auto_detect 1 \
#       /boot/firmware/config.txt.boot-screen-bak "# <why>"
#
# Usage (run directly on the Pi):
#   sudo bash deploy/set-boot-screen.sh            # apply
#   sudo bash deploy/set-boot-screen.sh --revert   # undo
#
# Every change takes effect on the NEXT boot only.
#
# Test overrides (the harness points these at fixtures; production leaves unset):
#   $PI_BOOT_FIRMWARE_DIR         -> /boot/firmware (initramfs, .bak, record)
#   $PI_CONFIG_TXT                -> <firmware dir>/config.txt
#   $PI_CMDLINE_TXT               -> <firmware dir>/cmdline.txt
#   $PI_PLYMOUTHD_CONF            -> /etc/plymouth/plymouthd.conf
#   $PI_PLYMOUTH_THEMES_DIR       -> /usr/share/plymouth/themes
#   $ECLIPSE_PLYMOUTH_THEME_SRC   -> <this dir>/plymouth/eclipse
# plymouth-set-default-theme and lsinitramfs are taken from PATH.
#
# Exit codes:
#   0  success (applied, already applied, or reverted)
#   1  configuration error / refused (bad argument, missing file, malformed
#      boot cmdline, backup copy or cmp failed) -- nothing was written
#   2  write or post-write verification failed
#   3  plymouth-set-default-theme -R failed (initramfs restored from the .bak)
#   4  -R failed AND restoring the initramfs failed -- DO NOT REBOOT
################################################################################

set -u

SELF_DIR="$(dirname "${BASH_SOURCE[0]}")"

FIRMWARE_DIR="${PI_BOOT_FIRMWARE_DIR:-/boot/firmware}"
CONFIG="${PI_CONFIG_TXT:-${FIRMWARE_DIR}/config.txt}"
CMDLINE="${PI_CMDLINE_TXT:-${FIRMWARE_DIR}/cmdline.txt}"
PLYMOUTHD_CONF="${PI_PLYMOUTHD_CONF:-/etc/plymouth/plymouthd.conf}"
THEMES_DIR="${PI_PLYMOUTH_THEMES_DIR:-/usr/share/plymouth/themes}"
THEME_SRC="${ECLIPSE_PLYMOUTH_THEME_SRC:-${SELF_DIR}/plymouth/eclipse}"

THEME="eclipse"
THEME_DST="${THEMES_DIR}/${THEME}"
# The theme this Pi ships with (plymouthd.conf Theme=pix, Atlas 2026-10-23):
# what --revert rebuilds with when no prior theme was recorded.
DEFAULT_PRIOR_THEME="pix"

INITRAMFS_2712="${FIRMWARE_DIR}/initramfs_2712"
INITRAMFS_8="${FIRMWARE_DIR}/initramfs8"
# Every .bak this script writes carries this tag; nothing else is ever pruned.
BAK_TAG=".bak-boot-screen-"
PRIOR_THEME_RECORD="${FIRMWARE_DIR}/eclipse-boot-screen.prior-theme"

# This script's own first-write-wins backups of the two text files. Not the
# shared .eclipse-bak (set-gpu-cma / enable-rtc-charging / set-display-mode
# keep the pristine pre-Eclipse original there): --revert deletes these.
CONFIG_BACKUP="${CONFIG}.boot-screen-bak"
CMDLINE_BACKUP="${CMDLINE}.boot-screen-bak"

CONFIG_KEY="disable_splash"
CONFIG_LINE="${CONFIG_KEY}=1"
CONFIG_MARKER="# eclipse set-boot-screen (US-885-b): no rainbow at power-on -- undo with set-boot-screen.sh --revert"

# No camera / DSI-panel auto-detect probe at boot (US-926-b). Applied BEFORE
# disable_splash, so an [all] this script opens belongs to these lines and the
# disable_splash block --revert removes never carries it. --revert leaves them.
AUTODETECT_KEYS="camera_auto_detect=0 display_auto_detect=0"
AUTODETECT_MARKER="# eclipse set-boot-screen (US-926-b): no camera/DSI auto-detect probe at boot -- undo: config-txt-keys.sh sets it back to 1"

ADD_TOKENS="loglevel=3 vt.global_cursor_default=0"
REMOVE_TOKEN="console=tty1"

usage() {
    echo "Usage: sudo bash deploy/set-boot-screen.sh [--revert]"
}

MODE="apply"
case "${1:-}" in
    '') ;;
    --revert) MODE="revert" ;;
    -h|--help) usage; exit 0 ;;
    *)
        echo "ERROR: unknown argument '${1}'. Nothing was written." >&2
        usage >&2
        exit 1
        ;;
esac
if [ "$#" -gt 1 ]; then
    echo "ERROR: too many arguments. Nothing was written." >&2
    usage >&2
    exit 1
fi

# The ONE cmdline.txt token editor every boot-line writer shares (US-885-a).
CMDLINE_TOKENS_LIB="${SELF_DIR}/lib/cmdline-tokens.sh"
if [ ! -r "$CMDLINE_TOKENS_LIB" ]; then
    echo "ERROR: shared cmdline helper not found at '${CMDLINE_TOKENS_LIB}'." >&2
    echo "       Nothing was written." >&2
    exit 1
fi
# shellcheck source=lib/cmdline-tokens.sh
. "$CMDLINE_TOKENS_LIB"

# The ONE config.txt key writer (US-926-b).
CONFIG_TXT_KEYS_LIB="${SELF_DIR}/lib/config-txt-keys.sh"
if [ ! -r "$CONFIG_TXT_KEYS_LIB" ]; then
    echo "ERROR: shared config.txt helper not found at '${CONFIG_TXT_KEYS_LIB}'." >&2
    echo "       Nothing was written." >&2
    exit 1
fi
# shellcheck source=lib/config-txt-keys.sh
. "$CONFIG_TXT_KEYS_LIB"

# ---- preflight: refuse before anything is written ----

if [ ! -f "$CONFIG" ] || [ ! -r "$CONFIG" ]; then
    echo "ERROR: boot config.txt not found or unreadable at '${CONFIG}'. Nothing was written." >&2
    exit 1
fi

if ! cmdline_check "$CMDLINE"; then
    exit 1
fi

for initramfs in "$INITRAMFS_2712" "$INITRAMFS_8"; do
    if [ ! -f "$initramfs" ]; then
        echo "ERROR: ${initramfs} not found -- it must be backed up before any rebuild." >&2
        echo "       Nothing was written." >&2
        exit 1
    fi
done

if [ "$MODE" = "apply" ] && [ ! -f "${THEME_SRC}/${THEME}.plymouth" ]; then
    echo "ERROR: theme source not found at '${THEME_SRC}' (no ${THEME}.plymouth)." >&2
    echo "       Nothing was written." >&2
    exit 1
fi

# ---- plymouth state ----

# The Theme= plymouthd.conf names ("" if none).
currentTheme() {
    [ -r "$PLYMOUTHD_CONF" ] || return 0
    awk -F= '
        $1 ~ /^[ \t]*Theme[ \t]*$/ { v = $2; gsub(/[ \t\r]/, "", v); print v; exit }
    ' "$PLYMOUTHD_CONF"
}

# True if every installed theme file is byte-identical to its source and the
# installed dir carries nothing the source does not.
themeFilesMatch() {
    local f
    [ -d "$THEME_DST" ] || return 1
    for f in "$THEME_SRC"/*; do
        cmp -s "$f" "${THEME_DST}/$(basename "$f")" || return 1
    done
    for f in "$THEME_DST"/*; do
        [ -e "${THEME_SRC}/$(basename "$f")" ] || return 1
    done
    return 0
}

initramfsCarriesTheme() {
    lsinitramfs "$INITRAMFS_2712" 2>/dev/null | grep -q "themes/${THEME}"
}

# ---- the initramfs backup pair ----

NEW_BAK_2712=""
NEW_BAK_8=""

# Copy both initramfs files to a dated .bak and cmp-verify each. On any failure
# remove the partial pair and return 1: nothing has been changed yet.
takeBackupPair() {
    local stamp src dst
    stamp="$(date +%Y%m%dT%H%M%S)-$$"
    NEW_BAK_2712="${INITRAMFS_2712}${BAK_TAG}${stamp}"
    NEW_BAK_8="${INITRAMFS_8}${BAK_TAG}${stamp}"
    for src in "$INITRAMFS_2712" "$INITRAMFS_8"; do
        dst="${src}${BAK_TAG}${stamp}"
        if ! cp "$src" "$dst" || ! cmp -s "$src" "$dst"; then
            rm -f "$NEW_BAK_2712" "$NEW_BAK_8"
            echo "ERROR: could not back up ${src} to ${dst} (copy or cmp failed)." >&2
            echo "       Refusing to rebuild the initramfs. Nothing was written." >&2
            return 1
        fi
        echo "Backed up ${src} -> ${dst} (cmp-verified)."
    done
    return 0
}

# Keep only the pair just written; never touch a .bak without this script's tag.
pruneOlderPairs() {
    local bak
    for bak in "${INITRAMFS_2712}${BAK_TAG}"* "${INITRAMFS_8}${BAK_TAG}"*; do
        [ -f "$bak" ] || continue
        [ "$bak" = "$NEW_BAK_2712" ] && continue
        [ "$bak" = "$NEW_BAK_8" ] && continue
        rm -f "$bak" && echo "Pruned older backup ${bak}."
    done
}

# Put one .bak back over its initramfs via a temp file + mv, then cmp it.
restoreOne() {
    local bak="$1" target="$2" tmp="${2}.eclipse-restore.$$"
    cp "$bak" "$tmp" && mv "$tmp" "$target" && cmp -s "$bak" "$target" && return 0
    rm -f "$tmp"
    return 1
}

# Run `plymouth-set-default-theme -R THEME`. On failure restore the pair taken
# for this rebuild and exit -- loudly.
rebuildInitramfs() {
    local theme="$1"
    echo "Rebuilding the initramfs: plymouth-set-default-theme -R ${theme}"
    if plymouth-set-default-theme -R "$theme"; then
        return 0
    fi
    echo "ERROR: plymouth-set-default-theme -R ${theme} FAILED." >&2
    echo "ERROR: the hook may already have copied a half-built image to ${FIRMWARE_DIR};" >&2
    echo "ERROR: restoring both initramfs files from the backups taken for this run." >&2
    if restoreOne "$NEW_BAK_2712" "$INITRAMFS_2712" && restoreOne "$NEW_BAK_8" "$INITRAMFS_8"; then
        echo "ERROR: restored and cmp-verified ${INITRAMFS_2712} and ${INITRAMFS_8}." >&2
        echo "ERROR: the boot screen was NOT changed. Investigate before the next deploy." >&2
        exit 3
    fi
    echo "ERROR: RESTORING THE INITRAMFS ALSO FAILED. DO NOT REBOOT THIS PI." >&2
    echo "ERROR: copy ${NEW_BAK_2712} -> ${INITRAMFS_2712} and" >&2
    echo "ERROR:      ${NEW_BAK_8} -> ${INITRAMFS_8} by hand and cmp them first." >&2
    exit 4
}

# ---- config.txt (through deploy/lib/config-txt-keys.sh) ----

applyConfig() {
    local pair rc
    for pair in $AUTODETECT_KEYS; do
        config_txt_set_key "$CONFIG" "${pair%%=*}" "${pair#*=}" "$CONFIG_BACKUP" "$AUTODETECT_MARKER"
        rc=$?
        [ "$rc" -eq 0 ] || return "$rc"
    done
    config_txt_set_key "$CONFIG" "$CONFIG_KEY" "1" "$CONFIG_BACKUP" "$CONFIG_MARKER"
}

# Undo disable_splash only: remove the block apply appended, or -- when apply
# rewrote an existing line in place -- put that line's pre-apply value (from
# the first-write-wins backup) back the same way. The auto-detect keys stay.
revertConfig() {
    local prior rc
    if grep -qxF -- "$CONFIG_MARKER" "$CONFIG"; then
        config_txt_remove_block "$CONFIG" "$CONFIG_MARKER" "$CONFIG_LINE" "$CONFIG_BACKUP" || return $?
        echo "Removed ${CONFIG_LINE} (set-boot-screen block) from ${CONFIG}."
    elif [ -f "$CONFIG_BACKUP" ] \
        && prior="$(config_txt_effective "$CONFIG_BACKUP" "$CONFIG_KEY")" \
        && [ -n "$prior" ] && [ "$prior" != "1" ] \
        && [ "$(config_txt_effective "$CONFIG" "$CONFIG_KEY")" = "1" ]; then
        config_txt_set_key "$CONFIG" "$CONFIG_KEY" "$prior" "$CONFIG_BACKUP" "$CONFIG_MARKER"
        rc=$?
        if [ "$rc" -eq 1 ]; then
            echo "WARN: ${CONFIG_KEY} was '${prior}' before apply and is not restorable by the writer;" >&2
            echo "WARN: set it by hand from ${CONFIG_BACKUP} if it matters." >&2
        elif [ "$rc" -ne 0 ]; then
            return "$rc"
        fi
    else
        echo "No set-boot-screen block in ${CONFIG} -- no change."
    fi
    rm -f "$CONFIG_BACKUP"
    return 0
}

# ---- cmdline.txt ----

applyCmdline() {
    local token rc
    for token in $ADD_TOKENS; do
        cmdline_add_token "$CMDLINE" "$token" "$CMDLINE_BACKUP"
        rc=$?
        [ "$rc" -eq 0 ] || return "$rc"
    done
    cmdline_remove_token "$CMDLINE" "$REMOVE_TOKEN" "$CMDLINE_BACKUP"
    rc=$?
    [ "$rc" -eq 0 ] || return "$rc"
    if ! _cmdline_has_token "$(cmdline_read_line "$CMDLINE")" "splash"; then
        echo "WARN: ${CMDLINE} carries no 'splash' token -- Plymouth will not show the" >&2
        echo "WARN: boot screen until it does. Not added here: it is not this script's token." >&2
    fi
    return 0
}

# Undo exactly what apply did, judged against the pre-apply line in the backup:
# a token apply added is one the backup lacks; console=tty1 comes back only if
# the backup had it. Then put the backup's tokens back in their original order
# (console= order is meaningful to the kernel), any token another writer added
# since (e.g. video=) kept after them.
revertCmdline() {
    local pristine current ordered="" token word rc
    if [ ! -f "$CMDLINE_BACKUP" ]; then
        echo "No set-boot-screen backup of ${CMDLINE} -- apply never changed it; no change."
        return 0
    fi
    pristine="$(cmdline_read_line "$CMDLINE_BACKUP")"

    for token in $ADD_TOKENS; do
        _cmdline_has_token "$pristine" "$token" && continue
        cmdline_remove_token "$CMDLINE" "$token" "$CMDLINE_BACKUP"
        rc=$?
        [ "$rc" -eq 0 ] || return "$rc"
    done
    if _cmdline_has_token "$pristine" "$REMOVE_TOKEN"; then
        cmdline_add_token "$CMDLINE" "$REMOVE_TOKEN" "$CMDLINE_BACKUP"
        rc=$?
        [ "$rc" -eq 0 ] || return "$rc"
    fi

    current="$(cmdline_read_line "$CMDLINE")"
    while IFS= read -r word; do
        _cmdline_has_token "$current" "$word" && ordered="${ordered:+${ordered} }${word}"
    done < <(_cmdline_words "$pristine")
    while IFS= read -r word; do
        _cmdline_has_token "$pristine" "$word" || ordered="${ordered:+${ordered} }${word}"
    done < <(_cmdline_words "$current")

    if [ "$ordered" != "$current" ]; then
        _cmdline_install "$CMDLINE" "$CMDLINE_BACKUP" "$current" "$ordered" "" ""
        rc=$?
        [ "$rc" -eq 0 ] || return "$rc"
    fi
    rm -f "$CMDLINE_BACKUP"
    echo "Restored the boot-screen tokens in ${CMDLINE}:"
    echo "  $(cmdline_read_line "$CMDLINE")"
    return 0
}

# ---- apply ----

if [ "$MODE" = "apply" ]; then
    echo "--- set-boot-screen: Plymouth theme '${THEME}' + quiet boot line ---"

    if [ "$(currentTheme)" = "$THEME" ] && themeFilesMatch && initramfsCarriesTheme; then
        echo "Theme '${THEME}' is the default, installed byte-identical and in the initramfs -- no rebuild."
    else
        takeBackupPair || exit 1
        pruneOlderPairs

        # Record the theme in place BEFORE the first install, beside the backup,
        # so --revert can put it back. First-write-wins: a re-install after an
        # asset change must not record 'eclipse' as the prior theme.
        prior="$(currentTheme)"
        if [ ! -f "$PRIOR_THEME_RECORD" ] && [ -n "$prior" ] && [ "$prior" != "$THEME" ]; then
            if ! printf '%s\n' "$prior" > "$PRIOR_THEME_RECORD"; then
                echo "ERROR: could not record the prior theme at ${PRIOR_THEME_RECORD}." >&2
                exit 2
            fi
            echo "Recorded the prior theme '${prior}' at ${PRIOR_THEME_RECORD}."
        fi

        if ! mkdir -p "$THEME_DST"; then
            echo "ERROR: could not create ${THEME_DST}." >&2
            exit 2
        fi
        for f in "$THEME_DST"/*; do
            [ -e "$f" ] || continue
            [ -e "${THEME_SRC}/$(basename "$f")" ] || rm -f "$f"
        done
        for f in "$THEME_SRC"/*; do
            if ! cp "$f" "${THEME_DST}/"; then
                echo "ERROR: could not install $(basename "$f") to ${THEME_DST}." >&2
                exit 2
            fi
        done
        if ! themeFilesMatch; then
            echo "ERROR: ${THEME_DST} is not byte-identical to ${THEME_SRC} after install." >&2
            exit 2
        fi
        echo "Installed the '${THEME}' theme to ${THEME_DST}."

        rebuildInitramfs "$THEME"

        if ! initramfsCarriesTheme; then
            echo "ERROR: -R ${THEME} succeeded but ${INITRAMFS_2712} does not list themes/${THEME}." >&2
            echo "       The WARNING screen will not show at the next boot." >&2
            exit 2
        fi
        echo "Theme '${THEME}' is the default and in ${INITRAMFS_2712}."
    fi

    applyConfig || exit $?
    applyCmdline || exit $?

    echo "REBOOT REQUIRED: the WARNING screen and quiet boot line take effect at the next boot."
    exit 0
fi

# ---- revert ----

echo "--- set-boot-screen --revert: restoring the prior boot screen ---"

priorTheme="$DEFAULT_PRIOR_THEME"
if [ -f "$PRIOR_THEME_RECORD" ]; then
    recorded="$(tr -d '[:space:]' < "$PRIOR_THEME_RECORD")"
    if printf '%s' "$recorded" | grep -qE '^[A-Za-z0-9._-]+$' && [ "$recorded" != "$THEME" ]; then
        priorTheme="$recorded"
    else
        echo "WARN: ${PRIOR_THEME_RECORD} holds '${recorded}', not a usable theme name; using ${DEFAULT_PRIOR_THEME}." >&2
    fi
else
    echo "No recorded prior theme -- reverting to '${DEFAULT_PRIOR_THEME}'."
fi

takeBackupPair || exit 1
pruneOlderPairs
rebuildInitramfs "$priorTheme"

if initramfsCarriesTheme; then
    echo "ERROR: -R ${priorTheme} succeeded but ${INITRAMFS_2712} still lists themes/${THEME}." >&2
    exit 2
fi
rm -rf "$THEME_DST"
rm -f "$PRIOR_THEME_RECORD"
echo "Theme '${priorTheme}' is the default again; ${THEME_DST} removed."

revertConfig || exit $?
revertCmdline || exit $?

echo "REBOOT REQUIRED: the prior boot screen returns at the next boot."
exit 0
