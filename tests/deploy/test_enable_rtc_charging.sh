#!/usr/bin/env bash
################################################################################
# tests/deploy/test_enable_rtc_charging.sh — Pi 5 RTC trickle-charge enablement
#
# Verifies deploy/enable-rtc-charging.sh against synthetic
# /boot/firmware/config.txt fixtures. Runs entirely on the dev workstation --
# no Pi required, no real boot partition touched. The production script's
# $PI_CONFIG_TXT override is the test seam (identical to the US-524
# set-gpu-cma.sh seam, and to $RPI_EEPROM_CONFIG in the US-253 script).
#
# US-620 / F-138. Measured on chi-eclipse-01 2026-08-28:
#   - /sys/class/rtc/rtc0/battery_voltage    = 0
#   - /sys/class/rtc/rtc0/charging_voltage   = 0
#   - /sys/class/rtc/rtc0/charging_voltage_max = 4400000   (4.4 V)
#   - /boot/firmware/config.txt has NO rtc/bbat line
#   - kernel on every boot: "setting system clock to 1970-01-01T00:00:13 UTC"
# The Pi 5 ships with RTC battery charging DISABLED and the cell it takes is
# RECHARGEABLE, so a NEW, correctly-fitted battery still reads 0 -- it was
# never charged. battery_voltage and charging_voltage are SEPARATE registers;
# reading both is what distinguishes a dead cell from an uncharged one.
#
# The fix is `dtparam=rtc_bbat_vchg=3000000` in config.txt, and it must be
# DEPLOY-MANAGED rather than hand-typed on the Pi -- the A-18 lesson (the live
# eclipse-rfkill-unblock fix was repo-unmanaged and a reflash would have lost
# it). A hand-typed RTC line has exactly that fate.
#
# Fixture fidelity: scenario 1 uses the live Pi's actual config.txt shape,
# including the trailing [cm4]/[cm5]/[all] conditional-filter sections.
# Section tracking is load-bearing in BOTH directions here:
#   - appending into a section that does not apply to a Pi 5 would be a false
#     "applied" claim (scenario 5), and
#   - an EXISTING rtc param inside such a section must not be read as "already
#     configured" (scenario 11) -- that would leave charging off while
#     reporting success, which is the exact inert-guard shape this project has
#     catalogued repeatedly.
#
# Usage:
#   bash tests/deploy/test_enable_rtc_charging.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/enable-rtc-charging.sh"

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

assert_not_contains() {
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
        [ -f "$file" ] && sed -n '1,40p' "$file"
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

# Re-reads the written file the way the FIRMWARE would: walks sections and
# reports the effective rtc_bbat_vchg value that actually applies to a Pi 5.
# Deliberately an independent re-implementation -- asserting with the
# production script's own finder would let a broken finder pass itself.
effective_rtc_value() {
    awk '
        {
            t = $0
            sub(/^[ \t]+/, "", t)
            sub(/[ \t]+$/, "", t)
        }
        t ~ /^\[/ { section = tolower(t); next }
        (section == "" || section == "[all]" || section == "[pi5]") &&
        t ~ /^dtparam[ \t]*=/ && t ~ /rtc_bbat_vchg[ \t]*=/ {
            v = t
            sub(/.*rtc_bbat_vchg[ \t]*=[ \t]*/, "", v)
            sub(/[,[:space:]].*$/, "", v)
            print v
            exit
        }
    ' "$1"
}

assert_effective_value() {
    local desc="$1" expected="$2" file="$3"
    local got
    got="$(effective_rtc_value "$file")"
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (effective=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected effective='$expected', got='$got')"
        sed -n '1,40p' "$file"
        FAIL=$((FAIL + 1))
    fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The live Pi's config.txt shape (chi-eclipse-01), which ends inside [all].
write_live_fixture() {
    cat > "$1" <<'EOF'
# For more options and information see
# http://rptl.io/configtxt

dtparam=i2c_arm=on
#dtparam=spi=on

dtparam=audio=on

camera_auto_detect=1
display_auto_detect=1
auto_initramfs=1

# Enable DRM VC4 V3D driver
dtoverlay=vc4-kms-v3d
max_framebuffers=2

disable_fw_kms_setup=1
arm_64bit=1
disable_overscan=1
arm_boost=1


[cm4]
otg_mode=1

[cm5]
dtoverlay=dwc2,dr_mode=host

[all]
EOF
}

echo "=== deploy/enable-rtc-charging.sh — US-620 scenario catalog ==="

# ---- 1. the live Pi: no rtc line at all -> append under the effective [all] ----
echo "--- Scenario 1: live Pi shape, no rtc_bbat_vchg line ---"
CFG="$WORK/s1-config.txt"
write_live_fixture "$CFG"
cp "$CFG" "$WORK/s1-original.txt"
out=$(PI_CONFIG_TXT="$CFG" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_file_contains "config gained the trickle-charge param" "dtparam=rtc_bbat_vchg=3000000" "$CFG"
assert_effective_value "the param is EFFECTIVE for a Pi 5" "3000000" "$CFG"
assert_contains "announces the reboot requirement" "REBOOT REQUIRED" "$out"
assert_file_contains "backup captured the pristine original" "dtparam=i2c_arm=on" "$CFG.eclipse-bak"
assert_file_lacks "backup is pre-change (no rtc param)" "rtc_bbat_vchg" "$CFG.eclipse-bak"
# Nothing else in the file may move.
assert_file_contains "unrelated dtparam preserved" "dtparam=audio=on" "$CFG"
assert_file_contains "[cm5] overlay untouched" "dtoverlay=dwc2,dr_mode=host" "$CFG"
assert_file_contains "vc4 overlay untouched" "dtoverlay=vc4-kms-v3d" "$CFG"
# [all] is already the section in effect at EOF, so no new header is needed.
header_count=$(grep -c '^\[all\]$' "$CFG")
assert_contains "no redundant [all] header added" "1" "$header_count"
diff_lines=$(diff "$WORK/s1-original.txt" "$CFG" | grep -c '^[<>]')
assert_contains "exactly one line added" "1" "$diff_lines"

# ---- 2. re-run is a no-op (idempotency) ----
echo "--- Scenario 2: re-run on an already-configured file ---"
cp "$CFG" "$WORK/s2-before.txt"
out=$(PI_CONFIG_TXT="$CFG" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "no-op exits 0" 0 "$rc"
assert_contains "reports already-set" "already" "$out"
assert_files_identical "file byte-identical after re-run" "$WORK/s2-before.txt" "$CFG"

# ---- 3. a FOREIGN charging value is respected, never clobbered ----
echo "--- Scenario 3: operator already set 3300000 ---"
CFG3="$WORK/s3-config.txt"
printf 'dtparam=audio=on\ndtparam=rtc_bbat_vchg=3300000\n' > "$CFG3"
cp "$CFG3" "$WORK/s3-before.txt"
out=$(PI_CONFIG_TXT="$CFG3" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "leaves the deploy healthy (exit 0)" 0 "$rc"
assert_contains "warns loudly" "WARN" "$out"
assert_contains "names the foreign value" "3300000" "$out"
assert_files_identical "file NOT modified" "$WORK/s3-before.txt" "$CFG3"

# ---- 4. an explicit =0 is CHARGING DISABLED and must be called out by name ----
echo "--- Scenario 4: operator explicitly disabled charging (=0) ---"
CFG4="$WORK/s4-config.txt"
printf 'dtparam=audio=on\ndtparam=rtc_bbat_vchg=0\n' > "$CFG4"
cp "$CFG4" "$WORK/s4-before.txt"
out=$(PI_CONFIG_TXT="$CFG4" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "does not halt the deploy (exit 0)" 0 "$rc"
assert_contains "warns loudly" "WARN" "$out"
assert_contains "says charging is DISABLED, not merely different" "DISABLED" "$out"
assert_files_identical "an explicit operator 0 is NOT overwritten" "$WORK/s4-before.txt" "$CFG4"

# ---- 5. the file ends in a section that does NOT apply to a Pi 5 ----
echo "--- Scenario 5: EOF section is [cm4] -> must open [all] first ---"
CFG5="$WORK/s5-config.txt"
printf 'dtparam=audio=on\n\n[cm4]\notg_mode=1\n' > "$CFG5"
out=$(PI_CONFIG_TXT="$CFG5" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_effective_value "param is EFFECTIVE, not stranded in [cm4]" "3000000" "$CFG5"
assert_file_contains "opened an [all] section" "[all]" "$CFG5"
assert_file_contains "[cm4] content preserved" "otg_mode=1" "$CFG5"

# ---- 6. a COMMENTED rtc line is not "already configured" ----
echo "--- Scenario 6: only a commented-out rtc line ---"
CFG6="$WORK/s6-config.txt"
printf 'dtparam=audio=on\n#dtparam=rtc_bbat_vchg=3000000\n' > "$CFG6"
out=$(PI_CONFIG_TXT="$CFG6" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_effective_value "a REAL param is now in effect" "3000000" "$CFG6"
assert_file_contains "the comment is preserved" "#dtparam=rtc_bbat_vchg=3000000" "$CFG6"

# ---- 7. missing config.txt is a loud config error ----
echo "--- Scenario 7: config.txt absent ---"
out=$(PI_CONFIG_TXT="$WORK/nope/config.txt" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "missing target exits 1" 1 "$rc"
assert_contains "names the missing path" "config.txt" "$out"

# ---- 8. writing 0 is refused: it is the DISABLED state this story fixes ----
echo "--- Scenario 8: ECLIPSE_RTC_BBAT_VCHG_UV=0 ---"
CFG8="$WORK/s8-config.txt"
printf 'dtparam=audio=on\n' > "$CFG8"
cp "$CFG8" "$WORK/s8-before.txt"
out=$(ECLIPSE_RTC_BBAT_VCHG_UV=0 PI_CONFIG_TXT="$CFG8" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses to write the disabled value (exit 1)" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s8-before.txt" "$CFG8"
assert_contains "explains that 0 means charging off" "0" "$out"

# ---- 9. above the MEASURED charging_voltage_max is refused before any write ----
echo "--- Scenario 9: 5000000 uV exceeds the measured 4400000 ceiling ---"
CFG9="$WORK/s9-config.txt"
printf 'dtparam=audio=on\n' > "$CFG9"
cp "$CFG9" "$WORK/s9-before.txt"
out=$(ECLIPSE_RTC_BBAT_VCHG_UV=5000000 PI_CONFIG_TXT="$CFG9" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "over-max exits 1" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s9-before.txt" "$CFG9"
assert_contains "names the measured ceiling" "4400000" "$out"

# ---- 10. the measured ceiling itself is accepted ----
echo "--- Scenario 10: ECLIPSE_RTC_BBAT_VCHG_UV=4400000 (the measured max) ---"
CFG10="$WORK/s10-config.txt"
printf 'dtparam=audio=on\n' > "$CFG10"
out=$(ECLIPSE_RTC_BBAT_VCHG_UV=4400000 PI_CONFIG_TXT="$CFG10" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "the measured max is a legal value" 0 "$rc"
assert_effective_value "applied at the ceiling" "4400000" "$CFG10"

# ---- 11. an rtc param stranded in [cm4] is NOT "already configured" ----
echo "--- Scenario 11: existing rtc param only inside [cm4] ---"
CFG11="$WORK/s11-config.txt"
printf 'dtparam=audio=on\n\n[cm4]\ndtparam=rtc_bbat_vchg=3000000\n' > "$CFG11"
out=$(PI_CONFIG_TXT="$CFG11" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_effective_value "an APPLICABLE param now exists" "3000000" "$CFG11"
assert_contains "does not claim it was already set" "REBOOT REQUIRED" "$out"

# ---- 12. the pristine backup survives a SECOND change ----
echo "--- Scenario 12: backup is first-write-wins (pristine original) ---"
CFG12="$WORK/s12-config.txt"
printf 'dtparam=audio=on\n' > "$CFG12"
ECLIPSE_RTC_BBAT_VCHG_UV=3300000 PI_CONFIG_TXT="$CFG12" bash "$SCRIPT" >/dev/null 2>&1
printf 'dtparam=audio=on\n' > "$CFG12"
PI_CONFIG_TXT="$CFG12" bash "$SCRIPT" >/dev/null 2>&1
assert_file_lacks "backup still has no rtc param at all" "rtc_bbat_vchg" "$CFG12.eclipse-bak"

# ---- 13. a non-numeric value is refused before any write ----
echo "--- Scenario 13: ECLIPSE_RTC_BBAT_VCHG_UV=3.0V ---"
CFG13="$WORK/s13-config.txt"
printf 'dtparam=audio=on\n' > "$CFG13"
cp "$CFG13" "$WORK/s13-before.txt"
out=$(ECLIPSE_RTC_BBAT_VCHG_UV=3.0V PI_CONFIG_TXT="$CFG13" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "non-numeric exits 1" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s13-before.txt" "$CFG13"

# ---- 14. shares the pristine backup with set-gpu-cma.sh, never overwrites it ----
echo "--- Scenario 14: a pre-existing .eclipse-bak (set-gpu-cma ran first) ---"
CFG14="$WORK/s14-config.txt"
printf 'dtparam=audio=on\ndtoverlay=vc4-kms-v3d,cma-256\n' > "$CFG14"
printf 'PRISTINE-FROM-SET-GPU-CMA\n' > "$CFG14.eclipse-bak"
out=$(PI_CONFIG_TXT="$CFG14" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_effective_value "rtc param applied" "3000000" "$CFG14"
assert_file_contains "the earlier pristine backup is kept" "PRISTINE-FROM-SET-GPU-CMA" "$CFG14.eclipse-bak"
assert_file_contains "the cma param set by the sibling step is untouched" "cma-256" "$CFG14"

# ---- 15. the post-write verification actually fires (US-620 VC-3, mutation M11) ----
#
# WHY THIS EXISTS. The script's honesty rests on verifying by RE-READING the
# file it just wrote rather than trusting the variable it meant to write. Every
# other scenario exercises a write that succeeds, so nothing could distinguish
# "verification works" from "verification can never fail" -- a mutation that
# made the check unfalsifiable passed the whole catalog green. That is the inert
# guard shape this project keeps cataloguing, and it sat on the one check that
# stands between a silent bad write and the script announcing "Applied".
#
# The failure it guards is real on a boot partition: a vfat /boot/firmware that
# accepts a write and does not persist it. Nothing in the script's own inputs
# can produce that, so the condition is injected from OUTSIDE with a PATH shim
# on awk that makes the COMPOSE step silently drop the param line. No
# production seam is added for testability -- the script is unmodified.
echo "--- Scenario 15: the composed file silently loses the param ---"
CFG15="$WORK/s15-config.txt"
printf 'dtparam=audio=on\n' > "$CFG15"

REAL_AWK="$(command -v awk)"
SHIM_BIN="$WORK/shim-bin"
mkdir -p "$SHIM_BIN"
# Delegates every awk call to the real awk EXCEPT the composer (identified by
# its `-v param=` argument), which is made to emit the input unchanged.
{
    printf '#!/usr/bin/env bash\n'
    printf 'for a in "$@"; do\n'
    printf '  case "$a" in\n'
    printf '    param=*) exec %s "{ print }" "${@: -1}" ;;\n' "$REAL_AWK"
    printf '  esac\n'
    printf 'done\n'
    printf 'exec %s "$@"\n' "$REAL_AWK"
} > "$SHIM_BIN/awk"
chmod +x "$SHIM_BIN/awk"

out=$(PATH="$SHIM_BIN:$PATH" PI_CONFIG_TXT="$CFG15" bash "$SCRIPT" 2>&1); rc=$?

# PREMISE CHECK FIRST: prove the bad write really happened. Without this the
# scenario could pass for the wrong reason (e.g. the shim never engaged) and
# would assert nothing at all.
assert_effective_value "PREMISE: the write really did lose the param" "" "$CFG15"
assert_exit "post-write verification refuses to claim success (exit 2)" 2 "$rc"
assert_contains "says verification failed, not 'Applied'" "verification failed" "$out"
assert_not_contains "does NOT announce success or a reboot" "REBOOT REQUIRED" "$out"
assert_not_contains "does NOT claim the param was applied" "Applied dtparam" "$out"
assert_contains "points the operator at the pristine backup" ".eclipse-bak" "$out"

# ---- summary ----
echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
