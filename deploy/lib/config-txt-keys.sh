#!/usr/bin/env bash
################################################################################
# deploy/lib/config-txt-keys.sh — the ONE config.txt key writer (US-926-b)
#
# Sourced (never executed) by every deploy script that sets a standalone
# `key=value` line in the Pi's /boot/firmware/config.txt. Moved out of
# set-boot-screen.sh (its disable_splash writer, US-885-b) and generalised to a
# key + value so set-boot-screen.sh also sets camera_auto_detect=0 and
# display_auto_detect=0 through it (Atlas Q6, 2026-10-24: the firmware's BSC
# "no ACK" probes before Starting OS are the camera and DSI auto-detect, and
# this car has neither). The deploy/lib/cmdline-tokens.sh pattern.
#
# SECTION-AWARE: only the top level, [all] and [pi5] reach a Pi 5, and the LAST
# line for a key in those sections is the one the firmware uses (the EFFECTIVE
# value). config_txt_set_key makes KEY=VALUE effective:
#
#   1. Already effective -> nothing is written; the file stays byte-identical
#      and no backup is taken.
#   2. An effective line with another value -> that line is REWRITTEN IN PLACE
#      (never shadowed by a second line further down). A file with no final
#      newline keeps none, so a rewrite and its undo are byte-identical.
#   3. No effective line -> MARKER then KEY=VALUE are appended; an [all] is
#      opened between them if the file ends inside another section (e.g. [cm4]),
#      which a Pi 5 would never read.
#   4. Backup before write, first-write-wins: the caller names its backup path;
#      the first write copies the original there and later writes keep it.
#   5. Verify after write: the effective value is re-read from the installed
#      file; a mismatch is a loud failure naming the backup.
#
# Standalone `key=value` lines ONLY. A token inside a `dtparam=` comma list
# (enable-rtc-charging.sh's rtc_bbat_vchg) is a different shape this writer has
# no mode for -- that script keeps its own writer (recorded debt, US-926-b).
#
# Functions (return codes: 0 done or nothing to do; 1 refused, nothing written;
# 2 write or post-write verification failed):
#   config_txt_effective FILE KEY                  print KEY's effective value
#   config_txt_section_at_eof FILE                 print the section at EOF
#   config_txt_set_key FILE KEY VALUE BACKUP MARKER  make KEY=VALUE effective
#   config_txt_remove_block FILE MARKER LINE BACKUP  drop a MARKER + LINE block
################################################################################

# Print "<line number> <value>" for KEY's effective line in FILE; nothing if
# no section that reaches a Pi 5 sets it.
_config_txt_effective_line() {
    awk -v key="$2" '
        { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t\r]+$/, "", t) }
        t ~ /^\[/ { section = tolower(t); next }
        (section == "" || section == "[all]" || section == "[pi5]") && index(t, key) == 1 {
            rest = substr(t, length(key) + 1)
            if (rest ~ /^[ \t]*=/) { sub(/^[ \t]*=[ \t]*/, "", rest); n = NR; last = rest }
        }
        END { if (n) print n " " last }
    ' "$1"
}

# The EFFECTIVE value of KEY in FILE; "" if none.
config_txt_effective() {
    local found
    found="$(_config_txt_effective_line "$1" "$2")"
    printf '%s\n' "${found#* }"
}

# The section in effect at EOF, lowercased ("" = top level).
config_txt_section_at_eof() {
    awk '
        { t = $0; sub(/^[ \t]+/, "", t); sub(/[ \t\r]+$/, "", t) }
        t ~ /^\[/ { section = tolower(t) }
        END { print section }
    ' "$1"
}

# Refuse a file that is not a readable regular file.
_config_txt_check() {
    if [ ! -f "$1" ] || [ ! -r "$1" ]; then
        echo "ERROR: boot config.txt not found or unreadable at '${1}'. Nothing was written." >&2
        return 1
    fi
    return 0
}

# Back up FILE to BACKUP once (first-write-wins). Return 2 if the copy fails.
_config_txt_backup() {
    local file="$1" backup="$2"
    [ -f "$backup" ] && return 0
    if ! cp "$file" "$backup"; then
        echo "ERROR: could not write backup ${backup}; ${file} unchanged." >&2
        return 2
    fi
    echo "Backed up ${file} -> ${backup}."
    return 0
}

# Move TMP over FILE; on failure remove TMP and return 2.
_config_txt_install() {
    local tmp="$1" file="$2"
    if ! mv "$tmp" "$file"; then
        rm -f "$tmp"
        echo "ERROR: failed to install the updated ${file}." >&2
        return 2
    fi
    return 0
}

_config_txt_tmp() {
    printf '%s/.config.txt.eclipse-keys-tmp.%s' "$(dirname "$1")" "$$"
}

# Make KEY=VALUE the effective setting in FILE (rules 1-5 in the header).
config_txt_set_key() {
    local file="$1" key="$2" value="$3" backup="$4" marker="$5"
    local param="${2}=${3}" found="" lineNo="" header="" noFinalNewline="" tmp=""

    # Both reach awk -v (which interprets backslashes) and a firmware parser
    # that splits on '=': plain words only.
    if ! printf '%s' "$key" | grep -qE '^[A-Za-z0-9_]+$' \
        || ! printf '%s' "$value" | grep -qE '^[A-Za-z0-9_.,:+-]+$'; then
        echo "ERROR: '${param}' is not a plain config.txt key=value. Nothing was written." >&2
        return 1
    fi
    _config_txt_check "$file" || return 1

    found="$(_config_txt_effective_line "$file" "$key")"
    if [ -n "$found" ] && [ "${found#* }" = "$value" ]; then
        echo "${param} already effective in ${file} -- no change."
        return 0
    fi

    _config_txt_backup "$file" "$backup" || return 2
    tmp="$(_config_txt_tmp "$file")"

    if [ -n "$found" ]; then
        lineNo="${found%% *}"
        # A file whose last byte is not a newline keeps it that way, so a
        # rewrite and its undo are byte-identical.
        [ -n "$(tail -c1 "$file")" ] && noFinalNewline=1
        if ! awk -v n="$lineNo" -v param="$param" -v nofinal="$noFinalNewline" '
                NR > 1 { print prev }
                { prev = (NR == n) ? param : $0 }
                END { if (NR) { if (nofinal) printf "%s", prev; else print prev } }
            ' "$file" > "$tmp"; then
            rm -f "$tmp"
            echo "ERROR: failed to compose the updated ${file}; unchanged." >&2
            return 2
        fi
    else
        case "$(config_txt_section_at_eof "$file")" in
            ''|'[all]'|'[pi5]') ;;
            *) header="[all]" ;;
        esac
        if ! awk -v marker="$marker" -v hdr="$header" -v param="$param" \
                '{ print } END { print marker; if (hdr != "") print hdr; print param }' \
                "$file" > "$tmp"; then
            rm -f "$tmp"
            echo "ERROR: failed to compose the updated ${file}; unchanged." >&2
            return 2
        fi
    fi
    _config_txt_install "$tmp" "$file" || return 2

    if [ "$(config_txt_effective "$file" "$key")" != "$value" ]; then
        echo "ERROR: post-write verification failed -- no effective ${param} in ${file}." >&2
        echo "       Restore with: sudo cp ${backup} ${file}" >&2
        return 2
    fi
    if [ -n "$lineNo" ]; then
        echo "Applied ${param} to ${file} (line ${lineNo} rewritten in place)."
    else
        echo "Applied ${param} to ${file}."
    fi
    return 0
}

# Remove every block config_txt_set_key appended for LINE under MARKER: the
# marker, the [all] it opened (kept if later lines follow, since they were
# written under it), and LINE. A marker not followed by LINE is dropped alone.
# When what is left equals BACKUP but for awk's final newline, BACKUP's exact
# bytes are installed.
config_txt_remove_block() {
    local file="$1" marker="$2" param="$3" backup="$4" tmp

    _config_txt_check "$file" || return 1
    if ! grep -qxF -- "$marker" "$file"; then
        return 0
    fi

    tmp="$(_config_txt_tmp "$file")"
    if ! awk -v marker="$marker" -v param="$param" '
            { line[NR] = $0 }
            END {
                for (i = 1; i <= NR; i++) {
                    if (line[i] != marker) { print line[i]; continue }
                    j = i + 1
                    hdr = (j <= NR && line[j] == "[all]") ? j : 0
                    if (hdr) j++
                    if (j <= NR && line[j] == param) {
                        if (hdr && j < NR) print line[hdr]
                        i = j
                    } else {
                        i = j - 1
                    }
                }
            }
        ' "$file" > "$tmp"; then
        rm -f "$tmp"
        echo "ERROR: failed to compose the reverted ${file}; unchanged." >&2
        return 2
    fi

    if [ -f "$backup" ] && [ "$(cat "$tmp")" = "$(cat "$backup")" ]; then
        cp "$backup" "$tmp" || { rm -f "$tmp"; return 2; }
    fi
    _config_txt_install "$tmp" "$file" || return 2

    if grep -qxF -- "$marker" "$file"; then
        echo "ERROR: post-write verification failed -- the marked block is still in ${file}." >&2
        return 2
    fi
    return 0
}
