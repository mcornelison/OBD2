#!/usr/bin/env bash
# scripts/bench_crash_drill.sh -- Layer-4 honest-instrument verification helper.
# READ-ONLY: prints the drill steps and reads back the verdict. The operator
# induces the crash by hand (sysrq / PSU yank) -- this script never does.
# Run from a host with SSH to chi-eclipse-01, Pi on BENCH PSU (not the slow
# battery). Usage: scripts/bench_crash_drill.sh <STAGE e.g. POWEROFF_INVOKED>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../deploy/addresses.sh"
STAGE="${1:?usage: bench_crash_drill.sh <STAGE e.g. POWEROFF_INVOKED>}"
echo "=== Layer-4 bench hard-crash drill helper (stage: ${STAGE}) ==="
echo "Pi: ${PI_USER}@${PI_HOST}  PI_PATH=${PI_PATH}"
echo
echo "1. Confirm the trail is armed for THIS boot (expect a RUNNING line):"
echo "   ssh ${PI_USER}@${PI_HOST} \"tail -n1 ${PI_PATH}/data/boot_progress\""
ssh "${PI_USER}@${PI_HOST}" "tail -n1 ${PI_PATH}/data/boot_progress 2>/dev/null || echo '(no trail file -- arm unit may not have run; investigate before drilling)'"
echo
echo "2. Induce the hard crash AT stage ${STAGE} -- run THIS on the Pi at the chosen moment (operator action, NOT this script):"
echo "     echo b | sudo tee /proc/sysrq-trigger      # immediate reboot, no shutdown (simulates a hard crash)"
echo "   (or physically yank the bench PSU for the drive-time-crash case)"
echo
echo "3. After the Pi reboots, read the verdict the arm unit wrote for the crashed boot:"
echo "   ssh ${PI_USER}@${PI_HOST} \"sqlite3 ${PI_PATH}/data/obd.db \\\"SELECT boot_id,prior_boot_clean,prior_boot_last_stage,prior_boot_reason FROM startup_log ORDER BY recorded_at DESC LIMIT 1;\\\"\""
echo
echo "PASS criteria depend on the case -- see docs/runbooks/2026-05-17-bench-hard-crash-drill.md."
echo "Hard-crash-after-POWEROFF_INVOKED  => prior_boot_clean=0, prior_boot_reason='poweroff_invoked_never_returned'"
echo "Real 'sudo systemctl poweroff'     => prior_boot_clean=1, prior_boot_reason='graceful'"
echo "PSU-yank mid-drive                 => prior_boot_clean=0 (reason reflects the rung reached)"
