#!/usr/bin/env bash
################################################################################
# tests/deploy/test_set_gpu_cma.sh — GPU CMA boot-config enforcement test
#
# Verifies deploy/set-gpu-cma.sh against synthetic /boot/firmware/config.txt
# fixtures. Runs entirely on the dev workstation -- no Pi required, no real
# boot partition touched. The production script's $PI_CONFIG_TXT override is
# the test seam (mirrors $RPI_EEPROM_CONFIG in the US-253 EEPROM script).
#
# US-524 / F-124: raise the Pi 5 GPU CMA pool from the 64 MiB default to
# 256 MiB, complementing US-522's --disable-gpu. The mechanism is the
# vc4-kms-v3d overlay's `cma-256` param in config.txt -- NOT a `cma=` kernel
# arg in cmdline.txt. Grounded on the live Pi 2026-08-03:
#   - /boot/firmware/config.txt carries a bare `dtoverlay=vc4-kms-v3d`
#   - /proc/cmdline has NO cma= parameter; dmesg shows the 64 MiB pool coming
#     from the device-tree `linux,cma` node
#   - /boot/firmware/overlays/README documents cma-64..cma-512 params for
#     vc4-kms-v3d (and -pi4/-pi5, which "See vc4-kms-v3d-pi4")
#
# Fixture fidelity: scenario 1 uses the LIVE Pi's actual config.txt shape,
# including its [cm4]/[cm5]/[all] conditional-filter sections -- section
# tracking is load-bearing (an overlay line inside [cm4] does NOT apply to a
# Pi 5, so appending cma-256 there would be a false "applied" claim).
#
# Usage:
#   bash tests/deploy/test_set_gpu_cma.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/set-gpu-cma.sh"

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

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The LIVE Pi's config.txt (read from 10.27.27.100 on 2026-08-03), trimmed of
# nothing that matters: the bare vc4-kms-v3d overlay at top level plus the
# [cm4]/[cm5]/[all] conditional sections that follow it.
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

echo "=== deploy/set-gpu-cma.sh — US-524 scenario catalog ==="

# ---- 1. bare vc4-kms-v3d at top level (the live Pi) -> append cma-256 ----
echo "--- Scenario 1: bare dtoverlay=vc4-kms-v3d (live Pi shape) ---"
CFG="$WORK/s1-config.txt"
write_live_fixture "$CFG"
cp "$CFG" "$WORK/s1-original.txt"
out=$(PI_CONFIG_TXT="$CFG" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies cleanly" 0 "$rc"
assert_file_contains "overlay line gained cma-256" "dtoverlay=vc4-kms-v3d,cma-256" "$CFG"
assert_contains "announces the reboot requirement" "REBOOT REQUIRED" "$out"
assert_file_contains "backup captured the pristine original" "dtoverlay=vc4-kms-v3d" "$CFG.eclipse-bak"
assert_file_lacks "backup is pre-change (no cma-256)" "cma-256" "$CFG.eclipse-bak"
# Nothing else in the file may move.
assert_file_contains "unrelated dtparam preserved" "dtparam=i2c_arm=on" "$CFG"
assert_file_contains "[cm5] overlay untouched" "dtoverlay=dwc2,dr_mode=host" "$CFG"
diff_lines=$(diff "$WORK/s1-original.txt" "$CFG" | grep -c '^[<>]')
assert_contains "exactly one line changed" "2" "$diff_lines"

# ---- 2. re-run is a no-op (idempotency) ----
echo "--- Scenario 2: re-run on an already-256 file ---"
cp "$CFG" "$WORK/s2-before.txt"
out=$(PI_CONFIG_TXT="$CFG" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "no-op exits 0" 0 "$rc"
assert_contains "reports already-set" "already" "$out"
assert_files_identical "file byte-identical after re-run" "$WORK/s2-before.txt" "$CFG"

# ---- 3. a FOREIGN cma- param is respected, never clobbered ----
echo "--- Scenario 3: operator already set cma-128 ---"
CFG3="$WORK/s3-config.txt"
printf 'dtparam=audio=on\ndtoverlay=vc4-kms-v3d,cma-128\nmax_framebuffers=2\n' > "$CFG3"
cp "$CFG3" "$WORK/s3-before.txt"
out=$(PI_CONFIG_TXT="$CFG3" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "leaves the deploy healthy (exit 0)" 0 "$rc"
assert_contains "warns loudly" "WARN" "$out"
assert_contains "names the foreign value" "cma-128" "$out"
assert_files_identical "file NOT modified" "$WORK/s3-before.txt" "$CFG3"
assert_file_lacks "no backup written when nothing changed" "x" "$CFG3.eclipse-bak"

# ---- 4. the explicit -pi5 overlay variant is also a valid target ----
echo "--- Scenario 4: dtoverlay=vc4-kms-v3d-pi5 ---"
CFG4="$WORK/s4-config.txt"
printf 'dtoverlay=vc4-kms-v3d-pi5\n' > "$CFG4"
out=$(PI_CONFIG_TXT="$CFG4" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies to the -pi5 variant" 0 "$rc"
assert_file_contains "variant gained cma-256" "dtoverlay=vc4-kms-v3d-pi5,cma-256" "$CFG4"

# ---- 5. other overlay params are preserved, cma appended ----
echo "--- Scenario 5: existing non-cma overlay params ---"
CFG5="$WORK/s5-config.txt"
printf 'dtoverlay=vc4-kms-v3d,noaudio\n' > "$CFG5"
out=$(PI_CONFIG_TXT="$CFG5" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "applies alongside existing params" 0 "$rc"
assert_file_contains "noaudio preserved, cma appended" "dtoverlay=vc4-kms-v3d,noaudio,cma-256" "$CFG5"

# ---- 6. a COMMENTED overlay line is not a target ----
echo "--- Scenario 6: only a commented-out overlay line ---"
CFG6="$WORK/s6-config.txt"
printf 'dtparam=audio=on\n#dtoverlay=vc4-kms-v3d\n' > "$CFG6"
cp "$CFG6" "$WORK/s6-before.txt"
out=$(PI_CONFIG_TXT="$CFG6" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses -- no active overlay line (exit 3)" 3 "$rc"
assert_files_identical "file NOT modified" "$WORK/s6-before.txt" "$CFG6"
assert_contains "explains the refusal" "vc4-kms-v3d" "$out"

# ---- 7. an overlay line inside a NON-applicable section is not a target ----
echo "--- Scenario 7: overlay only inside [cm4] ---"
CFG7="$WORK/s7-config.txt"
printf 'dtparam=audio=on\n\n[cm4]\ndtoverlay=vc4-kms-v3d\n' > "$CFG7"
cp "$CFG7" "$WORK/s7-before.txt"
out=$(PI_CONFIG_TXT="$CFG7" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "refuses -- [cm4] does not apply to a Pi 5 (exit 3)" 3 "$rc"
assert_files_identical "file NOT modified" "$WORK/s7-before.txt" "$CFG7"

# ---- 8. an overlay line under an explicit [all] IS a target ----
echo "--- Scenario 8: overlay under [all] ---"
CFG8="$WORK/s8-config.txt"
printf 'dtparam=audio=on\n\n[cm4]\notg_mode=1\n\n[all]\ndtoverlay=vc4-kms-v3d\n' > "$CFG8"
out=$(PI_CONFIG_TXT="$CFG8" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "[all] section applies" 0 "$rc"
assert_file_contains "overlay under [all] gained cma-256" "dtoverlay=vc4-kms-v3d,cma-256" "$CFG8"

# ---- 9. missing config.txt is a loud config error ----
echo "--- Scenario 9: config.txt absent ---"
out=$(PI_CONFIG_TXT="$WORK/nope/config.txt" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "missing target exits 1" 1 "$rc"
assert_contains "names the missing path" "config.txt" "$out"

# ---- 10. an unsupported CMA size is refused BEFORE any write ----
echo "--- Scenario 10: ECLIPSE_CMA_MB=250 (not an overlay-supported size) ---"
CFG10="$WORK/s10-config.txt"
printf 'dtoverlay=vc4-kms-v3d\n' > "$CFG10"
cp "$CFG10" "$WORK/s10-before.txt"
out=$(ECLIPSE_CMA_MB=250 PI_CONFIG_TXT="$CFG10" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "unsupported size exits 1" 1 "$rc"
assert_files_identical "file NOT modified" "$WORK/s10-before.txt" "$CFG10"
assert_contains "lists the supported sizes" "512" "$out"

# ---- 11. a supported non-default size is honoured ----
echo "--- Scenario 11: ECLIPSE_CMA_MB=128 ---"
CFG11="$WORK/s11-config.txt"
printf 'dtoverlay=vc4-kms-v3d\n' > "$CFG11"
out=$(ECLIPSE_CMA_MB=128 PI_CONFIG_TXT="$CFG11" bash "$SCRIPT" 2>&1); rc=$?
assert_exit "supported override applies" 0 "$rc"
assert_file_contains "overlay gained cma-128" "dtoverlay=vc4-kms-v3d,cma-128" "$CFG11"

# ---- 12. the pristine backup survives a SECOND change ----
echo "--- Scenario 12: backup is first-write-wins (pristine original) ---"
CFG12="$WORK/s12-config.txt"
printf 'dtoverlay=vc4-kms-v3d\n' > "$CFG12"
ECLIPSE_CMA_MB=128 PI_CONFIG_TXT="$CFG12" bash "$SCRIPT" >/dev/null 2>&1
# Now hand-force a different value and re-run; the backup must still be the
# ORIGINAL 64 MiB-default file, not the cma-128 intermediate.
printf 'dtoverlay=vc4-kms-v3d\n' > "$CFG12"
ECLIPSE_CMA_MB=256 PI_CONFIG_TXT="$CFG12" bash "$SCRIPT" >/dev/null 2>&1
assert_file_lacks "backup still has no cma param at all" "cma-" "$CFG12.eclipse-bak"

# ---- summary ----
echo
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] || exit 1
exit 0
