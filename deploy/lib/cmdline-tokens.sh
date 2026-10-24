#!/usr/bin/env bash
################################################################################
# deploy/lib/cmdline-tokens.sh — the ONE cmdline.txt token editor (US-885-a)
#
# Sourced (never executed) by every deploy script that edits the Pi's boot
# cmdline: set-display-mode.sh (its video= pin, US-552) and, from US-885-b,
# set-boot-screen.sh (the quiet-boot tokens). Two writers on one boot-critical
# file must not clobber each other, so neither carries its own editor: each
# adds or removes only the tokens it NAMES, through these functions.
#
# The checks are the ones set-display-mode.sh has carried since US-552 -- a
# corrupted cmdline.txt can break `root=` on a Pi that lives in a car with no
# local recovery, so every edit is bounded by:
#
#   1. The file must exist, be readable, carry EXACTLY ONE non-blank line (the
#      bootloader passes the first line; a stray newline silently truncates
#      every argument after it), and carry a `root=` argument (how we know it
#      is a boot cmdline at all). Anything else is refused, nothing written.
#   2. Idempotent: adding a token already present, or removing one that is
#      absent, writes NOTHING -- the file stays byte-identical and no backup is
#      taken.
#   3. Backup before write, first-write-wins: the caller names its backup path;
#      the first edit copies the pristine original there and later edits keep it.
#   4. The composed line is verified BEFORE it is installed (every unnamed token
#      and `root=` intact), written to a temp file beside the target and moved
#      over it, then re-read and verified again; a post-install mismatch
#      restores the backup.
#
# A token is compared WHOLE: removing `console=tty1` never touches
# `console=serial0,115200`. What to do about a same-NAME token with a different
# value (e.g. an operator's own video=) is the CALLER's policy -- look it up
# with cmdline_named_token before adding.
#
# Functions (return codes: 0 done or nothing to do; 1 refused, nothing written;
# 2 write or post-write verification failed):
#   cmdline_check FILE                    the step-1 checks alone
#   cmdline_read_line FILE                print the one boot line (after check)
#   cmdline_named_token FILE NAME         print the first NAME=... token, if any
#   cmdline_add_token FILE TOKEN BACKUP   append TOKEN unless already present
#   cmdline_remove_token FILE TOKEN BACKUP  drop every TOKEN occurrence
################################################################################

# Print the first non-blank line of FILE (the boot line).
cmdline_read_line() {
    grep -m1 '[^[:space:]]' "$1"
}

# Refuse (return 1, with a reason on stderr) unless FILE is a one-line boot
# cmdline carrying root=.
cmdline_check() {
    local file="$1" contentLines line

    if [ ! -f "$file" ]; then
        echo "ERROR: boot cmdline.txt not found at '${file}'." >&2
        echo "       On Raspberry Pi OS (bookworm) this lives at /boot/firmware/cmdline.txt." >&2
        return 1
    fi

    if [ ! -r "$file" ]; then
        echo "ERROR: '${file}' is not readable. Run this script with sudo." >&2
        return 1
    fi

    contentLines="$(grep -c '[^[:space:]]' "$file")"
    if [ "$contentLines" != "1" ]; then
        echo "ERROR: '${file}' has ${contentLines} non-blank lines; a boot cmdline is exactly 1." >&2
        echo "       Refusing to edit a malformed boot cmdline. Nothing was written." >&2
        return 1
    fi

    # `root=` is the token whose loss makes the Pi unbootable and headless. Its
    # presence is how we know this file is what we think it is; its survival is
    # verified again after every rewrite.
    line="$(cmdline_read_line "$file")"
    if ! printf '%s' "$line" | grep -qE '(^|[[:space:]])root='; then
        echo "ERROR: '${file}' carries no root= argument -- this is not a boot cmdline." >&2
        echo "       Refusing to edit it. Nothing was written." >&2
        return 1
    fi

    return 0
}

# Print the first token named NAME (NAME=...) on FILE's boot line; nothing if
# there is none. A bare flag (e.g. `quiet`) has no name and never matches.
cmdline_named_token() {
    local file="$1" name="$2"
    cmdline_read_line "$file" \
        | grep -oE "(^|[[:space:]])${name}=[^[:space:]]+" \
        | head -1 \
        | tr -d '[:space:]'
}

# Split LINE into whole tokens WITHOUT pathname expansion (an unquoted
# `for w in $line` would glob a token such as `*`), one per output line.
_cmdline_words() {
    local -a words
    read -ra words <<< "$1"
    [ "${#words[@]}" -eq 0 ] || printf '%s
' "${words[@]}"
}

# True if TOKEN is one whole token on LINE.
_cmdline_has_token() {
    local line="$1" token="$2" word
    while IFS= read -r word; do
        [ "$word" = "$token" ] && return 0
    done < <(_cmdline_words "$line")
    return 1
}

# A token argument must be one non-empty, whitespace-free word.
_cmdline_valid_token() {
    local token="$1"
    if [ -z "$token" ] || printf '%s' "$token" | grep -q '[[:space:]]'; then
        echo "ERROR: '${token}' is not a single cmdline token. Nothing was written." >&2
        return 1
    fi
    return 0
}

# Verify CANDIDATE keeps every token of ORIGINAL except DROPPED (may be empty),
# keeps root=, carries WANTED if given (may be empty), and never DROPPED.
_cmdline_verify() {
    local original="$1" candidate="$2" wanted="$3" dropped="$4" word
    while IFS= read -r word; do
        [ -n "$dropped" ] && [ "$word" = "$dropped" ] && continue
        _cmdline_has_token "$candidate" "$word" || return 1
    done < <(_cmdline_words "$original")
    printf '%s' "$candidate" | grep -qE '(^|[[:space:]])root=' || return 1
    if [ -n "$wanted" ]; then
        _cmdline_has_token "$candidate" "$wanted" || return 1
    fi
    if [ -n "$dropped" ]; then
        _cmdline_has_token "$candidate" "$dropped" && return 1
    fi
    return 0
}

# Back up FILE to BACKUP once (first-write-wins). Return 2 if the copy fails.
_cmdline_backup() {
    local file="$1" backup="$2"
    if [ ! -f "$backup" ]; then
        if ! cp "$file" "$backup"; then
            echo "ERROR: could not write backup ${backup}; refusing to modify the boot cmdline." >&2
            return 2
        fi
        echo "Backed up ${file} -> ${backup} (pristine original)."
    else
        echo "Backup ${backup} already exists (kept -- it holds the pristine original)."
    fi
    return 0
}

# Install NEWLINE as FILE via a temp file + mv, then re-read and re-verify.
_cmdline_install() {
    local file="$1" backup="$2" original="$3" newLine="$4" wanted="$5" dropped="$6"
    local tmp installedLines installedLine

    # Verify the COMPOSED line before it is installed, so the live boot cmdline
    # is never wrong even for an instant.
    if ! _cmdline_verify "$original" "$newLine" "$wanted" "$dropped"; then
        echo "ERROR: the composed boot cmdline lost an argument; ${file} left unchanged." >&2
        return 2
    fi

    tmp="$(dirname "$file")/.cmdline.txt.eclipse-tmp.$$"

    if ! printf '%s\n' "$newLine" > "$tmp"; then
        rm -f "$tmp"
        echo "ERROR: failed to compose the updated cmdline.txt; ${file} unchanged." >&2
        return 2
    fi

    if ! mv "$tmp" "$file"; then
        rm -f "$tmp"
        echo "ERROR: failed to install the updated ${file}." >&2
        echo "       The pristine copy is still at ${backup}." >&2
        return 2
    fi

    # Re-verify by re-reading the file just written -- not by trusting the variable.
    installedLines="$(grep -c '[^[:space:]]' "$file")"
    installedLine="$(cmdline_read_line "$file")"

    if [ "$installedLines" != "1" ] \
        || ! _cmdline_verify "$original" "$installedLine" "$wanted" "$dropped"; then
        echo "ERROR: post-write verification of ${file} FAILED. Restoring the backup." >&2
        if cp "$backup" "$file"; then
            echo "ERROR: restored the pristine ${file} from ${backup}. DO NOT REBOOT" >&2
            echo "ERROR: until this is understood, and verify the file by hand first." >&2
        else
            echo "ERROR: THE RESTORE ALSO FAILED. ${file} may be unbootable." >&2
            echo "ERROR: fix it by hand from ${backup} BEFORE rebooting this Pi." >&2
        fi
        return 2
    fi

    return 0
}

# Append TOKEN to FILE's boot line unless it is already there.
cmdline_add_token() {
    local file="$1" token="$2" backup="$3" line rc

    _cmdline_valid_token "$token" || return 1
    cmdline_check "$file" || return 1
    line="$(cmdline_read_line "$file")"

    if _cmdline_has_token "$line" "$token"; then
        echo "${token} is already in ${file} -- no change."
        return 0
    fi

    _cmdline_backup "$file" "$backup" || return 2
    _cmdline_install "$file" "$backup" "$line" "${line} ${token}" "$token" ""
    rc=$?
    return "$rc"
}

# Drop every occurrence of TOKEN from FILE's boot line; root= is never removable.
cmdline_remove_token() {
    local file="$1" token="$2" backup="$3" line word newLine="" rc

    _cmdline_valid_token "$token" || return 1
    cmdline_check "$file" || return 1
    line="$(cmdline_read_line "$file")"

    if printf '%s' "$token" | grep -qE '^root='; then
        echo "ERROR: refusing to remove '${token}' -- root= is what makes ${file} bootable." >&2
        return 1
    fi

    if ! _cmdline_has_token "$line" "$token"; then
        echo "${token} is not in ${file} -- no change."
        return 0
    fi

    while IFS= read -r word; do
        [ "$word" = "$token" ] && continue
        newLine="${newLine:+${newLine} }${word}"
    done < <(_cmdline_words "$line")

    _cmdline_backup "$file" "$backup" || return 2
    _cmdline_install "$file" "$backup" "$line" "$newLine" "" "$token"
    rc=$?
    return "$rc"
}
