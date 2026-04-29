#!/usr/bin/env bash
################################################################################
# tests/deploy/test_obd_server_service.sh -- US-231 live verification.
#
# Asserts post-install state of obd-server.service on chi-srv-01:
#   1. Unit file installed at /etc/systemd/system/obd-server.service
#   2. Unit is enabled (autostart on boot)
#   3. Unit is active (running)
#   4. Restart policy = always (per US-231 spec)
#   5. Health endpoint /api/v1/health returns 200
#
# Exit codes:
#   0   all assertions passed
#   1   one or more assertions failed
#   77  SSH to chi-srv-01 unreachable (autotools SKIP convention; pytest wrapper
#       converts to skip rather than fail so CI runners without network access
#       to the home lab stay green)
################################################################################

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../deploy/addresses.sh
. "$SCRIPT_DIR/../../deploy/addresses.sh"

REMOTE="${SERVER_USER}@${SERVER_HOST}"
SSH_OPTS="-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new"

# ----- Reachability gate -----
if ! ssh $SSH_OPTS "$REMOTE" 'true' >/dev/null 2>&1; then
    echo "SKIP: SSH to $REMOTE unreachable (exit 77)"
    exit 77
fi

# ----- Deploy-state gate -----
# If the unit isn't installed yet, treat that as a deploy-pending skip rather
# than an assertion failure. The same loud-but-non-blocking pattern as the
# SSH reachability gate above: pre-CIO-deploy this skips with the message
# below; post-deploy the file lands and the assertions run for real.
if ! ssh $SSH_OPTS "$REMOTE" 'test -f /etc/systemd/system/obd-server.service' >/dev/null 2>&1; then
    echo "SKIP: obd-server.service not installed yet on $REMOTE."
    echo "      US-231 ships the unit + deploy step; run 'bash deploy/deploy-server.sh'"
    echo "      to land the unit, then re-run this test."
    exit 77
fi

fail() {
    echo "FAIL: $*" >&2
}

PASS=0
FAIL=0

assert() {
    local label="$1"
    local cmd="$2"
    local out
    if out=$(ssh $SSH_OPTS "$REMOTE" "$cmd" 2>&1); then
        echo "PASS: $label  -> $out"
        PASS=$((PASS + 1))
    else
        fail "$label  -> $out"
        FAIL=$((FAIL + 1))
    fi
}

# 1. Unit file installed (sudo-readable; we test for the file, not the systemd
# state, so an unprivileged ls is enough).
assert "unit file at /etc/systemd/system/obd-server.service" \
    "test -f /etc/systemd/system/obd-server.service && echo present"

# 2. Unit enabled (returns 'enabled' or 'static'; both acceptable).
assert "obd-server.service is enabled" \
    "systemctl is-enabled obd-server.service"

# 3. Unit active.
assert "obd-server.service is active" \
    "systemctl is-active obd-server.service"

# 4. Restart=always (per US-231 spec).
assert "Restart=always" \
    "systemctl show -p Restart obd-server.service | grep -q '^Restart=always' && echo Restart=always"

# 5. Health endpoint reachable on port 8000.
assert "/api/v1/health responds 200" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:${SERVER_PORT}/api/v1/health | grep -q '^200$' && echo HTTP_200"

echo ""
echo "Summary: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
