################################################################################
# File Name: schema_diff.py
# Purpose/Description: TD-039 close (US-249) -- detect Pi <-> server schema
#     drift on shared capture tables at PR / pre-deploy time.  Loads the Pi
#     SQLite schema by executing the canonical CREATE TABLE strings under
#     ``src/pi/`` in an in-memory sqlite3 connection (column parsing
#     delegated to SQLite, no fragile regex), loads the server schema by
#     walking SQLAlchemy ``Base.metadata.tables``, and emits a deterministic
#     JSON diff report.  Exit 0 = shared tables clean; exit 1 = drift in at
#     least one shared table.  Pi-only and server-only tables are reported
#     but do NOT fail the exit code (each tier owns operational + analytics
#     tables that don't need a mirror).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-249) | Initial -- TD-039 schema-diff close.
# ================================================================================
################################################################################

"""Pi vs server schema drift detection (TD-039 / US-249).

**Why this exists.** Sprint 16 US-213 shipped the server schema migration
gate (``scripts/apply_server_migrations.py``) -- it runs every server
deploy and fails the deploy if a planned migration doesn't apply cleanly.
But the gate is only as effective as the migration list.  When Sprint 15
US-206 added cold-start metadata columns to ``drive_summary`` on the Pi
side, no v0004 migration was authored, so the gate ran every deploy,
found nothing to do, and passed -- the drift went undetected for weeks
until Sprint 19 US-237 emergency-shipped v0004.

This script closes that gap by **detecting** the drift directly: it diffs
the Pi DDL against the server SQLAlchemy models for tables present on
both tiers.  Anything in the diff is something a migration should
address (or an intentional divergence the operator should document and
allowlist out-of-band).

**What it does NOT do.** Auto-generate migrations (out of scope per the
US-249 invariants -- Pi schema is authoritative and server modernizes to
match, but the *generation* of the SQL ALTER statements remains a human
task because column-rename semantics, default-value choice, and index
strategy require judgment).

CLI::

    python scripts/schema_diff.py            # exits 0 if shared tables clean
    python scripts/schema_diff.py --verbose  # human-readable summary first

Output (stdout, JSON, deterministic ordering)::

    {
      "summary": {
        "piTableCount": N,
        "serverTableCount": M,
        "sharedTableCount": K,
        "tablesWithDrift": ["..."],
        "tablesWithPiOnlyDrift": ["..."]   # gate-trip subset
      },
      "tablesOnlyInPi": ["pi_state", "static_data", ...],
      "tablesOnlyInServer": ["sync_history", "anomaly_log", ...],
      "sharedTableDrift": {
        "drive_summary": {
          "columnsOnlyInPi":     ["..."],
          "columnsOnlyInServer": ["..."]
        }
      }
    }

The script exits non-zero ONLY when ``tablesWithPiOnlyDrift`` is
non-empty -- that is the TD-039 silent-data-loss direction.  Server-only
extras (analytics columns the Pi never sends, PK rename conventions
like ``drain_event_id`` -> ``id``) are reported in
``sharedTableDrift`` for visibility but do NOT fail the gate, because
they don't risk data loss and would otherwise drown CI in by-design
noise.

The four server-side mirror columns (``source_id``, ``source_device``,
``synced_at``, ``sync_batch_id``) are filtered out before drift
detection -- they exist by design on every synced table per the
US-CMP-003 sync convention and would otherwise drown the report in
noise.

Manual usage today; a future story can wire this into ``make
pre-commit`` or a GitHub Actions check.  See US-249 acceptance for the
deferred CI hookup.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

__all__ = [
    'SERVER_MIRROR_COLUMNS',
    'computeDiff',
    'loadPiSchema',
    'loadServerSchema',
    'main',
    'renderJson',
]


# ================================================================================
# Constants
# ================================================================================

# Server-side adornments added by every synced-table model (see
# ``src/server/db/models.py`` header).  Not Pi-side concepts -- filtered
# out of drift detection so the report stays signal-only.
SERVER_MIRROR_COLUMNS: frozenset[str] = frozenset({
    'source_id', 'source_device', 'synced_at', 'sync_batch_id',
})

# Pi PK columns that the sync client renames to ``id`` on the wire so
# the server's ``source_id`` mapping stays uniform with every other
# capture table.  Documented inside the producing modules:
#
# * ``battery_health_log.drain_event_id``: see
#   ``src/pi/power/battery_health.py`` "Sync shape (US-194 delta)" block.
# * ``calibration_sessions.session_id``: legacy Pi PK preserved for
#   sqlite cascade FK (calibration_data.session_id), wire-renamed to id.
#
# These are NOT TD-039 silent-data-loss drift -- they're documented
# rename pairs.  Filtered out of the gate-trip list so the script can
# be wired into pre-commit without firing on by-design rename pairs.
PI_PK_RENAMED_TO_ID: dict[str, str] = {
    'battery_health_log': 'drain_event_id',
    'calibration_sessions': 'session_id',
}

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]


# ================================================================================
# Pi loader -- execute canonical DDL in-memory, read columns via PRAGMA
# ================================================================================


def loadPiSchema() -> dict[str, set[str]]:
    """Load the Pi SQLite schema as ``{table: {columns}}``.

    Imports the canonical DDL string constants from ``src.pi.*`` and
    executes them in an in-memory sqlite3 connection.  Column extraction
    is delegated to ``PRAGMA table_info`` so we don't have to parse SQL
    ourselves (regex on CREATE TABLE is famously fragile).

    Tables loaded: every CREATE TABLE statement reachable from
    ``src.pi.obdii.database_schema.ALL_SCHEMAS`` plus the four standalone
    schema modules (``drive_summary``, ``dtc_log_schema``,
    ``battery_health``, ``pi_state``, ``sync_log``,
    ``calibration.types``).  Adding a new table on the Pi side requires
    extending the registry below.

    Returns:
        Mapping from table name to a set of its column names.

    Raises:
        ImportError: if any Pi schema module fails to import (caller
            should report and exit non-zero).
    """
    # Pi-side __init__.py modules use bare `pi.*` imports (legacy
    # python-OBD shadowing convention from knowledge/patterns-python-systems.md
    # -- ``src/`` must be on sys.path so ``pi.display`` resolves to
    # ``src/pi/display``).  Inject both ``<root>`` (for ``src.*``) and
    # ``<root>/src`` (for ``pi.*``) so the import chain doesn't blow up
    # whether we're called from CLI or pytest.
    _srcPath = _PROJECT_ROOT / 'src'
    _added: list[str] = []
    for path in (str(_PROJECT_ROOT), str(_srcPath)):
        if path not in sys.path:
            sys.path.insert(0, path)
            _added.append(path)
    try:
        from src.pi.calibration.types import SCHEMA_CALIBRATION_DATA
        from src.pi.data.sync_log import SYNC_LOG_SCHEMA
        from src.pi.obdii.database_schema import ALL_SCHEMAS
        from src.pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY
        from src.pi.obdii.dtc_log_schema import SCHEMA_DTC_LOG
        from src.pi.obdii.pi_state import SCHEMA_PI_STATE
        from src.pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG
    finally:
        # Pop only the entries WE added so we don't pollute sys.path.
        for path in _added:
            try:
                sys.path.remove(path)
            except ValueError:
                pass

    # Collect every (table_name, ddl) pair into one ordered registry.
    # ALL_SCHEMAS already carries the (name, ddl) shape; the standalone
    # modules contribute one CREATE TABLE each.
    registry: list[tuple[str, str]] = list(ALL_SCHEMAS) + [
        ('drive_summary', SCHEMA_DRIVE_SUMMARY),
        ('dtc_log', SCHEMA_DTC_LOG),
        ('battery_health_log', SCHEMA_BATTERY_HEALTH_LOG),
        ('pi_state', SCHEMA_PI_STATE),
        ('sync_log', SYNC_LOG_SCHEMA),
        ('calibration_data', SCHEMA_CALIBRATION_DATA),
    ]

    schema: dict[str, set[str]] = {}
    with sqlite3.connect(':memory:') as conn:
        # The canonical DDL uses FK constraints between tables; create
        # them in registry order (parent tables before child tables --
        # ALL_SCHEMAS already enforces this for the obdii.database_schema
        # group).  PRAGMA foreign_keys stays OFF (the default) so order
        # mismatches don't blow up the load.
        for tableName, ddl in registry:
            conn.execute(ddl)
            cols = {row[1] for row in conn.execute(
                f'PRAGMA table_info({tableName})',
            )}
            if cols:
                schema[tableName] = cols

    return schema


# ================================================================================
# Server loader -- walk SQLAlchemy Base.metadata
# ================================================================================


def loadServerSchema() -> dict[str, set[str]]:
    """Load the server schema as ``{table: {columns}}``.

    Imports ``src.server.db.models`` so SQLAlchemy populates
    ``Base.metadata.tables``, then walks the metadata to emit a
    framework-independent dict.  Bypasses the migration history
    intentionally: the source of truth for the server schema is the
    declarative model file, and US-249 invariant 1 says detection-only.

    Returns:
        Mapping from table name to a set of its column names.

    Raises:
        ImportError: if SQLAlchemy or the server models module is not
            importable in this environment (caller should skip on Pi
            hosts where the server stack isn't installed).
    """
    sys.path.insert(0, str(_PROJECT_ROOT))
    try:
        from src.server.db.models import Base
    finally:
        if sys.path and sys.path[0] == str(_PROJECT_ROOT):
            sys.path.pop(0)

    return {
        tableName: {col.name for col in table.columns}
        for tableName, table in Base.metadata.tables.items()
    }


# ================================================================================
# computeDiff -- pure function, deterministic output
# ================================================================================


def computeDiff(
    piSchema: dict[str, set[str]],
    serverSchema: dict[str, set[str]],
) -> dict:
    """Compute the Pi <-> server schema diff.

    Pure function -- takes plain dicts, returns a JSON-shaped dict.  All
    list outputs are sorted so the diff is deterministic across runs (CI
    diffs stay readable, snapshot tests are stable).

    Args:
        piSchema: ``{table_name: {column_names}}`` from ``loadPiSchema``
            or a test fixture.
        serverSchema: same shape from ``loadServerSchema`` or a fixture.

    Returns:
        Diff dict with the shape documented in the module docstring.
    """
    piTables = set(piSchema.keys())
    serverTables = set(serverSchema.keys())

    sharedTables = piTables & serverTables
    tablesOnlyInPi = sorted(piTables - serverTables)
    tablesOnlyInServer = sorted(serverTables - piTables)

    sharedTableDrift: dict[str, dict[str, list[str]]] = {}
    tablesWithPiOnlyDrift: list[str] = []
    for tableName in sorted(sharedTables):
        piCols = piSchema[tableName]
        # Strip server-side mirror surface before diffing.
        serverCols = serverSchema[tableName] - SERVER_MIRROR_COLUMNS

        # Treat known Pi-PK rename pairs as equivalent to server `id`.
        # If both sides have the documented rename pair (Pi has the
        # named PK, server has `id`), drop the Pi-side name from the
        # diff so the by-design rename doesn't trip the gate.
        renamedPk = PI_PK_RENAMED_TO_ID.get(tableName)
        if renamedPk and renamedPk in piCols and 'id' in serverCols:
            piCols = piCols - {renamedPk}
            serverCols = serverCols - {'id'}

        onlyPi = sorted(piCols - serverCols)
        onlyServer = sorted(serverCols - piCols)

        if onlyPi or onlyServer:
            sharedTableDrift[tableName] = {
                'columnsOnlyInPi': onlyPi,
                'columnsOnlyInServer': onlyServer,
            }
        if onlyPi:
            # The TD-039 failure direction: Pi added a column whose
            # rows have nowhere to land on the server side -> silent
            # data loss on next sync.  This is the gate trip.
            tablesWithPiOnlyDrift.append(tableName)

    tablesWithDrift = sorted(sharedTableDrift.keys())

    return {
        'summary': {
            'piTableCount': len(piTables),
            'serverTableCount': len(serverTables),
            'sharedTableCount': len(sharedTables),
            'tablesWithDrift': tablesWithDrift,
            # The TD-039 gate signal: tables where Pi has columns the
            # server lacks (excluding mirror surface).  Server-only
            # extras (analytics columns, by-design adornments) do NOT
            # appear here because they don't risk data loss.
            'tablesWithPiOnlyDrift': sorted(tablesWithPiOnlyDrift),
        },
        'tablesOnlyInPi': tablesOnlyInPi,
        'tablesOnlyInServer': tablesOnlyInServer,
        'sharedTableDrift': sharedTableDrift,
    }


# ================================================================================
# Output helpers
# ================================================================================


def renderJson(diff: dict) -> str:
    """Serialize the diff dict to indented JSON for stdout / CI logs."""
    return json.dumps(diff, indent=2, sort_keys=True)


def _renderHumanSummary(diff: dict) -> str:
    """Render a 1-screen human-readable summary (verbose mode preface)."""
    summary = diff['summary']
    piOnly = summary['tablesWithPiOnlyDrift']
    lines = [
        '=== Pi <-> Server Schema Diff (US-249 / TD-039) ===',
        f'Pi tables:     {summary["piTableCount"]}',
        f'Server tables: {summary["serverTableCount"]}',
        f'Shared tables: {summary["sharedTableCount"]}',
        f'Drift:         {len(summary["tablesWithDrift"])} '
        f'({", ".join(summary["tablesWithDrift"]) or "none"})',
        f'GATE FAILURE:  {len(piOnly)} '
        f'({", ".join(piOnly) or "none"})  '
        '<- Pi added columns server lacks (TD-039 class)',
        '',
    ]
    if diff['tablesOnlyInPi']:
        lines.append(f'Pi-only tables: {", ".join(diff["tablesOnlyInPi"])}')
    if diff['tablesOnlyInServer']:
        lines.append(
            f'Server-only tables: {", ".join(diff["tablesOnlyInServer"])}',
        )
    if summary['tablesWithDrift']:
        lines.append('')
        lines.append('Drift detail:')
        for tableName in summary['tablesWithDrift']:
            d = diff['sharedTableDrift'][tableName]
            lines.append(f'  {tableName}:')
            if d['columnsOnlyInPi']:
                lines.append(
                    f'    Pi only:     {", ".join(d["columnsOnlyInPi"])}',
                )
            if d['columnsOnlyInServer']:
                lines.append(
                    f'    Server only: {", ".join(d["columnsOnlyInServer"])}',
                )
    lines.append('')
    return '\n'.join(lines)


# ================================================================================
# CLI
# ================================================================================


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='schema_diff',
        description=(
            'Detect Pi <-> server schema drift on shared capture tables. '
            'Exit 0 = shared tables clean, exit 1 = drift detected.'
        ),
    )
    parser.add_argument(
        '--verbose', action='store_true',
        help='Print a human-readable summary before the JSON payload.',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        Exit code -- 0 if no drift in shared tables (Pi-only / server-only
        tables are tier-owned and don't trip the gate); 1 if at least one
        shared table has column-set divergence outside the mirror surface.
    """
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    piSchema = loadPiSchema()
    serverSchema = loadServerSchema()
    diff = computeDiff(piSchema, serverSchema)

    if args.verbose:
        sys.stderr.write(_renderHumanSummary(diff))

    sys.stdout.write(renderJson(diff))
    sys.stdout.write('\n')

    # Gate trips ONLY on the TD-039 failure direction: Pi added a
    # column the server lacks (silent-data-loss class).  Server-only
    # extras (analytics columns, PK rename conventions) are reported
    # but don't fail the gate -- they are by-design and would create
    # CI false-positive fatigue if they tripped exit-1 every run.
    return 1 if diff['summary']['tablesWithPiOnlyDrift'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
