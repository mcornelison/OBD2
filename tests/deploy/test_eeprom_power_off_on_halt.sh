#!/usr/bin/env bash
################################################################################
# tests/deploy/test_eeprom_power_off_on_halt.sh — US-253 enforcement-script test
#
# Verifies deploy/enforce-eeprom-power-off-on-halt.sh against PATH-mocked
# `rpi-eeprom-config` covering all real-world states. Runs entirely on the
# dev workstation -- no Pi required, no actual EEPROM modified.
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
# $3 (apply sentinel) so the test can inspect what was applied.
make_mock() {
    local mockPath="$1" cannedConfig="$2" applySentinel="$3"
    cat > "$mockPath" <<EOF
#!/usr/bin/env bash
# Test mock for rpi-eeprom-config -- US-253 test only
if [ "\$#" -eq 0 ]; then
    cat <<CONFIG
${cannedConfig}
CONFIG
    exit 0
fi
if [ "\$1" = "--apply" ] && [ -n "\${2:-}" ]; then
    cp "\$2" "${applySentinel}"
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
    # $1 = mockPath, captures stdout+stderr for inspection.
    local mockPath="$1"
    RPI_EEPROM_CONFIG="$mockPath" bash "$SCRIPT" 2>&1
}

# ---- preconditions ----

echo "=== test_eeprom_power_off_on_halt.sh ==="
echo "Script under test: $SCRIPT"

if [ ! -f "$SCRIPT" ]; then
    echo "  FAIL: script not found at $SCRIPT"
    exit 1
fi

# All scenarios share a temp area; each scenario writes its own mock + sentinel.
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t eeprom)
trap 'rm -rf "$TMP"' EXIT

# ---- scenario 1: setting absent -> no-op (defaults to 0) ----

echo ""
echo "scenario 1: POWER_OFF_ON_HALT line absent (defaults to 0)"
S1_DIR="$TMP/s1"
mkdir -p "$S1_DIR"
S1_MOCK="$S1_DIR/rpi-eeprom-config"
S1_APPLIED="$S1_DIR/applied.conf"
make_mock "$S1_MOCK" "BOOT_UART=0
WAKE_ON_GPIO=1
PSU_MAX_CURRENT=5000" "$S1_APPLIED"

S1_OUT=$(run_with_mock "$S1_MOCK")
S1_RC=$?
assert_exit       "exits 0 when setting absent"        "0"               "$S1_RC"
assert_contains   "logs 'not present ... defaults to 0'" "not present"   "$S1_OUT"
assert_file_missing "no --apply was invoked (idempotency)" "$S1_APPLIED"

# ---- scenario 2: setting already 0 -> no-op ----

echo ""
echo "scenario 2: POWER_OFF_ON_HALT=0 (already correct)"
S2_DIR="$TMP/s2"
mkdir -p "$S2_DIR"
S2_MOCK="$S2_DIR/rpi-eeprom-config"
S2_APPLIED="$S2_DIR/applied.conf"
make_mock "$S2_MOCK" "BOOT_UART=0
POWER_OFF_ON_HALT=0
WAKE_ON_GPIO=1" "$S2_APPLIED"

S2_OUT=$(run_with_mock "$S2_MOCK")
S2_RC=$?
assert_exit       "exits 0 when already =0"          "0"                 "$S2_RC"
assert_contains   "logs 'already set'"               "already set"       "$S2_OUT"
assert_file_missing "no --apply was invoked (idempotency)" "$S2_APPLIED"

# ---- scenario 3: setting =1 -> rewrite to 0 via --apply ----

echo ""
echo "scenario 3: POWER_OFF_ON_HALT=1 (deep sleep, MUST rewrite to 0)"
S3_DIR="$TMP/s3"
mkdir -p "$S3_DIR"
S3_MOCK="$S3_DIR/rpi-eeprom-config"
S3_APPLIED="$S3_DIR/applied.conf"
make_mock "$S3_MOCK" "BOOT_UART=0
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=1" "$S3_APPLIED"

S3_OUT=$(run_with_mock "$S3_MOCK")
S3_RC=$?
assert_exit       "exits 0 on successful rewrite"        "0"                  "$S3_RC"
assert_contains   "logs 'rewriting to 0'"                "rewriting to 0"     "$S3_OUT"
assert_contains   "logs success message"                 "applied"            "$S3_OUT"
assert_file_exists "--apply WAS invoked"                 "$S3_APPLIED"
APPLIED_CONTENT=$(cat "$S3_APPLIED")
assert_contains   "applied config has POWER_OFF_ON_HALT=0" "POWER_OFF_ON_HALT=0" "$APPLIED_CONTENT"
assert_not_contains "applied config has NO POWER_OFF_ON_HALT=1" "POWER_OFF_ON_HALT=1" "$APPLIED_CONTENT"
assert_contains   "applied config preserves other keys (BOOT_UART)" "BOOT_UART=0" "$APPLIED_CONTENT"
assert_contains   "applied config preserves other keys (WAKE_ON_GPIO)" "WAKE_ON_GPIO=1" "$APPLIED_CONTENT"

# ---- scenario 4: setting =2 -> rewrite to 0 ----

echo ""
echo "scenario 4: POWER_OFF_ON_HALT=2 (other non-zero value, also rewrite)"
S4_DIR="$TMP/s4"
mkdir -p "$S4_DIR"
S4_MOCK="$S4_DIR/rpi-eeprom-config"
S4_APPLIED="$S4_DIR/applied.conf"
make_mock "$S4_MOCK" "POWER_OFF_ON_HALT=2" "$S4_APPLIED"

S4_OUT=$(run_with_mock "$S4_MOCK")
S4_RC=$?
assert_exit       "exits 0 on successful rewrite"     "0"                  "$S4_RC"
assert_file_exists "--apply WAS invoked"              "$S4_APPLIED"
APPLIED_CONTENT4=$(cat "$S4_APPLIED")
assert_contains   "applied config has POWER_OFF_ON_HALT=0" "POWER_OFF_ON_HALT=0" "$APPLIED_CONTENT4"

# ---- scenario 5: tool missing -> exit 1 with clear error ----

echo ""
echo "scenario 5: rpi-eeprom-config missing"
S5_OUT=$(RPI_EEPROM_CONFIG="/nonexistent/rpi-eeprom-config" bash "$SCRIPT" 2>&1)
S5_RC=$?
assert_exit       "exits 1 when tool missing"        "1"                   "$S5_RC"
assert_contains   "error mentions missing tool"      "not found"           "$S5_OUT"

# ---- scenario 6: apply fails -> exit 2 ----

echo ""
echo "scenario 6: rpi-eeprom-config --apply fails (transient error)"
S6_DIR="$TMP/s6"
mkdir -p "$S6_DIR"
S6_MOCK="$S6_DIR/rpi-eeprom-config"
make_mock_apply_fails "$S6_MOCK" "POWER_OFF_ON_HALT=1"

S6_OUT=$(run_with_mock "$S6_MOCK")
S6_RC=$?
assert_exit       "exits 2 when apply fails"         "2"                  "$S6_RC"
assert_contains   "error mentions apply failure"     "--apply"            "$S6_OUT"

# ---- scenario 7: idempotency drill -- run twice, second run is no-op ----

echo ""
echo "scenario 7: idempotency -- two consecutive runs converge"
# Run 1: =1 -> apply (rewrite to 0). Then swap mock to one that reports =0.
# Run 2: should be no-op.
S7_DIR="$TMP/s7"
mkdir -p "$S7_DIR"
S7_MOCK="$S7_DIR/rpi-eeprom-config"
S7_APPLIED="$S7_DIR/applied.conf"
make_mock "$S7_MOCK" "POWER_OFF_ON_HALT=1" "$S7_APPLIED"
S7_RUN1_OUT=$(run_with_mock "$S7_MOCK")
S7_RUN1_RC=$?
assert_exit       "first run exits 0"                "0"                  "$S7_RUN1_RC"
assert_file_exists "first run applied"                "$S7_APPLIED"

# Now mock returns =0 (post-rewrite state). Wipe sentinel; second run must NOT re-apply.
rm -f "$S7_APPLIED"
make_mock "$S7_MOCK" "POWER_OFF_ON_HALT=0" "$S7_APPLIED"
S7_RUN2_OUT=$(run_with_mock "$S7_MOCK")
S7_RUN2_RC=$?
assert_exit       "second run exits 0"               "0"                  "$S7_RUN2_RC"
assert_contains   "second run logs 'already set'"    "already set"        "$S7_RUN2_OUT"
assert_file_missing "second run did NOT re-apply"     "$S7_APPLIED"

# ---- summary ----

echo ""
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
