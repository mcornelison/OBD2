#!/usr/bin/env bash
################################################################################
# File Name: export_regression_fixture.sh
# Purpose:   One-shot: SCP the live Pi's data/obd.db to the workstation,
#            apply US-195 + US-200 in-place migrations (idempotent), filter
#            to the Session 23 drill window, and write the result to
#            data/regression/pi-inputs/eclipse_idle.db + metadata.json.
#
#            This is the canonical way to regenerate the eclipse_idle
#            regression fixture.  Invoke after a drill, or when the Pi
#            schema changes (post-sprint) so the fixture picks up the
#            post-migration shape.
# Author:    Rex (Ralph agent)
# Created:   2026-04-19
# Story:     US-197 (US-168 carryforward)
#
# Prereqs:
#   - Key-based SSH: ssh mcornelison@10.27.27.28 hostname
#   - Python 3.11+ available locally (uses src/pi/obdii/*.py migration helpers).
#
# Usage:
#   bash scripts/export_regression_fixture.sh
#   bash scripts/export_regression_fixture.sh --source-session 2026-04-19
#   bash scripts/export_regression_fixture.sh --dry-run
#   bash scripts/export_regression_fixture.sh --pi-path /custom/Eclipse-01
#
# The --source-session flag is a label that goes into metadata.json; it
# does NOT affect which rows are exported (those are all real rows in the
# Pi's current data/obd.db).  The filter happens inside the Python step.
#
# Invariants:
#   * Does NOT modify the Pi's data/obd.db (read-only SCP copy).
#   * Does NOT delete rows from the exported fixture -- migration adds
#     the data_source + drive_id columns; existing rows inherit
#     data_source='real' by DEFAULT and drive_id=NULL by SQLite ALTER
#     TABLE semantics (US-200 Invariant #4).
#   * Exit 0 = success.  Exit 2 = misuse / missing prereq.  Exit 1 =
#     fixture invalid after build (sanity check failure).
################################################################################

set -eu
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONF_FILE="$REPO_ROOT/deploy/deploy.conf"

# B-044: source canonical addresses. deploy.conf overrides below.
# shellcheck source=../deploy/addresses.sh
. "$REPO_ROOT/deploy/addresses.sh"

if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
fi

SOURCE_SESSION="$(date +%Y-%m-%d)"
DRY_RUN="0"
FIXTURE_DIR="$REPO_ROOT/data/regression/pi-inputs"
TMP_DIR="$FIXTURE_DIR/tmp"
RAW_LOCAL="$TMP_DIR/pi_obd_raw.db"
OUT_DB="$FIXTURE_DIR/eclipse_idle.db"
OUT_META="$FIXTURE_DIR/eclipse_idle.metadata.json"

usage() {
    cat <<'EOF'
Usage: bash scripts/export_regression_fixture.sh [OPTIONS]

Options:
  --source-session YYYY-MM-DD   Label for metadata.json (default: today).
  --pi-path PATH                Override Pi project root.
  --dry-run                     Print plan only; no SSH, no file writes.
  --help, -h                    Show this help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --source-session) SOURCE_SESSION="$2"; shift 2 ;;
        --pi-path)        PI_PATH="$2"; shift 2 ;;
        --dry-run)        DRY_RUN="1"; shift ;;
        --help|-h)        usage; exit 0 ;;
        *) echo "ERROR: Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

banner() {
    echo ""
    echo "================================================================"
    echo " $1"
    echo "================================================================"
}

if [ "$DRY_RUN" = "1" ]; then
    banner "DRY RUN -- plan"
    echo "  scp $PI_USER@$PI_HOST:$PI_PATH/data/obd.db  ->  $RAW_LOCAL"
    echo "  migrate in-place (US-195 data_source, US-200 drive_id)"
    echo "  write $OUT_DB"
    echo "  write $OUT_META (source_session=$SOURCE_SESSION)"
    exit 0
fi

banner "Step 1 / 4 -- SSH gate + tmp dir"
if ! ssh -p "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        "$PI_USER@$PI_HOST" 'hostname' >/dev/null 2>&1; then
    echo "ERROR: SSH gate failed -- cannot reach $PI_USER@$PI_HOST" >&2
    exit 2
fi
mkdir -p "$TMP_DIR"
echo "  SSH gate OK, tmp dir: $TMP_DIR"

banner "Step 2 / 4 -- SCP Pi data/obd.db (read-only copy)"
scp -P "$PI_PORT" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    "$PI_USER@$PI_HOST:$PI_PATH/data/obd.db" "$RAW_LOCAL"
echo "  raw fixture: $RAW_LOCAL ($(stat -c '%s' "$RAW_LOCAL" 2>/dev/null \
     || stat -f '%z' "$RAW_LOCAL") bytes)"

banner "Step 3 / 4 -- apply migrations + filter + write fixture"
# Delegate to Python so we reuse the production migration helpers from
# src/pi/obdii/data_source.py + drive_id.py (single source of truth).
# The filter is WHERE data_source='real' AND timestamp starts with
# SOURCE_SESSION; exporter-side because the Pi db may contain earlier
# test writes we don't want in the fixture.
PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

"$PYTHON_BIN" - "$REPO_ROOT" "$RAW_LOCAL" "$OUT_DB" "$OUT_META" "$SOURCE_SESSION" <<'PYEOF'
import json
import shutil
import sqlite3
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

repoRoot, rawDb, outDb, outMeta, sourceSession = (
    Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]),
    Path(sys.argv[4]), sys.argv[5],
)


def loadModule(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dataSource = loadModule(
    '_export_data_source', repoRoot / 'src' / 'pi' / 'obdii' / 'data_source.py',
)
driveId = loadModule(
    '_export_drive_id', repoRoot / 'src' / 'pi' / 'obdii' / 'drive_id.py',
)

# Copy to target; all mutations (migrations + filtering) happen on the
# copy so the raw SCP output is preserved for diagnostics.
shutil.copy2(rawDb, outDb)

conn = sqlite3.connect(str(outDb))
try:
    migratedDs = dataSource.ensureAllCaptureTables(conn)
    migratedDi = driveId.ensureAllDriveIdColumns(conn)
    driveId.ensureDriveCounter(conn)

    # Filter realtime_data to real+session rows.  Preserves all other
    # tables (connection_log, statistics) unchanged -- the fixture is
    # meant to carry the full drill's artefacts, not just one table.
    conn.execute(
        "DELETE FROM realtime_data "
        "WHERE data_source IS NOT NULL AND data_source <> 'real'"
    )
    conn.execute(
        "DELETE FROM realtime_data "
        "WHERE substr(timestamp, 1, 10) <> ?",
        (sourceSession,),
    )
    conn.commit()

    cursor = conn.cursor()
    rowCount = cursor.execute(
        'SELECT COUNT(*) FROM realtime_data'
    ).fetchone()[0]
    params = sorted(
        row[0] for row in cursor.execute(
            'SELECT DISTINCT parameter_name FROM realtime_data'
        )
    )
    window = cursor.execute(
        'SELECT MIN(timestamp), MAX(timestamp) FROM realtime_data'
    ).fetchone()
    if rowCount == 0:
        print('ERROR: fixture has 0 rows after filter -- is '
              f'source_session={sourceSession!r} correct?',
              file=sys.stderr)
        sys.exit(1)
finally:
    conn.close()

# Build metadata
def parseTs(s: str) -> datetime:
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f'unparseable: {s!r}')


duration = (parseTs(window[1]) - parseTs(window[0])).total_seconds()
meta = {
    'fixture_name': 'eclipse_idle',
    'captured_date': sourceSession,
    'vehicle': {
        'make': 'Mitsubishi',
        'model': 'Eclipse GST (2G DSM)',
        'year': 1998,
        'engine': '4G63 turbo (stock with modified EPROM)',
        'owner': 'CIO',
    },
    'pids_captured': params,
    'pid_count': len(params),
    'row_count': rowCount,
    'sampling_rate_per_sec':
        round(rowCount / duration, 2) if duration > 0 else None,
    'capture_window': {
        'start': window[0],
        'end': window[1],
        'duration_seconds': round(duration, 1),
    },
    'data_source': 'real',
    'tune_context': {
        'ecu': 'stock 2G with modified EPROM',
        'ltft_observed_flat_at_zero': True,
        'interpretation': 'Tune is dialed -- LTFT 0.00% flat across all samples',
    },
    'source_drill': {
        'session': 23,
        'date': sourceSession,
        'description':
            'Warm-idle OBD-II capture from the CIO\'s 1998 Eclipse GST. '
            'See specs/grounded-knowledge.md Real Vehicle Data section.',
    },
    'source_record': {
        'raw_pi_db': 'chi-eclipse-01:~/Projects/Eclipse-01/data/obd.db',  # b044-exempt: historical metadata (Session 23)
        'server_db': 'chi-srv-01:obd2db realtime_data '  # b044-exempt: historical metadata
                     'device_id=chi-eclipse-01',  # b044-exempt: historical metadata
    },
    'migration_applied': {
        'us_195_data_source': True,
        'us_195_data_source_tables_migrated': migratedDs,
        'us_200_drive_id_column': True,
        'us_200_drive_id_tables_migrated': migratedDi,
        'us_200_drive_id_values_preserved_null': True,
    },
    'invariants': [
        f'All {rowCount} rows tagged data_source=\'real\'.',
        f'All {rowCount} rows have drive_id=NULL (US-200 Invariant #4).',
        'Fixture is read-only; replay harness must retag \'replay\' on replay.',
        'Do not edit row values by hand -- regenerate via this script.',
    ],
    'range_bands_owner': 'Spool (offices/tuner/) -- PM Rule 7',
    'notes':
        'Grounded values for this fixture live in '
        'specs/grounded-knowledge.md \'Real Vehicle Data\' section.',
}
outMeta.write_text(json.dumps(meta, indent=2) + '\n')
print(f'  wrote {outDb} ({outDb.stat().st_size} bytes)')
print(f'  wrote {outMeta} ({outMeta.stat().st_size} bytes)')
print(f'  rows={rowCount} params={len(params)} '
      f'duration={duration:.1f}s source_session={sourceSession}')
PYEOF

banner "Step 4 / 4 -- sanity check"
# Hand the path to Python via argv rather than inlining it -- sidesteps
# git-bash vs. Windows-native path conversion and quoting pitfalls.
ROWS=$("$PYTHON_BIN" -c "import sqlite3, sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT COUNT(*) FROM realtime_data').fetchone()[0])" "$OUT_DB" 2>/dev/null || echo 0)
if ! [[ "$ROWS" =~ ^[0-9]+$ ]] || [ "$ROWS" -eq 0 ]; then
    echo "ERROR: fixture $OUT_DB has 0 rows -- export FAILED" >&2
    exit 1
fi
echo "  fixture OK: $ROWS rows in realtime_data"
echo "Overall: PASS"
