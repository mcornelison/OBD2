#!/usr/bin/env bash
################################################################################
# tests/deploy/test_deploy_pi.sh — Smoke test for deploy/deploy-pi.sh
#
# Verifies flag parsing, --help output, --dry-run safety, and exit codes
# WITHOUT requiring SSH access to a real Pi. Run from the repo root or any CWD.
#
# Usage:
#   bash tests/deploy/test_deploy_pi.sh
#
# Exit codes:
#   0  - all assertions passed
#   1  - one or more assertions failed
################################################################################

set -u

# Locate the script under test relative to this test file (CWD-independent).
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
SCRIPT="$REPO_ROOT/deploy/deploy-pi.sh"

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

# Extended grep (supports regex alternation like foo|bar). Use when the
# deploy-pi.sh branch depends on the local toolchain (rsync vs tar).
assert_matches_regex() {
    local desc="$1" pattern="$2" haystack="$3"
    if echo "$haystack" | grep -Eq -- "$pattern"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        echo "         expected to match regex: $pattern"
        echo "         in output:"
        echo "$haystack" | sed 's/^/           > /'
        FAIL=$((FAIL + 1))
    fi
}

# ---- preconditions ----

echo "=== test_deploy_pi.sh ==="
echo "Script under test: $SCRIPT"

if [ ! -f "$SCRIPT" ]; then
    echo "  FAIL: script not found at $SCRIPT"
    exit 1
fi
if [ ! -r "$SCRIPT" ]; then
    echo "  FAIL: script not readable"
    exit 1
fi

# ---- test 1: --help exits 0 and prints usage ----

echo ""
echo "test 1: --help"
HELP_OUT=$(bash "$SCRIPT" --help 2>&1)
HELP_RC=$?
assert_exit       "--help exits 0"           "0"                  "$HELP_RC"
assert_contains   "--help shows Usage line"  "Usage: bash deploy/deploy-pi.sh"  "$HELP_OUT"
assert_contains   "--help mentions --init"   "--init"             "$HELP_OUT"
assert_contains   "--help mentions --restart" "--restart"         "$HELP_OUT"
assert_contains   "--help mentions --dry-run" "--dry-run"         "$HELP_OUT"
assert_contains   "--help mentions PI_HOST"   "PI_HOST"           "$HELP_OUT"

# ---- test 2: -h short flag works the same ----

echo ""
echo "test 2: -h short flag"
SHORT_OUT=$(bash "$SCRIPT" -h 2>&1)
SHORT_RC=$?
assert_exit       "-h exits 0"               "0"                  "$SHORT_RC"
assert_contains   "-h shows Usage line"      "Usage:"             "$SHORT_OUT"

# ---- test 3: unknown flag exits non-zero ----

echo ""
echo "test 3: unknown flag rejected"
BAD_OUT=$(bash "$SCRIPT" --frobnicate 2>&1)
BAD_RC=$?
assert_exit       "--frobnicate exits 2"     "2"                  "$BAD_RC"
assert_contains   "error mentions the bad flag" "--frobnicate"    "$BAD_OUT"

# ---- test 4: --init + --restart conflict ----

echo ""
echo "test 4: --init and --restart are mutually exclusive"
CONF_OUT=$(bash "$SCRIPT" --init --restart --dry-run 2>&1)
CONF_RC=$?
assert_exit       "--init --restart exits 2" "2"                  "$CONF_RC"
assert_contains   "error names mutual exclusion" "mutually exclusive" "$CONF_OUT"

# ---- test 5: --dry-run default mode prints intentions, no real SSH ----

# Create a tiny throwaway deploy.conf in a temp area to point at an unreachable
# host — proves --dry-run NEVER touches the network.
echo ""
echo "test 5: --dry-run default mode is offline-safe"
TMP=$(mktemp -d 2>/dev/null || mktemp -d -t depl)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/deploy"  # mimic deploy/ structure relative to script
cp "$SCRIPT" "$TMP/deploy/deploy-pi.sh"
# deploy-pi.sh sources ../deploy/addresses.sh (B-044 canonical bash-side
# mirror); the isolated tmp copy needs it too.
cp "$REPO_ROOT/deploy/addresses.sh" "$TMP/deploy/addresses.sh"
cat > "$TMP/deploy/deploy.conf" <<EOF
PI_HOST=192.0.2.1
PI_USER=nobody
PI_PATH=/tmp/will-never-exist
PI_PORT=22
EOF

DRY_OUT=$(bash "$TMP/deploy/deploy-pi.sh" --dry-run 2>&1)
DRY_RC=$?
assert_exit       "--dry-run exits 0"        "0"                  "$DRY_RC"
assert_contains   "dry-run announces target" "192.0.2.1"          "$DRY_OUT"
assert_contains   "dry-run announces user"   "nobody"             "$DRY_OUT"
assert_contains   "dry-run shows DRY-RUN ssh" "DRY-RUN ssh"       "$DRY_OUT"
# sync_tool dry-run marker: "DRY-RUN rsync" when rsync is installed locally,
# "DRY-RUN tar" when falling back to the tar-over-ssh path (vanilla Windows
# git-bash typically has no rsync). Either announcement satisfies the
# "dry-run shows which sync tool would run" contract.
assert_matches_regex "dry-run shows DRY-RUN <sync-tool>" \
                     "DRY-RUN (rsync|tar) from" "$DRY_OUT"
assert_not_contains "dry-run did NOT call real ssh (no Permission denied/Connection refused)" \
                  "Permission denied" "$DRY_OUT"
assert_not_contains "dry-run did NOT call real ssh (no Connection refused)" \
                  "Connection refused" "$DRY_OUT"

# ---- test 6: --dry-run --init mode is also offline-safe ----

echo ""
echo "test 6: --dry-run --init is offline-safe"
DRY_INIT_OUT=$(bash "$TMP/deploy/deploy-pi.sh" --init --dry-run 2>&1)
DRY_INIT_RC=$?
assert_exit       "--init --dry-run exits 0" "0"                  "$DRY_INIT_RC"
assert_contains   "shows wipe step"          "wiping legacy"      "$DRY_INIT_OUT"
assert_contains   "shows hostname step"      "hostname"           "$DRY_INIT_OUT"
assert_contains   "shows venv step"          "venv at"            "$DRY_INIT_OUT"

# ---- test 7: --restart --dry-run is offline-safe ----

echo ""
echo "test 7: --restart --dry-run is offline-safe"
DRY_RESTART_OUT=$(bash "$TMP/deploy/deploy-pi.sh" --restart --dry-run 2>&1)
DRY_RESTART_RC=$?
assert_exit       "--restart --dry-run exits 0" "0"               "$DRY_RESTART_RC"
assert_contains   "shows restart step"       "Restarting"         "$DRY_RESTART_OUT"
assert_not_contains "no rsync in restart-only" "rsync"            "$DRY_RESTART_OUT"

# ---- test 8: deploy.conf overrides defaults ----

echo ""
echo "test 8: deploy.conf overrides defaults"
cat > "$TMP/deploy/deploy.conf" <<EOF
PI_HOST=10.99.99.99
PI_USER=alt-user
PI_PATH=/srv/alt
EOF
ALT_OUT=$(bash "$TMP/deploy/deploy-pi.sh" --dry-run 2>&1)
assert_contains   "alt PI_HOST applied"      "10.99.99.99"        "$ALT_OUT"
assert_contains   "alt PI_USER applied"      "alt-user"           "$ALT_OUT"
assert_contains   "alt PI_PATH applied"      "/srv/alt"           "$ALT_OUT"

# ---- summary ----

echo ""
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
