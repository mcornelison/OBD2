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
# 2026-05-01    | Rex (US-256) | Sprint 19/20 retro -- TD-043 class detection.
#               |              | Add loadServerNotNullNoDefault() + extend
#               |              | computeDiff with serverRequiredColumnsMissingOnPi
#               |              | rule (severity=high gate trip).  Wires CLI to
#               |              | call the new loader so the rule fires whenever
#               |              | a server NOT-NULL column has no default + Pi
#               |              | sync writer omits it (the TD-043 silent-failure
#               |              | class).
# 2026-09-09    | Rex (US-607) | TD-079 -- the hand-kept registry was blind to
#               |              | dtc_freeze_frame (US-368 created it via an
#               |              | ensureX helper, which on the Pi IS the
#               |              | migration system).  Add its DDL, and add
#               |              | syncedPiTables() + the
#               |              | syncedTablesInvisibleToPiLoader rule so the
#               |              | NEXT such omission fails the gate by name
#               |              | instead of being reported as a server-only
#               |              | table.
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
        "tablesWithPiOnlyDrift": ["..."],   # TD-039 gate trip
        "tablesWithRequiredColumnGap": ["..."]  # TD-043 gate trip
      },
      "tablesOnlyInPi": ["pi_state", "static_data", ...],
      "tablesOnlyInServer": ["sync_history", "anomaly_log", ...],
      "sharedTableDrift": {
        "drive_summary": {
          "columnsOnlyInPi":     ["..."],
          "columnsOnlyInServer": ["..."]
        }
      },
      "serverRequiredColumnsMissingOnPi": {
        "drive_summary": ["device_id", "start_time"]
      }
    }

The script exits non-zero when ANY gate trips:

* ``tablesWithPiOnlyDrift`` non-empty -- TD-039 silent-data-loss
  direction (Pi added a column the server lacks).
* ``tablesWithRequiredColumnGap`` non-empty -- TD-043 silent-sync-failure
  direction (server has a NOT-NULL column with no default that the Pi
  sync writer never populates -- every Pi INSERT into that table will
  fail with the MariaDB-1364 / SQLite-NOT-NULL-constraint error class).
* ``syncedTablesInvisibleToPiLoader`` non-empty -- TD-079 blind-gate
  direction (a table is registered for sync but :func:`loadPiSchema`
  cannot see it, so the two rules above say nothing at all about it).

**Why the third rule exists (US-607 / TD-079).**  The Pi registry below
is a hand-kept list of ``CREATE TABLE`` constants, and on the Pi the
``ensureXSchema`` helpers ARE the migration system -- so a table can
land the normal way and never reach this file.  ``dtc_freeze_frame``
did exactly that: created by US-368, registered for sync by US-369, and
absent here for four sprints.  The failure was not silence.  The gate
read the SERVER's copy of the table, found no Pi counterpart, and filed
it under ``tablesOnlyInServer`` -- a category this module documents as
tier-owned and deliberately gate-exempt.  A synced, cross-tier table sat
in the output the whole time, wearing the label that means "nothing to
see here".

The third rule closes the class rather than the instance: its subject is
computed from the sync registries themselves (:func:`syncedPiTables`),
so the next ensureX-only table fails the gate by name on the day it is
registered, whether or not anyone remembers this file exists.

Server-only extras (analytics columns the Pi never sends, PK rename
conventions like ``drain_event_id`` -> ``id``) are reported in
``sharedTableDrift`` for visibility but do NOT fail the gate, because
they don't risk data loss and would otherwise drown CI in by-design
noise.  Only columns that are NOT NULL and have no default land in the
TD-043 gate-trip list -- the analytics-only nullable extras are
correctly classified as visibility-only.

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
import contextlib
import json
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

__all__ = [
    'SERVER_MIRROR_COLUMNS',
    'computeDiff',
    'loadPiSchema',
    'loadServerNotNullNoDefault',
    'loadServerSchema',
    'main',
    'renderJson',
    'syncedPiTables',
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
# US-543 (A-4 parity guard): this map MUST agree, both directions, with the
# non-'id' entries of ``src.pi.data.sync_log.PK_COLUMN`` -- the registry the
# sync client actually derives the rename from (``pkColumn != 'id'`` ->
# ``_renamePkToId``).  ``drive_summary`` was missing here for four sprints:
# its rename shipped and worked (the client never reads this map), but the
# DECLARATION was stale, which is the "new synced table added without its
# mapping" gap.  ``tests/lint/test_pi_server_contract_parity.py`` now pins it.
PI_PK_RENAMED_TO_ID: dict[str, str] = {
    'battery_health_log': 'drain_event_id',
    'calibration_sessions': 'session_id',
    # US-206 / US-194: drive_summary's PK IS drive_id (the per-drive natural
    # monotonic cursor); the client renames it to ``id`` on the outbound
    # payload so the server's ``id -> source_id`` rule applies uniformly.  The
    # server ALSO carries its own ``drive_id`` column, mirrored from source_id
    # by the US-372 chk_drive_id_source_id invariant -- a different fact from
    # the Pi's PK, which is why both names appear on the server side.
    'drive_summary': 'drive_id',
}

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _piImportPath() -> Iterator[None]:
    """Put ``<root>`` and ``<root>/src`` on ``sys.path`` for the block's duration.

    Pi-side ``__init__.py`` modules use bare ``pi.*`` imports (the legacy
    python-OBD shadowing convention from
    ``knowledge/patterns-python-systems.md`` -- ``src/`` must be on ``sys.path``
    so ``pi.display`` resolves to ``src/pi/display``).  Both ``<root>`` (for
    ``src.*``) and ``<root>/src`` (for ``pi.*``) are injected so the import chain
    doesn't blow up whether we're called from the CLI or from pytest.

    Only entries this helper actually added are popped again, so a caller that
    already had them on the path keeps them.
    """
    added: list[str] = []
    for path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / 'src')):
        if path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)
    try:
        yield
    finally:
        for path in added:
            try:
                sys.path.remove(path)
            except ValueError:
                pass


# ================================================================================
# The synced-table subject -- computed from the registries, never hand-kept
# ================================================================================


def syncedPiTables() -> frozenset[str]:
    """Return every Pi table registered to cross the sync wire, computed live.

    The union of the two wire paths, read from the registries the sync client
    itself derives from:

    * ``src.pi.data.sync_log.PK_COLUMN`` -- the integer-PK delta path.
    * ``src.common.sync.snapshot_registry.SNAPSHOT_SYNC`` -- the natural-key
      snapshot path added by US-416.

    COMPLETE BY CONSTRUCTION, and deliberately so.  TD-079's defect class is "a
    hand-kept inventory of a set that keeps growing"; a guard whose own subject
    was a second hand-kept list would reproduce that defect inside the fix for
    it.  Computed on every call rather than snapshotted at import, so a table
    registered for sync tomorrow is in the subject the same day.

    ``scripts/audit_sync_contract_parity.syncedTables()`` derives the same set
    for the US-543 A-4 gate.  Neither is a copy of the other's declaration --
    both read the same two registries -- but two readers CAN drift if a third
    wire path is added and only one of them learns about it.  That residual is
    pinned by ``tests/scripts/test_schema_diff.py`` rather than left implicit,
    and the dependency is not imported across because the A-4 audit already
    imports FROM this module (the cycle would be real).

    Returns:
        Frozen set of table names.

    Raises:
        ImportError: if either registry module fails to import.
    """
    with _piImportPath():
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC
        from src.pi.data.sync_log import PK_COLUMN

        return frozenset(PK_COLUMN) | frozenset(SNAPSHOT_SYNC)


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
    ``src.pi.obdii.database_schema.ALL_SCHEMAS`` plus the standalone
    schema modules (``drive_summary``, ``dtc_log_schema``,
    ``dtc_freeze_frame_schema``, ``battery_health``, ``pi_state``,
    ``sync_log``, ``calibration.types``).  Adding a new table on the Pi
    side requires extending the registry below -- and forgetting to is
    exactly TD-079, so :func:`syncedPiTables` is diffed against this
    function's output by the gate and by
    ``tests/scripts/test_schema_diff.py``.  The list stays hand-kept; what
    changed in US-607 is that letting it go stale is now LOUD.

    Returns:
        Mapping from table name to a set of its column names.

    Raises:
        ImportError: if any Pi schema module fails to import (caller
            should report and exit non-zero).
    """
    with _piImportPath():
        from src.pi.calibration.types import SCHEMA_CALIBRATION_DATA
        from src.pi.data.sync_log import SYNC_LOG_SCHEMA
        from src.pi.obdii.database_schema import ALL_SCHEMAS
        from src.pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY
        from src.pi.obdii.dtc_freeze_frame_schema import SCHEMA_DTC_FREEZE_FRAME
        from src.pi.obdii.dtc_log_schema import SCHEMA_DTC_LOG
        from src.pi.obdii.pi_state import SCHEMA_PI_STATE
        from src.pi.power.battery_health import SCHEMA_BATTERY_HEALTH_LOG

    # Collect every (table_name, ddl) pair into one ordered registry.
    # ALL_SCHEMAS already carries the (name, ddl) shape; the standalone
    # modules contribute one CREATE TABLE each.
    registry: list[tuple[str, str]] = list(ALL_SCHEMAS) + [
        ('drive_summary', SCHEMA_DRIVE_SUMMARY),
        ('dtc_log', SCHEMA_DTC_LOG),
        # US-368/US-369 (F-109).  Created by ``ensureDtcFreezeFrameTable`` and
        # registered for sync, but absent from this list until US-607 -- so the
        # gate compared nothing for it and labelled it server-only.  See the
        # module docstring's TD-079 note.
        ('dtc_freeze_frame', SCHEMA_DTC_FREEZE_FRAME),
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


def loadServerNotNullNoDefault() -> dict[str, set[str]]:
    """Load server columns that are ``NOT NULL`` AND have no default.

    The TD-043 silent-sync-failure class: server declared a column
    ``NOT NULL`` with no Python default and no ``server_default``, but
    the Pi sync writer never populates it.  Every Pi INSERT into that
    table fails with ``Field 'X' doesn't have a default value`` (MariaDB
    1364) or ``NOT NULL constraint failed: T.X`` (SQLite).

    Returns:
        Mapping ``{table_name: {column_names}}`` where each listed
        column has ``column.nullable is False`` and BOTH
        ``column.default is None`` AND ``column.server_default is None``.
        Tables without any such columns are absent from the dict.

    Raises:
        ImportError: same as :func:`loadServerSchema` -- if SQLAlchemy
            or the server models module isn't importable.
    """
    sys.path.insert(0, str(_PROJECT_ROOT))
    try:
        from src.server.db.models import Base
    finally:
        if sys.path and sys.path[0] == str(_PROJECT_ROOT):
            sys.path.pop(0)

    result: dict[str, set[str]] = {}
    for tableName, table in Base.metadata.tables.items():
        offenders = {
            col.name for col in table.columns
            if col.nullable is False
            and col.default is None
            and col.server_default is None
            # Auto-increment integer PKs ARE technically NOT NULL with
            # no explicit default but the database supplies the value
            # at INSERT time.  Filter them out so the rule doesn't fire
            # on the by-design ``id`` column on every synced table.
            and not (col.primary_key and col.autoincrement is not False)
        }
        if offenders:
            result[tableName] = offenders
    return result


# ================================================================================
# computeDiff -- pure function, deterministic output
# ================================================================================


def computeDiff(
    piSchema: dict[str, set[str]],
    serverSchema: dict[str, set[str]],
    serverNotNullNoDefault: dict[str, set[str]] | None = None,
    syncedTables: set[str] | frozenset[str] | None = None,
) -> dict:
    """Compute the Pi <-> server schema diff.

    Pure function -- takes plain dicts, returns a JSON-shaped dict.  All
    list outputs are sorted so the diff is deterministic across runs (CI
    diffs stay readable, snapshot tests are stable).

    Args:
        piSchema: ``{table_name: {column_names}}`` from ``loadPiSchema``
            or a test fixture.
        serverSchema: same shape from ``loadServerSchema`` or a fixture.
        serverNotNullNoDefault: optional mapping
            ``{table_name: {column_names}}`` for the TD-043 rule
            (columns where the server declares ``NOT NULL`` AND has no
            default).  When provided, ``serverRequiredColumnsMissingOnPi``
            and ``tablesWithRequiredColumnGap`` are computed; when
            ``None`` (default for back-compat with the US-249 callers),
            the rule is skipped and those keys are omitted from the
            output.
        syncedTables: optional set of table names registered to cross the
            sync wire, normally :func:`syncedPiTables`.  When provided,
            ``summary.syncedTablesInvisibleToPiLoader`` names every one
            of them that ``piSchema`` does not contain -- the TD-079
            blind-gate rule.  When ``None`` the rule is skipped and the
            key is omitted, matching how the TD-043 rule handles its own
            back-compat.

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

    # ---- TD-043 rule (US-256): NOT-NULL-without-default + Pi-omitted ----
    # The silent-sync-failure direction.  Only computed when caller
    # passes the per-column nullable/default state; back-compat with
    # the US-249 two-arg callers stays intact (the new keys are simply
    # omitted from the output).
    serverRequiredColumnsMissingOnPi: dict[str, list[str]] = {}
    tablesWithRequiredColumnGap: list[str] = []
    if serverNotNullNoDefault is not None:
        for tableName in sorted(sharedTables):
            requiredOnServer = serverNotNullNoDefault.get(tableName, set())
            if not requiredOnServer:
                continue
            piCols = piSchema[tableName]
            # Required-on-server columns that the Pi schema does NOT
            # have are the gate trip.  Filter mirror surface out -- the
            # server populates those itself at INSERT time, so a
            # NOT-NULL there is by design.
            missing = sorted(
                requiredOnServer - piCols - SERVER_MIRROR_COLUMNS,
            )
            if missing:
                serverRequiredColumnsMissingOnPi[tableName] = missing
                tablesWithRequiredColumnGap.append(tableName)

    summary: dict[str, object] = {
        'piTableCount': len(piTables),
        'serverTableCount': len(serverTables),
        'sharedTableCount': len(sharedTables),
        'tablesWithDrift': tablesWithDrift,
        # The TD-039 gate signal: tables where Pi has columns the
        # server lacks (excluding mirror surface).  Server-only
        # extras (analytics columns, by-design adornments) do NOT
        # appear here because they don't risk data loss.
        'tablesWithPiOnlyDrift': sorted(tablesWithPiOnlyDrift),
    }
    out: dict[str, object] = {
        'summary': summary,
        'tablesOnlyInPi': tablesOnlyInPi,
        'tablesOnlyInServer': tablesOnlyInServer,
        'sharedTableDrift': sharedTableDrift,
    }
    if serverNotNullNoDefault is not None:
        # The TD-043 gate signal: server requires a column that Pi
        # never populates -> every Pi INSERT fails with MariaDB 1364
        # / SQLite NOT-NULL-constraint until a v0006-class migration
        # makes the column nullable or supplies a default.
        summary['tablesWithRequiredColumnGap'] = sorted(
            tablesWithRequiredColumnGap,
        )
        out['serverRequiredColumnsMissingOnPi'] = (
            serverRequiredColumnsMissingOnPi
        )
    if syncedTables is not None:
        # The TD-079 gate signal: a table is registered for sync but the Pi
        # loader cannot see it, so BOTH rules above are silent about it and the
        # server's copy gets filed under tablesOnlyInServer -- the category that
        # means "tier-owned, nothing to check".  Reported as an EMPTY list when
        # clean rather than omitted, so "the rule ran and found nothing" is
        # distinguishable from "the rule did not run".
        summary['syncedTablesInvisibleToPiLoader'] = sorted(
            set(syncedTables) - piTables,
        )
    return out


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
    requiredGap = summary.get('tablesWithRequiredColumnGap', [])
    blindSpots = summary.get('syncedTablesInvisibleToPiLoader', [])
    lines = [
        '=== Pi <-> Server Schema Diff (US-249 / TD-039 + TD-043 + TD-079) ===',
        f'Pi tables:     {summary["piTableCount"]}',
        f'Server tables: {summary["serverTableCount"]}',
        f'Shared tables: {summary["sharedTableCount"]}',
        f'Drift:         {len(summary["tablesWithDrift"])} '
        f'({", ".join(summary["tablesWithDrift"]) or "none"})',
        f'TD-039 GATE:   {len(piOnly)} '
        f'({", ".join(piOnly) or "none"})  '
        '<- Pi added columns server lacks (silent data loss)',
        f'TD-043 GATE:   {len(requiredGap)} '
        f'({", ".join(requiredGap) or "none"})  '
        '<- server requires columns Pi omits (silent sync failure)',
        f'TD-079 GATE:   {len(blindSpots)} '
        f'({", ".join(blindSpots) or "none"})  '
        '<- synced tables loadPiSchema() cannot see (gate blind, not clean)',
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
    requiredGapDetail = diff.get('serverRequiredColumnsMissingOnPi') or {}
    if requiredGapDetail:
        lines.append('')
        lines.append('TD-043 detail (server NOT-NULL no-default + Pi omits):')
        for tableName in sorted(requiredGapDetail.keys()):
            cols = requiredGapDetail[tableName]
            lines.append(f'  {tableName}: {", ".join(cols)}')
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
    serverNotNullNoDefault = loadServerNotNullNoDefault()
    diff = computeDiff(
        piSchema, serverSchema, serverNotNullNoDefault, syncedPiTables(),
    )

    if args.verbose:
        sys.stderr.write(_renderHumanSummary(diff))

    sys.stdout.write(renderJson(diff))
    sys.stdout.write('\n')

    # Gate trips on ANY failure direction:
    #   * TD-039 -- Pi added a column server lacks (silent-data-loss).
    #   * TD-043 -- server requires a column Pi never populates
    #     (silent-sync-failure / 1364 storm).
    #   * TD-079 -- a synced table is invisible to loadPiSchema, so the two
    #     rules above examined nothing at all for it.  A gate that cannot SEE a
    #     table must not exit 0 over it: "no drift found" and "nowhere to look"
    #     are different answers and only one of them is clean.
    # Server-only nullable extras (analytics columns, PK rename
    # conventions) are reported but don't fail the gate -- they are
    # by-design and would create CI false-positive fatigue.
    summary = diff['summary']
    piOnlyTrip = bool(summary['tablesWithPiOnlyDrift'])
    requiredGapTrip = bool(summary.get('tablesWithRequiredColumnGap', []))
    blindSpotTrip = bool(summary.get('syncedTablesInvisibleToPiLoader', []))
    return 1 if (piOnlyTrip or requiredGapTrip or blindSpotTrip) else 0


if __name__ == '__main__':
    raise SystemExit(main())
