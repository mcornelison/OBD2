#!/usr/bin/env bash
# server_snapshot.sh — capture chi-srv-01 state for pre/post comparisons.
#
# Use case: power cycle, OS upgrade, service redeploy, post-incident triage.
# Writes a timestamped section-tagged dump to stdout. Pipe to a file for diffing.
#
# Usage:
#   ./server_snapshot.sh > /tmp/srv_pre.txt
#   <reboot/upgrade/restart>
#   ./server_snapshot.sh > /tmp/srv_post.txt
#   diff -u /tmp/srv_pre.txt /tmp/srv_post.txt
#
# Capture surfaces (data-integrity, service-health, tier-functionality):
#   1. Host: hostname, uptime, kernel, load, disk, mem
#   2. Services: obd-server, mariadb, ollama (active state + main PID + restart count)
#   3. obd-server: HTTP /api/v1/health probe + listening port + recent log tail
#   4. MariaDB: row counts + MAX(id) for the canonical sync-target tables
#   5. MariaDB: error log tail (catches innodb recovery messages on post-reboot)
#   6. Ollama: tags endpoint + loaded models
#   7. Recent reboot trail (`last reboot | head`)

set -uo pipefail

REMOTE="${REMOTE:-chi-srv-01}"
ENV_FILE="${ENV_FILE:-/mnt/projects/O/OBD2v2/.env}"

ssh "$REMOTE" bash -s <<REMOTE_SCRIPT
set -uo pipefail
ENV_FILE="$ENV_FILE"

DB_PASS=\$(grep -oP '(?<=mysql\+aiomysql://obd2:)[^@]+' "\$ENV_FILE" 2>/dev/null)
mysql_q() { mysql -u obd2 -p"\$DB_PASS" obd2db -e "\$1" 2>&1; }

echo "===== SERVER SNAPSHOT \$(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
echo "remote=\$(hostname) snapshot_taken_by=server_snapshot.sh"
echo

echo "=== 1. host ==="
echo "uptime: \$(uptime)"
echo "kernel: \$(uname -r)"
echo "boot_id: \$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
df -h / 2>&1 | head -3
free -h 2>&1 | head -3
echo

echo "=== 2. services ==="
for svc in obd-server mariadb ollama; do
  active=\$(systemctl is-active "\$svc" 2>&1)
  pid=\$(systemctl show -p MainPID --value "\$svc" 2>&1)
  nrestarts=\$(systemctl show -p NRestarts --value "\$svc" 2>&1)
  active_since=\$(systemctl show -p ActiveEnterTimestamp --value "\$svc" 2>&1)
  echo "\$svc | active=\$active | pid=\$pid | n_restarts=\$nrestarts | active_since=\$active_since"
done
echo

echo "=== 3. obd-server health ==="
curl -sS --max-time 5 -w "\nhttp_status=%{http_code} time_total=%{time_total}s\n" \
  http://localhost:8000/api/v1/health 2>&1 | head -20
echo "--- recent obd-server log (last 10 lines) ---"
journalctl -u obd-server -n 10 --no-pager 2>&1 | tail -10
echo

echo "=== 4. mariadb row counts (canonical sync-target tables) ==="
# One query per table — schemas vary, isolating each prevents a single
# missing-column error from killing the whole snapshot.
printf '%-22s %12s %12s\n' table row_count max_id
for t in realtime_data drive_summary drive_statistics alert_log connection_log \
         battery_health_log sync_history ai_recommendations analysis_history \
         anomaly_log trend_snapshots; do
  out=\$(mysql -u obd2 -p"\$DB_PASS" obd2db -BNe \
    "SELECT COUNT(*), COALESCE(MAX(id),0) FROM \$t" 2>&1)
  printf '%-22s %s\n' "\$t" "\$out"
done
echo

echo "=== 5. mariadb error log (last 15 lines) ==="
LOG=\$(sudo -n tail -15 /var/log/mysql/error.log 2>/dev/null || \
       tail -15 /var/lib/mysql/*.err 2>/dev/null || \
       journalctl -u mariadb -n 15 --no-pager 2>/dev/null | tail -15)
echo "\$LOG"
echo

echo "=== 6. ollama ==="
curl -sS --max-time 5 http://localhost:11434/api/tags 2>&1 \
  | python3 -c "import sys,json
try:
  d=json.load(sys.stdin)
  for m in d.get('models',[]):
    print(f\"{m['name']:30} {m['size']:>12} bytes  modified={m['modified_at']}\")
except Exception as e:
  print('ollama probe failed:',e)
" 2>&1
echo

echo "=== 7. recent reboot trail ==="
last reboot 2>&1 | head -5
echo

echo "===== END SNAPSHOT ====="
REMOTE_SCRIPT
