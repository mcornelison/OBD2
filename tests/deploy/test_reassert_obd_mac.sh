#!/usr/bin/env bash
################################################################################
# tests/deploy/test_reassert_obd_mac.sh — self-heal corrector test (US-477)
#
# Verifies deploy/reassert-obd-mac.sh against fixture /etc/default/obdlink
# copies in a temp dir. Runs entirely on the dev workstation -- no Pi required,
# no real /etc/default/obdlink touched. This is the bench evidence for
# US-477 validationCriterion 2 (a fixture holding the 07-17 phantom MAC is
# self-healed to the canonical 00:04:3E:85:0D:FB, channel preserved).
#
# Usage:
#   bash tests/deploy/test_reassert_obd_mac.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/reassert-obd-mac.sh"

CANONICAL="00:04:3E:85:0D:FB"
PHANTOM="00:04:3C:84:15:6B"

PASS=0
FAIL=0

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
        echo "  FAIL: $desc — should NOT contain: $needle"
        FAIL=$((FAIL + 1))
    fi
}

# Assert a fixture file's effective OBD_BT_MAC equals $2.
assert_file_mac() {
    local desc="$1" expected="$2" path="$3"
    local got
    got=$(grep -E '^[[:space:]]*OBD_BT_MAC[[:space:]]*=' "$path" | head -1 | cut -d= -f2- | tr -d '[:space:]')
    if [ "$got" = "$expected" ]; then
        echo "  PASS: $desc (file MAC=$got)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc (expected file MAC=$expected, got=$got)"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== test_reassert_obd_mac.sh (US-477 self-heal) ==="
echo "Script under test: $SCRIPT"

if [ ! -f "$SCRIPT" ]; then
    echo "  FAIL: script not found at $SCRIPT"
    exit 1
fi

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t reassert)
trap 'rm -rf "$TMP"' EXIT

# A drifted env file exactly like the 07-17 incident: phantom MAC + channel=1.
make_drifted() {
    local path="$1" mac="$2"
    cat > "$path" <<EOF
# Managed by deploy/install-rfcomm-bind.sh
OBD_BT_MAC=${mac}
OBD_BT_CHANNEL=1
EOF
}

# ---- scenario 1: phantom MAC present -> self-heal to canonical ----
echo ""
echo "scenario 1: drifted phantom MAC -> corrected to canonical (self-heal)"
F1="$TMP/obdlink1"
make_drifted "$F1" "$PHANTOM"
S1_OUT=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F1" 2>&1)
S1_RC=$?
assert_exit        "exits 0 on correction"                 "0"           "$S1_RC"
assert_contains    "logs 'corrected'"                      "corrected"   "$S1_OUT"
assert_contains    "log names the phantom being replaced"  "$PHANTOM"    "$S1_OUT"
assert_file_mac    "file now holds canonical MAC"          "$CANONICAL"  "$F1"
assert_contains    "OBD_BT_CHANNEL=1 preserved"            "OBD_BT_CHANNEL=1" "$(cat "$F1")"
assert_not_contains "phantom MAC gone from file"           "$PHANTOM"    "$(cat "$F1")"

# ---- scenario 2: already canonical -> idempotent no-op ----
echo ""
echo "scenario 2: already canonical -> no-op (idempotent)"
F2="$TMP/obdlink2"
make_drifted "$F2" "$CANONICAL"
BEFORE2=$(cat "$F2")
S2_OUT=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F2" 2>&1)
S2_RC=$?
assert_exit     "exits 0 when already canonical"  "0"                 "$S2_RC"
assert_contains "logs 'already canonical'"        "already canonical" "$S2_OUT"
if [ "$BEFORE2" = "$(cat "$F2")" ]; then
    echo "  PASS: file unchanged on no-op"; PASS=$((PASS + 1))
else
    echo "  FAIL: file changed on no-op"; FAIL=$((FAIL + 1))
fi

# ---- scenario 3: OBD_BT_MAC line absent -> append canonical ----
echo ""
echo "scenario 3: no OBD_BT_MAC line -> append canonical"
F3="$TMP/obdlink3"
printf '# stub env file\nOBD_BT_CHANNEL=1\n' > "$F3"
S3_OUT=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F3" 2>&1)
S3_RC=$?
assert_exit     "exits 0 on append"        "0"            "$S3_RC"
assert_contains "logs 'appended'"          "appended"     "$S3_OUT"
assert_file_mac "file now holds canonical" "$CANONICAL"   "$F3"
assert_contains "channel still present"    "OBD_BT_CHANNEL=1" "$(cat "$F3")"

# ---- scenario 4: env file missing -> nothing to re-assert (exit 0) ----
echo ""
echo "scenario 4: env file missing -> nothing to re-assert"
S4_OUT=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$TMP/does-not-exist" 2>&1)
S4_RC=$?
assert_exit     "exits 0 when file missing"     "0"                     "$S4_RC"
assert_contains "logs 'nothing to re-assert'"   "nothing to re-assert"  "$S4_OUT"

# ---- scenario 5: --dry-run against phantom -> reports, does NOT write ----
echo ""
echo "scenario 5: --dry-run reports the self-heal but leaves the file drifted"
F5="$TMP/obdlink5"
make_drifted "$F5" "$PHANTOM"
S5_OUT=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F5" --dry-run 2>&1)
S5_RC=$?
assert_exit     "exits 0 in dry-run"                  "0"           "$S5_RC"
assert_contains "dry-run logs 'would correct'"        "would correct" "$S5_OUT"
assert_contains "dry-run names canonical target"      "$CANONICAL"  "$S5_OUT"
assert_file_mac "file STILL phantom (dry-run wrote nothing)" "$PHANTOM" "$F5"

# ---- scenario 6: invalid MAC -> exit 2 ----
echo ""
echo "scenario 6: invalid MAC rejected"
F6="$TMP/obdlink6"
make_drifted "$F6" "$PHANTOM"
S6_OUT=$(bash "$SCRIPT" --mac "not-a-mac" --env-file "$F6" 2>&1)
S6_RC=$?
assert_exit     "exits 2 on invalid MAC"   "2"              "$S6_RC"
assert_contains "error mentions valid MAC" "not a valid"    "$S6_OUT"

# ---- scenario 7: missing MAC (no flag, no env) -> exit 2 ----
echo ""
echo "scenario 7: no canonical MAC supplied"
F7="$TMP/obdlink7"
make_drifted "$F7" "$PHANTOM"
S7_OUT=$(env -u OBD_BT_MAC bash "$SCRIPT" --env-file "$F7" 2>&1)
S7_RC=$?
assert_exit     "exits 2 when MAC missing"      "2"          "$S7_RC"
assert_contains "error mentions MAC required"   "MAC required" "$S7_OUT"

# ---- scenario 8: MAC read from $OBD_BT_MAC env ----
echo ""
echo "scenario 8: canonical MAC sourced from \$OBD_BT_MAC"
F8="$TMP/obdlink8"
make_drifted "$F8" "$PHANTOM"
S8_OUT=$(OBD_BT_MAC="$CANONICAL" bash "$SCRIPT" --env-file "$F8" 2>&1)
S8_RC=$?
assert_exit  "exits 0 (MAC from env)"       "0"          "$S8_RC"
assert_file_mac "file healed via env MAC"   "$CANONICAL" "$F8"

# ---- scenario 9: idempotency drill -- two consecutive runs converge ----
echo ""
echo "scenario 9: idempotency -- run twice, second is a no-op"
F9="$TMP/obdlink9"
make_drifted "$F9" "$PHANTOM"
R1=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F9" 2>&1); RC1=$?
R2=$(bash "$SCRIPT" --mac "$CANONICAL" --env-file "$F9" 2>&1); RC2=$?
assert_exit     "first run exits 0"            "0"                 "$RC1"
assert_contains "first run corrects"           "corrected"         "$R1"
assert_exit     "second run exits 0"           "0"                 "$RC2"
assert_contains "second run is a no-op"        "already canonical" "$R2"
assert_file_mac "converged on canonical"       "$CANONICAL"        "$F9"

echo ""
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
