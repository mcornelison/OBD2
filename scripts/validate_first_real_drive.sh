#!/usr/bin/env bash
################################################################################
# File Name: validate_first_real_drive.sh
# Purpose:   CIO-runnable end-to-end validator for the first real drive in the
#            Sprint 15 window (US-208, B-037 Pi Sprint kickoff).  Exercises
#            the full capture surface shipped through Sprint 14 + 15:
#              * canonical UTC-ISO timestamps (US-202 / TD-027)
#              * drive_id minted + inherited across realtime/stats/alert/dtc/
#                drive_summary (US-200)
#              * data_source tagging (US-195)
#              * 6 new Mode 01 PIDs + ELM_VOLTAGE (US-199)
#              * DTC Mode 03/07 capture (US-204)
#              * drive-metadata row with ambient/battery/barometric (US-206)
#              * Pi -> server sync (US-149/154/194)
#              * report.py summary (US-160)
#              * Spool AI analysis endpoint (US-CMP-005 / US-147)
#              * I-016 thermostat disposition from sustained warm-idle
#
# Author:    Rex (Ralph agent)
# Created:   2026-04-20
# Story:     US-208 (Sprint 15)
#
# Prereqs:
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname    (Pi)
#   - Key-based SSH: ssh mcornelison@10.27.27.10 hostname    (server)
#   - Post-US-204 + US-205 + US-206 schema on both tiers.
#
# Usage:
#   bash scripts/validate_first_real_drive.sh                   # latest drive on Pi
#   bash scripts/validate_first_real_drive.sh --drive-id 1      # explicit drive
#   bash scripts/validate_first_real_drive.sh --dry-run         # plan only, no SSH
#   bash scripts/validate_first_real_drive.sh --fixture-db PATH # off-Pi test mode
#   bash scripts/validate_first_real_drive.sh --skip-sync       # skip sync step
#   bash scripts/validate_first_real_drive.sh --skip-report     # skip report.py
#   bash scripts/validate_first_real_drive.sh --skip-spool      # skip AI smoke
#   bash scripts/validate_first_real_drive.sh --help
#
# Exit codes:
#   0 -- every step PASS (or not-applicable cleanly reported)
#   1 -- one or more steps FAIL (diagnostic printed per step)
#   2 -- misuse (bad flag, SSH gate failed, missing fixture, etc.)
#
# Invariants (US-208):
#   * READ-ONLY against Pi + server DBs.  No UPDATE / DELETE / MIGRATE.
#   * Activity-gated: if no real drive data is present, validator reports
#     "no real drive data in window" cleanly and exits 0 on dry-run.
#   * No silent skips -- every step prints PASS / FAIL / N/A with reason.
#   * No hardcoded absolute row counts -- shape + presence only, never
#     "expected N rows" (duration-dependent).
################################################################################

set -u
set -o pipefail

# ----------------------------------------------------------------------------
# Addresses (B-044): source canonical config mirror.  deploy.conf overrides.
# ----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

PI_VENV='$HOME/obd2-venv'

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

# ----------------------------------------------------------------------------
# CLI defaults.
# ----------------------------------------------------------------------------
DRIVE_ID=""
DRY_RUN="0"
FIXTURE_DB=""
SKIP_SYNC="0"
SKIP_REPORT="0"
SKIP_SPOOL="0"
COOLANT_THRESHOLD_C="82"
MIN_DISTINCT_PARAMS="8"
MIN_SUSTAINED_WARMUP_MIN="15"

show_help() {
    cat <<EOF
Usage: bash scripts/validate_first_real_drive.sh [OPTIONS]

End-to-end validator for the first real drive in the Sprint 15 window.
Exercises Sprint 14+15 capture surface: canonical timestamps, drive_id,
data_source, 21+ PIDs, DTCs, drive_summary, sync, report, Spool AI.

Options:
  --drive-id N                Validate drive_id=N (default: latest on Pi).
  --fixture-db PATH           Off-Pi mode: query LOCAL sqlite fixture instead
                              of SSHing to the Pi.  Skips SSH + sync + spool.
  --dry-run                   Print plan only; no SSH, no writes.
  --skip-sync                 Skip the sync_now.py push step.
  --skip-report               Skip the report.py generation step.
  --skip-spool                Skip the Spool AI /analyze smoke step.
  --coolant-threshold-c N     I-016 gate (default: 82 C, i.e. 180 F).
  --min-distinct-params N     Minimum parameter_name diversity (default: 8).
  --min-sustained-warmup-min M  Drill minimum duration (default: 15 min).
  --help, -h                  Show this help.

Environment (overridable via deploy/deploy.conf):
  PI_HOST=$PI_HOST  PI_USER=$PI_USER  PI_PORT=$PI_PORT  PI_PATH=$PI_PATH
  SERVER_HOST=$SERVER_HOST  SERVER_USER=$SERVER_USER  SERVER_PORT=$SERVER_PORT
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --drive-id) DRIVE_ID="$2"; shift 2 ;;
        --fixture-db) FIXTURE_DB="$2"; shift 2 ;;
        --dry-run) DRY_RUN="1"; shift ;;
        --skip-sync) SKIP_SYNC="1"; shift ;;
        --skip-report) SKIP_REPORT="1"; shift ;;
        --skip-spool) SKIP_SPOOL="1"; shift ;;
        --coolant-threshold-c) COOLANT_THRESHOLD_C="$2"; shift 2 ;;
        --min-distinct-params) MIN_DISTINCT_PARAMS="$2"; shift 2 ;;
        --min-sustained-warmup-min) MIN_SUSTAINED_WARMUP_MIN="$2"; shift 2 ;;
        --help|-h) show_help; exit 0 ;;
        *)
            echo "ERROR: Unknown flag: $1" >&2
            show_help >&2
            exit 2
            ;;
    esac
done

# ----------------------------------------------------------------------------
# Helpers.
# ----------------------------------------------------------------------------
PASS_COUNT=0
FAIL_COUNT=0
NA_COUNT=0

banner() {
    echo ""
    echo "===================================================================="
    echo "$1"
    echo "===================================================================="
}

record_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    echo "  PASS: $1"
}

record_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    echo "  FAIL: $1" >&2
}

record_na() {
    NA_COUNT=$((NA_COUNT + 1))
    echo "  N/A : $1"
}

# Fixture mode uses the local sqlite3 CLI; SSH mode routes queries through
# the Pi / server.
sqlite_query_pi() {
    if [ -n "$FIXTURE_DB" ]; then
        sqlite3 "$FIXTURE_DB" "$1"
    else
        ssh -p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
            "$PI_USER@$PI_HOST" "sqlite3 $PI_PATH/data/obd.db \"$1\" 2>/dev/null"
    fi
}

ssh_pi_gate() {
    ssh -p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "$PI_USER@$PI_HOST" 'hostname' > /dev/null 2>&1
}

ssh_server_gate() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "$SERVER_USER@$SERVER_HOST" 'hostname' > /dev/null 2>&1
}

# ----------------------------------------------------------------------------
# Dry-run short-circuit: print plan, exit 0.
# ----------------------------------------------------------------------------
if [ "$DRY_RUN" = "1" ]; then
    cat <<EOF
DRY RUN -- US-208 First Real Drive Validator

Configuration:
  PI_HOST=$PI_HOST  PI_USER=$PI_USER  PI_PORT=$PI_PORT
  PI_PATH=$PI_PATH
  SERVER_HOST=$SERVER_HOST  SERVER_USER=$SERVER_USER
  DRIVE_ID=${DRIVE_ID:-<latest>}
  FIXTURE_DB=${FIXTURE_DB:-<none -- live Pi mode>}
  COOLANT_THRESHOLD_C=$COOLANT_THRESHOLD_C
  MIN_DISTINCT_PARAMS=$MIN_DISTINCT_PARAMS
  MIN_SUSTAINED_WARMUP_MIN=$MIN_SUSTAINED_WARMUP_MIN

Planned steps:
  1  SSH gate (Pi, server -- skipped in fixture mode).
  2  Resolve drive_id (argument, or MAX(drive_id) from Pi realtime_data).
  3  Drive window: MIN/MAX timestamp for drive_id on Pi.
  4  realtime_data: row count > 0 in window, data_source='real',
     drive_id matches, canonical ISO-8601Z timestamp suffix,
     distinct parameter_name >= $MIN_DISTINCT_PARAMS.
  5  dtc_log: entries for drive_id (0 = clean + reported explicitly).
  6  drive_summary: exactly 1 row for drive_id; ambient nullable;
     starting_battery + barometric present if cold start.
  7  I-016 coolant disposition: MAX(coolant) vs $COOLANT_THRESHOLD_C C gate;
     sustained warmup >= $MIN_SUSTAINED_WARMUP_MIN min -> BENIGN / ESCALATE /
     INCONCLUSIVE.
  8  sync_now.py -- push Pi delta rows to $SERVER_HOSTNAME (skipped: $SKIP_SYNC).
  9  report.py --drive <id> -- human-readable summary (skipped: $SKIP_REPORT).
 10  Spool AI: POST /api/v1/analyze with {drive_id:N, parameters:{}} --
     (skipped: $SKIP_SPOOL).  'insufficient data' return is valid.

No commands will be executed.
EOF
    exit 0
fi

# ----------------------------------------------------------------------------
# Live validation begins.
# ----------------------------------------------------------------------------
banner "US-208 First-Drive Validator"

# ---- Step 1 -- SSH / fixture gate -------------------------------------------
banner "Step 1 -- Access gate"
if [ -n "$FIXTURE_DB" ]; then
    if [ ! -f "$FIXTURE_DB" ]; then
        record_fail "fixture DB not found: $FIXTURE_DB"
        echo "SUMMARY: 0 pass / 1 fail"
        exit 2
    fi
    if ! command -v sqlite3 > /dev/null 2>&1; then
        record_fail "sqlite3 CLI not on PATH -- install it to run fixture mode"
        exit 2
    fi
    record_pass "fixture mode (local DB, sqlite3 CLI available)"
    # In fixture mode we auto-skip sync + spool (no live server reachable).
    SKIP_SYNC="1"
    SKIP_SPOOL="1"
else
    if ssh_pi_gate; then
        record_pass "SSH gate Pi ($PI_USER@$PI_HOST)"
    else
        record_fail "SSH gate Pi unreachable -- check key-based auth"
        exit 2
    fi
    if [ "$SKIP_SYNC" = "0" ] || [ "$SKIP_REPORT" = "0" ] || [ "$SKIP_SPOOL" = "0" ]; then
        if ssh_server_gate; then
            record_pass "SSH gate server ($SERVER_USER@$SERVER_HOST)"
        else
            record_fail "SSH gate server unreachable -- check key-based auth"
            echo "  (continuing -- sync/report/spool steps will record FAIL)"
        fi
    fi
fi

# ---- Step 2 -- Resolve drive_id ---------------------------------------------
banner "Step 2 -- Resolve drive_id"
if [ -z "$DRIVE_ID" ]; then
    LATEST=$(sqlite_query_pi "SELECT MAX(drive_id) FROM realtime_data WHERE drive_id IS NOT NULL" 2>/dev/null | tr -d '[:space:]')
    if [ -z "$LATEST" ] || [ "$LATEST" = "" ] || ! [[ "$LATEST" =~ ^[0-9]+$ ]]; then
        record_na "no drive_id present in realtime_data -- no real drive to validate"
        echo "SUMMARY: $PASS_COUNT pass / $FAIL_COUNT fail / $NA_COUNT n/a"
        echo "No real drive data in window."
        exit 0
    fi
    DRIVE_ID="$LATEST"
    record_pass "resolved latest drive_id=$DRIVE_ID"
else
    record_pass "explicit drive_id=$DRIVE_ID"
fi

# ---- Step 3 -- Drive window bounds ------------------------------------------
banner "Step 3 -- Drive window bounds"
WINDOW_START=$(sqlite_query_pi "SELECT MIN(timestamp) FROM realtime_data WHERE drive_id = $DRIVE_ID" | tr -d '[:space:]')
WINDOW_END=$(sqlite_query_pi "SELECT MAX(timestamp) FROM realtime_data WHERE drive_id = $DRIVE_ID" | tr -d '[:space:]')
if [ -z "$WINDOW_START" ] || [ "$WINDOW_START" = "" ]; then
    record_fail "no realtime_data rows for drive_id=$DRIVE_ID"
    echo "SUMMARY: $PASS_COUNT pass / $FAIL_COUNT fail / $NA_COUNT n/a"
    exit 1
fi
record_pass "window_start=$WINDOW_START  window_end=$WINDOW_END"

# ---- Step 4 -- realtime_data checks -----------------------------------------
banner "Step 4 -- realtime_data sanity"
ROW_COUNT=$(sqlite_query_pi "SELECT COUNT(*) FROM realtime_data WHERE drive_id = $DRIVE_ID" | tr -d '[:space:]')
if [[ "$ROW_COUNT" =~ ^[0-9]+$ ]] && [ "$ROW_COUNT" -gt 0 ]; then
    record_pass "realtime_data rows for drive_id=$DRIVE_ID: $ROW_COUNT"
else
    record_fail "realtime_data has 0 rows for drive_id=$DRIVE_ID"
fi

NON_REAL=$(sqlite_query_pi "SELECT COUNT(*) FROM realtime_data WHERE drive_id = $DRIVE_ID AND data_source != 'real'" | tr -d '[:space:]')
if [ "${NON_REAL:-0}" = "0" ]; then
    record_pass "all rows tagged data_source='real'"
else
    record_fail "$NON_REAL rows have data_source != 'real' in window"
fi

# Canonical timestamp format: strftime('%Y-%m-%dT%H:%M:%SZ','now') -- ends in Z.
BAD_TS=$(sqlite_query_pi "SELECT COUNT(*) FROM realtime_data WHERE drive_id = $DRIVE_ID AND timestamp NOT LIKE '%Z'" | tr -d '[:space:]')
if [ "${BAD_TS:-0}" = "0" ]; then
    record_pass "timestamps match canonical ISO-8601Z format"
else
    record_fail "$BAD_TS timestamps do NOT end with 'Z'"
fi

DISTINCT_PARAMS=$(sqlite_query_pi "SELECT COUNT(DISTINCT parameter_name) FROM realtime_data WHERE drive_id = $DRIVE_ID" | tr -d '[:space:]')
if [[ "$DISTINCT_PARAMS" =~ ^[0-9]+$ ]] && [ "$DISTINCT_PARAMS" -ge "$MIN_DISTINCT_PARAMS" ]; then
    record_pass "distinct parameter_name: $DISTINCT_PARAMS (>= $MIN_DISTINCT_PARAMS)"
else
    record_fail "distinct parameter_name: $DISTINCT_PARAMS < $MIN_DISTINCT_PARAMS"
fi

# ---- Step 5 -- dtc_log ------------------------------------------------------
banner "Step 5 -- dtc_log"
DTC_COUNT=$(sqlite_query_pi "SELECT COUNT(*) FROM dtc_log WHERE drive_id = $DRIVE_ID" 2>/dev/null | tr -d '[:space:]')
if ! [[ "${DTC_COUNT:-x}" =~ ^[0-9]+$ ]]; then
    record_fail "dtc_log table missing (US-204 not applied?)"
elif [ "$DTC_COUNT" = "0" ]; then
    record_pass "dtc_log: 0 DTCs for drive_id=$DRIVE_ID (clean drive -- no codes)"
else
    record_pass "dtc_log: $DTC_COUNT DTC(s) for drive_id=$DRIVE_ID (captured + logged)"
    DTC_ROWS=$(sqlite_query_pi "SELECT dtc_code || '/' || status FROM dtc_log WHERE drive_id = $DRIVE_ID" 2>/dev/null)
    echo "    DTC list: $DTC_ROWS"
fi

# ---- Step 6 -- drive_summary ------------------------------------------------
banner "Step 6 -- drive_summary"
SUM_COUNT=$(sqlite_query_pi "SELECT COUNT(*) FROM drive_summary WHERE drive_id = $DRIVE_ID" 2>/dev/null | tr -d '[:space:]')
if ! [[ "${SUM_COUNT:-x}" =~ ^[0-9]+$ ]]; then
    record_fail "drive_summary table missing (US-206 not applied?)"
elif [ "$SUM_COUNT" = "1" ]; then
    record_pass "drive_summary: 1 row for drive_id=$DRIVE_ID"
    SUM_ROW=$(sqlite_query_pi "SELECT ambient_temp_at_start_c, starting_battery_v, barometric_kpa_at_start FROM drive_summary WHERE drive_id = $DRIVE_ID" 2>/dev/null)
    echo "    ambient/battery/baro: $SUM_ROW"
    # Ambient NULL is OK (warm restart); surface it explicitly so the CIO knows.
    AMBIENT_NULL=$(sqlite_query_pi "SELECT COUNT(*) FROM drive_summary WHERE drive_id = $DRIVE_ID AND ambient_temp_at_start_c IS NULL" 2>/dev/null | tr -d '[:space:]')
    if [ "${AMBIENT_NULL:-0}" = "1" ]; then
        echo "    ambient=NULL -> warm restart (per US-206 cold-start rule)"
    fi
else
    record_fail "drive_summary: expected exactly 1 row, got $SUM_COUNT"
fi

# ---- Step 7 -- I-016 coolant disposition -----------------------------------
banner "Step 7 -- I-016 coolant disposition"
MAX_COOLANT=$(sqlite_query_pi "SELECT MAX(value) FROM realtime_data WHERE drive_id = $DRIVE_ID AND parameter_name = 'COOLANT_TEMP'" 2>/dev/null | tr -d '[:space:]')
if [ -z "$MAX_COOLANT" ] || [ "$MAX_COOLANT" = "" ]; then
    record_na "coolant_temp not captured in window -- I-016 undeterminable"
else
    echo "    max coolant: ${MAX_COOLANT} C (gate: ${COOLANT_THRESHOLD_C} C)"
    # Use awk for float compare -- bash only does integer math.
    ABOVE=$(awk -v m="$MAX_COOLANT" -v t="$COOLANT_THRESHOLD_C" \
        'BEGIN{print (m+0 >= t+0) ? 1 : 0}')
    # Drive duration in seconds (timestamp diff via sqlite julianday).
    DURATION_MIN=$(sqlite_query_pi "SELECT CAST((julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 1440 AS INTEGER) FROM realtime_data WHERE drive_id = $DRIVE_ID" 2>/dev/null | tr -d '[:space:]')
    echo "    duration: ${DURATION_MIN:-?} min (gate: ${MIN_SUSTAINED_WARMUP_MIN} min)"
    DURATION_OK=$(awk -v d="${DURATION_MIN:-0}" -v m="$MIN_SUSTAINED_WARMUP_MIN" \
        'BEGIN{print (d+0 >= m+0) ? 1 : 0}')
    if [ "$DURATION_OK" = "0" ]; then
        record_na "I-016 INCONCLUSIVE -- drive < ${MIN_SUSTAINED_WARMUP_MIN} min"
        echo "    (need sustained warm-idle >= ${MIN_SUSTAINED_WARMUP_MIN} min for disposition)"
    elif [ "$ABOVE" = "1" ]; then
        record_pass "I-016 BENIGN -- max coolant ${MAX_COOLANT} C >= ${COOLANT_THRESHOLD_C} C over ${DURATION_MIN} min"
    else
        record_pass "I-016 ESCALATE -- max coolant ${MAX_COOLANT} C < ${COOLANT_THRESHOLD_C} C over ${DURATION_MIN} min"
        echo "    -> file hardware-investigation story in Sprint 16+"
    fi
fi

# ---- Step 8 -- sync_now.py --------------------------------------------------
banner "Step 8 -- Pi -> server sync"
if [ "$SKIP_SYNC" = "1" ]; then
    record_na "sync step skipped (--skip-sync or fixture mode)"
else
    if ssh -p "$PI_PORT" -o StrictHostKeyChecking=no "$PI_USER@$PI_HOST" \
            "cd $PI_PATH && $PI_VENV/bin/python scripts/sync_now.py" \
            > /tmp/us208_sync.out 2>&1; then
        record_pass "sync_now.py completed"
        tail -n 10 /tmp/us208_sync.out | sed 's/^/    /'
    else
        record_fail "sync_now.py failed -- see /tmp/us208_sync.out"
        tail -n 10 /tmp/us208_sync.out | sed 's/^/    /' >&2
    fi
fi

# ---- Step 9 -- report.py ----------------------------------------------------
banner "Step 9 -- report.py drive summary"
if [ "$SKIP_REPORT" = "1" ]; then
    record_na "report step skipped (--skip-report or fixture mode)"
else
    if ssh -o StrictHostKeyChecking=no "$SERVER_USER@$SERVER_HOST" \
            "cd $SERVER_PROJECT_PATH && python scripts/report.py --drive $DRIVE_ID" \
            > /tmp/us208_report.out 2>&1; then
        record_pass "report.py --drive $DRIVE_ID completed"
        head -n 20 /tmp/us208_report.out | sed 's/^/    /'
    else
        record_fail "report.py failed -- see /tmp/us208_report.out"
        tail -n 10 /tmp/us208_report.out | sed 's/^/    /' >&2
    fi
fi

# ---- Step 10 -- Spool AI smoke ----------------------------------------------
banner "Step 10 -- Spool AI /analyze smoke"
if [ "$SKIP_SPOOL" = "1" ]; then
    record_na "Spool step skipped (--skip-spool or fixture mode)"
else
    ANALYZE_URL="${SERVER_BASE_URL}/api/v1/analyze"
    PAYLOAD='{"drive_id":'"$DRIVE_ID"',"parameters":{}}'
    HTTP_STATUS=$(curl -s -o /tmp/us208_spool.out -w '%{http_code}' \
        -X POST -H 'Content-Type: application/json' \
        --max-time 180 \
        -d "$PAYLOAD" "$ANALYZE_URL" 2>/dev/null)
    if [ "$HTTP_STATUS" = "200" ]; then
        record_pass "Spool /analyze returned 200 for drive_id=$DRIVE_ID"
        # 'insufficient data' or empty recommendations both count as valid
        # smoke results per US-208 acceptance #4.
        head -c 400 /tmp/us208_spool.out | sed 's/^/    /'
        echo ""
    else
        record_fail "Spool /analyze returned HTTP $HTTP_STATUS (expected 200)"
        head -c 400 /tmp/us208_spool.out | sed 's/^/    /' >&2
    fi
fi

# ---- Summary ---------------------------------------------------------------
echo ""
echo "===================================================================="
echo "SUMMARY: $PASS_COUNT pass / $FAIL_COUNT fail / $NA_COUNT n/a"
echo "        drive_id=$DRIVE_ID  window=$WINDOW_START..$WINDOW_END"
echo "===================================================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
