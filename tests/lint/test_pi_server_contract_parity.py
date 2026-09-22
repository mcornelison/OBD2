################################################################################
# File Name: test_pi_server_contract_parity.py
# Purpose/Description: US-543 (Atlas A-4) -- the STANDING gate that fails when
#     Pi (obd.db) and server (obd2db) drift on a shared sync contract.  Six
#     assertions over the APPLIED schema on both tiers.  Pattern of
#     tests/lint/test_address_mirror_consistency.py: pure check functions in
#     scripts/audit_sync_contract_parity.py, driven here.
#
#     Every assertion is proven RED by an injected mismatch, not merely run
#     green over the current repo -- a parity guard that has never been seen to
#     fail is indistinguishable from one that cannot fail (US-459's tuple
#     compare passed for weeks over a live DB that rejected every foreign row).
#     Those injections are DETECTOR-side (a synthetic schema handed to a check).
#     US-722 adds the SUBJECT-side control: a column planted by ALTER into the
#     real applied Pi DB, in every registered table, must reach the gate.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-10    | Rex (US-543) | Initial -- A-4 standing contract-parity gate.
# 2026-09-09    | Rex (US-607) | TD-079 closed the dtc_freeze_frame blindness,
#               |              | so TestPiLoaderReadsTheAppliedSchema's
#               |              | assertion that the DDL loader MISSES it became
#               |              | false.  Rewritten to the inverse, durable
#               |              | claim: on the synced surface the two Pi loaders
#               |              | must AGREE.  See that class docstring.
# 2026-09-10    | Rex (US-722) | TestSubjectControl -- the gate's table/column
#               |              | REACH proven RED, not just its checks.
# ================================================================================
################################################################################

"""A-4 standing gate: the Pi and server shared sync contracts must agree.

Layers, weakest last (each is labelled so a skip can never read as a pass):

* **Mechanism tests** (always run).  Each check is fed a synthetic schema with
  ONE deliberate divergence and must report it.  This is the US-543
  validationCriterion -- "introduce a deliberate Pi/server shared-contract
  mismatch -> the parity CI test fails before deploy" -- executed as a test
  rather than left as a manual drill.
* **Standing gate** (always runs).  The live repo's APPLIED Pi schema vs the
  server schema must be clean.
* **Applied-server layer** (skips honestly off-CI).  Provisions a real MariaDB
  11.x (US-464/470 harness), applies the real provisioning path, and reads the
  columns back out of ``information_schema``.  Only this layer can see the
  BL-019 class (Python widened, deployed DB never ALTERed).

Run locally::

    pytest tests/lint/test_pi_server_contract_parity.py -v
    python scripts/audit_sync_contract_parity.py --verbose
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_sync_contract_parity as parity
from scripts.audit_sync_contract_parity import (
    ColumnSpec,
    checkAppliedMatchesModel,
    checkCanonicalTimestampRoundTrip,
    checkContractParity,
    checkCrossTierResolverDeclaration,
    checkDataQualityEnumParity,
    checkDataSourceEnumParity,
    checkPkRenameParity,
    checkServerRequiredColumnsCoveredByPi,
    checkSyncedColumnParity,
    checkTimestampParity,
    loadPiAppliedSchema,
    loadServerModelSchema,
    piPrimaryKeys,
    piWireColumns,
    syncedTables,
)

REPO_ROOT = Path(__file__).parent.parent.parent


# ================================================================================
# Fixtures -- the real repo loaded ONCE (initialize() is a real DB build)
# ================================================================================


@pytest.fixture(scope='module')
def piSchema() -> dict[str, dict[str, ColumnSpec]]:
    """The APPLIED Pi schema: a real ObdDatabase.initialize() run."""
    return loadPiAppliedSchema()


@pytest.fixture(scope='module')
def serverSchema() -> dict[str, dict[str, ColumnSpec]]:
    """The server schema as the SQLAlchemy models declare it."""
    return loadServerModelSchema()


def _codeIdentifiers(source: str) -> set[str]:
    """Return every identifier that appears in EXECUTABLE code in ``source``.

    An AST walk, not a substring scan: names inside comments and docstrings are
    not code and must not satisfy (or trip) a design guard.  Used by
    :class:`TestGuardDesign` to assert the audit module never calls
    ``create_all`` -- a module that merely *documents* the create_all trap in
    its header would fail a naive ``'create_all' not in source``.
    """
    import ast

    tree = ast.parse(source)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.alias):
            identifiers.add(node.name.rsplit('.', 1)[-1])
            if node.asname:
                identifiers.add(node.asname)
    return identifiers


def _provisionServerSchema(connection: Any, dbName: str) -> None:  # pragma: no cover
    """Build the server schema on a live MariaDB, as deploy-server.sh --init does.

    CI-only path (no Docker on the Windows bench).  Kept out of the test body
    so the deploy-parity intent is explicit: this reproduces the real
    provisioning step, and the assertion is then made against what MariaDB
    actually stored -- never against the metadata that built it.
    """
    from sqlalchemy import create_engine

    from src.server.db.models import Base

    def _text(value: Any) -> str:
        return value.decode() if isinstance(value, bytes) else str(value)

    url = (
        f'mysql+pymysql://{_text(connection.user)}@'
        f'{_text(connection.host)}:{connection.port}/{dbName}'
    )
    Base.metadata.create_all(create_engine(url))


def _spec(name: str, kind: str, *, notNull: bool = False,
          hasDefault: bool = False) -> ColumnSpec:
    """Build a ColumnSpec tersely for the synthetic-schema mechanism tests."""
    return ColumnSpec(name=name, kind=kind, notNull=notNull, hasDefault=hasDefault)


def _syntheticPair() -> tuple[dict, dict]:
    """Return a matching (pi, server) pair for one synced table.

    Deliberately minimal: each mechanism test mutates ONE fact so the assertion
    that fires is unambiguous.
    """
    pi = {
        'realtime_data': {
            'id': _spec('id', 'int', notNull=True, hasDefault=True),
            'timestamp': _spec('timestamp', 'datetime', notNull=True),
            'parameter_name': _spec('parameter_name', 'text', notNull=True),
            'value': _spec('value', 'float'),
        },
    }
    server = {
        'realtime_data': {
            'id': _spec('id', 'int', notNull=True, hasDefault=True),
            'source_id': _spec('source_id', 'int', notNull=True),
            'source_device': _spec('source_device', 'text', notNull=True),
            'timestamp': _spec('timestamp', 'datetime', notNull=True),
            'parameter_name': _spec('parameter_name', 'text', notNull=True),
            'value': _spec('value', 'float'),
        },
    }
    return pi, server


_TABLES = {'realtime_data': 'delta'}
_PKS = {'realtime_data': 'id'}


# ================================================================================
# The table set is COMPLETE BY CONSTRUCTION (US-543 DoD)
# ================================================================================


class TestSyncedTableSetIsCompleteByConstruction:
    """The audited set is the registries themselves, never a hand-kept list."""

    def test_syncedTables_isExactlyThePkColumnAndSnapshotRegistries(self) -> None:
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC
        from src.pi.data.sync_log import PK_COLUMN

        assert set(syncedTables()) == set(PK_COLUMN) | set(SNAPSHOT_SYNC)

    def test_syncedTables_newDeltaTable_isCoveredWithoutTouchingTheGuard(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The AC's "a future synced table auto-covered": register a table the
        # way a real story would and it must appear in the audited set with no
        # edit to this test or to the audit module.
        from src.pi.data.sync_log import PK_COLUMN

        monkeypatch.setitem(PK_COLUMN, 'edr_event_vault', 'id')
        assert syncedTables().get('edr_event_vault') == 'delta'

    def test_syncedTables_newSnapshotTable_isAlsoCovered(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # US-416 added a SECOND wire path; a guard that watched only PK_COLUMN
        # would report parity over a table set that is not the synced set.
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec

        monkeypatch.setitem(
            SNAPSHOT_SYNC, 'edr_snapshot',
            SnapshotSyncSpec(naturalKeyCols=('event_id',), cursorCol='recorded_at'),
        )
        assert syncedTables().get('edr_snapshot') == 'snapshot'

    def test_everySyncedTable_existsInTheAppliedPiSchema(
        self, piSchema: dict[str, dict[str, ColumnSpec]],
    ) -> None:
        missing = sorted(set(syncedTables()) - set(piSchema))
        assert not missing, (
            f'tables registered for sync that the Pi boot never creates: {missing}'
        )


# ================================================================================
# Assertion 2's precondition: the Pi side is APPLIED, not the DDL constants
# ================================================================================


class TestPiLoaderReadsTheAppliedSchema:
    """The Pi loader runs ensure-schema; it does not read the DDL constants.

    US-607 REWROTE THIS CLASS, and the reason is the finding.  It used to assert
    that ``scripts/schema_diff.loadPiSchema`` was BLIND to ``dtc_freeze_frame``
    -- true when US-543 wrote it, and a fair way to prove the applied loader was
    not redundant.  But an assertion that pins a defect goes red the day the
    defect is fixed, and TD-079/US-607 fixed exactly that one.  The claim is now
    the INVERSE, which is the durable direction: on the SYNCED surface the two
    loaders must AGREE, and any disagreement is TD-079 growing back.

    That makes this a SECOND, independent detector of the same class, taken from
    the other end: ``tests/scripts/test_schema_diff.py`` measures the DDL
    registry against the sync REGISTRIES, while this measures it against what
    the Pi's real ``initialize()`` boot actually creates.  A table could be
    missed by one route and caught by the other.

    The applied loader is still required, and this class proves it rather than
    asserting it -- see the two tests below.  Measured on this tree 2026-09-09:
    the ``ensureXSchema``-ALTER column class the US-543 docstring names (US-419
    ``data_quality``, US-252 ``vcell``, the US-289 SOC columns) currently has NO
    live instance -- every one has since been folded into a DDL constant.  The
    class stays live even with no instance, so the justification below rests on
    facts that ARE currently true instead.
    """

    def test_bothPiLoadersAgreeOnTheSyncedTableSet(
        self, piSchema: dict[str, dict[str, ColumnSpec]],
    ) -> None:
        """TD-079 from the applied side: the DDL registry must not go stale.

        Failing here means a table the Pi boot really creates and really syncs
        is absent from ``schema_diff``'s hand-kept CREATE TABLE registry, so the
        drift gate compares nothing for it -- and files the server's copy under
        ``tablesOnlyInServer``, the category that means "tier-owned, exempt".
        """
        from scripts.schema_diff import loadPiSchema

        synced = set(syncedTables())
        invisible = sorted((set(piSchema) & synced) - (set(loadPiSchema()) & synced))

        assert not invisible, (
            f'synced tables the Pi boot creates but scripts/schema_diff.'
            f'loadPiSchema cannot see: {invisible}. TD-079 has grown back -- '
            f'add each DDL constant to the registry in loadPiSchema().'
        )

    def test_theAgreementCheckCanActuallyFail(self) -> None:
        """Positive control -- without it the test above is an inert guard.

        Reproduces the pre-US-607 state synthetically: the applied side knows a
        synced table, the DDL side does not.  If the set arithmetic above were
        ever inverted or emptied, this is what notices.
        """
        applied = {'realtime_data': {}, 'dtc_freeze_frame': {}}
        ddl = {'realtime_data': set()}
        synced = {'realtime_data', 'dtc_freeze_frame'}

        assert sorted((set(applied) & synced) - (set(ddl) & synced)) == [
            'dtc_freeze_frame',
        ]

    def test_theTwoLoadersAreNotInterchangeable_soTheAppliedPathStays(
        self, piSchema: dict[str, dict[str, ColumnSpec]],
    ) -> None:
        """Why US-543's expensive loader survives US-607 closing the table gap.

        Two measured facts, either of which alone is sufficient:

        1. The applied loader returns per-column ``ColumnSpec`` -- kind, notNull
           and hasDefault.  ``loadPiSchema`` returns bare ``set[str]`` of names
           and structurally CANNOT answer A2, A5 or A6.
        2. Neither table set contains the other.  The DDL loader lists tables
           the Pi's ``initialize()`` boot never creates (they are built by other
           init paths), so substituting it here would assert parity over tables
           that do not exist on a booted Pi.
        """
        from scripts.schema_diff import loadPiSchema

        ddl = loadPiSchema()

        # The capability, not one column's nullability (that belongs to the
        # schema, not to this guard): the applied loader answers three questions
        # per column, and at least one synced column exercises each answer.
        specs = [s for cols in piSchema.values() for s in cols.values()]
        assert any(s.notNull for s in specs)
        assert any(s.hasDefault for s in specs)
        assert {s.kind for s in specs} > {'text'}
        # The DDL loader's whole return value is a set of NAMES -- there is no
        # place in that shape for any of the three.
        assert isinstance(ddl['realtime_data'], set)

        neverBooted = sorted(set(ddl) - set(piSchema))
        assert neverBooted, (
            'the DDL registry no longer names any table absent from the booted '
            'Pi schema -- fact 2 has expired; fact 1 still stands, but re-read '
            'this docstring before leaning on it.'
        )

    def test_appliedLoader_returnsPopulatedColumnSpecs(
        self, piSchema: dict[str, dict[str, ColumnSpec]],
    ) -> None:
        # Positive control: an empty/degenerate load would make every absence
        # assertion below pass vacuously.
        columns = piSchema['realtime_data']
        assert columns['value'].kind == 'float'
        assert columns['parameter_name'].kind == 'text'
        assert columns['id'].hasDefault is True


# ================================================================================
# A1 -- enum parity
# ================================================================================


class TestA1EnumParity:
    """data_source set-equality both ways; data_quality conditional on the wire."""

    def test_dataSource_realTuples_agree(self) -> None:
        from src.pi.obdii.data_source import DATA_SOURCE_VALUES as piValues
        from src.server.db.models import DATA_SOURCE_VALUES as serverValues

        assert checkDataSourceEnumParity(piValues, serverValues) == []

    def test_dataSource_piHasValueServerLacks_isRed(self) -> None:
        # The A-10 saga verbatim: US-424 added 'foreign' to the Pi tuple.
        violations = checkDataSourceEnumParity(
            ('real', 'replay', 'foreign'), ('real', 'replay'),
        )
        assert len(violations) == 1
        assert violations[0].assertionId == 'A1'
        assert 'foreign' in violations[0].message

    def test_dataSource_serverHasValuePiLacks_isRed(self) -> None:
        violations = checkDataSourceEnumParity(
            ('real',), ('real', 'synthetic'),
        )
        assert len(violations) == 1
        assert 'synthetic' in violations[0].message

    def test_dataSource_bothDirectionsReportedSeparately(self) -> None:
        violations = checkDataSourceEnumParity(('real', 'a'), ('real', 'b'))
        assert len(violations) == 2

    def test_dataQuality_whileWireStripped_parityIsNotRequired(self) -> None:
        # Today the Pi's data_quality is a local honest-instrument flag the
        # sync strips; the server computes its own.  Demanding equality here
        # would assert a falsehood.
        assert checkDataQualityEnumParity(
            ('full', 'clock_unsynced'),
            ('full', 'attribution_anomaly'),
            wireStripped=frozenset({'data_quality'}),
        ) == []

    def test_dataQuality_onceItCrossesTheWire_divergenceIsRed(self) -> None:
        # The teeth: drop the strip and the check flips to set-equality.
        violations = checkDataQualityEnumParity(
            ('full', 'clock_unsynced'),
            ('full', 'attribution_anomaly'),
            wireStripped=frozenset(),
        )
        assert len(violations) == 1
        assert 'clock_unsynced' in violations[0].message
        assert 'attribution_anomaly' in violations[0].message

    def test_dataQuality_onceItCrossesTheWire_equalVocabulariesPass(self) -> None:
        assert checkDataQualityEnumParity(
            ('full', 'x'), ('x', 'full'), wireStripped=frozenset(),
        ) == []

    def test_dataQuality_liveStripSetStillCarriesTheColumn(self) -> None:
        # Pins the premise of the conditional branch.  If a future story
        # un-strips data_quality this fails, pointing at the decision rather
        # than letting the enum check go quietly dormant.
        assert 'data_quality' in parity.WIRE_STRIPPED_COLUMNS


# ================================================================================
# A2 -- applied vs declared
# ================================================================================


class TestA2AppliedSchemaVerdict:
    """The applied-vs-declared alarm itself (hermetic; the live layer skips)."""

    def test_appliedMatchesModel_identical_isGreen(self) -> None:
        _, server = _syntheticPair()
        assert checkAppliedMatchesModel(server, server, ['realtime_data']) == []

    def test_appliedMissingColumn_isRed(self) -> None:
        # BL-019 in miniature: the model declares a column the deployed DB
        # never gained because no migration ran.
        _, server = _syntheticPair()
        applied = {'realtime_data': dict(server['realtime_data'])}
        del applied['realtime_data']['value']
        violations = checkAppliedMatchesModel(applied, server, ['realtime_data'])
        assert len(violations) == 1
        assert violations[0].assertionId == 'A2'
        assert 'value' in violations[0].message

    def test_appliedMissingTable_isRed(self) -> None:
        _, server = _syntheticPair()
        violations = checkAppliedMatchesModel({}, server, ['realtime_data'])
        assert len(violations) == 1
        assert 'no such table' in violations[0].message

    def test_appliedEmptyColumnDict_isRedNotSilentlyGreen(self) -> None:
        # An empty per-table dict is the shape a failed/partial introspection
        # returns; it must never read as "no drift".
        _, server = _syntheticPair()
        violations = checkAppliedMatchesModel(
            {'realtime_data': {}}, server, ['realtime_data'],
        )
        assert violations

    def test_checkContractParity_withoutAppliedSchema_skipsA2NeverFakesIt(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        # No real DB -> A2 does not run.  It must NOT be silently satisfied by
        # substituting the models for the applied schema (that substitution IS
        # the US-459 theatre-trap).
        violations = checkContractParity(piSchema, serverSchema)
        assert not any(v.assertionId == 'A2' for v in violations)


class TestA2AppliedSchemaLive:
    """The real applied-server layer: MariaDB 11.x, read from information_schema.

    SKIPPED when no real MariaDB is reachable.  The skip is honest -- it never
    reports green over a database it did not read.  SQLite / a Python-metadata
    stand-in is explicitly NOT used here; that substitution is the BL-019 ->
    BL-021 trap this whole guard exists to close.
    """

    def test_appliedServerSchemaMatchesTheModels(self) -> None:
        harness = pytest.importorskip(
            'tests.server._mariadb_chain_harness',
            reason='real-MariaDB harness unavailable',
        )
        ctx = harness.acquireMariaDb()
        try:
            connection, dbName = ctx.__enter__()
        except harness.MariaDbUnavailable as err:  # pragma: no cover -- bench path
            pytest.skip(f'no real MariaDB 11.x reachable: {err}')

        try:  # pragma: no cover -- CI-only path (no Docker/MariaDB on the bench)
            # Provision the server schema the way deploy-server.sh --init does,
            # letting REAL MariaDB execute the DDL, then read the result back
            # out of information_schema.  Note what is and is not happening
            # here: the metadata is the PROVISIONER, and the assertion is made
            # against the columns MariaDB actually ended up with.  The US-459
            # trap was making the metadata the ORACLE (comparing Python to
            # Python, or reading back from SQLite) -- that would pass over a
            # deployed DB whose migration never ran.
            _provisionServerSchema(connection, dbName)

            def runSql(sql: str) -> str:
                cursor = connection.cursor()
                try:
                    cursor.execute(sql.rstrip(';'))
                    return harness.formatMysqlBatchOutput(cursor.fetchall())
                finally:
                    cursor.close()

            applied = parity.loadServerAppliedSchema(runSql, dbName)
            assert applied, 'information_schema returned no columns'
            violations = checkAppliedMatchesModel(
                applied, loadServerModelSchema(), list(syncedTables()),
            )
            assert not violations, '\n'.join(v.render() for v in violations)
        finally:
            ctx.__exit__(None, None, None)


# ================================================================================
# A3 -- synced-table shared-column parity
# ================================================================================


class TestA3SyncedColumnParity:
    """Every column the Pi puts on the wire exists on the server, compatibly."""

    def test_matchingSchemas_areGreen(self) -> None:
        pi, server = _syntheticPair()
        assert checkSyncedColumnParity(pi, server, _TABLES, _PKS) == []

    def test_piColumnMissingOnServer_isRed(self) -> None:
        # The deliberate mismatch from the validationCriterion: a Pi story adds
        # a capture column and no server migration ships.
        pi, server = _syntheticPair()
        pi['realtime_data']['boost_psi'] = _spec('boost_psi', 'float')
        violations = checkSyncedColumnParity(pi, server, _TABLES, _PKS)
        assert len(violations) == 1
        assert violations[0].assertionId == 'A3'
        assert 'boost_psi' in violations[0].message

    def test_typeKindMismatch_isRed(self) -> None:
        pi, server = _syntheticPair()
        server['realtime_data']['value'] = _spec('value', 'text')
        violations = checkSyncedColumnParity(pi, server, _TABLES, _PKS)
        assert len(violations) == 1
        assert 'type-kind mismatch' in violations[0].message

    def test_textVsDatetime_isCompatibleNotAViolation(self) -> None:
        # Canonical ISO-8601 is stored as TEXT on one tier and DATETIME on the
        # other by design; check 6 guards the FORMAT, so this must not be noise.
        pi, server = _syntheticPair()
        pi['realtime_data']['timestamp'] = _spec('timestamp', 'text')
        assert checkSyncedColumnParity(pi, server, _TABLES, _PKS) == []

    def test_serverOnlyAnalyticsColumn_isNotAViolation(self) -> None:
        # The server computes columns the Pi never sends; asserting on those
        # would make the guard fire constantly and get it disabled.
        pi, server = _syntheticPair()
        server['realtime_data']['computed_load'] = _spec('computed_load', 'float')
        assert checkSyncedColumnParity(pi, server, _TABLES, _PKS) == []

    def test_wireStrippedPiColumn_isNotSentSoNotAViolation(self) -> None:
        pi, server = _syntheticPair()
        pi['realtime_data']['_sync_modified_at'] = _spec('_sync_modified_at', 'text')
        assert checkSyncedColumnParity(pi, server, _TABLES, _PKS) == []

    def test_missingPiTable_isRed(self) -> None:
        _, server = _syntheticPair()
        violations = checkSyncedColumnParity({}, server, _TABLES, _PKS)
        assert len(violations) == 1
        assert 'APPLIED Pi schema has no such table' in violations[0].message

    def test_missingServerTable_isRed(self) -> None:
        pi, _ = _syntheticPair()
        violations = checkSyncedColumnParity(pi, {}, _TABLES, _PKS)
        assert len(violations) == 1
        assert 'server has no such table' in violations[0].message

    def test_realRepo_syncedColumnsAgree(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        violations = checkSyncedColumnParity(
            piSchema, serverSchema, syncedTables(), piPrimaryKeys(),
        )
        assert not violations, '\n'.join(v.render() for v in violations)


class TestA3CrossTierResolverDeclaration:
    """The one exemption that is declared rather than derived is self-policed."""

    def test_realRepo_resolverDeclarationIsConsistent(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        violations = checkCrossTierResolverDeclaration(piSchema, serverSchema)
        assert not violations, '\n'.join(v.render() for v in violations)

    def test_declaredPiColumnGone_isRedNotSilentlySuppressing(self) -> None:
        # A stale exemption is worse than no exemption: it suppresses a real
        # check-3 finding for a column that no longer exists.
        violations = checkCrossTierResolverDeclaration(
            {'t': {}}, {'t': {'vehicle_info_id': _spec('vehicle_info_id', 'int')}},
            resolved={'t': {'vehicle_info_vin': 'vehicle_info_id'}},
        )
        assert any('stale' in v.message for v in violations)

    def test_resolverTargetMissingOnServer_isRed(self) -> None:
        violations = checkCrossTierResolverDeclaration(
            {'t': {'vehicle_info_vin': _spec('vehicle_info_vin', 'text')}}, {'t': {}},
            resolved={'t': {'vehicle_info_vin': 'vehicle_info_id'}},
        )
        assert any('no ' in v.message and 'vehicle_info_id' in v.message
                   for v in violations)

    def test_droppedColumnReappearsOnServer_isRed(self) -> None:
        # If the server gains a column we declared intentionally dropped, the
        # Pi's value is now being discarded into an empty column.
        violations = checkCrossTierResolverDeclaration(
            {'t': {'data_source': _spec('data_source', 'text')}},
            {'t': {'data_source': _spec('data_source', 'text')}},
            resolved={'t': {'data_source': None}},
        )
        assert any('discarded' in v.message for v in violations)


class TestPiWireColumns:
    """The wire surface applies exactly the transforms the sync client applies."""

    def test_pkRenamedToId(self) -> None:
        columns = {
            'drain_event_id': _spec('drain_event_id', 'int'),
            'notes': _spec('notes', 'text'),
        }
        wire = piWireColumns('battery_health_log', columns, 'drain_event_id')
        assert set(wire) == {'id', 'notes'}

    def test_idPkLeftAlone(self) -> None:
        columns = {'id': _spec('id', 'int'), 'notes': _spec('notes', 'text')}
        assert set(piWireColumns('power_log', columns, 'id')) == {'id', 'notes'}

    def test_snapshotTableHasNoPkRename(self) -> None:
        columns = {'boot_id': _spec('boot_id', 'text')}
        assert set(piWireColumns('startup_log', columns, None)) == {'boot_id'}

    def test_wireStrippedColumnsRemoved(self) -> None:
        columns = {
            'id': _spec('id', 'int'),
            'data_quality': _spec('data_quality', 'text'),
            '_sync_modified_at': _spec('_sync_modified_at', 'text'),
        }
        assert set(piWireColumns('power_log', columns, 'id')) == {'id'}


# ================================================================================
# A4 -- PK-rename mapping parity
# ================================================================================


class TestA4PkRenameParity:
    """Every non-'id' Pi PK's rename to 'id' is declared and consistent."""

    def test_realRepo_renameMapAgreesWithPkColumn(
        self, serverSchema: dict,
    ) -> None:
        from scripts.schema_diff import PI_PK_RENAMED_TO_ID

        violations = checkPkRenameParity(
            piPrimaryKeys(), PI_PK_RENAMED_TO_ID, serverSchema,
        )
        assert not violations, '\n'.join(v.render() for v in violations)

    def test_undeclaredRename_isRed(self) -> None:
        # The live gap this story found: drive_summary's PK is drive_id and the
        # client renames it, but PI_PK_RENAMED_TO_ID never declared it.
        violations = checkPkRenameParity(
            {'drive_summary': 'drive_id'},
            {},
            {'drive_summary': {'source_id': _spec('source_id', 'int')}},
        )
        assert len(violations) == 1
        assert violations[0].assertionId == 'A4'
        assert 'NOT declared' in violations[0].message

    def test_staleDeclaration_isRed(self) -> None:
        violations = checkPkRenameParity(
            {}, {'retired_table': 'old_pk'}, {},
        )
        assert len(violations) == 1
        assert 'stale' in violations[0].message

    def test_disagreeingDeclaration_isRed(self) -> None:
        violations = checkPkRenameParity(
            {'t': 'drain_event_id'},
            {'t': 'session_id'},
            {'t': {'source_id': _spec('source_id', 'int')}},
        )
        assert any('disagrees' in v.message for v in violations)

    def test_renamedPkWithNoServerSourceId_isRed(self) -> None:
        # The rename exists to make 'id' -> source_id work; without the
        # destination column the whole point is void.
        violations = checkPkRenameParity(
            {'t': 'session_id'}, {'t': 'session_id'}, {'t': {}},
        )
        assert any('source_id' in v.message for v in violations)

    def test_idPkTablesAreNotRequiredToDeclareARename(self) -> None:
        assert checkPkRenameParity({'power_log': 'id'}, {}, {}) == []

    def test_everyRenameInTheAcceptSetSourcesFromThePiPk(self) -> None:
        """
        Given: the LIVE _TABLE_REGISTRY the server accepts sync payloads with
        When: every declared rename is inspected
        Then: each sources from 'id' -- it is a PK rename, the one kind
            runSyncUpsert branches on.

        US-689: the converse of this class's sentence. A NON-PK rename is a
        column-spelling seam -- the server quietly accepting a name the Pi no
        longer sends, which reads as compatibility and ages into a second
        vocabulary for one fact. The drive_summary IAT seam was the last one
        and it is gone; this goes red on the commit that adds another.

        Read from the IMPORTED dict, never a copied literal: a copy would pass
        while the shipped registry drifted.
        """
        from src.server.api.sync import _TABLE_REGISTRY

        offenders = {
            table: [(src, dst) for src, dst in renames if src != 'id']
            for table, (_model, renames) in _TABLE_REGISTRY.items()
            if any(src != 'id' for src, _dst in renames)
        }

        assert offenders == {}, (
            f"non-PK rename(s) in the sync accept-set: {offenders}. A rename "
            "that does not source from the Pi PK is a column-spelling seam; "
            "rename the column on the Pi instead (US-689)."
        )

    def test_everyColumnThePiSENDS_existsOnTheServerWithTheSameSpelling(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        """
        Given: the APPLIED Pi schema and the server models -- both loaded, not
            described
        When: every column a delta-sync payload would carry is resolved (the
            Pi PK renamed to id -> source_id, the wire-stripped Pi-local
            columns removed)
        Then: each exists on the server table under the IDENTICAL spelling.

        US-689 made this a runtime rule: an unknown column now RAISES instead
        of being dropped by executemany. That makes exact spelling -- case,
        underscores and all -- part of the wire contract, so it has to be
        checked against the real schemas rather than asserted in a comment.
        Before US-689 a mismatch here cost one silently discarded value; now it
        fails the batch, which is why this guard sits beside the change.
        """
        from src.pi.data.sync_log import (
            _WIRE_STRIPPED_COLUMNS,
            DELTA_SYNC_TABLES,
            PK_COLUMN,
        )
        from src.server.api.sync import _TABLE_REGISTRY

        offenders: dict[str, list[str]] = {}
        for table in sorted(set(DELTA_SYNC_TABLES) & set(_TABLE_REGISTRY)):
            piCols = piSchema.get(table)
            serverCols = serverSchema.get(table)
            if not piCols or not serverCols:
                continue
            renames = dict(_TABLE_REGISTRY[table][1])
            missing = []
            for name in piCols:
                if name in _WIRE_STRIPPED_COLUMNS:
                    continue
                # The Pi PK travels as 'id' and lands in source_id.
                if name == PK_COLUMN.get(table):
                    continue
                wireName = renames.get(name, name)
                if wireName not in serverCols:
                    missing.append(f"{name} -> {wireName}")
            if missing:
                offenders[table] = missing

        assert offenders == {}, (
            "a Pi column would be sent under a spelling the server model does "
            f"not declare, and US-689 now makes that RAISE: {offenders}"
        )

    def test_theRegistryIsPopulated_soTheRenameCheckIsNotVacuous(self) -> None:
        """A registry that failed to import, or one with no renames at all,
        would make the check above pass by having nothing to look at."""
        from src.server.api.sync import _TABLE_REGISTRY

        assert len(_TABLE_REGISTRY) > 5
        assert 'drive_summary' in _TABLE_REGISTRY
        # At least one PK rename still exists, so "sources from id" is a real
        # filter rather than a statement about an empty set.
        assert any(
            any(src == 'id' for src, _dst in renames)
            for _model, renames in _TABLE_REGISTRY.values()
        )


# ================================================================================
# A5 -- Pi ensure-schema coverage
# ================================================================================


class TestA5EnsureSchemaCoverage:
    """Server columns the Pi MUST supply exist on the Pi's applied schema."""

    def test_matchingSchemas_areGreen(self) -> None:
        pi, server = _syntheticPair()
        assert checkServerRequiredColumnsCoveredByPi(
            pi, server, _TABLES, _PKS,
        ) == []

    def test_serverRequiredColumnMissingOnPi_isRed(self) -> None:
        # TD-043 class: NOT NULL, no default, and the Pi never sends it ->
        # MariaDB 1364 on every push.
        pi, server = _syntheticPair()
        server['realtime_data']['device_id'] = _spec(
            'device_id', 'text', notNull=True,
        )
        violations = checkServerRequiredColumnsCoveredByPi(
            pi, server, _TABLES, _PKS,
        )
        assert len(violations) == 1
        assert violations[0].assertionId == 'A5'
        assert 'device_id' in violations[0].message

    def test_serverNullableColumnMissingOnPi_isNotAViolation(self) -> None:
        pi, server = _syntheticPair()
        server['realtime_data']['optional_note'] = _spec('optional_note', 'text')
        assert checkServerRequiredColumnsCoveredByPi(
            pi, server, _TABLES, _PKS,
        ) == []

    def test_serverRequiredButDefaulted_isNotAViolation(self) -> None:
        pi, server = _syntheticPair()
        server['realtime_data']['ingested'] = _spec(
            'ingested', 'int', notNull=True, hasDefault=True,
        )
        assert checkServerRequiredColumnsCoveredByPi(
            pi, server, _TABLES, _PKS,
        ) == []

    def test_serverMirrorColumnsAreExempt(self) -> None:
        # source_id / source_device are NOT NULL with no default by design and
        # are supplied by the server ingest, never by the Pi payload.
        pi, server = _syntheticPair()
        assert 'source_id' not in pi['realtime_data']
        assert checkServerRequiredColumnsCoveredByPi(
            pi, server, _TABLES, _PKS,
        ) == []

    def test_columnReachableOnlyViaPkRename_isCovered(self) -> None:
        pi = {'t': {'session_id': _spec('session_id', 'int')}}
        server = {'t': {'id': _spec('id', 'int', notNull=True)}}
        assert checkServerRequiredColumnsCoveredByPi(
            pi, server, {'t': 'delta'}, {'t': 'session_id'},
        ) == []

    def test_realRepo_everyServerRequiredColumnIsCovered(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        violations = checkServerRequiredColumnsCoveredByPi(
            piSchema, serverSchema, syncedTables(), piPrimaryKeys(),
        )
        assert not violations, '\n'.join(v.render() for v in violations)


# ================================================================================
# A6 -- timestamp / format parity
# ================================================================================


class TestA6TimestampParity:
    """Synced timestamps are ISO-8601 on both tiers, and the format round-trips."""

    def test_matchingSchemas_areGreen(self) -> None:
        pi, server = _syntheticPair()
        assert checkTimestampParity(pi, server, _TABLES, _PKS) == []

    def test_piStoresEpochNumber_isRed(self) -> None:
        # The silent corruption: no coercion happens on the wire, so an epoch
        # int landing in a DATETIME column is wrong by decades with no error.
        pi, server = _syntheticPair()
        pi['realtime_data']['timestamp'] = _spec('timestamp', 'int')
        violations = checkTimestampParity(pi, server, _TABLES, _PKS)
        assert len(violations) == 1
        assert violations[0].assertionId == 'A6'
        assert 'on the Pi' in violations[0].message

    def test_serverStoresEpochNumber_isRed(self) -> None:
        pi, server = _syntheticPair()
        server['realtime_data']['timestamp'] = _spec('timestamp', 'float')
        violations = checkTimestampParity(pi, server, _TABLES, _PKS)
        assert len(violations) == 1
        assert 'on the server' in violations[0].message

    def test_nonTimestampColumnsAreNotChecked(self) -> None:
        pi, server = _syntheticPair()
        pi['realtime_data']['value'] = _spec('value', 'float')
        assert checkTimestampParity(pi, server, _TABLES, _PKS) == []

    @pytest.mark.parametrize(
        'name',
        ['timestamp', 'recorded_at', 'start_timestamp', 'prior_last_entry_ts',
         'end_time'],
    )
    def test_timestampNamesAreRecognised(self, name: str) -> None:
        # A pattern that failed to match would make every A6 assertion pass
        # vacuously -- the positive control for the column selector.
        pi = {'t': {name: _spec(name, 'int')}}
        server = {'t': {name: _spec(name, 'datetime')}}
        assert checkTimestampParity(pi, server, {'t': 'delta'}, {'t': 'id'})

    def test_canonicalPiTimestampRoundTripsThroughServerIngest(self) -> None:
        # End-to-end, not a declaration: the exact string utcIsoNow() emits is
        # pushed through the server's own _parseDateTime.
        assert checkCanonicalTimestampRoundTrip() == []

    def test_roundTripAlarmFiresWhenIngestStopsParsing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Model the failure: an ingest coercion that passes the string through
        # (what a trailing-'Z' regression looks like) must be caught.
        import src.server.api.sync as serverSync

        monkeypatch.setattr(serverSync, '_parseDateTime', lambda value: value)
        violations = checkCanonicalTimestampRoundTrip()
        assert len(violations) == 1
        assert violations[0].assertionId == 'A6'
        assert 'does NOT parse' in violations[0].message

    def test_realRepo_timestampsAgree(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        violations = checkTimestampParity(
            piSchema, serverSchema, syncedTables(), piPrimaryKeys(),
        )
        assert not violations, '\n'.join(v.render() for v in violations)


# ================================================================================
# The standing gate + the validationCriterion, end to end
# ================================================================================


class TestStandingGate:
    """Acceptance: the live repo's Pi <-> server contracts agree."""

    def test_checkContractParity_realRepo_isClean(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        violations = checkContractParity(piSchema, serverSchema)
        if violations:
            report = '\n'.join(f'  - {v.render()}' for v in violations)
            pytest.fail(
                f'A-4 violation: {len(violations)} Pi<->server contract '
                f'divergence(s). The Pi and server must agree on the shared '
                f'sync contract or the next deploy syncs into a rejection.\n'
                f'{report}',
            )

    def test_cliMain_realRepo_exitsZero(self, capsys: Any) -> None:
        assert parity.main([]) == 0
        assert 'OK' in capsys.readouterr().out

    def test_deliberateMismatch_failsTheGateBeforeDeploy(
        self, piSchema: dict, serverSchema: dict,
    ) -> None:
        """US-543 validationCriterion, executed rather than left as a drill.

        Introduce a deliberate Pi/server shared-contract mismatch against the
        REAL loaded schemas -- the Pi gains a capture column no server
        migration shipped -- and the aggregate gate must fail.
        """
        drifted = {table: dict(cols) for table, cols in piSchema.items()}
        drifted['realtime_data']['knock_retard_deg'] = _spec(
            'knock_retard_deg', 'float',
        )
        violations = checkContractParity(drifted, serverSchema)
        assert any(
            v.assertionId == 'A3' and 'knock_retard_deg' in v.message
            for v in violations
        )

    def test_cliMain_onDrift_exitsOne(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any,
    ) -> None:
        # The exit code is the CI contract; a check that reports drift on
        # stdout while exiting 0 would never fail a pipeline.
        monkeypatch.setattr(
            parity, 'checkContractParity',
            lambda *a, **k: [parity.ParityViolation('A3', 't', 'injected')],
        )
        assert parity.main([]) == 1
        assert 'DRIFT' in capsys.readouterr().out


# A column no server model declares, so a Pi table carrying it is an A3 finding.
_PLANTED_COLUMN = 'us722_planted_probe'


class TestSubjectControl:
    """US-722: the gate's SUBJECT -- which tables and columns it reaches -- can fail.

    Every mechanism test above is DETECTOR-side: a synthetic schema, usually one
    table, handed straight to a check function.  The deliberate-mismatch test
    uses the real schemas but plants into ONE table's already-loaded dict, so
    the loader and the table set are never exercised.  A guard is a detector
    applied to a subject, and the burn this file carries -- US-543 asserting the
    DDL loader's blindness as evidence -- was a subject failure.
    """

    def test_subjectControl_columnPlantedInEveryRegisteredTable_failsTheGate(
        self, tmp_path: Path, serverSchema: dict,
    ) -> None:
        """
        Given: a Pi DB built by the real boot path, then ALTERed so EVERY table
               the sync registries register carries a column no server model has
        When:  the real loader reads that DB and the aggregate gate runs with its
               default table set
        Then:  the gate reports the planted column in every registered table

        The claim comes from PK_COLUMN and SNAPSHOT_SYNC directly, NOT from
        syncedTables(): derive it from the function under test and narrowing
        that function narrows the plant with it.  Narrow the table set, what the
        aggregation hands a check, or the loader's read of the applied DB, and
        this goes RED while the standing gate stays green over a clean tree.

        Measured 2026-09-10, each mutation reverted from the HEAD blob: the
        aggregate handing A3 only the delta tables, and the loader booting a
        fresh DB instead of reading the one it is handed, turned THIS test and
        nothing else red.  syncedTables() forgetting the snapshot path turned it
        red beside the two registry pins.  It plants via A3 only -- it proves the
        gate REACHES every registered table and column, not that each of A4-A6
        is wired into the aggregate; those stay with their own real-repo tests.
        """
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC
        from src.pi.data.sync_log import PK_COLUMN

        claimed = sorted(set(PK_COLUMN) | set(SNAPSHOT_SYNC))
        assert claimed, 'both sync registries are empty -- nothing to plant in'

        dbPath = str(tmp_path / 'obd.db')
        loadPiAppliedSchema(dbPath)
        conn = sqlite3.connect(dbPath)
        try:
            for table in claimed:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {_PLANTED_COLUMN} REAL')
            conn.commit()
        finally:
            conn.close()

        violations = checkContractParity(loadPiAppliedSchema(dbPath), serverSchema)

        reached = {
            v.table for v in violations
            if v.assertionId == 'A3' and _PLANTED_COLUMN in v.message
        }
        missed = sorted(set(claimed) - reached)
        assert not missed, (
            f'a column planted in a registered synced table was not reported, so '
            f'the gate no longer reaches: {missed}'
        )


class TestGuardDesign:
    """Pins the properties that make this guard non-theatre (US-459 lesson)."""

    def test_codeIdentifiers_positiveControl(self) -> None:
        # Positive control for the scanner below.  An absence assertion is
        # worthless without proof that the thing could have been found: a
        # scanner that silently returned an empty set would pass the next test
        # over a module that calls create_all on every line.
        assert 'create_all' in _codeIdentifiers(
            'from sqlalchemy import create_engine\n'
            'Base.metadata.create_all(create_engine(url))\n',
        )

    def test_codeIdentifiers_ignoresCommentsAndDocstrings(self) -> None:
        # Negative control -- and the reason this is an AST scan rather than a
        # substring match: the audit module DOCUMENTS the create_all trap in
        # its own header, so `'create_all' not in source` fails on a CORRECT
        # file (the US-522 substring lesson in its false-positive direction).
        assert 'create_all' not in _codeIdentifiers(
            '"""Never substitutes create_all for the applied schema."""\n'
            '# create_all is the trap this closes\n'
            'x = 1\n',
        )

    def test_guardNeverSubstitutesCreateAllForTheAppliedServerSchema(self) -> None:
        # The applied-server loader must read information_schema.  A
        # create_all/SQLite stand-in inside the audit module would silently
        # convert the applied-schema assertion back into a metadata compare --
        # the US-459 theatre-trap, re-introduced by "simplification".
        source = (
            REPO_ROOT / 'scripts' / 'audit_sync_contract_parity.py'
        ).read_text(encoding='utf-8')
        identifiers = _codeIdentifiers(source)
        assert 'create_all' not in identifiers
        assert 'information_schema' in source

    def test_everyAssertionIdIsDocumented(self) -> None:
        assert set(parity.ASSERTION_TITLES) == {'A1', 'A2', 'A3', 'A4', 'A5', 'A6'}

    def test_violationRenderNamesTheAssertionAndTable(self) -> None:
        rendered = parity.ParityViolation('A3', 'power_log', 'boom').render()
        assert 'A3' in rendered
        assert 'power_log' in rendered
