#!/usr/bin/env bash
# ============================================================================
# review_run.sh — Spool's real-vs-sim OBD data review tool
# ----------------------------------------------------------------------------
# Pulls a time-sliced subset of Pi SQLite + server MariaDB OBD data, grades
# PID coverage and value ranges against Spool's Phase 1 tuning spec, and
# diffs Pi↔server for end-to-end sync integrity.
#
# REUSE INTENT: this is Spool's own review tooling, not production code.
# Keep it simple, parameterized, and portable across runs (Session 23,
# Sprint 14 post-TD-023 drill, and every real-data review after that).
#
# USAGE:
#   ./review_run.sh [options]
#
# OPTIONS:
#   --since TIMESTAMP    Lower bound (e.g. "2026-04-19 07:18:00"). Required.
#   --until TIMESTAMP    Upper bound. Default: "9999-12-31".
#   --pi-host HOST       Default: chi-eclipse-01
#   --pi-db PATH         Default: ~/Projects/Eclipse-01/data/obd.db
#   --server-host HOST   Default: chi-srv-01
#   --server-db NAME     Default: obd2db
#   --server-env PATH    Path to .env with DATABASE_URL on server.
#                        Default: /mnt/projects/O/OBD2v2/.env
#   --skip-server        Pi-only review (for when server is down)
#   --skip-pi            Server-only review
#   -h, --help           Show this help
#
# EXAMPLES:
#   # Session 23 first-real-data review:
#   ./review_run.sh --since "2026-04-19 07:18:00"
#
#   # A bounded slice:
#   ./review_run.sh --since "2026-04-19 07:18:00" --until "2026-04-19 07:21:00"
#
#   # After CR #4 lands, filter to only real data:
#   ./review_run.sh --since "2026-04-19 07:18:00" --source real
#   (NOTE: --source flag not yet implemented; will be added once the
#    data_source column exists in the schema.)
#
# PREREQUISITES:
#   - Passwordless SSH to --pi-host and --server-host
#   - sqlite3 installed on Pi
#   - mysql client + readable .env with DATABASE_URL on server
# ============================================================================

set -euo pipefail

SINCE=""
UNTIL="9999-12-31"
PI_HOST="chi-eclipse-01"
PI_DB="~/Projects/Eclipse-01/data/obd.db"
SERVER_HOST="chi-srv-01"
SERVER_DB="obd2db"
SERVER_ENV="/mnt/projects/O/OBD2v2/.env"
SKIP_SERVER=0
SKIP_PI=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --since)        SINCE="$2"; shift 2 ;;
    --until)        UNTIL="$2"; shift 2 ;;
    --pi-host)      PI_HOST="$2"; shift 2 ;;
    --pi-db)        PI_DB="$2"; shift 2 ;;
    --server-host)  SERVER_HOST="$2"; shift 2 ;;
    --server-db)    SERVER_DB="$2"; shift 2 ;;
    --server-env)   SERVER_ENV="$2"; shift 2 ;;
    --skip-server)  SKIP_SERVER=1; shift ;;
    --skip-pi)      SKIP_PI=1; shift ;;
    -h|--help)      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)              echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SINCE" ]]; then
  echo "ERROR: --since is required. Use --help for usage." >&2
  exit 2
fi

echo "============================================================"
echo " Spool Review — slice [$SINCE, $UNTIL]"
echo "============================================================"

# ---------------------------------------------------------------------------
# Pi SQLite side
# ---------------------------------------------------------------------------
if [[ "$SKIP_PI" -eq 0 ]]; then
  echo ""
  echo "--- Pi SQLite ($PI_HOST:$PI_DB) ---"
  ssh "$PI_HOST" "sqlite3 $PI_DB" <<SQL
.headers on
.mode column
.width 25 6 12 12 12 10
SELECT 'total_rows_in_slice' as metric, COUNT(*) as val
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL';
SELECT 'distinct_timestamps' as metric, COUNT(DISTINCT timestamp) as val
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL';
SELECT 'capture_window_sec' as metric,
       CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400 AS INT) as val
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL';
.print ""
.print "-- PID coverage & ranges --"
SELECT parameter_name, COUNT(*) as n,
       printf('%.2f', MIN(value)) as min,
       printf('%.2f', MAX(value)) as max,
       printf('%.2f', AVG(value)) as avg,
       unit
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL'
  GROUP BY parameter_name, unit
  ORDER BY parameter_name;
.print ""
.print "-- Connection log (slice +/- 2 min context) --"
SELECT id, timestamp, event_type, success, retry_count,
       substr(coalesce(error_message,''), 1, 50) as err_snippet
  FROM connection_log
  WHERE timestamp >= datetime('$SINCE', '-2 minutes')
    AND timestamp <= datetime('$UNTIL', '+2 minutes')
  ORDER BY timestamp;
.print ""
.print "-- Sync log state --"
SELECT * FROM sync_log;
SQL
fi

# ---------------------------------------------------------------------------
# Server MariaDB side
# ---------------------------------------------------------------------------
if [[ "$SKIP_SERVER" -eq 0 ]]; then
  echo ""
  echo "--- Server MariaDB ($SERVER_HOST:$SERVER_DB) ---"
  # shellcheck disable=SC2029
  ssh "$SERVER_HOST" "bash -s" <<REMOTE
set -euo pipefail
DB_URL=\$(grep '^DATABASE_URL=' "$SERVER_ENV" | cut -d= -f2-)
# Parse user:pass@host/db from mysql+aiomysql://user:pass@host/db
CREDS=\$(echo "\$DB_URL" | sed -E 's|^mysql\+aiomysql://([^:]+):([^@]+)@[^/]+/.*|\1 \2|')
DB_USER=\$(echo "\$CREDS" | awk '{print \$1}')
DB_PASS=\$(echo "\$CREDS" | awk '{print \$2}')

mysql -u "\$DB_USER" -p"\$DB_PASS" "$SERVER_DB" <<SQL
SELECT 'total_rows_in_slice' metric, COUNT(*) val
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL';
SELECT parameter_name, COUNT(*) n,
       ROUND(MIN(value),2) mn,
       ROUND(MAX(value),2) mx,
       ROUND(AVG(value),2) av,
       unit
  FROM realtime_data
  WHERE timestamp >= '$SINCE' AND timestamp <= '$UNTIL'
  GROUP BY parameter_name, unit
  ORDER BY parameter_name;
SELECT '---statistics---' x;
SELECT parameter_name,
       ROUND(min_value,2) mn,
       ROUND(max_value,2) mx,
       ROUND(avg_value,2) av,
       sample_count n,
       profile_id
  FROM statistics
  WHERE analysis_date >= '$SINCE' AND analysis_date <= '$UNTIL'
  ORDER BY parameter_name;
SELECT '---sync_history_recent---' x;
SELECT id, device_id, started_at, rows_synced, status,
       SUBSTRING(tables_synced, 1, 60) AS tables_snippet
  FROM sync_history
  ORDER BY id DESC LIMIT 6;
SQL
REMOTE
fi

echo ""
echo "============================================================"
echo " Review complete. Compare PID row counts and value ranges"
echo " between Pi and server — they should match byte-for-byte."
echo " Grade values against Spool's Phase 1 thresholds in"
echo " offices/tuner/knowledge.md."
echo "============================================================"
