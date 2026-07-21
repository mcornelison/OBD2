#!/usr/bin/env bash
################################################################################
# File Name: test_verify_pre_drive.sh
# Purpose:   US-479 bash driver test for scripts/verify_pre_drive.sh -- the
#            CIO-runnable pre-drive green-light wrapper. Exercises arg handling,
#            the --dry-run ordered plan (canonical MAC + verify_bt_pair
#            composition + connect-edge live window), and a real --bench run that
#            reports CAPTURE: PASS with the connect-edge exercised.
# Author:    Rex (Ralph agent)
# Created:   2026-07-20
# Story:     US-479
################################################################################

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GATE="$REPO_ROOT/scripts/verify_pre_drive.sh"
CANON_MAC="00:04:3E:85:0D:FB"

PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); printf '  [PASS] %s\n' "$1"; }
bad()  { FAIL=$((FAIL + 1)); printf '  [FAIL] %s\n' "$1"; }

# run <expected_exit> <label> -- runs the gate, checks exit code; exports $OUT.
run() {
    local expected="$1"; shift
    local label="$1"; shift
    OUT="$("$@" 2>&1)"
    local rc=$?
    if [ "$rc" = "$expected" ]; then
        ok "$label (exit $rc)"
    else
        bad "$label (expected exit $expected, got $rc)"
        printf '        --- output ---\n%s\n' "$OUT" | sed 's/^/        /'
    fi
}

contains() {
    local label="$1" needle="$2"
    if printf '%s' "$OUT" | grep -qF -- "$needle"; then
        ok "$label"
    else
        bad "$label (missing: $needle)"
    fi
}

before() {
    # asserts $2 appears before $3 in $OUT
    local label="$1" first="$2" second="$3"
    local li si
    li=$(printf '%s\n' "$OUT" | grep -nF -- "$first" | head -1 | cut -d: -f1)
    si=$(printf '%s\n' "$OUT" | grep -nF -- "$second" | head -1 | cut -d: -f1)
    if [ -n "$li" ] && [ -n "$si" ] && [ "$li" -lt "$si" ]; then
        ok "$label"
    else
        bad "$label (order wrong: '$first'@$li vs '$second'@$si)"
    fi
}

echo "== verify_pre_drive.sh driver =="

# 1. --help
run 0 "--help exits 0" bash "$GATE" --help
contains "--help describes the gate" "pre-drive green-light"

# 2. unknown flag -> misuse
run 2 "unknown flag exits 2" bash "$GATE" --nope

# 3. duration below floor -> misuse
run 2 "duration below floor exits 2" bash "$GATE" --duration 3

# 4. --dry-run live plan
run 0 "--dry-run exits 0" bash "$GATE" --dry-run
contains "dry-run uses the canonical OBDLink MAC" "$CANON_MAC"
contains "dry-run composes verify_bt_pair.sh" "verify_bt_pair.sh"
contains "dry-run runs the KOEO sub-check" "pre_drive_greenlight.py --live --koeo-only"
contains "dry-run runs the live capture window" "pre_drive_greenlight.py --live --duration"
before "BT bond/link reported before the live window" "Steps 1-2 / 5" "Step 4 / 5"

# 5. --koeo-only skips the authoritative window
run 0 "--koeo-only --dry-run exits 0" bash "$GATE" --koeo-only --dry-run
contains "koeo-only skips the live-idle window" "live-idle window SKIPPED"

# 6. --bench real run -> CAPTURE PASS with connect-edge exercised
run 0 "--bench --duration 5 exits 0" bash "$GATE" --bench --duration 5
contains "bench reports CAPTURE PASS" "CAPTURE: PASS"
contains "bench exercised the connect-edge" "connect-edge=exercised"
contains "bench warns it is not a live PASS" "NOT an in-vehicle PASS"

echo ""
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" = "0" ]
