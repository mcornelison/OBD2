#!/usr/bin/env bash
################################################################################
# tests/deploy/test_eeprom_power_off_on_halt.sh — enforcement-script test
#
# Verifies deploy/enforce-eeprom-power-off-on-halt.sh against PATH-mocked
# `rpi-eeprom-config` covering all real-world states. Runs entirely on the
# dev workstation -- no Pi required, no actual EEPROM modified.
#
# **SS-T8 (Atlas 2026-05-19) inverts the target value**: per the CIO-locked
# Pi 5 + X1209-HAT decision (2026-05-18) and the Check-B empirical
# confirmation (Finding B cleared at `=1`, 1 cycle), the correct setting is
# `POWER_OFF_ON_HALT=1`, NOT `=0`. The prior force-`=0` was a defect that
# reverted the correct setting on every deploy (the documentation root of
# the V0.27.x chain blocker, finding F-6). This test catalog is now the
# regression net for the corrected target.
#
# Mock strategy: each scenario writes a tiny stub script named
# `rpi-eeprom-config` into a temp dir, points $RPI_EEPROM_CONFIG at it (the
# enforcement script's test override seam), and invokes the production
# script. The stub emits canned config text on plain calls and records
# `--apply` invocations to a sentinel file we then inspect.
#
# Usage:
#   bash tests/deploy/test_eeprom_power_off_on_halt.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/enforce-eeprom-power-off-on-halt.sh"

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
        echo "         in output:"
        echo "$haystack" | sed 's/^/           > /'
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local desc="$1" needle="$2" haystack="$3"
    if ! echo "$haystack" | grep -qF -- "$needle"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc — should NOT have contained: $needle"
        FAIL=$((FAIL + 1))
    fi
}

assert_file_exists() {
    local desc="$1" path="$2"
    if [ -f "$path" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc — expected file at $path"
        FAIL=$((FAIL + 1))
    fi
}

assert_file_missing() {
    local desc="$1" path="$2"
    if [ ! -f "$path" ]; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc — file unexpectedly exists at $path"
        FAIL=$((FAIL + 1))
    fi
}

# Build a mock rpi-eeprom-config in $1 (target path) that prints $2 (canned
# config text) on plain calls and on `--apply <file>` copies the file to
# $3 (apply sentinel) so the test can inspect what was applied. Every
# `--apply` also appends one line to "$3.count" (US-926-a: exactly ONE apply).
make_mock() {
    local mockPath="$1" cannedConfig="$2" applySentinel="$3"
    cat > "$mockPath" <<EOF
#!/usr/bin/env bash
# Test mock for rpi-eeprom-config
if [ "\$#" -eq 0 ]; then
    cat <<CONFIG
${cannedConfig}
CONFIG
    exit 0
fi
if [ "\$1" = "--apply" ] && [ -n "\${2:-}" ]; then
    cp "\$2" "${applySentinel}"
    echo apply >> "${applySentinel}.count"
    exit 0
fi
echo "mock rpi-eeprom-config: unsupported invocation: \$*" >&2
exit 99
EOF
    chmod +x "$mockPath"
}

# Same shape but the apply step always fails -- proves the script propagates
# the error.
make_mock_apply_fails() {
    local mockPath="$1" cannedConfig="$2"
    cat > "$mockPath" <<EOF
#!/usr/bin/env bash
if [ "\$#" -eq 0 ]; then
    cat <<CONFIG
${cannedConfig}
CONFIG
    exit 0
fi
if [ "\$1" = "--apply" ]; then
    echo "mock: apply failed" >&2
    exit 1
fi
exit 99
EOF
    chmod +x "$mockPath"
}

run_with_mock() {
    # $1 = mockPath, $2 = optional rpi-eeprom-update mock; captures
    # stdout+stderr for inspection. Without $2 the image probe points at a
    # path that does not exist, so no scenario ever reaches a real tool.
    local mockPath="$1" updateMock="${2:-/nonexistent/rpi-eeprom-update}"
    RPI_EEPROM_CONFIG="$mockPath" RPI_EEPROM_UPDATE="$updateMock" bash "$SCRIPT" 2>&1
}

# Build a mock rpi-eeprom-update in $1 that answers `-l` with $2 (the latest
# packaged image path) and appends every invocation's args to $3, tagged
# before-apply / after-apply by whether the apply sentinel $4 exists yet.
make_update_mock() {
    local mockPath="$1" imagePath="$2" callLog="$3" applySentinel="$4"
    cat > "$mockPath" <<EOF
#!/usr/bin/env bash
if [ -f "${applySentinel}" ]; then when=after-apply; else when=before-apply; fi
echo "\$when \$*" >> "${callLog}"
if [ "\$*" = "-l" ]; then
    echo "${imagePath}"
    exit 0
fi
exit 99
EOF
    chmod +x "$mockPath"
}

# ---- preconditions ----

echo "=== test_eeprom_power_off_on_halt.sh (SS-T8: enforces =1) ==="
echo "Script under test: $SCRIPT"

if [ ! -f "$SCRIPT" ]; then
    echo "  FAIL: script not found at $SCRIPT"
    exit 1
fi

# All scenarios share a temp area; each scenario writes its own mock + sentinel.
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t eeprom)
trap 'rm -rf "$TMP"' EXIT

# ---- scenario 1: setting absent -> rewrite to explicit =1 ----
#
# Pre-SS-T8 this scenario expected a no-op ("default is 0, OK").  On a Pi 5 +
# X1209-HAT that default is WRONG (Finding B); the script must rewrite to an
# explicit =1 so the deployed state is unambiguous and persists across
# bootloader updates.

echo ""
echo "scenario 1: POWER_OFF_ON_HALT line absent (default 0 is WRONG on HAT)"
S1_DIR="$TMP/s1"
mkdir -p "$S1_DIR"
S1_MOCK="$S1_DIR/rpi-eeprom-config"
S1_APPLIED="$S1_DIR/applied.conf"
make_mock "$S1_MOCK" "BOOT_UART=0
WAKE_ON_GPIO=1
PSU_MAX_CURRENT=5000" "$S1_APPLIED"

S1_OUT=$(run_with_mock "$S1_MOCK")
S1_RC=$?
assert_exit       "exits 0 on rewrite when setting absent" "0"                "$S1_RC"
assert_contains   "logs 'not present ... rewriting to 1'"  "rewriting to 1"   "$S1_OUT"
assert_file_exists "--apply WAS invoked"                   "$S1_APPLIED"
S1_APPLIED_CONTENT=$(cat "$S1_APPLIED")
assert_contains   "applied config has POWER_OFF_ON_HALT=1" "POWER_OFF_ON_HALT=1" "$S1_APPLIED_CONTENT"
assert_contains   "applied config preserves BOOT_UART=0"   "BOOT_UART=0"      "$S1_APPLIED_CONTENT"

# ---- scenario 2: setting already 0 -> rewrite to =1 ----

echo ""
echo "scenario 2: POWER_OFF_ON_HALT=0 (WRONG on HAT, MUST rewrite to =1)"
S2_DIR="$TMP/s2"
mkdir -p "$S2_DIR"
S2_MOCK="$S2_DIR/rpi-eeprom-config"
S2_APPLIED="$S2_DIR/applied.conf"
make_mock "$S2_MOCK" "BOOT_UART=0
POWER_OFF_ON_HALT=0
WAKE_ON_GPIO=1" "$S2_APPLIED"

S2_OUT=$(run_with_mock "$S2_MOCK")
S2_RC=$?
assert_exit       "exits 0 on successful rewrite"            "0"                  "$S2_RC"
assert_contains   "logs 'rewriting to 1'"                    "rewriting to 1"     "$S2_OUT"
assert_contains   "logs success message"                     "applied"            "$S2_OUT"
assert_file_exists "--apply WAS invoked"                     "$S2_APPLIED"
APPLIED_CONTENT=$(cat "$S2_APPLIED")
assert_contains   "applied config has POWER_OFF_ON_HALT=1"   "POWER_OFF_ON_HALT=1" "$APPLIED_CONTENT"
assert_not_contains "applied config has NO POWER_OFF_ON_HALT=0" "POWER_OFF_ON_HALT=0" "$APPLIED_CONTENT"
assert_contains   "applied config preserves BOOT_UART"       "BOOT_UART=0"        "$APPLIED_CONTENT"
assert_contains   "applied config preserves WAKE_ON_GPIO"    "WAKE_ON_GPIO=1"     "$APPLIED_CONTENT"

# ---- scenario 3: setting =1 -> no-op (already correct on HAT) ----

echo ""
echo "scenario 3: POWER_OFF_ON_HALT=1 (already correct on HAT, no-op)"
S3_DIR="$TMP/s3"
mkdir -p "$S3_DIR"
S3_MOCK="$S3_DIR/rpi-eeprom-config"
S3_APPLIED="$S3_DIR/applied.conf"
# MOVED PIN (US-926-a): "no apply" now needs EVERY table key right, so the
# NET_INSTALL_* keys join the canned config; POWER_OFF_ON_HALT=1 is unchanged.
make_mock "$S3_MOCK" "BOOT_UART=0
NET_INSTALL_AT_POWER_ON=0
NET_INSTALL_ENABLED=0
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=1" "$S3_APPLIED"

S3_OUT=$(run_with_mock "$S3_MOCK")
S3_RC=$?
assert_exit       "exits 0 when already =1"                "0"                  "$S3_RC"
assert_contains   "logs 'already set'"                     "already set"        "$S3_OUT"
assert_file_missing "no --apply was invoked (idempotency)" "$S3_APPLIED"

# ---- scenario 4: setting =2 -> rewrite to =1 ----

echo ""
echo "scenario 4: POWER_OFF_ON_HALT=2 (other non-=1 value, must rewrite)"
S4_DIR="$TMP/s4"
mkdir -p "$S4_DIR"
S4_MOCK="$S4_DIR/rpi-eeprom-config"
S4_APPLIED="$S4_DIR/applied.conf"
make_mock "$S4_MOCK" "POWER_OFF_ON_HALT=2" "$S4_APPLIED"

S4_OUT=$(run_with_mock "$S4_MOCK")
S4_RC=$?
assert_exit       "exits 0 on successful rewrite"          "0"                  "$S4_RC"
assert_file_exists "--apply WAS invoked"                   "$S4_APPLIED"
APPLIED_CONTENT4=$(cat "$S4_APPLIED")
assert_contains   "applied config has POWER_OFF_ON_HALT=1" "POWER_OFF_ON_HALT=1" "$APPLIED_CONTENT4"

# ---- scenario 5: tool missing -> exit 1 with clear error ----

echo ""
echo "scenario 5: rpi-eeprom-config missing"
S5_OUT=$(RPI_EEPROM_CONFIG="/nonexistent/rpi-eeprom-config" bash "$SCRIPT" 2>&1)
S5_RC=$?
assert_exit       "exits 1 when tool missing"           "1"                  "$S5_RC"
assert_contains   "error mentions missing tool"         "not found"          "$S5_OUT"

# ---- scenario 6: apply fails -> exit 2 ----

echo ""
echo "scenario 6: rpi-eeprom-config --apply fails (transient error)"
S6_DIR="$TMP/s6"
mkdir -p "$S6_DIR"
S6_MOCK="$S6_DIR/rpi-eeprom-config"
# Use =0 so the script tries to rewrite (and the mock then fails the --apply).
make_mock_apply_fails "$S6_MOCK" "POWER_OFF_ON_HALT=0"

S6_OUT=$(run_with_mock "$S6_MOCK")
S6_RC=$?
assert_exit       "exits 2 when apply fails"            "2"                  "$S6_RC"
assert_contains   "error mentions apply failure"        "--apply"            "$S6_OUT"

# ---- scenario 7: idempotency drill -- run twice, second run is no-op ----

echo ""
echo "scenario 7: idempotency -- two consecutive runs converge on =1"
# Run 1: =0 -> apply (rewrite to =1). Then swap mock to one that reports =1.
# Run 2: should be no-op.
S7_DIR="$TMP/s7"
mkdir -p "$S7_DIR"
S7_MOCK="$S7_DIR/rpi-eeprom-config"
S7_APPLIED="$S7_DIR/applied.conf"
make_mock "$S7_MOCK" "POWER_OFF_ON_HALT=0" "$S7_APPLIED"
S7_RUN1_OUT=$(run_with_mock "$S7_MOCK")
S7_RUN1_RC=$?
assert_exit        "first run exits 0"              "0"                  "$S7_RUN1_RC"
assert_file_exists "first run applied"              "$S7_APPLIED"

# Now mock returns =1 (post-rewrite state). Wipe sentinel; second run must NOT re-apply.
# MOVED PIN (US-926-a): the converged state is exactly what run 1 applied --
# every table key at its required value -- not POWER_OFF_ON_HALT=1 alone.
S7_CONVERGED=$(cat "$S7_APPLIED")
rm -f "$S7_APPLIED" "$S7_APPLIED.count"
make_mock "$S7_MOCK" "$S7_CONVERGED" "$S7_APPLIED"
S7_RUN2_OUT=$(run_with_mock "$S7_MOCK")
S7_RUN2_RC=$?
assert_exit        "second run exits 0"             "0"                  "$S7_RUN2_RC"
assert_contains    "second run logs 'already set'"  "already set"        "$S7_RUN2_OUT"
assert_file_missing "second run did NOT re-apply"   "$S7_APPLIED"

# ==== US-926-a: the boot-speed key table, one read, one MERGED apply ====

IMAGE="/lib/firmware/raspberrypi/bootloader-2712/default/pieeprom-2026-05-26.bin"

# ---- scenario 8 (i): every table key already right -> no apply ----

echo ""
echo "scenario 8: every table key already right (no apply, no image probe)"
S8_DIR="$TMP/s8"
mkdir -p "$S8_DIR"
S8_MOCK="$S8_DIR/rpi-eeprom-config"
S8_APPLIED="$S8_DIR/applied.conf"
S8_UPDATE="$S8_DIR/rpi-eeprom-update"
S8_CALLS="$S8_DIR/update-calls"
make_mock "$S8_MOCK" "[all]
BOOT_UART=0
BOOT_ORDER=0xf461
NET_INSTALL_AT_POWER_ON=0
NET_INSTALL_ENABLED=0
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=1" "$S8_APPLIED"
make_update_mock "$S8_UPDATE" "$IMAGE" "$S8_CALLS" "$S8_APPLIED"

S8_OUT=$(run_with_mock "$S8_MOCK" "$S8_UPDATE")
S8_RC=$?
assert_exit         "exits 0 when every key is right"         "0"  "$S8_RC"
assert_contains     "POWER_OFF_ON_HALT keeps its message"     "POWER_OFF_ON_HALT=1 already set (wake-on-power OK)." "$S8_OUT"
assert_contains     "BOOT_UART already"                       "BOOT_UART=0 already set" "$S8_OUT"
assert_contains     "NET_INSTALL_AT_POWER_ON already"         "NET_INSTALL_AT_POWER_ON=0 already set" "$S8_OUT"
assert_contains     "NET_INSTALL_ENABLED already"             "NET_INSTALL_ENABLED=0 already set" "$S8_OUT"
assert_file_missing "no --apply was invoked"                  "$S8_APPLIED"
assert_file_missing "no image probe without an apply"         "$S8_CALLS"

# ---- scenario 9 (ii)+(iii): TODAY'S CAR (Spool read-back) ----
#
# Running config as read off the car: BOOT_UART=1, BOOT_ORDER=0xf461,
# NET_INSTALL_AT_POWER_ON=1, POWER_OFF_ON_HALT=1, WAKE_ON_GPIO=1. The section
# header, a comment and a blank line ride along to prove every non-table line
# survives byte-identical and in order.

echo ""
echo "scenario 9: today's car -> ONE merged apply, every live key kept"
S9_DIR="$TMP/s9"
mkdir -p "$S9_DIR"
S9_MOCK="$S9_DIR/rpi-eeprom-config"
S9_APPLIED="$S9_DIR/applied.conf"
S9_UPDATE="$S9_DIR/rpi-eeprom-update"
S9_CALLS="$S9_DIR/update-calls"
make_mock "$S9_MOCK" "[all]
BOOT_UART=1
BOOT_ORDER=0xf461
# kept as read
NET_INSTALL_AT_POWER_ON=1

POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=1" "$S9_APPLIED"
make_update_mock "$S9_UPDATE" "$IMAGE" "$S9_CALLS" "$S9_APPLIED"

S9_OUT=$(run_with_mock "$S9_MOCK" "$S9_UPDATE")
S9_RC=$?
assert_exit        "exits 0 on the merged apply"              "0"  "$S9_RC"
assert_file_exists "--apply WAS invoked"                      "$S9_APPLIED"
S9_COUNT=$(wc -l < "$S9_APPLIED.count" 2>/dev/null | tr -d '[:space:]')
assert_exit        "exactly ONE --apply"                      "1"  "${S9_COUNT:-0}"
S9_EXPECTED="$S9_DIR/expected.conf"
printf '%s\n' "[all]" "BOOT_UART=0" "BOOT_ORDER=0xf461" "# kept as read" \
    "NET_INSTALL_AT_POWER_ON=0" "" "POWER_OFF_ON_HALT=1" "WAKE_ON_GPIO=1" \
    "NET_INSTALL_ENABLED=0" > "$S9_EXPECTED"
if cmp -s "$S9_EXPECTED" "$S9_APPLIED"; then
    echo "  PASS: applied file is the running config, table keys merged in place"
    PASS=$((PASS + 1))
else
    echo "  FAIL: applied file differs from the merged running config"
    diff "$S9_EXPECTED" "$S9_APPLIED" | sed 's/^/           > /'
    FAIL=$((FAIL + 1))
fi
assert_contains    "logs BOOT_UART 1 -> 0"                    "BOOT_UART 1 -> 0" "$S9_OUT"
assert_contains    "logs NET_INSTALL_AT_POWER_ON 1 -> 0"      "NET_INSTALL_AT_POWER_ON 1 -> 0" "$S9_OUT"
assert_contains    "logs NET_INSTALL_ENABLED absent -> 0"     "NET_INSTALL_ENABLED absent -> 0" "$S9_OUT"
assert_contains    "logs POWER_OFF_ON_HALT already set"       "POWER_OFF_ON_HALT=1 already set" "$S9_OUT"
assert_contains    "(iii) log names the image"                "applying onto pieeprom-2026-05-26.bin" "$S9_OUT"
S9_CALL_LOG=$(cat "$S9_CALLS" 2>/dev/null)
assert_contains    "(iii) image probed BEFORE the apply"      "before-apply -l" "$S9_CALL_LOG"
assert_not_contains "(iii) image never probed after the apply" "after-apply" "$S9_CALL_LOG"
assert_not_contains "never runs rpi-eeprom-update -a"         " -a" "$S9_CALL_LOG"

# ---- scenario 10 (iv): PSU_MAX_CURRENT in the running config is untouched ----

echo ""
echo "scenario 10: PSU_MAX_CURRENT=3000 preserved untouched"
S10_DIR="$TMP/s10"
mkdir -p "$S10_DIR"
S10_MOCK="$S10_DIR/rpi-eeprom-config"
S10_APPLIED="$S10_DIR/applied.conf"
make_mock "$S10_MOCK" "[all]
BOOT_UART=1
PSU_MAX_CURRENT=3000
POWER_OFF_ON_HALT=1" "$S10_APPLIED"

S10_OUT=$(run_with_mock "$S10_MOCK")
S10_RC=$?
assert_exit        "exits 0"                                  "0"  "$S10_RC"
assert_file_exists "--apply WAS invoked"                      "$S10_APPLIED"
S10_CONTENT=$(cat "$S10_APPLIED")
assert_contains    "PSU_MAX_CURRENT=3000 kept"                "PSU_MAX_CURRENT=3000" "$S10_CONTENT"
S10_PSU_LINES=$(grep -c 'PSU_MAX_CURRENT' "$S10_APPLIED")
assert_exit        "PSU_MAX_CURRENT appears exactly once"     "1"  "$S10_PSU_LINES"
assert_not_contains "PSU_MAX_CURRENT never logged as a change" "PSU_MAX_CURRENT" "$S10_OUT"

# ---- scenario 11: no image probe available -> still one apply, says so ----

echo ""
echo "scenario 11: rpi-eeprom-update unavailable -> apply proceeds, logged"
S11_DIR="$TMP/s11"
mkdir -p "$S11_DIR"
S11_MOCK="$S11_DIR/rpi-eeprom-config"
S11_APPLIED="$S11_DIR/applied.conf"
make_mock "$S11_MOCK" "BOOT_UART=1
POWER_OFF_ON_HALT=1" "$S11_APPLIED"

S11_OUT=$(run_with_mock "$S11_MOCK")
S11_RC=$?
assert_exit        "exits 0"                                  "0"  "$S11_RC"
assert_file_exists "--apply WAS invoked"                      "$S11_APPLIED"
assert_contains    "logs the image is unknown"                "WARNING: could not read the bootloader image" "$S11_OUT"

# ---- scenario 12: negative -- today's car, apply fails -> exit 2 ----

echo ""
echo "scenario 12: today's car, --apply fails -> exit 2, config unchanged"
S12_DIR="$TMP/s12"
mkdir -p "$S12_DIR"
S12_MOCK="$S12_DIR/rpi-eeprom-config"
make_mock_apply_fails "$S12_MOCK" "BOOT_UART=1
BOOT_ORDER=0xf461
NET_INSTALL_AT_POWER_ON=1
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=1"

S12_OUT=$(run_with_mock "$S12_MOCK")
S12_RC=$?
assert_exit        "exits 2 when apply fails"                 "2"  "$S12_RC"
assert_contains    "error says the config is unchanged"       "EEPROM config unchanged" "$S12_OUT"
assert_not_contains "no success line after a failed apply"    "Effect persists" "$S12_OUT"

# ---- summary ----

echo ""
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
