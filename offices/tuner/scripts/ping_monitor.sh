#!/usr/bin/env bash
# ============================================================================
# ping_monitor.sh - poll host availability and log transitions
# ----------------------------------------------------------------------------
# Pings a target host every N seconds (default 5). Logs:
#   - START timestamp
#   - FIRST FAILURE timestamp (state transition ok -> fail)
#   - RECOVERY timestamp (state transition fail -> ok)
#   - Periodic heartbeat lines (every ~1 min during each state) so the log
#     proves the monitor is alive
#
# USAGE:
#   ./ping_monitor.sh <host> [interval_sec] [logfile]
#
# Output is tee'd to stdout + logfile.  Designed to run in background;
# tail -f the logfile to watch.
# ============================================================================

set -u

HOST="${1:-10.27.27.28}"
INTERVAL="${2:-5}"
LOGFILE="${3:-/tmp/pi_ping_monitor_$(date -u +%Y%m%dT%H%M%SZ).log}"

# Windows ping syntax (git bash on Windows): -n count -w timeout_ms
# Linux ping syntax: -c count -W timeout_sec
if ping -n 1 -w 1000 127.0.0.1 >/dev/null 2>&1; then
  PING_CMD="ping -n 1 -w 2000"
else
  PING_CMD="ping -c 1 -W 2"
fi

NOW() { date -u +%Y-%m-%dT%H:%M:%SZ; }

START_TIME="$(NOW)"
echo "[$START_TIME] START monitoring $HOST every ${INTERVAL}s" | tee -a "$LOGFILE"
echo "[$START_TIME] ping cmd: $PING_CMD $HOST" | tee -a "$LOGFILE"
echo "[$START_TIME] logfile: $LOGFILE" | tee -a "$LOGFILE"

LAST_STATE="unknown"
PING_N=0
CONSEC=0
STATE_START="$START_TIME"

while true; do
  PING_N=$((PING_N + 1))
  T="$(NOW)"
  if $PING_CMD "$HOST" >/dev/null 2>&1; then
    STATE="ok"
  else
    STATE="fail"
  fi

  if [ "$STATE" != "$LAST_STATE" ]; then
    # State transition
    if [ "$LAST_STATE" = "unknown" ]; then
      echo "[$T] INITIAL STATE = $STATE (ping #$PING_N)" | tee -a "$LOGFILE"
    elif [ "$STATE" = "fail" ]; then
      echo "[$T] *** FIRST FAILURE (ping #$PING_N) -- host unreachable" | tee -a "$LOGFILE"
      echo "[$T]     previous ok streak: $CONSEC pings starting $STATE_START" | tee -a "$LOGFILE"
    else
      echo "[$T] *** RECOVERY (ping #$PING_N) -- host back online" | tee -a "$LOGFILE"
      echo "[$T]     previous fail streak: $CONSEC pings starting $STATE_START" | tee -a "$LOGFILE"
    fi
    CONSEC=1
    STATE_START="$T"
  else
    CONSEC=$((CONSEC + 1))
  fi

  # Heartbeat every ~1 min (12 pings at 5s interval) in each state
  if [ $((CONSEC % 12)) -eq 1 ] && [ "$CONSEC" -gt 1 ]; then
    echo "[$T] heartbeat state=$STATE consec=$CONSEC (ping #$PING_N)" | tee -a "$LOGFILE"
  fi

  LAST_STATE="$STATE"
  sleep "$INTERVAL"
done
