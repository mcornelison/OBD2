#!/usr/bin/env bash
################################################################################
# tests/deploy/test_set_display_mode.sh — HDMI/KMS output-mode pin test
#
# Verifies deploy/set-display-mode.sh against synthetic /sys/class/drm and
# /boot/firmware/cmdline.txt fixtures. Runs entirely on the dev workstation --
# no Pi required, no real boot partition touched. Three env seams stand in for
# the live surfaces (mirrors $PI_CONFIG_TXT in the US-524 CMA script):
#   $PI_DRM_DIR        -> /sys/class/drm         (connector status + EDID modes)
#   $PI_CMDLINE_TXT    -> /boot/firmware/cmdline.txt
#   $PI_FB_SIZE_FILE   -> /sys/class/graphics/fb0/virtual_size
#
# US-552 / F-127 (Atlas A-16 display-pipeline fidelity): the deploy pins NO
# output mode, so the Pi negotiates whatever EDID offers -- likely 1080p into a
# 480x320-native panel, which scale-up-then-downsamples every glyph and raises
# the legibility floor the US-540 type scale was set against.
#
# THE TWO SAFETY INTERLOCKS ARE THE POINT OF THIS CATALOG (scenarios 4 + 5).
# This script writes to cmdline.txt -- the surface US-524 deliberately refused
# to touch, because a corrupted one breaks `root=` on a Pi that lives in a car.
# It is the ONLY boot-level mechanism on a Pi 5 (the legacy hdmi_group/hdmi_mode
# config.txt settings are not supported there), so the risk is bounded instead
# of avoided:
#   - the connector is DISCOVERED from sysfs, never assumed (scenario 9), and a
#     panel that is absent or ambiguous means NOTHING is written (4, 6);
#   - the target mode must be one the panel ITSELF advertises (5). A mode the
#     panel never claimed could scan out black in a car with no local recovery,
#     so an unadvertised target is a loud refusal, not a forced timing;
#   - the rewritten line is verified BEFORE it is installed and again after, and
#     a malformed multi-line cmdline.txt is refused outright (10, 11).
#
# Usage:
#   bash tests/deploy/test_set_display_mode.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/set-display-mode.sh"

PASS=0
FAIL=0

# ---- helpers ----

assert_exit() {
    local desc="$1" expected="$2" got="$3"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (exit=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected exit=$expected, got=$got)"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if echo "$haystack" | grep -qF -- "$needle"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected to find: $needle"
        echo "         in: $haystack"
        FAIL=$((FAIL + 1))
    fi
}

assert_lacks() {
    local desc="$1" needle="$2" haystack="$3"
    if echo "$haystack" | grep -qF -- "$needle"; then
        echo "  FAIL: $desc"
        echo "         did NOT expect to find: $needle"
        echo "         in: $haystack"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    fi
}

assert_file_contains() {
    local desc="$1" needle="$2" file="$3"
    if grep -qF -- "$needle" "$file" 2>/dev/null; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected to find: $needle"
        echo "         in file: $file"
        [ -f "$file" ] && sed -n '1,10p' "$file"
        FAIL=$((FAIL + 1))
    fi
}

assert_file_lacks() {
    local desc="$1" needle="$2" file="$3"
    if grep -qF -- "$needle" "$file" 2>/dev/null; then
        echo "  FAIL: $desc"
        echo "         did NOT expect to find: $needle"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    fi
}

assert_files_identical() {
    local desc="$1" a="$2" b="$3"
    if cmp -s "$a" "$b"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (files differ)"
        diff "$a" "$b" | head -10
        FAIL=$((FAIL + 1))
    fi
}

assert_line_count() {
    local desc="$1" expected="$2" file="$3" got
    got="$(wc -l < "$file" | tr -d ' ')"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (lines=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected $expected line(s), got $got)"
        FAIL=$((FAIL + 1))
    fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The live Pi's cmdline.txt shape (Raspberry Pi OS bookworm, Pi 5): ONE line,
# space-separated kernel args, `root=` load-bearing. Every scenario that writes
# asserts these tokens survive -- losing root= is the unbootable-headless-box
# failure US-524's header warns about.
write_cmdline_fixture() {
    printf '%s\n' \
'console=serial0,115200 console=tty1 root=PARTUUID=13c15a4b-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=US' \
        > "$1"
}

# A sysfs-shaped DRM tree. $1 = dir, $2 = HDMI-A-1 status, $3 = HDMI-A-1 modes,
# $4 = HDMI-A-2 status, $5 = HDMI-A-2 modes. Real sysfs `status` files carry a
# trailing newline and `modes` is one mode per line, PREFERRED FIRST.
write_drm_fixture() {
    local dir="$1"
    rm -rf "$dir"
    mkdir -p "$dir/card1-HDMI-A-1" "$dir/card1-HDMI-A-2"
    printf '%s\n' "$2" > "$dir/card1-HDMI-A-1/status"
    printf '%s' "$3" > "$dir/card1-HDMI-A-1/modes"
    printf '%s\n' "$4" > "$dir/card1-HDMI-A-2/status"
    printf '%s' "$5" > "$dir/card1-HDMI-A-2/modes"
}

# A SYNTHETIC panel that DOES advertise the target mode. It exercises the
# script's WRITE path and nothing more.
#
# ** IT IS NOT WHAT THE SHIPPING PANEL REPORTS. ** Until US-560 the comment here
# claimed it was ("as a 3.5\" 480x320 HDMI panel reports it"), which is how a
# fixture came to manufacture the very fact that made US-552 look applicable:
# nobody had read the panel's EDID, so the suite could only ever go green.
# Grounding a hardware claim in a fixture is the fabrication Refusal Rule 2
# exists to stop. The measured list is below; scenario 15 pins it.
PANEL_MODES='1920x1080
1280x720
640x480
480x320
'

# The SHIPPING panel's REAL advertised list -- MEASURED 2026-08-21 on
# chi-eclipse-01 (US-560) via `cat /sys/class/drm/card1-HDMI-A-1/modes`, with
# the EDID identifying mfg=OSY model=HDMI35 and a PREFERRED detailed timing of
# 1280x720. There is NO 480x320 anywhere in it.
#
# The 3.5" GLASS is 480x320 (docs/hardware-reference.md), but the panel is a
# SCALER: it accepts standard HDMI timings and downsamples to the glass in
# hardware. Glass resolution and signal timing are two different quantities --
# conflating them is what put a 480x320 KMS target on a panel that never
# offered one.
OSOYOO_HDMI35_MEASURED_MODES='1280x720
1920x1080
1280x1024
1440x900
1280x800
1024x768
800x600
720x480
640x480
720x400
'
NO_PANEL_MODES=''

FB_1080P="$WORK/fb-1080p"
printf '1920,1080\n' > "$FB_1080P"
FB_NATIVE="$WORK/fb-native"
printf '480,320\n' > "$FB_NATIVE"
# What the live Pi actually scans out today (measured 2026-08-21, US-560).
FB_720P="$WORK/fb-720p"
printf '1280,720\n' > "$FB_720P"

echo "=== deploy/set-display-mode.sh — US-552 scenario catalog ==="

# ---- 1. the live shape: panel on HDMI-A-1, output negotiated to 1080p ----
echo "--- Scenario 1: 480x320 panel scanning out 1080p -> pin it ---"
DRM="$WORK/s1-drm"
CMD="$WORK/s1-cmdline.txt"
write_drm_fixture "$DRM" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD"
cp "$CMD" "$WORK/s1-original.txt"
out=$(PI_DRM_DIR="$DRM" PI_CMDLINE_TXT="$CMD" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_file_contains "cmdline gained the video= pin" "video=HDMI-A-1:480x320" "$CMD"
assert_line_count "cmdline is still exactly ONE line" 1 "$CMD"
assert_file_contains "root= survived" "root=PARTUUID=13c15a4b-02" "$CMD"
assert_file_contains "trailing arg survived" "cfg80211.ieee80211_regdom=US" "$CMD"
assert_file_contains "leading arg survived" "console=serial0,115200" "$CMD"
assert_contains "announces the reboot requirement" "REBOOT REQUIRED" "$out"
assert_contains "reports the mode it OBSERVED, not just the one it set" "1920x1080" "$out"
assert_contains "names the connector it discovered" "HDMI-A-1" "$out"
assert_file_contains "backup captured the pristine original" "root=PARTUUID=13c15a4b-02" "$CMD.eclipse-bak"
assert_file_lacks "backup is pre-change (no video= pin)" "video=" "$CMD.eclipse-bak"

# ---- 2. re-run is a no-op (idempotency) ----
echo "--- Scenario 2: re-run on an already-pinned cmdline ---"
cp "$CMD" "$WORK/s2-before.txt"
out=$(PI_DRM_DIR="$DRM" PI_CMDLINE_TXT="$CMD" PI_FB_SIZE_FILE="$FB_NATIVE" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "no-op exits 0" 0 "$rc"
assert_contains "reports already-pinned" "already" "$out"
assert_lacks "does NOT re-announce a reboot it did not earn" "REBOOT REQUIRED" "$out"
assert_files_identical "file byte-identical after re-run" "$WORK/s2-before.txt" "$CMD"

# ---- 3. a FOREIGN video= is respected, never clobbered ----
echo "--- Scenario 3: operator already pinned a different mode ---"
DRM3="$WORK/s3-drm"
CMD3="$WORK/s3-cmdline.txt"
write_drm_fixture "$DRM3" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
printf '%s\n' 'root=PARTUUID=13c15a4b-02 rootwait video=HDMI-A-1:800x480@60 quiet' > "$CMD3"
cp "$CMD3" "$WORK/s3-before.txt"
out=$(PI_DRM_DIR="$DRM3" PI_CMDLINE_TXT="$CMD3" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "leaves the deploy healthy (exit 0)" 0 "$rc"
assert_contains "warns loudly" "WARN" "$out"
assert_contains "names the foreign value" "video=HDMI-A-1:800x480@60" "$out"
assert_files_identical "file NOT modified" "$WORK/s3-before.txt" "$CMD3"
assert_file_lacks "no backup written when nothing changed" "root=" "$CMD3.eclipse-bak"

# ---- 4. SAFETY INTERLOCK: no connected panel -> write nothing ----
echo "--- Scenario 4: no HDMI connector reports connected (bench, panel unplugged) ---"
DRM4="$WORK/s4-drm"
CMD4="$WORK/s4-cmdline.txt"
write_drm_fixture "$DRM4" "disconnected" "$NO_PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD4"
cp "$CMD4" "$WORK/s4-before.txt"
out=$(PI_DRM_DIR="$DRM4" PI_CMDLINE_TXT="$CMD4" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "does NOT halt the deploy (exit 0)" 0 "$rc"
assert_contains "warns that nothing was pinned" "WARN" "$out"
assert_files_identical "file NOT modified" "$WORK/s4-before.txt" "$CMD4"

# ---- 5. SAFETY INTERLOCK: the panel never advertises the target mode ----
echo "--- Scenario 5: connected panel does NOT advertise 480x320 ---"
DRM5="$WORK/s5-drm"
CMD5="$WORK/s5-cmdline.txt"
write_drm_fixture "$DRM5" "connected" '1920x1080
1280x720
' "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD5"
cp "$CMD5" "$WORK/s5-before.txt"
out=$(PI_DRM_DIR="$DRM5" PI_CMDLINE_TXT="$CMD5" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses to force an unadvertised timing, deploy healthy" 0 "$rc"
assert_contains "warns" "WARN" "$out"
assert_contains "reports what the panel DOES advertise" "1920x1080" "$out"
assert_contains "names the mode it wanted" "480x320" "$out"
assert_files_identical "file NOT modified" "$WORK/s5-before.txt" "$CMD5"

# ---- 6. SAFETY INTERLOCK: two connected connectors is ambiguous ----
echo "--- Scenario 6: both HDMI connectors connected ---"
DRM6="$WORK/s6-drm"
CMD6="$WORK/s6-cmdline.txt"
write_drm_fixture "$DRM6" "connected" "$PANEL_MODES" "connected" "$PANEL_MODES"
write_cmdline_fixture "$CMD6"
cp "$CMD6" "$WORK/s6-before.txt"
out=$(PI_DRM_DIR="$DRM6" PI_CMDLINE_TXT="$CMD6" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses to guess which panel, deploy healthy" 0 "$rc"
assert_contains "warns" "WARN" "$out"
assert_contains "names both connectors" "HDMI-A-2" "$out"
assert_files_identical "file NOT modified" "$WORK/s6-before.txt" "$CMD6"

# ---- 7. missing cmdline.txt is a loud config error ----
echo "--- Scenario 7: cmdline.txt absent ---"
DRM7="$WORK/s7-drm"
write_drm_fixture "$DRM7" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
out=$(PI_DRM_DIR="$DRM7" PI_CMDLINE_TXT="$WORK/nope/cmdline.txt" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "missing target exits 1" 1 "$rc"
assert_contains "names the missing path" "cmdline.txt" "$out"

# ---- 8. a malformed target mode is refused BEFORE any write ----
echo "--- Scenario 8: ECLIPSE_DISPLAY_MODE=not-a-mode ---"
DRM8="$WORK/s8-drm"
CMD8="$WORK/s8-cmdline.txt"
write_drm_fixture "$DRM8" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD8"
cp "$CMD8" "$WORK/s8-before.txt"
out=$(ECLIPSE_DISPLAY_MODE="not-a-mode" PI_DRM_DIR="$DRM8" PI_CMDLINE_TXT="$CMD8" \
      PI_FB_SIZE_FILE="$FB_1080P" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "malformed mode exits 1" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s8-before.txt" "$CMD8"

# ---- 9. the connector is DISCOVERED, not assumed to be HDMI-A-1 ----
echo "--- Scenario 9: the panel is on HDMI-A-2 ---"
DRM9="$WORK/s9-drm"
CMD9="$WORK/s9-cmdline.txt"
write_drm_fixture "$DRM9" "disconnected" "$NO_PANEL_MODES" "connected" "$PANEL_MODES"
write_cmdline_fixture "$CMD9"
out=$(PI_DRM_DIR="$DRM9" PI_CMDLINE_TXT="$CMD9" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "pins the connector that is actually connected" 0 "$rc"
assert_file_contains "pinned HDMI-A-2" "video=HDMI-A-2:480x320" "$CMD9"
assert_file_lacks "did NOT pin the empty port" "HDMI-A-1" "$CMD9"

# ---- 10. a multi-line cmdline.txt is refused (already malformed) ----
echo "--- Scenario 10: cmdline.txt carries two lines ---"
DRM10="$WORK/s10-drm"
CMD10="$WORK/s10-cmdline.txt"
write_drm_fixture "$DRM10" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
printf 'root=PARTUUID=13c15a4b-02 rootwait\nquiet splash\n' > "$CMD10"
cp "$CMD10" "$WORK/s10-before.txt"
out=$(PI_DRM_DIR="$DRM10" PI_CMDLINE_TXT="$CMD10" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses a malformed boot cmdline (exit 1)" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s10-before.txt" "$CMD10"

# ---- 11. a cmdline.txt with no root= is refused ----
echo "--- Scenario 11: cmdline.txt has no root= (not a boot cmdline) ---"
DRM11="$WORK/s11-drm"
CMD11="$WORK/s11-cmdline.txt"
write_drm_fixture "$DRM11" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
printf 'quiet splash\n' > "$CMD11"
cp "$CMD11" "$WORK/s11-before.txt"
out=$(PI_DRM_DIR="$DRM11" PI_CMDLINE_TXT="$CMD11" PI_FB_SIZE_FILE="$FB_1080P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses to edit a file that is not a boot cmdline (exit 1)" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s11-before.txt" "$CMD11"

# ---- 12. the pristine backup survives a SECOND change ----
echo "--- Scenario 12: backup is first-write-wins (pristine original) ---"
DRM12="$WORK/s12-drm"
CMD12="$WORK/s12-cmdline.txt"
write_drm_fixture "$DRM12" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD12"
PI_DRM_DIR="$DRM12" PI_CMDLINE_TXT="$CMD12" PI_FB_SIZE_FILE="$FB_1080P" \
    bash "$SCRIPT" >/dev/null 2>&1
# Hand-restore the un-pinned file and re-run; the backup must still be the
# ORIGINAL, not the pinned intermediate.
write_cmdline_fixture "$CMD12"
PI_DRM_DIR="$DRM12" PI_CMDLINE_TXT="$CMD12" PI_FB_SIZE_FILE="$FB_1080P" \
    bash "$SCRIPT" >/dev/null 2>&1
assert_file_lacks "backup still carries no video= at all" "video=" "$CMD12.eclipse-bak"

# ---- 13. the target mode is a parameter, not a constant ----
echo "--- Scenario 13: ECLIPSE_DISPLAY_MODE=640x480 (advertised) ---"
DRM13="$WORK/s13-drm"
CMD13="$WORK/s13-cmdline.txt"
write_drm_fixture "$DRM13" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD13"
out=$(ECLIPSE_DISPLAY_MODE="640x480" PI_DRM_DIR="$DRM13" PI_CMDLINE_TXT="$CMD13" \
      PI_FB_SIZE_FILE="$FB_1080P" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "honours a supported override" 0 "$rc"
assert_file_contains "pinned the override mode" "video=HDMI-A-1:640x480" "$CMD13"
assert_file_lacks "did not also pin the default" "480x320" "$CMD13"

# ---- 14. an absent framebuffer file must not break the run ----
echo "--- Scenario 14: /sys/class/graphics/fb0/virtual_size missing ---"
DRM14="$WORK/s14-drm"
CMD14="$WORK/s14-cmdline.txt"
write_drm_fixture "$DRM14" "connected" "$PANEL_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD14"
out=$(PI_DRM_DIR="$DRM14" PI_CMDLINE_TXT="$CMD14" PI_FB_SIZE_FILE="$WORK/nope/fb" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "still pins (the observed mode is informational)" 0 "$rc"
assert_file_contains "pin applied" "video=HDMI-A-1:480x320" "$CMD14"
assert_contains "says the observation is unavailable rather than inventing one" "unknown" "$out"

# ---- 15. the SHIPPING panel, as measured: 480x320 is UNREACHABLE ----
#
# US-560 set out to APPLY the US-552 pin to the live Pi and could not: the
# OSOYOO HDMI35 advertises no 480x320 timing at all, so interlock 5 refused --
# correctly, and without writing a byte. That refusal is the story's finding.
#
# This scenario pins the MEASURED hardware against the real script so the fact
# survives as a tested contract instead of being rediscovered from a car seat.
# It is deliberately disposition-INDEPENDENT: it asserts what the panel offers
# and that we do not force a timing it never claimed. It does not encode any
# particular ruling on what to pin INSTEAD -- that call is Atlas's (BL-034).
echo "--- Scenario 15: real OSOYOO HDMI35 EDID -> 480x320 is not advertised ---"
DRM15="$WORK/s15-drm"
CMD15="$WORK/s15-cmdline.txt"
write_drm_fixture "$DRM15" "connected" "$OSOYOO_HDMI35_MEASURED_MODES" "disconnected" "$NO_PANEL_MODES"
write_cmdline_fixture "$CMD15"
cp "$CMD15" "$WORK/s15-original.txt"
out=$(PI_DRM_DIR="$DRM15" PI_CMDLINE_TXT="$CMD15" PI_FB_SIZE_FILE="$FB_720P" \
      bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses on the REAL panel, deploy stays healthy" 0 "$rc"
assert_files_identical "the boot cmdline was NOT touched" "$CMD15" "$WORK/s15-original.txt"
assert_contains "names the unadvertised target" "does not advertise 480x320" "$out"
assert_contains "routes the disposition to Atlas rather than forcing it" "EDID finding for Atlas" "$out"
assert_contains "reports the observed 720p rather than inventing a mode" "1280x720" "$out"
# 720x480 is the ONLY advertised mode that shares the glass's 3:2 aspect
# (480/320 = 720/480 = 1.5); every other entry is 16:9, 4:3, 16:10 or 5:4.
# Asserted so the alternative Atlas is asked to rule on stays grounded in the
# measured list rather than being invented later from memory.
assert_contains "surfaces the real advertised list for the ruling" "720x480" "$out"

# ---- summary ----
echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
