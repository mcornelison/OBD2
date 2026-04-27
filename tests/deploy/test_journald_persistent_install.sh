#!/usr/bin/env bash
################################################################################
# tests/deploy/test_journald_persistent_install.sh
#
# US-230 acceptance test: after deploy-pi.sh step_install_journald_persistent
# ships, the Pi has /var/log/journal/<machine-id>/ as a real directory AND
# `journalctl --disk-usage` reports non-zero bytes. Spool's 2026-04-23
# post-deploy audit caught the exact failure mode this test guards: parent
# dir present, machine-id subdir missing, logs still on tmpfs.
#
# Skip behavior:
#   - SSH to the Pi unreachable (batch-mode, 5s timeout)    -> skip (exit 77)
#     so CI runners without Pi access don't red-flag the sprint suite.
#   - SSH reaches the Pi but /var/log/journal is empty/bad  -> fail (exit 1).
#   - Everything green                                       -> pass (exit 0).
#
# Usage:
#   bash tests/deploy/test_journald_persistent_install.sh
#
# Config knobs (env overrides; defaults match deploy/addresses.sh):
#   PI_HOST / PI_USER / PI_PORT  -- same defaults as deploy-pi.sh
################################################################################

set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/../.." && pwd)"

# shellcheck source=../../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

# Per-operator override via deploy/deploy.conf (gitignored).
if [ -f "$REPO_ROOT/deploy/deploy.conf" ]; then
    # shellcheck disable=SC1091
    . "$REPO_ROOT/deploy/deploy.conf"
fi

# Standard autotools-style skip code; pytest/bash harnesses both recognize 77.
SKIP_RC=77

PASS=0
FAIL=0

echo "=== test_journald_persistent_install.sh (US-230) ==="
echo "Target: ${PI_USER}@${PI_HOST}:${PI_PORT:-22}"

# Preflight: SSH reachability probe with a short BatchMode timeout so the
# test never hangs on a network-less CI runner.
if ! ssh -p "${PI_PORT:-22}" \
        -o ConnectTimeout=5 \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        "${PI_USER}@${PI_HOST}" 'echo ok' >/dev/null 2>&1; then
    echo "SKIP: SSH to ${PI_USER}@${PI_HOST} not available (BatchMode, 5s timeout)."
    echo "      This is expected on CI runners without Pi access."
    echo "      On the CIO workstation, ensure key-based SSH is configured."
    exit $SKIP_RC
fi

echo "SSH gate OK."

# Collect the three signals in a single round-trip so a flapping network
# doesn't cause half-state. All three echoed on their own line with a
# fixed prefix we parse below.
probe_out=$(ssh -p "${PI_PORT:-22}" \
                -o ConnectTimeout=10 \
                -o BatchMode=yes \
                "${PI_USER}@${PI_HOST}" '
    mid=$(cat /etc/machine-id 2>/dev/null || true)
    echo "MACHINE_ID=${mid}"
    if [ -n "$mid" ] && [ -d "/var/log/journal/$mid" ]; then
        echo "SUBDIR_EXISTS=yes"
    else
        echo "SUBDIR_EXISTS=no"
    fi
    echo "DISK_USAGE=$(journalctl --disk-usage 2>&1 || true)"
    echo "IS_ACTIVE=$(systemctl is-active systemd-journald 2>&1 || true)"
' 2>&1)

if [ $? -ne 0 ]; then
    echo "  FAIL: SSH probe failed; output was:"
    echo "$probe_out" | sed 's/^/    /'
    exit 1
fi

# Parse the probe output into variables the assertions can test.
machine_id=$(echo "$probe_out" | sed -n 's/^MACHINE_ID=//p' | head -1)
subdir_exists=$(echo "$probe_out" | sed -n 's/^SUBDIR_EXISTS=//p' | head -1)
disk_usage=$(echo "$probe_out" | sed -n 's/^DISK_USAGE=//p' | head -1)
is_active=$(echo "$probe_out" | sed -n 's/^IS_ACTIVE=//p' | head -1)

echo "Pi reports:"
echo "  machine-id:        ${machine_id}"
echo "  /var/log/journal/<id> exists: ${subdir_exists}"
echo "  journalctl --disk-usage: ${disk_usage}"
echo "  systemd-journald:  ${is_active}"

# ---- assertions ----

echo ""
echo "assertion 1: /etc/machine-id is non-empty"
if [ -n "$machine_id" ]; then
    echo "  PASS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: /etc/machine-id is empty or missing on the Pi"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "assertion 2: /var/log/journal/<machine-id>/ exists (US-230 AC #4)"
if [ "$subdir_exists" = "yes" ]; then
    echo "  PASS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: /var/log/journal/${machine_id} is missing."
    echo "        This is Spool's 2026-04-23 failure mode: Storage=persistent set but"
    echo "        journald never created the machine-id subdir, so logs flow to tmpfs."
    echo "        Run: bash deploy/deploy-pi.sh   to re-assert the drop-in + restart."
    FAIL=$((FAIL + 1))
fi

echo ""
echo "assertion 3: journalctl --disk-usage reports > 0 bytes"
# Positive match: 'take up NsuffixX in' where N starts 1-9 (rejects 0B).
if echo "$disk_usage" | grep -qE 'take up [1-9][0-9.]*[BKMGT]? in'; then
    echo "  PASS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: journalctl reports zero disk usage: '${disk_usage}'"
    echo "        Persistent journal exists but no logs have been written to it."
    FAIL=$((FAIL + 1))
fi

echo ""
echo "assertion 4: systemd-journald is active"
if [ "$is_active" = "active" ]; then
    echo "  PASS"
    PASS=$((PASS + 1))
else
    echo "  FAIL: systemd-journald reports '${is_active}' instead of 'active'."
    FAIL=$((FAIL + 1))
fi

echo ""
echo "=== summary: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
