#!/usr/bin/env bash
################################################################################
# tests/deploy/test_cmdline_tokens.sh — shared cmdline.txt token helper catalog
#
# Verifies deploy/lib/cmdline-tokens.sh (US-885-a / F-139) against synthetic
# cmdline.txt fixtures. Runs entirely on the dev workstation -- no Pi, no real
# boot partition.
#
# WHY: two deploy scripts (set-display-mode.sh's video= pin and US-885-b's
# set-boot-screen.sh quiet-boot tokens) edit the ONE-line boot cmdline. Each
# must add/remove only the tokens it names, never clobber the other's, never
# lose root=, and never write a file that is already malformed.
#
# Usage:
#   bash tests/deploy/test_cmdline_tokens.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
LIB="$REPO_ROOT/deploy/lib/cmdline-tokens.sh"

PASS=0
FAIL=0

# ---- helpers ----

assert_rc() {
    local desc="$1" expected="$2" got="$3"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (rc=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected rc=$expected, got=$got)"
        FAIL=$((FAIL + 1))
    fi
}

assert_eq() {
    local desc="$1" expected="$2" got="$3"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected: $expected"
        echo "         got:      $got"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if printf '%s\n' "$haystack" | grep -qF -- "$needle"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected to find: $needle"
        echo "         in: $haystack"
        FAIL=$((FAIL + 1))
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

assert_absent() {
    local desc="$1" path="$2"
    if [ -e "$path" ]; then
        echo "  FAIL: $desc ($path exists)"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    fi
}

# Count whole-token occurrences of $1 in file $2.
token_count() {
    tr ' ' '\n' < "$2" | grep -cxF -- "$1"
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

LIVE_LINE='console=serial0,115200 console=tty1 root=PARTUUID=13c15a4b-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=US'

write_cmdline_fixture() {
    printf '%s\n' "$LIVE_LINE" > "$1"
}

if [ ! -f "$LIB" ]; then
    echo "FAIL: helper library missing: $LIB"
    echo
    echo "=== Results: 0 passed, 1 failed ==="
    exit 1
fi

# shellcheck source=../../deploy/lib/cmdline-tokens.sh
. "$LIB"

echo "=== deploy/lib/cmdline-tokens.sh — US-885-a scenario catalog ==="

# ---- 1. add appends once (the story example) ----
echo "--- Scenario 1: add video= to the live shape ---"
CMD="$WORK/s1-cmdline.txt"
write_cmdline_fixture "$CMD"
out=$(cmdline_add_token "$CMD" "video=HDMI-A-1:480x320" "$CMD.bak" 2>&1); rc=$?
assert_rc "add succeeds" 0 "$rc"
assert_eq "same line with video= appended once" \
    "$LIVE_LINE video=HDMI-A-1:480x320" "$(cat "$CMD")"
assert_eq "still exactly one line" "1" "$(wc -l < "$CMD" | tr -d ' ')"
assert_files_identical "backup is the pre-edit original" "$CMD.bak" <(printf '%s\n' "$LIVE_LINE")
assert_absent "no temp file left behind" "$(dirname "$CMD")/.cmdline.txt.eclipse-tmp.$$"

# ---- 2. add twice -> one token, second add byte-identical ----
echo "--- Scenario 2: add video= twice ---"
cp "$CMD" "$WORK/s2-before.txt"
out=$(cmdline_add_token "$CMD" "video=HDMI-A-1:480x320" "$CMD.bak" 2>&1); rc=$?
assert_rc "second add is a no-op success" 0 "$rc"
assert_eq "exactly one video= token" "1" "$(token_count "video=HDMI-A-1:480x320" "$CMD")"
assert_files_identical "file byte-identical after the second add" "$WORK/s2-before.txt" "$CMD"
assert_contains "says nothing changed" "already" "$out"

# ---- 3. remove a token that is not present -> byte-identical, no backup ----
echo "--- Scenario 3: remove a token not present ---"
CMD3="$WORK/s3-cmdline.txt"
write_cmdline_fixture "$CMD3"
cp "$CMD3" "$WORK/s3-before.txt"
out=$(cmdline_remove_token "$CMD3" "loglevel=3" "$CMD3.bak" 2>&1); rc=$?
assert_rc "remove of an absent token succeeds" 0 "$rc"
assert_files_identical "file byte-identical" "$WORK/s3-before.txt" "$CMD3"
assert_absent "no backup taken when nothing changes" "$CMD3.bak"

# ---- 4. remove a present token; every other token (root= too) survives ----
echo "--- Scenario 4: remove console=tty1 ---"
CMD4="$WORK/s4-cmdline.txt"
write_cmdline_fixture "$CMD4"
out=$(cmdline_remove_token "$CMD4" "console=tty1" "$CMD4.bak" 2>&1); rc=$?
assert_rc "remove succeeds" 0 "$rc"
assert_eq "console=tty1 gone, everything else in order" \
    'console=serial0,115200 root=PARTUUID=13c15a4b-02 rootfstype=ext4 fsck.repair=yes rootwait quiet splash plymouth.ignore-serial-consoles cfg80211.ieee80211_regdom=US' \
    "$(cat "$CMD4")"
assert_eq "the other console= token is untouched" "1" "$(token_count "console=serial0,115200" "$CMD4")"
assert_files_identical "backup is the pre-edit original" "$CMD4.bak" <(printf '%s\n' "$LIVE_LINE")
cp "$CMD4" "$WORK/s4-after.txt"
out=$(cmdline_remove_token "$CMD4" "console=tty1" "$CMD4.bak" 2>&1); rc=$?
assert_rc "second remove is a no-op success" 0 "$rc"
assert_files_identical "second remove byte-identical" "$WORK/s4-after.txt" "$CMD4"

# ---- 5. multi-line cmdline.txt is refused, file untouched ----
echo "--- Scenario 5: multi-line cmdline.txt ---"
CMD5="$WORK/s5-cmdline.txt"
printf 'root=PARTUUID=13c15a4b-02 rootwait\nquiet splash\n' > "$CMD5"
cp "$CMD5" "$WORK/s5-before.txt"
out=$(cmdline_add_token "$CMD5" "loglevel=3" "$CMD5.bak" 2>&1); rc=$?
assert_rc "add refuses a multi-line file" 1 "$rc"
assert_files_identical "file untouched by add" "$WORK/s5-before.txt" "$CMD5"
assert_absent "no backup on refusal" "$CMD5.bak"
out=$(cmdline_remove_token "$CMD5" "quiet" "$CMD5.bak" 2>&1); rc=$?
assert_rc "remove refuses a multi-line file" 1 "$rc"
assert_files_identical "file untouched by remove" "$WORK/s5-before.txt" "$CMD5"
assert_contains "names the line count" "2 non-blank lines" "$out"

# ---- 6. no root= is refused ----
echo "--- Scenario 6: cmdline.txt with no root= ---"
CMD6="$WORK/s6-cmdline.txt"
printf 'quiet splash\n' > "$CMD6"
cp "$CMD6" "$WORK/s6-before.txt"
out=$(cmdline_add_token "$CMD6" "loglevel=3" "$CMD6.bak" 2>&1); rc=$?
assert_rc "refuses a file with no root=" 1 "$rc"
assert_files_identical "file untouched" "$WORK/s6-before.txt" "$CMD6"
assert_contains "says why" "root=" "$out"

# ---- 7. missing cmdline.txt is refused ----
echo "--- Scenario 7: cmdline.txt absent ---"
out=$(cmdline_add_token "$WORK/nope/cmdline.txt" "loglevel=3" "$WORK/nope.bak" 2>&1); rc=$?
assert_rc "missing file refused" 1 "$rc"
assert_contains "names the missing path" "cmdline.txt" "$out"

# ---- 8. removing root= itself is refused ----
echo "--- Scenario 8: remove root= ---"
CMD8="$WORK/s8-cmdline.txt"
write_cmdline_fixture "$CMD8"
cp "$CMD8" "$WORK/s8-before.txt"
out=$(cmdline_remove_token "$CMD8" "root=PARTUUID=13c15a4b-02" "$CMD8.bak" 2>&1); rc=$?
assert_rc "refuses to remove root=" 1 "$rc"
assert_files_identical "file untouched" "$WORK/s8-before.txt" "$CMD8"

# ---- 9. a token must be a single whitespace-free word ----
echo "--- Scenario 9: malformed token arguments ---"
CMD9="$WORK/s9-cmdline.txt"
write_cmdline_fixture "$CMD9"
cp "$CMD9" "$WORK/s9-before.txt"
out=$(cmdline_add_token "$CMD9" "loglevel=3 init=/bin/sh" "$CMD9.bak" 2>&1); rc=$?
assert_rc "a token with a space is refused" 1 "$rc"
out=$(cmdline_add_token "$CMD9" "" "$CMD9.bak" 2>&1); rc=$?
assert_rc "an empty token is refused" 1 "$rc"
assert_files_identical "file untouched" "$WORK/s9-before.txt" "$CMD9"

# ---- 10. backup is first-write-wins (pristine original) ----
echo "--- Scenario 10: backup keeps the pristine original ---"
CMD10="$WORK/s10-cmdline.txt"
write_cmdline_fixture "$CMD10"
cmdline_add_token "$CMD10" "loglevel=3" "$CMD10.bak" >/dev/null 2>&1
cmdline_add_token "$CMD10" "vt.global_cursor_default=0" "$CMD10.bak" >/dev/null 2>&1
assert_files_identical "backup is still the very first original" "$CMD10.bak" <(printf '%s\n' "$LIVE_LINE")

# ---- 11. two writers in either order give the union ----
echo "--- Scenario 11: two writers, either order -> union of tokens ---"
A="$WORK/s11-a.txt"
B="$WORK/s11-b.txt"
write_cmdline_fixture "$A"
write_cmdline_fixture "$B"
cmdline_add_token "$A" "video=HDMI-A-1:480x320" "$A.bak" >/dev/null 2>&1
cmdline_add_token "$A" "loglevel=3" "$A.bak" >/dev/null 2>&1
cmdline_remove_token "$A" "console=tty1" "$A.bak" >/dev/null 2>&1
cmdline_remove_token "$B" "console=tty1" "$B.bak" >/dev/null 2>&1
cmdline_add_token "$B" "loglevel=3" "$B.bak" >/dev/null 2>&1
cmdline_add_token "$B" "video=HDMI-A-1:480x320" "$B.bak" >/dev/null 2>&1
sortedA="$(tr ' ' '\n' < "$A" | sort | tr '\n' ' ')"
sortedB="$(tr ' ' '\n' < "$B" | sort | tr '\n' ' ')"
assert_eq "same token set in either order" "$sortedA" "$sortedB"
assert_eq "video= present once" "1" "$(token_count "video=HDMI-A-1:480x320" "$A")"
assert_eq "loglevel=3 present once" "1" "$(token_count "loglevel=3" "$A")"
assert_eq "console=tty1 absent" "0" "$(token_count "console=tty1" "$A")"

# ---- 12. named-token lookup ----
echo "--- Scenario 12: cmdline_named_token ---"
CMD12="$WORK/s12-cmdline.txt"
printf '%s\n' 'root=PARTUUID=13c15a4b-02 rootwait video=HDMI-A-1:800x480@60 quiet' > "$CMD12"
assert_eq "finds the video= token by name" "video=HDMI-A-1:800x480@60" \
    "$(cmdline_named_token "$CMD12" video)"
assert_eq "an absent name prints nothing" "" "$(cmdline_named_token "$CMD12" loglevel)"
assert_eq "a bare flag is not a named token" "" "$(cmdline_named_token "$CMD12" quiet)"

# ---- summary ----
echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
