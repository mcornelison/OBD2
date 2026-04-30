#!/usr/bin/env bash
################################################################################
# File: ups_drain_monitor.sh
# Purpose: Background monitor for Pi UPS drain tests. Polls SOC + VCELL +
#          PowerSource via SSH every N seconds, logs to a timestamped file.
#          Replaces the inline bash loop Spool kept rewriting in drain tests
#          1-4 (2026-04-20 through 2026-04-29).
# Author: Spool (Tuning SME)
# Created: 2026-04-29
#
# Background note: After 4 drain tests, the inline pattern was identical each
# time — start a SSH-poll loop, log SOC/VCELL/PowerSource, manually mark unplug
# timestamp, kill PID at end. CIO directive: "save your code and scripts as
# reusable tools." This is that.
#
# What it logs (one line per cadence tick):
#   HH:MM:SSZ UP   <SOC%>,<VCELL_V>,<PowerSource>     # Pi reachable
#   HH:MM:SSZ DOWN ssh-unreachable                    # Pi silent
#
# Markers for unplug/replug events:
#   ./ups_drain_monitor.sh --mark "CIO unplugged"    # appends MARKER line
#
# Usage:
#   ./ups_drain_monitor.sh                          # start (default 20s)
#   ./ups_drain_monitor.sh --cadence 10 --label "test 5"
#   ./ups_drain_monitor.sh --mark "CIO unplugged"   # mark current latest log
#   ./ups_drain_monitor.sh --stop                   # kill running monitor(s)
#   ./ups_drain_monitor.sh --tail                   # tail current latest log
################################################################################

set -euo pipefail

# Defaults
CADENCE=20                     # seconds between polls
PI_HOST="chi-eclipse-01"       # SSH target (chi-eclipse-01 from ~/.ssh/config)
LOG_DIR="/tmp"                 # where logs land
LABEL=""                       # optional label written into log header
LOG_PREFIX="pi_ups_drain"      # log filename prefix

usage() {
  sed -n '5,28p' "$0" | sed 's/^# //; s/^#//'
  exit "${1:-0}"
}

# Find current latest log (used by --mark, --tail, --stop)
find_latest_log() {
  ls -t "$LOG_DIR/${LOG_PREFIX}_"*.log 2>/dev/null | head -1 || true
}

# Parse args
ACTION="start"
MARK_TEXT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cadence)   CADENCE="$2"; shift 2 ;;
    --label)     LABEL="$2"; shift 2 ;;
    --host)      PI_HOST="$2"; shift 2 ;;
    --log-dir)   LOG_DIR="$2"; shift 2 ;;
    --mark)      ACTION="mark"; MARK_TEXT="$2"; shift 2 ;;
    --stop)      ACTION="stop"; shift ;;
    --tail)      ACTION="tail"; shift ;;
    -h|--help)   usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

# --mark mode: append a MARKER line to the latest log
if [ "$ACTION" = "mark" ]; then
  LOG=$(find_latest_log)
  [ -z "$LOG" ] && { echo "No drain log found in $LOG_DIR" >&2; exit 1; }
  echo ">>> $(date -u +%H:%M:%SZ) MARKER: ${MARK_TEXT}" >> "$LOG"
  echo "Marked: $LOG"
  tail -3 "$LOG"
  exit 0
fi

# --tail mode: tail current latest log
if [ "$ACTION" = "tail" ]; then
  LOG=$(find_latest_log)
  [ -z "$LOG" ] && { echo "No drain log found" >&2; exit 1; }
  echo "Tailing: $LOG"
  tail -f "$LOG"
fi

# --stop mode: kill any running monitor processes
if [ "$ACTION" = "stop" ]; then
  PIDS=$(ps -ef | grep -v grep | grep "ups_drain_monitor.sh" | grep -v "$$" | awk '{print $2}' || true)
  if [ -z "$PIDS" ]; then
    echo "No running monitor found"
    exit 0
  fi
  echo "Killing PIDs: $PIDS"
  kill $PIDS 2>/dev/null || true
  sleep 1
  for p in $PIDS; do
    if ps -p "$p" >/dev/null 2>&1; then
      kill -9 "$p" 2>/dev/null || true
    fi
  done
  echo "Done."
  exit 0
fi

# --start mode (default): launch monitor as background process
TS=$(date -u +%Y%m%dT%H%M%SZ)
LOG="${LOG_DIR}/${LOG_PREFIX}_${TS}.log"
{
  echo "=== UPS drain monitor — start $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  [ -n "$LABEL" ] && echo "Label: $LABEL"
  echo "Host: $PI_HOST  Cadence: ${CADENCE}s"
} > "$LOG"

# Launch the polling loop in the background
(
  while true; do
    T=$(date -u +%H:%M:%SZ)
    OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=3 "$PI_HOST" "cd ~/Projects/Eclipse-01 && python -c 'import sys;sys.path.insert(0,\"src\");sys.path.insert(0,\".\");from pi.hardware.ups_monitor import UpsMonitor;m=UpsMonitor();print(f\"{m.getBatteryPercentage():.1f},{m.getBatteryVoltage():.3f},{m.getPowerSource().name}\");m.close()'" 2>/dev/null || true)
    if [ -n "$OUT" ]; then
      echo "$T UP   $OUT" >> "$LOG"
    else
      echo "$T DOWN ssh-unreachable" >> "$LOG"
    fi
    sleep "$CADENCE"
  done
) &

PID=$!
echo "Monitor started"
echo "  PID:     $PID"
echo "  Log:     $LOG"
echo "  Cadence: ${CADENCE}s"
echo ""
echo "Use:"
echo "  $0 --mark 'CIO unplugged'    # mark unplug timestamp"
echo "  $0 --tail                    # follow live"
echo "  $0 --stop                    # kill monitor"
