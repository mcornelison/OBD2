################################################################################
# File Name: audit_sync_contract_parity.py
# Purpose/Description: A-4 Pi<->server shared-contract PARITY GUARD (US-543).
#     The recurring divergence class -- Pi and server disagreeing about the
#     SHARED sync contract (enum vocabulary, synced column surface, PK-rename
#     mapping, timestamp format) -- has shipped green four times (BL-019 stale
#     data_source enum, BL-020 create_all FK drift, US-459 tuple-compare
#     theatre, BL-021 inline CHECK).  F-076 NORMALIZES the contract; this module
#     KEEPS it normalized.  Pattern of scripts/audit_address_mirrors.py: pure,
#     importable check functions over loaded schemas + a CLI, driven by a
#     standing pytest gate (tests/lint/test_pi_server_contract_parity.py).
#
#     LOAD-BEARING (US-459 lesson): the Pi side is loaded from the APPLIED
#     SQLite schema -- an ObdDatabase.initialize() run, i.e. every ensureX
#     helper, read back through PRAGMA table_info -- NOT from the DDL string
#     constants.  The server side is loaded from the APPLIED MariaDB schema
#     (information_schema, real-DB harness) when one is reachable; the
#     SQLAlchemy-model loader is a clearly-labelled WEAKER layer that cannot
#     see applied drift.  A Python-constant compare is what shipped BL-019.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-543) | Initial -- A-4 contract parity guard, 6 checks.
# ================================================================================
################################################################################

"""A-4 Pi <-> server shared-contract parity audit (US-543).

Six assertions, each a pure function over loaded schemas so the *mechanism*
(not a mock) is what the gate tests:

1. :func:`checkDataSourceEnumParity` / :func:`checkDataQualityEnumParity` --
   enum value-sets agree, set-equality both ways.
2. :func:`checkAppliedMatchesModel` -- the APPLIED server schema carries the
   columns the models declare (the BL-019 / US-459 drift class: the Python
   constant moved, the deployed DB did not).
3. :func:`checkSyncedColumnParity` -- every column the Pi actually PUTS ON THE
   WIRE exists on the server with a compatible type.
4. :func:`checkPkRenameParity` -- every non-``id`` Pi PK's rename to ``id`` is
   declared and consistent.
5. :func:`checkServerRequiredColumnsCoveredByPi` -- every server column that is
   NOT NULL with no default is provided by the Pi's ensure-schema surface.
6. :func:`checkTimestampParity` + :func:`checkCanonicalTimestampRoundTrip` --
   synced timestamp columns are ISO-8601 text on both tiers, and the exact
   string the Pi emits round-trips through the server's ingest coercion.

The table set (:func:`syncedTables`) is COMPLETE BY CONSTRUCTION: it is
``sync_log.PK_COLUMN`` (the delta wire path, named by the US-543 DoD) unioned
with ``snapshot_registry.SNAPSHOT_SYNC`` (the natural-key wire path added in
US-416).  Neither is a hand-maintained list, so a synced table added tomorrow
is covered the day it lands -- no second registry to forget.

The two wire paths and their tier-local exemptions
--------------------------------------------------

What crosses the wire is NOT "the Pi's columns".  ``sync_log.getDeltaRows`` /
``getSnapshotRows`` strip :data:`WIRE_STRIPPED_COLUMNS` (Pi-local bookkeeping),
and ``client._renamePkToId`` renames a non-``id`` PK.  The server then adds its
OWN mirror adornments (``source_id`` / ``source_device`` / ``synced_at`` /
``sync_batch_id``) plus server-computed analytics columns.  Parity is asserted
over the SYNCED SURFACE only -- assert more and the guard cries wolf on every
by-design tier-local column, which is how a guard gets disabled.

Direction matters, and the two directions catch different bugs:

* Pi -> server (check 3): the Pi sends a column the server lacks -> the
  SQLAlchemy bulk insert errors on an unmapped key; the whole push is rejected.
* server -> Pi (check 5): the server declares a column NOT NULL with no
  default and the Pi never sends it -> ``Field 'X' doesn't have a default
  value`` (MariaDB 1364).  This is the TD-043 class, re-asserted here against
  the APPLIED Pi schema rather than the DDL constants.

CLI::

    python scripts/audit_sync_contract_parity.py            # exit 1 on drift
    python scripts/audit_sync_contract_parity.py --verbose  # list every check
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    'ASSERTION_TITLES',
    'CROSS_TIER_RESOLVED_COLUMNS',
    'SERVER_MIRROR_COLUMNS',
    'TIMESTAMP_COLUMN_PATTERN',
    'WIRE_STRIPPED_COLUMNS',
    'ColumnSpec',
    'ParityViolation',
    'checkAppliedMatchesModel',
    'checkCanonicalTimestampRoundTrip',
    'checkContractParity',
    'checkCrossTierResolverDeclaration',
    'checkDataQualityEnumParity',
    'checkDataSourceEnumParity',
    'checkPkRenameParity',
    'checkServerRequiredColumnsCoveredByPi',
    'checkSyncedColumnParity',
    'checkTimestampParity',
    'loadPiAppliedSchema',
    'loadServerAppliedSchema',
    'loadServerModelSchema',
    'main',
    'piWireColumns',
    'syncedTables',
]

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]


# ================================================================================
# Import plumbing (Pi modules use bare ``pi.*`` imports -- src/ must be on path)
# ================================================================================


def _withRepoOnPath() -> list[str]:
    """Insert ``<root>`` and ``<root>/src`` on ``sys.path``; return what we added.

    Mirrors ``scripts/schema_diff.py``: Pi packages use bare ``pi.*`` imports
    (the python-OBD shadowing convention), so both entries are required whether
    this module is driven from the CLI or from pytest.
    """
    added: list[str] = []
    for path in (str(_PROJECT_ROOT), str(_PROJECT_ROOT / 'src')):
        if path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)
    return added


def _popRepoFromPath(added: Sequence[str]) -> None:
    """Remove only the ``sys.path`` entries :func:`_withRepoOnPath` added."""
    for path in added:
        try:
            sys.path.remove(path)
        except ValueError:  # pragma: no cover -- another caller already popped it
            pass


# ================================================================================
# Column model + type-kind normalisation
# ================================================================================


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column, normalised so SQLite and MariaDB/SQLAlchemy are comparable.

    Attributes:
        name: Column name (identical spelling on both tiers -- the sync applies
            no renaming beyond the PK, which is why a rename IS a violation).
        kind: Normalised type kind -- one of ``int`` / ``float`` / ``text`` /
            ``datetime`` / ``blob`` / ``any``.  Raw type spellings (``TEXT``
            vs ``VARCHAR(64)`` vs ``String``) are not comparable across tiers;
            kinds are.
        notNull: True iff the column rejects NULL.
        hasDefault: True iff a Python-side or DB-side default supplies a value
            when the writer omits the column.
    """

    name: str
    kind: str
    notNull: bool = False
    hasDefault: bool = False


# Type-kind lookup for SQLite declared types (PRAGMA table_info's ``type``) and
# SQLAlchemy type-class names.  Both tiers are folded into ONE vocabulary so a
# comparison is meaningful; an unrecognised spelling maps to 'any' (never a
# false violation from a type this table does not know).
_KIND_BY_TOKEN: dict[str, str] = {
    # --- SQLite declared types -------------------------------------------
    'INTEGER': 'int', 'INT': 'int', 'BIGINT': 'int', 'SMALLINT': 'int',
    'BOOLEAN': 'int', 'TINYINT': 'int',
    'REAL': 'float', 'FLOAT': 'float', 'DOUBLE': 'float', 'NUMERIC': 'float',
    'DECIMAL': 'float',
    'TEXT': 'text', 'VARCHAR': 'text', 'CHAR': 'text', 'CLOB': 'text',
    'JSON': 'text',
    'DATETIME': 'datetime', 'DATE': 'datetime', 'TIMESTAMP': 'datetime',
    'BLOB': 'blob',
    # --- SQLAlchemy type-class names (upper-cased) ------------------------
    'BIGINTEGER': 'int', 'SMALLINTEGER': 'int',
    'UNICODE': 'text', 'UNICODETEXT': 'text', 'STRING': 'text',
}

# Pairs that are DIFFERENT kinds but genuinely compatible on the wire.
# ISO-8601 timestamps are the whole reason this exists: the Pi declares
# ``DATETIME`` (SQLite type affinity, still storing canonical ISO TEXT) and the
# server declares either ``DateTime`` or ``String(40)`` depending on whether the
# column must survive NULL / non-parseable journal values (see StartupLog).
# Both are the same fact; check 6 is what actually guards the FORMAT.
_COMPATIBLE_KIND_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({'text', 'datetime'}),
})


def _kindOf(rawType: str) -> str:
    """Normalise a declared SQLite type or SQLAlchemy type name to a kind.

    Length/precision suffixes (``VARCHAR(64)``, ``DECIMAL(10,2)``) are dropped
    before lookup -- the width is a tier-local storage decision, not part of
    the shared contract.  An empty or unknown spelling yields ``'any'``, which
    compares compatible with everything (a guard must not invent violations
    out of a type it simply does not recognise).
    """
    token = re.split(r'[( ]', (rawType or '').strip().upper(), maxsplit=1)[0]
    if not token:
        return 'any'
    return _KIND_BY_TOKEN.get(token, 'any')


def _kindsCompatible(piKind: str, serverKind: str) -> bool:
    """Return True iff a Pi column of ``piKind`` can land in ``serverKind``."""
    if piKind == 'any' or serverKind == 'any' or piKind == serverKind:
        return True
    return frozenset({piKind, serverKind}) in _COMPATIBLE_KIND_PAIRS


# ================================================================================
# Contract constants (all DERIVED -- nothing here is a hand-kept second copy)
# ================================================================================

# Server-side adornments every synced-table model adds.  Imported-by-value from
# schema_diff so the two audits share ONE definition of "not a Pi concept".
try:  # pragma: no cover -- exercised by both import paths in the gate
    from scripts.schema_diff import SERVER_MIRROR_COLUMNS
except ImportError:  # pragma: no cover -- CLI run from inside scripts/
    from schema_diff import SERVER_MIRROR_COLUMNS  # type: ignore[no-redef]

# Pi-local columns that must never reach the server.  Sourced from the sync
# reader itself (``sync_log._WIRE_STRIPPED_COLUMNS``) rather than restated:
# if the strip list changes, this guard changes WITH it, and check 1's
# data_quality branch flips from "not a shared contract" to "must be equal".
WIRE_STRIPPED_COLUMNS: frozenset[str]

# The THIRD wire transform, and the one that is NOT derivable from a registry.
#
# Most synced tables ride the generic path in ``api/sync.runSyncUpsert``, which
# binds every payload key straight onto the model -- so an unmapped key really
# does error the whole batch (what check 3 asserts).  ``dtc_freeze_frame`` does
# NOT: US-369 gave it a bespoke resolver (``api/sync._syncDtcFreezeFrameRows``)
# that builds an EXPLICIT column list and performs cross-tier FK resolution, so
# a Pi column can legitimately be renamed (``vehicle_info_vin`` is resolved to
# the server's ``vehicle_info_id``) or deliberately dropped (``data_source``:
# the freeze frame's origin is carried by its parent dtc_log row).
#
# This map is a DECLARATION, not a derivation -- the resolver's key set lives in
# imperative code with no registry to read.  It is therefore self-policed from
# both sides by the gate: every target column named here must EXIST on the
# server, and every column declared dropped must still have NO server
# counterpart.  Adding a resolver mapping without updating this map is the one
# drift this guard cannot discover on its own; that residual is called out in
# the module docstring on purpose rather than left implicit.
#
# ``None`` as a value means "consumed by the resolver, intentionally not stored".
CROSS_TIER_RESOLVED_COLUMNS: dict[str, dict[str, str | None]] = {
    'dtc_freeze_frame': {
        # Resolved server-side to the vehicle_info row live at capture time.
        'vehicle_info_vin': 'vehicle_info_id',
        # Origin lives on the parent dtc_log row; the server model has no
        # data_source column for freeze frames by design.
        'data_source': None,
    },
}

# A column carrying a point in time.  Suffix-based because the naming is
# consistent across both tiers (``*_at`` / ``*_ts`` / ``*_time`` / ``timestamp``)
# and a rename would itself be a check-3 violation.
TIMESTAMP_COLUMN_PATTERN: str = r'(^|_)(timestamp|ts|at|time)$'

ASSERTION_TITLES: dict[str, str] = {
    'A1': 'enum parity (data_source / data_quality, set-equality both ways)',
    'A2': 'applied schema matches the declared model (NOT a Python-tuple compare)',
    'A3': 'synced-table shared-column parity (Pi wire surface exists on server)',
    'A4': 'PK-rename mapping parity (Pi PK -> server id declared + consistent)',
    'A5': 'Pi ensure-schema coverage (server-required columns exist on the Pi)',
    'A6': 'timestamp/format parity (canonical ISO-8601 UTC on both tiers)',
}


@dataclass(frozen=True, slots=True)
class ParityViolation:
    """One contract divergence.

    Attributes:
        assertionId: ``A1``..``A6`` -- which of the six assertions tripped.
        table: Synced table the violation belongs to (``''`` for global facts
            like the enum vocabularies, which are not per-table).
        message: Operator-facing description naming BOTH tiers' values, so the
            failure says what to change rather than only that something differs.
    """

    assertionId: str
    table: str
    message: str

    def render(self) -> str:
        """Return a one-line human-readable form for CLI / pytest output."""
        where = f' [{self.table}]' if self.table else ''
        return f'{self.assertionId}{where}: {self.message}'


def _loadWireStrippedColumns() -> frozenset[str]:
    """Read the wire-strip set from the Pi sync reader (define-once)."""
    added = _withRepoOnPath()
    try:
        from src.pi.data.sync_log import _WIRE_STRIPPED_COLUMNS

        return frozenset(_WIRE_STRIPPED_COLUMNS)
    finally:
        _popRepoFromPath(added)


WIRE_STRIPPED_COLUMNS = _loadWireStrippedColumns()


def syncedTables() -> dict[str, str]:
    """Return ``{table: wirePath}`` for every table that crosses the wire.

    ``wirePath`` is ``'delta'`` (integer-PK cursor, ``sync_log.PK_COLUMN``) or
    ``'snapshot'`` (natural-key cursor, ``snapshot_registry.SNAPSHOT_SYNC``).

    COMPLETE BY CONSTRUCTION -- both registries are the ones the sync client
    itself reads, computed on every call rather than snapshotted, so a table
    registered for sync tomorrow is guarded the same day.  The US-543 DoD names
    PK_COLUMN; SNAPSHOT_SYNC is unioned in because US-416 added a SECOND wire
    path and a guard that saw only one of them would report parity over a table
    set that is not the set actually being synced.
    """
    added = _withRepoOnPath()
    try:
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC
        from src.pi.data.sync_log import PK_COLUMN
    finally:
        _popRepoFromPath(added)

    tables: dict[str, str] = dict.fromkeys(PK_COLUMN, 'delta')
    for tableName in SNAPSHOT_SYNC:
        tables[tableName] = 'snapshot'
    return tables


def piPrimaryKeys() -> dict[str, str]:
    """Return ``{table: pkColumn}`` for the delta-synced tables (PK_COLUMN)."""
    added = _withRepoOnPath()
    try:
        from src.pi.data.sync_log import PK_COLUMN

        return dict(PK_COLUMN)
    finally:
        _popRepoFromPath(added)


# ================================================================================
# Loaders -- APPLIED schema on both tiers (US-459: never the Python constants)
# ================================================================================


def loadPiAppliedSchema(dbPath: str | None = None) -> dict[str, dict[str, ColumnSpec]]:
    """Load the APPLIED Pi SQLite schema, after every ensure-schema helper runs.

    Runs the REAL boot path -- ``ObdDatabase.initialize()`` -- against a
    throwaway SQLite file, then reads the result back with ``PRAGMA
    table_info``.  This is the load-bearing difference from
    ``scripts/schema_diff.loadPiSchema``, which executes the DDL string
    constants: columns added by an ``ensureXSchema`` ALTER (US-419
    ``data_quality``, US-252 ``vcell``, the US-289 SOC columns) exist ONLY
    after initialize() and are invisible to a constants-only load.  On the Pi
    the ensureX helpers ARE the migration system, so they are what must be
    audited (US-543 assertion 5).

    Args:
        dbPath: Optional path for the throwaway DB.  Defaults to a fresh temp
            file, which is the normal case; tests pass a path to inspect it.

    Returns:
        ``{table: {column: ColumnSpec}}`` for every table the Pi boot creates.
        SQLite internal tables (``sqlite_*``) are excluded.
    """
    added = _withRepoOnPath()
    try:
        from src.pi.obdii.database import ObdDatabase
    finally:
        _popRepoFromPath(added)

    tempDir: tempfile.TemporaryDirectory[str] | None = None
    if dbPath is None:
        tempDir = tempfile.TemporaryDirectory(prefix='us543-pi-applied-')
        dbPath = str(Path(tempDir.name) / 'obd.db')

    try:
        ObdDatabase(dbPath).initialize()
        conn = sqlite3.connect(dbPath)
        try:
            tableNames = [
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                )
            ]
            schema: dict[str, dict[str, ColumnSpec]] = {}
            for tableName in tableNames:
                columns: dict[str, ColumnSpec] = {}
                for row in conn.execute(f'PRAGMA table_info({tableName})'):
                    _cid, name, declType, notNull, defaultValue, isPk = row
                    columns[name] = ColumnSpec(
                        name=name,
                        kind=_kindOf(declType),
                        notNull=bool(notNull),
                        # An INTEGER PRIMARY KEY is the sqlite rowid alias: the
                        # engine supplies it, so it is "defaulted" for the
                        # purposes of a missing-value audit.
                        hasDefault=defaultValue is not None or bool(isPk),
                    )
                schema[tableName] = columns
            return schema
        finally:
            conn.close()
    finally:
        if tempDir is not None:
            tempDir.cleanup()


def loadServerModelSchema() -> dict[str, dict[str, ColumnSpec]]:
    """Load the server schema from the SQLAlchemy models (the WEAKER layer).

    This is what the models DECLARE, not what the deployed database HAS.  It is
    exposed because it is the only server view available on a bench with no
    MariaDB, and because check 2 needs it as one side of the applied-vs-declared
    comparison -- but a parity run over models alone CANNOT see the BL-019 drift
    class (Python widened, live DB not ALTERed).  Callers must label it as such;
    :func:`checkAppliedMatchesModel` is the check that closes the gap.
    """
    added = _withRepoOnPath()
    try:
        from src.server.db.models import Base
    finally:
        _popRepoFromPath(added)

    schema: dict[str, dict[str, ColumnSpec]] = {}
    for tableName, table in Base.metadata.tables.items():
        columns: dict[str, ColumnSpec] = {}
        for col in table.columns:
            autoPk = bool(col.primary_key) and col.autoincrement is not False
            columns[col.name] = ColumnSpec(
                name=col.name,
                kind=_kindOf(type(col.type).__name__),
                notNull=col.nullable is False,
                hasDefault=(
                    col.default is not None
                    or col.server_default is not None
                    or autoPk
                ),
            )
        schema[tableName] = columns
    return schema


_APPLIED_COLUMNS_SQL: str = (
    'SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, '
    'COLUMN_DEFAULT, EXTRA '
    'FROM information_schema.COLUMNS '
    "WHERE TABLE_SCHEMA = '{dbName}' "
    'ORDER BY TABLE_NAME, ORDINAL_POSITION;'
)


def appliedColumnsSql(dbName: str) -> str:
    """Return the ``information_schema`` query for the APPLIED server schema."""
    return _APPLIED_COLUMNS_SQL.format(dbName=dbName)


def loadServerAppliedSchema(
    runSql: Any,
    dbName: str,
) -> dict[str, dict[str, ColumnSpec]]:
    """Load the APPLIED server schema from a real MariaDB's information_schema.

    Args:
        runSql: Callable taking the SQL string and returning ``mysql -B -N``
            shaped stdout (tab-delimited, header-less, SQL NULL rendered as the
            literal ``NULL``).  The US-464 harness's ``MariaDbCommandRunner``
            produces exactly this shape, so the gate can drive a real
            testcontainer without a second transport.
        dbName: Schema to introspect (must be the connected database).

    Returns:
        ``{table: {column: ColumnSpec}}`` as the DEPLOYED database actually
        carries it -- the only view that can catch a migration that never ran.
    """
    stdout = runSql(appliedColumnsSql(dbName))
    schema: dict[str, dict[str, ColumnSpec]] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 6:
            continue
        tableName, columnName, dataType, isNullable, columnDefault, extra = parts[:6]
        schema.setdefault(tableName, {})[columnName] = ColumnSpec(
            name=columnName,
            kind=_kindOf(dataType),
            notNull=isNullable.upper() == 'NO',
            hasDefault=(
                columnDefault != 'NULL' or 'auto_increment' in extra.lower()
            ),
        )
    return schema


# ================================================================================
# The wire surface -- what the Pi actually sends
# ================================================================================


def piWireColumns(
    tableName: str,
    piColumns: dict[str, ColumnSpec],
    pkColumn: str | None,
) -> dict[str, ColumnSpec]:
    """Return the columns the Pi actually PUTS ON THE WIRE for ``tableName``.

    Applies the two transforms the sync reader/client apply, in their order:

    1. strip :data:`WIRE_STRIPPED_COLUMNS`
       (``sync_log.getDeltaRows`` / ``getSnapshotRows``), and
    2. rename a non-``id`` ``pkColumn`` to ``id`` (``client._renamePkToId``).

    The result is the exact key-set the server's bulk upsert binds, which is
    why parity is asserted over THIS and not over the Pi's raw column list.

    Args:
        tableName: Synced table (used only in the returned specs' provenance).
        piColumns: Applied Pi columns for the table.
        pkColumn: The table's Pi PK, or ``None`` for snapshot-path tables
            (which are pushed verbatim -- no PK rename).
    """
    wire: dict[str, ColumnSpec] = {
        name: spec for name, spec in piColumns.items()
        if name not in WIRE_STRIPPED_COLUMNS
    }
    if pkColumn and pkColumn != 'id' and pkColumn in wire:
        spec = wire.pop(pkColumn)
        wire['id'] = ColumnSpec(
            name='id',
            kind=spec.kind,
            notNull=spec.notNull,
            hasDefault=spec.hasDefault,
        )
    _ = tableName  # provenance only; kept in the signature for call-site clarity
    return wire


def _isTimestampColumn(name: str) -> bool:
    """Return True iff ``name`` looks like a point-in-time column."""
    return re.search(TIMESTAMP_COLUMN_PATTERN, name) is not None


# ================================================================================
# Assertion 1 -- enum parity
# ================================================================================


def checkDataSourceEnumParity(
    piValues: Sequence[str],
    serverValues: Sequence[str],
) -> list[ParityViolation]:
    """A1: the ``data_source`` value-sets must be set-equal BOTH ways.

    This is the A-10 saga in one assertion: US-424 added ``'foreign'`` to the
    Pi tuple; the server side had to gain it too or every foreign-tagged row
    would be an unknown value on ingest.  Both directions are reported
    separately because they fail for opposite reasons -- a Pi-only value is a
    row the server will reject, a server-only value is a value the Pi can never
    produce (dead vocabulary, usually a half-finished widen).
    """
    piSet, serverSet = set(piValues), set(serverValues)
    violations: list[ParityViolation] = []
    piOnly = sorted(piSet - serverSet)
    serverOnly = sorted(serverSet - piSet)
    if piOnly:
        violations.append(ParityViolation(
            'A1', '',
            f'data_source values present on the Pi but NOT on the server: '
            f'{piOnly}. A row tagged with one of these syncs up into a value '
            f'the server does not know (the BL-019 / drive-33 landmine).',
        ))
    if serverOnly:
        violations.append(ParityViolation(
            'A1', '',
            f'data_source values present on the server but NOT on the Pi: '
            f'{serverOnly}. The Pi can never emit these -- either the widen is '
            f'half-finished or the value is dead vocabulary.',
        ))
    return violations


def checkDataQualityEnumParity(
    piValues: Sequence[str],
    serverValues: Sequence[str],
    wireStripped: frozenset[str] = WIRE_STRIPPED_COLUMNS,
) -> list[ParityViolation]:
    """A1: ``data_quality`` parity, CONDITIONAL on it actually being shared.

    Today ``data_quality`` is NOT a shared contract: the Pi's values are local
    honest-instrument flags (``full`` / ``clock_unsynced``, US-419 / F-080) and
    ``sync_log._WIRE_STRIPPED_COLUMNS`` strips the column from every payload,
    because the server computes its OWN data_quality at ingest (Pi = emitter,
    server = authority -- B-104).  The server vocabulary is a different fact
    entirely (``attribution_anomaly`` / ``foreign_vehicle`` /
    ``unmappable_legacy``), so demanding set-equality NOW would assert a
    falsehood and force one tier to adopt the other's vocabulary.

    So the guard asserts the contract that actually exists, and keeps teeth:
    while the column is wire-stripped, parity is NOT required and the STRIP is
    what is asserted.  The day someone removes ``data_quality`` from the strip
    set, this check flips to full set-equality both ways and fails until the
    vocabularies are unified -- which is precisely the A-10 failure mode
    (a Pi-only value arriving at a server that does not know it).

    Args:
        piValues: Pi-side data_quality vocabulary.
        serverValues: Server-side data_quality vocabulary (union across the
            per-table enums -- the server's ingest sees them as one namespace).
        wireStripped: The live strip set; injected so the gate can drive the
            not-stripped branch without mutating the sync module.
    """
    if 'data_quality' in wireStripped:
        return []
    piSet, serverSet = set(piValues), set(serverValues)
    if piSet == serverSet:
        return []
    return [ParityViolation(
        'A1', '',
        'data_quality now crosses the sync wire (it was removed from '
        'sync_log._WIRE_STRIPPED_COLUMNS) but the vocabularies differ: '
        f'Pi-only={sorted(piSet - serverSet)}, '
        f'server-only={sorted(serverSet - piSet)}. A synced column REQUIRES '
        'set-equality both ways -- unify the vocabulary or restore the strip.',
    )]


# ================================================================================
# Assertion 2 -- applied vs declared
# ================================================================================


def checkAppliedMatchesModel(
    appliedSchema: dict[str, dict[str, ColumnSpec]],
    modelSchema: dict[str, dict[str, ColumnSpec]],
    tables: Sequence[str],
) -> list[ParityViolation]:
    """A2: the APPLIED server schema carries what the models declare.

    The BL-019 / US-459 drift class: a Python constant or model column moved
    and the deployed database never did.  A tuple-vs-tuple compare ships GREEN
    over exactly this, which is why the gate feeds ``appliedSchema`` from a
    real MariaDB's ``information_schema`` and not from ``create_all``.

    A missing TABLE is reported as loudly as a missing column -- an absent
    table on the applied side means every push to it fails, and an empty
    per-table column dict must never read as "no drift".
    """
    violations: list[ParityViolation] = []
    for tableName in sorted(tables):
        declared = modelSchema.get(tableName)
        if declared is None:
            continue
        applied = appliedSchema.get(tableName)
        if not applied:
            violations.append(ParityViolation(
                'A2', tableName,
                'the models declare this synced table but the APPLIED server '
                'schema has no such table -- a migration never ran.',
            ))
            continue
        missing = sorted(set(declared) - set(applied))
        if missing:
            violations.append(ParityViolation(
                'A2', tableName,
                f'columns declared by the server models but ABSENT from the '
                f'applied schema: {missing}. The Python side moved and the '
                f'deployed DB did not (BL-019); a migration is owed.',
            ))
    return violations


# ================================================================================
# Assertion 3 -- synced-table shared-column parity
# ================================================================================


def checkSyncedColumnParity(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    tables: dict[str, str],
    primaryKeys: dict[str, str],
) -> list[ParityViolation]:
    """A3: every column the Pi puts on the wire exists on the server, compatibly.

    Asserts the SYNCED surface only.  Server mirror adornments
    (:data:`SERVER_MIRROR_COLUMNS`) and server-computed analytics columns are
    exempt by construction -- they are checked from the other direction by
    :func:`checkServerRequiredColumnsCoveredByPi`, which is the direction that
    can actually break an insert.

    A missing Pi table is a violation (a registered synced table the Pi boot
    never creates cannot be pushed); a missing SERVER table is a violation for
    the same reason in the other direction.
    """
    violations: list[ParityViolation] = []
    for tableName in sorted(tables):
        piColumns = piSchema.get(tableName)
        if not piColumns:
            violations.append(ParityViolation(
                'A3', tableName,
                'registered for sync but the APPLIED Pi schema has no such '
                'table -- the ensure-schema path never creates it.',
            ))
            continue
        serverColumns = serverSchema.get(tableName)
        if not serverColumns:
            violations.append(ParityViolation(
                'A3', tableName,
                'registered for sync but the server has no such table -- every '
                'push to it is rejected.',
            ))
            continue

        resolved = CROSS_TIER_RESOLVED_COLUMNS.get(tableName, {})
        wire = piWireColumns(tableName, piColumns, primaryKeys.get(tableName))
        for name, spec in sorted(wire.items()):
            # ``id`` is bound to source_id by the server upsert, never to a
            # server column of that name (see api/sync.py) -- check 4 owns it.
            if name == 'id':
                continue
            if name in resolved:
                # Handled by the table's cross-tier resolver, not the generic
                # bind; the DECLARATION is audited by
                # :func:`checkCrossTierResolverDeclaration`.
                continue
            serverSpec = serverColumns.get(name)
            if serverSpec is None:
                violations.append(ParityViolation(
                    'A3', tableName,
                    f'the Pi puts {name!r} on the wire but the server has no '
                    f'such column -- the bulk insert errors on the unmapped '
                    f'key and the WHOLE batch is rejected.',
                ))
                continue
            if not _kindsCompatible(spec.kind, serverSpec.kind):
                violations.append(ParityViolation(
                    'A3', tableName,
                    f'column {name!r} type-kind mismatch: Pi={spec.kind}, '
                    f'server={serverSpec.kind}. The sync applies no value '
                    f'coercion beyond the PK rename, so the value lands '
                    f'mistyped or is silently truncated.',
                ))
    return violations


def checkCrossTierResolverDeclaration(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    resolved: dict[str, dict[str, str | None]] = CROSS_TIER_RESOLVED_COLUMNS,
) -> list[ParityViolation]:
    """A3: the cross-tier resolver declaration is self-consistent.

    :data:`CROSS_TIER_RESOLVED_COLUMNS` is the one part of the wire contract
    that cannot be read from a registry, so it is policed from both sides
    rather than trusted:

    * the Pi column being resolved must still EXIST on the Pi (otherwise the
      exemption is stale and is silently suppressing a real check-3 finding);
    * a declared TARGET column must exist on the server (a resolver writing a
      column the server does not have fails on every push);
    * a column declared DROPPED must still have no server counterpart -- if the
      server gained one, the drop is no longer intentional-by-design and the
      Pi's value is being thrown away while a column sits there empty.
    """
    violations: list[ParityViolation] = []
    for tableName in sorted(resolved):
        piColumns = piSchema.get(tableName, {})
        serverColumns = serverSchema.get(tableName, {})
        for piColumn, target in sorted(
            resolved[tableName].items(), key=lambda item: item[0],
        ):
            if piColumn not in piColumns:
                violations.append(ParityViolation(
                    'A3', tableName,
                    f'cross-tier resolver declares Pi column {piColumn!r} but '
                    f'the applied Pi schema no longer has it -- the exemption '
                    f'is stale and may be masking a real parity gap.',
                ))
            if target is None:
                if piColumn in serverColumns:
                    violations.append(ParityViolation(
                        'A3', tableName,
                        f'{piColumn!r} is declared intentionally dropped by the '
                        f'cross-tier resolver, but the server now HAS a column '
                        f'of that name -- the Pi value is being discarded into '
                        f'an empty column.',
                    ))
            elif target not in serverColumns:
                violations.append(ParityViolation(
                    'A3', tableName,
                    f'cross-tier resolver maps {piColumn!r} -> {target!r} but '
                    f'the server has no {target!r} column.',
                ))
    return violations


# ================================================================================
# Assertion 4 -- PK-rename mapping parity
# ================================================================================


def checkPkRenameParity(
    primaryKeys: dict[str, str],
    declaredRenames: dict[str, str],
    serverSchema: dict[str, dict[str, ColumnSpec]],
) -> list[ParityViolation]:
    """A4: every non-``id`` Pi PK's rename to ``id`` is declared + consistent.

    ``client._renamePkToId`` DERIVES the rename from ``sync_log.PK_COLUMN``
    (``pkColumn != 'id'`` -> rename), so PK_COLUMN is the authority.
    ``schema_diff.PI_PK_RENAMED_TO_ID`` is a second, hand-kept declaration of
    the same fact used to suppress by-design drift; the two must agree in BOTH
    directions.  A new synced table with a non-``id`` PK added to PK_COLUMN and
    not to the declaration is exactly the gap the AC names.

    Also asserts the destination exists: a renamed payload binds ``id`` ->
    ``source_id``, so the server table must carry ``source_id``.
    """
    violations: list[ParityViolation] = []
    derived = {
        table: pk for table, pk in primaryKeys.items() if pk != 'id'
    }

    for table in sorted(set(derived) - set(declaredRenames)):
        violations.append(ParityViolation(
            'A4', table,
            f'Pi PK is {derived[table]!r} (renamed to \'id\' on the wire by '
            f'client._renamePkToId) but the rename is NOT declared in '
            f'schema_diff.PI_PK_RENAMED_TO_ID -- a synced table was added '
            f'without its mapping.',
        ))
    for table in sorted(set(declaredRenames) - set(derived)):
        violations.append(ParityViolation(
            'A4', table,
            f'a PK rename is declared ({declaredRenames[table]!r} -> \'id\') '
            f'but sync_log.PK_COLUMN does not register this table with a '
            f'non-\'id\' PK -- the declaration is stale.',
        ))
    for table in sorted(set(derived) & set(declaredRenames)):
        if derived[table] != declaredRenames[table]:
            violations.append(ParityViolation(
                'A4', table,
                f'PK rename disagrees: sync_log.PK_COLUMN says '
                f'{derived[table]!r}, schema_diff.PI_PK_RENAMED_TO_ID says '
                f'{declaredRenames[table]!r}.',
            ))

    for table in sorted(derived):
        serverColumns = serverSchema.get(table)
        if serverColumns is not None and 'source_id' not in serverColumns:
            violations.append(ParityViolation(
                'A4', table,
                'the renamed PK binds \'id\' -> \'source_id\' on ingest but '
                'the server table has no source_id column.',
            ))
    return violations


# ================================================================================
# Assertion 5 -- Pi ensure-schema coverage
# ================================================================================


def checkServerRequiredColumnsCoveredByPi(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    tables: dict[str, str],
    primaryKeys: dict[str, str],
) -> list[ParityViolation]:
    """A5: every server column the Pi MUST supply exists on the Pi.

    The shared surface, defined from the direction that can actually break an
    insert (TD-043): a server column that is ``NOT NULL`` with no default and
    is not a mirror adornment can only be satisfied by a value the Pi sends.
    If the Pi's ensure-schema path has no such column, every push to that table
    fails with ``Field 'X' doesn't have a default value`` (MariaDB 1364).

    On the Pi, ``ensureXSchema`` IS the migration system -- there is no
    ``schema_migrations`` table -- which is why this is asserted against the
    APPLIED Pi schema (post-``initialize()``), not the DDL constants: a column
    added by an ALTER helper is invisible to a constants-only read.
    """
    violations: list[ParityViolation] = []
    for tableName in sorted(tables):
        serverColumns = serverSchema.get(tableName)
        piColumns = piSchema.get(tableName)
        if not serverColumns or not piColumns:
            # Missing-table cases are reported once, by check 3.
            continue
        wire = piWireColumns(tableName, piColumns, primaryKeys.get(tableName))
        for name, spec in sorted(serverColumns.items()):
            if name in SERVER_MIRROR_COLUMNS or name == 'id':
                continue
            if not spec.notNull or spec.hasDefault:
                continue
            if name not in wire:
                violations.append(ParityViolation(
                    'A5', tableName,
                    f'server column {name!r} is NOT NULL with no default, so '
                    f'the Pi must supply it -- but no Pi ensureXSchema/DDL '
                    f'column of that name reaches the wire. Every push to this '
                    f'table fails (MariaDB 1364 / TD-043 class).',
                ))
    return violations


# ================================================================================
# Assertion 6 -- timestamp / format parity
# ================================================================================


def checkTimestampParity(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    tables: dict[str, str],
    primaryKeys: dict[str, str],
) -> list[ParityViolation]:
    """A6: synced timestamp columns are ISO-8601-shaped on BOTH tiers.

    The sync applies no coercion beyond the PK rename, so a tier storing epoch
    numbers where the other stores ISO-8601 text corrupts silently -- the value
    lands, no error is raised, and the timestamp is wrong by 56 years.  The
    kind check is therefore the guard: a timestamp column must be ``text`` or
    ``datetime`` on both tiers, never ``int`` / ``float``.

    The FORMAT itself (canonical ``%Y-%m-%dT%H:%M:%SZ``, TD-027 / US-202) is
    asserted end-to-end by :func:`checkCanonicalTimestampRoundTrip`.
    """
    violations: list[ParityViolation] = []
    isoKinds = {'text', 'datetime', 'any'}
    for tableName in sorted(tables):
        piColumns = piSchema.get(tableName)
        serverColumns = serverSchema.get(tableName)
        if not piColumns or not serverColumns:
            continue
        wire = piWireColumns(tableName, piColumns, primaryKeys.get(tableName))
        for name, spec in sorted(wire.items()):
            if name == 'id' or not _isTimestampColumn(name):
                continue
            serverSpec = serverColumns.get(name)
            if serverSpec is None:
                continue  # reported by check 3
            if spec.kind not in isoKinds:
                violations.append(ParityViolation(
                    'A6', tableName,
                    f'timestamp column {name!r} is {spec.kind} on the Pi -- '
                    f'canonical ISO-8601 UTC text is the contract (TD-027); a '
                    f'numeric epoch corrupts silently on ingest.',
                ))
            if serverSpec.kind not in isoKinds:
                violations.append(ParityViolation(
                    'A6', tableName,
                    f'timestamp column {name!r} is {serverSpec.kind} on the '
                    f'server -- canonical ISO-8601 UTC is the contract '
                    f'(TD-027); the sync does no format coercion.',
                ))
    return violations


def checkCanonicalTimestampRoundTrip() -> list[ParityViolation]:
    """A6: the exact string the Pi emits parses on the server, end to end.

    Not a declaration -- a round trip.  Takes a real ``utcIsoNow()`` value (the
    canonical writer every capture-table timestamp routes through since
    TD-027 / US-202) and pushes it through the server's own ingest coercion
    ``api.sync._parseDateTime``.  A non-``datetime`` result means the server
    silently PASSES THE STRING THROUGH into a DateTime column -- the exact
    shape of a silent format divergence, and the reason a trailing-``Z``
    change or an ``fromisoformat`` behaviour change must fail here rather than
    on the next drive's upload.
    """
    added = _withRepoOnPath()
    try:
        from datetime import datetime

        from src.common.time.helper import utcIsoNow
        from src.server.api.sync import _parseDateTime
    finally:
        _popRepoFromPath(added)

    emitted = utcIsoNow()
    parsed = _parseDateTime(emitted)
    if not isinstance(parsed, datetime):
        return [ParityViolation(
            'A6', '',
            f'the canonical Pi timestamp {emitted!r} does NOT parse through '
            f'the server ingest coercion (_parseDateTime returned '
            f'{type(parsed).__name__}); the raw string would be written into a '
            f'DateTime column with no error raised.',
        )]
    return []


# ================================================================================
# Aggregator + CLI
# ================================================================================


def checkContractParity(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    *,
    tables: dict[str, str] | None = None,
    primaryKeys: dict[str, str] | None = None,
    appliedServerSchema: dict[str, dict[str, ColumnSpec]] | None = None,
) -> list[ParityViolation]:
    """Run every hermetic assertion and return all violations found.

    Assertion 2 runs only when ``appliedServerSchema`` is supplied -- there is
    no substitute for a real database, and a SQLite/``create_all`` stand-in is
    the trap this guard exists to close, so its absence is a SKIP the caller
    must surface, never a silent pass.

    Args:
        piSchema: APPLIED Pi schema (:func:`loadPiAppliedSchema`).
        serverSchema: Server schema -- applied when available, models otherwise.
        tables: Synced-table set; defaults to :func:`syncedTables`.
        primaryKeys: Pi PK registry; defaults to :func:`piPrimaryKeys`.
        appliedServerSchema: APPLIED server schema for assertion 2.
    """
    tables = syncedTables() if tables is None else tables
    primaryKeys = piPrimaryKeys() if primaryKeys is None else primaryKeys

    added = _withRepoOnPath()
    try:
        from scripts.schema_diff import PI_PK_RENAMED_TO_ID
        from src.pi.diagnostics.clock_sync import (
            CLOCK_QUALITY_CLOCK_UNSYNCED,
            CLOCK_QUALITY_FULL,
        )
        from src.pi.obdii.data_source import (
            DATA_SOURCE_VALUES as PI_DATA_SOURCE_VALUES,
        )
        from src.server.db.models import (
            DATA_SOURCE_VALUES as SERVER_DATA_SOURCE_VALUES,
        )
        from src.server.db.models import (
            DRIVE_STATISTICS_DATA_QUALITY_VALUES,
            DRIVE_SUMMARY_DATA_QUALITY_VALUES,
            DRIVES_DATA_QUALITY_VALUES,
        )
    finally:
        _popRepoFromPath(added)

    serverDataQuality = (
        *DRIVES_DATA_QUALITY_VALUES,
        *DRIVE_SUMMARY_DATA_QUALITY_VALUES,
        *DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    )
    piDataQuality = (CLOCK_QUALITY_FULL, CLOCK_QUALITY_CLOCK_UNSYNCED)

    violations: list[ParityViolation] = []
    violations += checkDataSourceEnumParity(
        PI_DATA_SOURCE_VALUES, SERVER_DATA_SOURCE_VALUES,
    )
    violations += checkDataQualityEnumParity(piDataQuality, serverDataQuality)
    if appliedServerSchema is not None:
        violations += checkAppliedMatchesModel(
            appliedServerSchema, serverSchema, list(tables),
        )
    violations += checkSyncedColumnParity(
        piSchema, serverSchema, tables, primaryKeys,
    )
    violations += checkCrossTierResolverDeclaration(piSchema, serverSchema)
    violations += checkPkRenameParity(
        primaryKeys, PI_PK_RENAMED_TO_ID, serverSchema,
    )
    violations += checkServerRequiredColumnsCoveredByPi(
        piSchema, serverSchema, tables, primaryKeys,
    )
    violations += checkTimestampParity(
        piSchema, serverSchema, tables, primaryKeys,
    )
    violations += checkCanonicalTimestampRoundTrip()
    return violations


def _buildArgParser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            'A-4 Pi<->server shared-contract parity audit (US-543). '
            'Exit 0 = contracts agree; exit 1 = at least one divergence.'
        ),
    )
    parser.add_argument(
        '--verbose', action='store_true',
        help='list every assertion and the synced-table set that was checked',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns:
        ``0`` when every contract agrees, ``1`` when any violation is found.
    """
    args = _buildArgParser().parse_args(argv)
    tables = syncedTables()
    piSchema = loadPiAppliedSchema()
    serverSchema = loadServerModelSchema()
    violations = checkContractParity(
        piSchema, serverSchema, tables=tables, primaryKeys=piPrimaryKeys(),
    )

    if args.verbose:
        print('A-4 contract parity audit (US-543)')
        for assertionId, title in sorted(ASSERTION_TITLES.items()):
            print(f'  {assertionId}: {title}')
        print(f'  synced tables ({len(tables)}): {sorted(tables)}')
        print(
            '  NOTE: assertion A2 (applied server schema) requires a real '
            'MariaDB and is NOT run by this CLI -- see '
            'tests/lint/test_pi_server_contract_parity.py.',
        )

    if not violations:
        print('OK: Pi <-> server shared contracts agree.')
        return 0
    print(f'DRIFT: {len(violations)} contract violation(s):')
    for violation in violations:
        print(f'  - {violation.render()}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
