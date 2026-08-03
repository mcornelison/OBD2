#!/usr/bin/env bash
################################################################################
# set-gpu-cma.sh — Pi 5 GPU CMA pool sizing (US-524 / F-124)
#
# Idempotently ensures the vc4-kms-v3d overlay in /boot/firmware/config.txt
# carries a `cma-<MB>` parameter (default 256), raising the contiguous-memory
# pool the GPU/display stack allocates from. Complements US-522's
# `--disable-gpu`; it is NOT a standalone fix for the kiosk freeze class.
#
# **Why config.txt and NOT cmdline.txt.** Grounded on the live Pi
# (10.27.27.100, Raspberry Pi 5 Model B Rev 1.1, 2026-08-03):
#   - /proc/cmdline carries NO `cma=` parameter. The 64 MiB pool comes from
#     the device tree: `dmesg` shows "Reserved memory: created CMA memory pool
#     ... size 64 MiB" against the `linux,cma` reserved-memory node.
#   - /boot/firmware/config.txt carries a bare `dtoverlay=vc4-kms-v3d`.
#   - /boot/firmware/overlays/README documents cma-64 .. cma-512 params on
#     vc4-kms-v3d (and on -pi4; -pi5 "See vc4-kms-v3d-pi4"). This is the
#     vendor-supported mechanism for the size the device tree declares.
# The overlay param is also the RECOVERABLE mechanism: a bad overlay param
# makes the firmware skip the overlay (dark display, SSH still up), whereas a
# malformed cmdline.txt can break `root=` and leave an unbootable headless box.
#
# Usage (run directly on the Pi):
#   sudo bash deploy/set-gpu-cma.sh
#
# Behavior:
#   - Locates the EFFECTIVE `dtoverlay=vc4-kms-v3d[-pi4|-pi5]` line: uncommented,
#     and in a section that applies to this board (top-level, [all], or [pi5]).
#     A line inside e.g. [cm4] is NOT a target -- appending there would be a
#     false "applied" claim on a Pi 5.
#   - Already `cma-<MB>` at the requested size -> no-op.
#   - A DIFFERENT `cma-*` param already present -> left alone with a loud WARN.
#     Someone else owns that value; an optional headroom tweak must not clobber
#     an explicit operator/tuning decision, nor fail an otherwise-good deploy.
#   - Otherwise -> back up config.txt once, append `,cma-<MB>`, verify the
#     rewritten line, and announce that a REBOOT is required.
#
# The change takes effect ONLY on the next boot. This script never reboots and
# never claims the pool was raised -- `grep CmaTotal /proc/meminfo` still reads
# the old value until then, and saying otherwise would be a confident lie.
#
# Test override:
#   - $PI_CONFIG_TXT retargets the file (test harness points it at a fixture).
#     Production callers leave it unset and the real boot config is used.
#   - $ECLIPSE_CMA_MB overrides the size; must be an overlay-supported value.
#
# Exit codes:
#   0  success (applied, already correct, or foreign cma- left alone)
#   1  configuration error (target file missing/unreadable, unsupported size)
#   2  write or post-write verification failed
#   3  no applicable vc4-kms-v3d overlay line to modify (nothing written)
################################################################################

set -u

TARGET="${PI_CONFIG_TXT:-/boot/firmware/config.txt}"
CMA_MB="${ECLIPSE_CMA_MB:-256}"
BACKUP="${TARGET}.eclipse-bak"

# Sizes the vc4-kms-v3d overlay actually accepts, read from the Pi's own
# /boot/firmware/overlays/README (2026-08-03). An unsupported value would make
# the firmware reject the overlay -- i.e. no KMS driver and a dark display --
# so it is refused here BEFORE anything is written.
SUPPORTED_CMA_SIZES="64 96 128 192 256 320 384 448 512"

sizeIsSupported() {
    local candidate="$1" size
    for size in $SUPPORTED_CMA_SIZES; do
        [ "$candidate" = "$size" ] && return 0
    done
    return 1
}

if ! sizeIsSupported "$CMA_MB"; then
    echo "ERROR: CMA size '${CMA_MB}' is not supported by the vc4-kms-v3d overlay." >&2
    echo "       Supported sizes (MB): ${SUPPORTED_CMA_SIZES}" >&2
    echo "       Nothing was written." >&2
    exit 1
fi

if [ ! -f "$TARGET" ]; then
    echo "ERROR: boot config.txt not found at '${TARGET}'." >&2
    echo "       On Raspberry Pi OS (bookworm) this lives at /boot/firmware/config.txt." >&2
    exit 1
fi

if [ ! -r "$TARGET" ]; then
    echo "ERROR: '${TARGET}' is not readable. Run this script with sudo." >&2
    exit 1
fi

# Locate the EFFECTIVE overlay line and print its 1-based line number.
#
# config.txt is section-scoped: a `[cm4]` / `[pi4]` / `[HDMI:0]` header makes
# every following line conditional until the next header. Only the implicit
# top-level section, `[all]`, and `[pi5]` reach this board, so only those are
# considered -- otherwise we would append cma to a line the firmware ignores
# and then report success.
findOverlayLine() {
    awk '
        {
            t = $0
            sub(/^[ \t]+/, "", t)
            sub(/[ \t]+$/, "", t)
        }
        t ~ /^\[/ { section = tolower(t); next }
        (section == "" || section == "[all]" || section == "[pi5]") &&
        t ~ /^dtoverlay[ \t]*=[ \t]*vc4-kms-v3d(-pi4|-pi5)?([ \t]*,.*)?$/ {
            print NR
            exit
        }
    ' "$1"
}

lineNo="$(findOverlayLine "$TARGET")"

if [ -z "$lineNo" ]; then
    echo "ERROR: no applicable 'dtoverlay=vc4-kms-v3d' line found in ${TARGET}." >&2
    echo "       Looked in the top-level, [all] and [pi5] sections only (a line" >&2
    echo "       under e.g. [cm4] does not apply to a Pi 5). Commented-out lines" >&2
    echo "       are ignored. CMA left at its device-tree default; nothing written." >&2
    exit 3
fi

currentLine="$(sed -n "${lineNo}p" "$TARGET")"

# Token-match the params, never a substring of the whole line: `cma-256` is a
# prefix of nothing valid here, but `cma-` params are comma-separated and a
# raw `grep -F cma-256` would also match a comment or an unrelated overlay.
if printf '%s' "$currentLine" | grep -qE ',[[:space:]]*cma-'"${CMA_MB}"'[[:space:]]*(,|$)'; then
    echo "cma-${CMA_MB} already set on the vc4-kms-v3d overlay (line ${lineNo}) -- no change."
    echo "  ${currentLine}"
    exit 0
fi

if printf '%s' "$currentLine" | grep -qE ',[[:space:]]*cma-'; then
    existingCma="$(printf '%s' "$currentLine" | grep -oE 'cma-[^,[:space:]]*' | head -1)"
    echo "WARN: the vc4-kms-v3d overlay already carries '${existingCma}' (line ${lineNo})." >&2
    echo "WARN: leaving it alone -- US-524 will not clobber an explicitly-set CMA size." >&2
    echo "WARN: to move to cma-${CMA_MB}, edit ${TARGET} by hand and reboot." >&2
    echo "  ${currentLine}"
    exit 0
fi

# ---- apply ----

# Back up ONCE, first-write-wins, so the preserved copy is the pristine
# pre-Eclipse original rather than whatever the previous run left behind.
if [ ! -f "$BACKUP" ]; then
    if ! cp "$TARGET" "$BACKUP"; then
        echo "ERROR: could not write backup ${BACKUP}; refusing to modify boot config." >&2
        exit 2
    fi
    echo "Backed up ${TARGET} -> ${BACKUP} (pristine original)."
else
    echo "Backup ${BACKUP} already exists (kept -- it holds the pristine original)."
fi

trimmedLine="$(printf '%s' "$currentLine" | sed -E 's/[[:space:]]+$//')"
newLine="${trimmedLine},cma-${CMA_MB}"

# Write beside the target and rename, so an interrupted write can never leave a
# truncated config.txt on the boot partition.
tmp="$(dirname "$TARGET")/.config.txt.eclipse-tmp.$$"
trap 'rm -f "$tmp"' EXIT

if ! awk -v n="$lineNo" -v repl="$newLine" 'NR == n { print repl; next } { print }' \
        "$TARGET" > "$tmp"; then
    echo "ERROR: failed to compose the updated config.txt; ${TARGET} unchanged." >&2
    exit 2
fi

if ! mv "$tmp" "$TARGET"; then
    echo "ERROR: failed to install the updated ${TARGET}." >&2
    echo "       The pristine copy is still at ${BACKUP}." >&2
    exit 2
fi

# Verify by re-reading the file we just wrote -- not by trusting the variable.
verifyNo="$(findOverlayLine "$TARGET")"
verifyLine=""
[ -n "$verifyNo" ] && verifyLine="$(sed -n "${verifyNo}p" "$TARGET")"

if ! printf '%s' "$verifyLine" | grep -qE ',[[:space:]]*cma-'"${CMA_MB}"'[[:space:]]*(,|$)'; then
    echo "ERROR: post-write verification failed -- cma-${CMA_MB} is not present in ${TARGET}." >&2
    echo "       Restore with: sudo cp ${BACKUP} ${TARGET}" >&2
    exit 2
fi

echo "Applied cma-${CMA_MB} to the vc4-kms-v3d overlay (line ${verifyNo}):"
echo "  ${verifyLine}"
echo "REBOOT REQUIRED: the CMA pool is still at its previous size until the Pi reboots."
echo "  Confirm after reboot with: grep CmaTotal /proc/meminfo   (expect ~$((CMA_MB * 1024)) kB)"
exit 0
