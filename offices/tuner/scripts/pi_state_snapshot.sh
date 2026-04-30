#!/usr/bin/env bash
################################################################################
# File: pi_state_snapshot.sh
# Purpose: One-shot probe of Pi live state for tuning-SME review. Pulls
#          power state (SOC/VCELL/PowerSource), latest drive_id, drive_summary
#          metadata (US-228 NULL bug check), recent connection_log events,
#          sync_log status, and service state. Replaces the inline SSH burst
#          Spool kept rewriting during system tests / drive grading.
# Author: Spool (Tuning SME)
# Created: 2026-04-29
#
# Background: This SSH+sqlite burst pattern was used 6+ times during the
# 2026-04-23 / 2026-04-29 system tests (drives 3, 4, 5; drain tests 1-4).
# CIO directive: "save your code and scripts as reusable tools."
#
# Sections (all on by default; use --section flags to filter):
#   --power        SOC / VCELL / PowerSource via UpsMonitor
#   --drive        Latest drive_id + drive_summary US-228 metadata check
#   --conn         Last 10 connection_log events
#   --sync         sync_log table state
#   --service      eclipse-obd.service systemd state
#   --fingerprint  Aggregate stats for the most recent drive_id (or --drive-id N)
#
# Usage:
#   ./pi_state_snapshot.sh                          # all sections
#   ./pi_state_snapshot.sh --power --drive          # filter
#   ./pi_state_snapshot.sh --fingerprint            # latest drive only
#   ./pi_state_snapshot.sh --fingerprint --drive-id 3
#   ./pi_state_snapshot.sh --host chi-eclipse-01    # explicit host
################################################################################

set -euo pipefail

# Defaults
PI_HOST="chi-eclipse-01"
DRIVE_ID=""             # blank = use latest
SECTIONS=""             # blank = all sections

usage() {
  sed -n '5,32p' "$0" | sed 's/^# //; s/^#//'
  exit "${1:-0}"
}

# Parse args; section flags additive (presence enables them; if any provided,
# only those run)
ENABLE_POWER=1
ENABLE_DRIVE=1
ENABLE_CONN=1
ENABLE_SYNC=1
ENABLE_SERVICE=1
ENABLE_FINGERPRINT=0
ANY_SECTION=0

while [ $# -gt 0 ]; do
  case "$1" in
    --power)        SECTIONS="$SECTIONS power"; ANY_SECTION=1; shift ;;
    --drive)        SECTIONS="$SECTIONS drive"; ANY_SECTION=1; shift ;;
    --conn)         SECTIONS="$SECTIONS conn"; ANY_SECTION=1; shift ;;
    --sync)         SECTIONS="$SECTIONS sync"; ANY_SECTION=1; shift ;;
    --service)      SECTIONS="$SECTIONS service"; ANY_SECTION=1; shift ;;
    --fingerprint)  SECTIONS="$SECTIONS fingerprint"; ANY_SECTION=1; shift ;;
    --drive-id)     DRIVE_ID="$2"; shift 2 ;;
    --host)         PI_HOST="$2"; shift 2 ;;
    -h|--help)      usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

# If user passed any --section flag, restrict to those; otherwise run all-default
if [ "$ANY_SECTION" = "1" ]; then
  ENABLE_POWER=0; ENABLE_DRIVE=0; ENABLE_CONN=0; ENABLE_SYNC=0; ENABLE_SERVICE=0; ENABLE_FINGERPRINT=0
  for s in $SECTIONS; do
    case "$s" in
      power)        ENABLE_POWER=1 ;;
      drive)        ENABLE_DRIVE=1 ;;
      conn)         ENABLE_CONN=1 ;;
      sync)         ENABLE_SYNC=1 ;;
      service)      ENABLE_SERVICE=1 ;;
      fingerprint)  ENABLE_FINGERPRINT=1 ;;
    esac
  done
fi

# Build a single SSH burst — all sections inside one heredoc to avoid N round-trips
DRIVE_FILTER=""
if [ -n "$DRIVE_ID" ]; then
  DRIVE_FILTER="WHERE drive_id=$DRIVE_ID"
else
  DRIVE_FILTER="WHERE drive_id=(SELECT MAX(drive_id) FROM realtime_data)"
fi

ssh -o BatchMode=yes -o ConnectTimeout=5 "$PI_HOST" "cd ~/Projects/Eclipse-01 && \
  echo '=== pi_state_snapshot @ '\$(date -u +%Y-%m-%dT%H:%M:%SZ)' ===' && \
  if [ $ENABLE_POWER = 1 ]; then \
    echo '--- POWER STATE ---' && \
    python -c 'import sys;sys.path.insert(0,\"src\");sys.path.insert(0,\".\");from pi.hardware.ups_monitor import UpsMonitor;m=UpsMonitor();print(f\"SOC={m.getBatteryPercentage():.1f}%  VCELL={m.getBatteryVoltage():.3f}V  Source={m.getPowerSource().name}\");m.close()'; \
  fi; \
  if [ $ENABLE_DRIVE = 1 ]; then \
    echo '--- DRIVE_SUMMARY (last 5 — US-228 NULL metadata check) ---' && \
    sqlite3 -column -header data/obd.db 'SELECT drive_id, drive_start_timestamp, ambient_temp_at_start_c AS iat, starting_battery_v AS batt, barometric_kpa_at_start AS baro FROM drive_summary ORDER BY drive_id DESC LIMIT 5;'; \
  fi; \
  if [ $ENABLE_CONN = 1 ]; then \
    echo '--- CONNECTION_LOG (last 10) ---' && \
    sqlite3 -column -header data/obd.db 'SELECT timestamp, event_type, success, retry_count FROM connection_log ORDER BY id DESC LIMIT 10;'; \
  fi; \
  if [ $ENABLE_SYNC = 1 ]; then \
    echo '--- SYNC_LOG ---' && \
    sqlite3 -column -header data/obd.db 'SELECT table_name, last_synced_id, last_synced_at, status FROM sync_log;'; \
  fi; \
  if [ $ENABLE_SERVICE = 1 ]; then \
    echo '--- ECLIPSE-OBD.SERVICE ---' && \
    systemctl show eclipse-obd -p ActiveState -p SubState -p MainPID; \
  fi; \
  if [ $ENABLE_FINGERPRINT = 1 ]; then \
    echo '--- FINGERPRINT (drive: $([ -n \"$DRIVE_ID\" ] && echo $DRIVE_ID || echo latest)) ---' && \
    sqlite3 -column -header data/obd.db \"SELECT parameter_name, COUNT(*) AS n, ROUND(MIN(value),2) AS min, ROUND(AVG(value),2) AS avg, ROUND(MAX(value),2) AS max FROM realtime_data $DRIVE_FILTER GROUP BY parameter_name ORDER BY parameter_name;\"; \
  fi"
