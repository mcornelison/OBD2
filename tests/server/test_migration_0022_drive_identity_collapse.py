################################################################################
# File Name: test_migration_0022_drive_identity_collapse.py
# Purpose/Description: US-451 (F-104 / D-8) migration unit tests for v0022 -- the
#                      drive-identity collapse.  Verifies (1) the drives.
#                      data_quality CHECK widen with 'unmappable_legacy', (2) the
#                      NULL-natural-key legacy flag UPDATE + zero-survivor probe,
#                      (3) the drive_statistics + drive_derived_signals summary_id
#                      FK re-point from drive_summary.id to drives.drive_id
#                      (INFORMATION_SCHEMA name discovery, DROP + re-ADD), plus
#                      ORM parity, INFORMATION_SCHEMA-probe idempotency,
#                      post-condition probes, failure propagation, and registry
#                      registration.  Hermetic FakeRunner -- no SSH, no MariaDB
#                      (mirrors test_migration_0015_foreign_vehicle_data_quality).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-451) | Initial -- F-104/D-8 drive-identity collapse.
# ================================================================================
################################################################################

"""TDD tests for the v0022 drive-identity-collapse migration (US-451 / F-104)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY,
    DRIVES_DATA_QUALITY_VALUES,
    DriveDerivedSignal,
    DriveStatistic,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0022_us451_drive_identity_collapse as m0022,
)

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0015)
# ================================================================================


@dataclass
class FakeRunner:
    """Scripted runner.  First matching needle wins (insertion order)."""

    handlers: list[tuple[str, Callable[[str], subprocess.CompletedProcess[str]]]] = (
        field(default_factory=list)
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ''
        self.calls.append({'argv': list(argv), 'input': sql, 'timeout': timeout})
        for needle, handler in self.handlers:
            if needle in sql:
                return handler(sql)
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout='', stderr='',
        )

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=1, stdout='', stderr=stderr,
    )


def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db')


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(addrs=_addrs(), creds=_creds(), runner=runner)


# CHECK_CLAUSE strings -- stale (pre-v0022, no unmappable_legacy) then widened.
_DRIVES_CLAUSE_STALE = (
    "data_quality in ('full','attribution_anomaly','foreign_vehicle')\n"
)
_DRIVES_CLAUSE_WIDE = (
    "data_quality in ('full','attribution_anomaly','foreign_vehicle',"
    "'unmappable_legacy')\n"
)

# The auto-named (drive_statistics) + v0017-named (drive_derived_signals) stale
# FKs the production DB carries before the re-point.
_STATS_STALE_FK = 'drive_statistics_ibfk_1'
_DERIVED_STALE_FK = 'fk_drive_derived_signals_summary'


def _tablesHandler(
    missing: frozenset[str] = frozenset(),
) -> Callable[[str], subprocess.CompletedProcess[str]]:
    """serverTableExists probe -- '1' unless the table is in ``missing``."""

    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        for table in ('drives', 'drive_statistics', 'drive_derived_signals'):
            if f"TABLE_NAME='{table}'" in sql:
                return _ok(stdout='0\n' if table in missing else '1\n')
        return _ok(stdout='1\n')

    return handler


def _fkHandlerProduction(sql: str) -> subprocess.CompletedProcess[str]:
    """Live state: summary_id FKs still reference drive_summary; drives after."""
    isStats = "TABLE_NAME='drive_statistics'" in sql
    if "REFERENCED_TABLE_NAME='drive_summary'" in sql:
        return _ok(stdout=f'{_STATS_STALE_FK}\n' if isStats
                   else f'{_DERIVED_STALE_FK}\n')
    # REFERENCED_TABLE_NAME='drives' -- present after the re-point.
    return _ok(stdout=(f'{m0022.DRIVE_STATISTICS_FK_NAME}\n' if isStats
                       else f'{m0022.DRIVE_DERIVED_SIGNALS_FK_NAME}\n'))


def _fkHandlerMigrated(sql: str) -> subprocess.CompletedProcess[str]:
    """Fully-migrated: no drive_summary-referencing FK; drives-referencing set."""
    if "REFERENCED_TABLE_NAME='drive_summary'" in sql:
        return _ok(stdout='')
    isStats = "TABLE_NAME='drive_statistics'" in sql
    return _ok(stdout=(f'{m0022.DRIVE_STATISTICS_FK_NAME}\n' if isStats
                       else f'{m0022.DRIVE_DERIVED_SIGNALS_FK_NAME}\n'))


def _scriptProductionState(
    runner: FakeRunner, legacySurvivorsAfter: str = '0\n',
) -> None:
    """Live DB: stale CHECK, unflagged legacy rows, drive_summary-referencing FKs.

    The CHECK_CLAUSE probe returns the stale clause on the entry probe and the
    widened clause on the post-condition probe (counter, mirrors v0015).
    """
    runner.handlers.append(('information_schema.KEY_COLUMN_USAGE', _fkHandlerProduction))

    clauseCalls = {'n': 0}

    def clause(_s: str) -> subprocess.CompletedProcess[str]:
        clauseCalls['n'] += 1
        return _ok(stdout=_DRIVES_CLAUSE_STALE if clauseCalls['n'] == 1
                   else _DRIVES_CLAUSE_WIDE)

    runner.handlers.append(('information_schema.CHECK_CONSTRAINTS', clause))
    runner.handlers.append(('information_schema.TABLES', _tablesHandler()))
    # Zero-survivor post-probe for the legacy flag.
    runner.handlers.append((
        'SELECT COUNT(*) FROM drives',
        lambda _s: _ok(stdout=legacySurvivorsAfter),
    ))


def _scriptFullyMigratedState(runner: FakeRunner) -> None:
    """Already-collapsed DB (fresh create_all or a prior run) -- every no-op."""
    runner.handlers.append(('information_schema.KEY_COLUMN_USAGE', _fkHandlerMigrated))
    runner.handlers.append((
        'information_schema.CHECK_CONSTRAINTS',
        lambda _s: _ok(stdout=_DRIVES_CLAUSE_WIDE),
    ))
    runner.handlers.append(('information_schema.TABLES', _tablesHandler()))
    runner.handlers.append((
        'SELECT COUNT(*) FROM drives', lambda _s: _ok(stdout='0\n'),
    ))


def _singleTableFkHandler(
    tableName: str,
    newFkName: str,
    *,
    stale: str | None = None,
    hasDrivesFk: bool = False,
    orphans: str = '0\n',
) -> Callable[[str], subprocess.CompletedProcess[str]]:
    """One comprehensive handler for a single table's ``_repointSummaryFk`` probes.

    Registered under the table name as needle (every probe SQL in the substep
    names the table).  Models the three applied FK states:

    * ``stale`` set, ``hasDrivesFk`` False -> **state 1** (FK -> drive_summary).
    * ``stale`` None, ``hasDrivesFk`` True -> **state 2** (FK -> drives; no-op).
    * ``stale`` None, ``hasDrivesFk`` False -> **state 3** (no FK; ADD-only).

    After an ``ADD CONSTRAINT`` is observed the drives-referencing probe flips to
    return ``newFkName`` so the post-condition probe passes (states 1 + 3).
    """
    state = {'added': hasDrivesFk}

    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if 'information_schema.TABLES' in sql:
            return _ok(stdout='1\n')
        if 'ADD CONSTRAINT' in sql:
            state['added'] = True
            return _ok()
        if 'DROP FOREIGN KEY' in sql:
            return _ok()
        if 'information_schema.KEY_COLUMN_USAGE' in sql:
            if "REFERENCED_TABLE_NAME='drive_summary'" in sql:
                return _ok(stdout=f'{stale}\n' if stale else '')
            # REFERENCED_TABLE_NAME='drives'
            return _ok(stdout=f'{newFkName}\n' if state['added'] else '')
        if 'LEFT JOIN drives' in sql:  # orphan pre-condition probe
            return _ok(stdout=orphans)
        return _ok()

    return handler


# ================================================================================
# Module shape + registry
# ================================================================================


class TestModuleExports:
    def test_versionIs0022(self) -> None:
        assert m0022.VERSION == '0022'

    def test_descriptionMentionsUs451(self) -> None:
        assert 'US-451' in m0022.DESCRIPTION

    def test_descriptionMentionsUnmappableLegacy(self) -> None:
        assert 'unmappable_legacy' in m0022.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0022.MIGRATION.version == '0022'
        assert callable(m0022.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        assert '0022' in [m.version for m in ALL_MIGRATIONS]

    def test_registrySortedAndV0022DirectlyAfterV0021(self) -> None:
        # De-brittled (US-454 lesson): assert present + sorted + directly after
        # its predecessor, NOT an absolute-tail assertion that silently breaks
        # on the next registry append.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0022' in versions
        assert versions[versions.index('0022') - 1] == '0021'

    def test_fkConstraintNamesMatchOrm(self) -> None:
        statsFkNames = {
            fk.name
            for fk in DriveStatistic.__table__.columns['summary_id'].foreign_keys
        }
        derivedFkNames = {
            fk.name
            for fk in DriveDerivedSignal.__table__.columns['summary_id'].foreign_keys
        }
        assert m0022.DRIVE_STATISTICS_FK_NAME in statsFkNames
        assert m0022.DRIVE_DERIVED_SIGNALS_FK_NAME in derivedFkNames


# ================================================================================
# ORM parity -- the identity collapse the migration mirrors
# ================================================================================


class TestOrmParity:
    def test_drivesEnumCarriesUnmappableLegacy(self) -> None:
        assert DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY in DRIVES_DATA_QUALITY_VALUES

    def test_drivesEnumKeepsSubsumedValues(self) -> None:
        for value in ('full', 'attribution_anomaly', 'foreign_vehicle'):
            assert value in DRIVES_DATA_QUALITY_VALUES

    def test_driveStatisticsFkTargetsDrives(self) -> None:
        col = DriveStatistic.__table__.columns['summary_id']
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert 'drives.drive_id' in targets
        assert 'drive_summary.id' not in targets

    def test_driveDerivedSignalsFkTargetsDrives(self) -> None:
        col = DriveDerivedSignal.__table__.columns['summary_id']
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert 'drives.drive_id' in targets
        assert 'drive_summary.id' not in targets


# ================================================================================
# DDL parity -- the emitted SQL is shaped from the ORM SSOT
# ================================================================================


class TestDdlParity:
    def test_dropCheckTargetsNamedConstraint(self) -> None:
        ddl = m0022.DROP_DRIVES_CHECK_DDL
        assert ddl.startswith('ALTER TABLE drives')
        assert f'DROP CONSTRAINT {m0022.DRIVES_CHECK_NAME}' in ddl

    def test_addCheckIncludesUnmappableAndEveryOrmValue(self) -> None:
        ddl = m0022.ADD_DRIVES_CHECK_DDL
        assert DRIVES_DATA_QUALITY_UNMAPPABLE_LEGACY in ddl
        for value in DRIVES_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl
        assert f'ADD CONSTRAINT {m0022.DRIVES_CHECK_NAME}' in ddl

    def test_flagDdlShape(self) -> None:
        ddl = m0022.FLAG_UNMAPPABLE_LEGACY_DDL
        assert ddl.startswith('UPDATE drives SET data_quality=')
        assert "'unmappable_legacy'" in ddl
        assert 'source_drive_id IS NULL' in ddl
        # The default-guard preserves a more-specific existing marker.
        assert "data_quality='full'" in ddl

    def test_statsAddFkTargetsDrivesDriveId(self) -> None:
        ddl = m0022.ADD_DRIVE_STATISTICS_FK_DDL
        assert ddl.startswith('ALTER TABLE drive_statistics')
        assert f'ADD CONSTRAINT {m0022.DRIVE_STATISTICS_FK_NAME}' in ddl
        assert 'FOREIGN KEY (summary_id)' in ddl
        assert 'REFERENCES drives(drive_id)' in ddl
        assert 'ON DELETE CASCADE' in ddl

    def test_derivedAddFkTargetsDrivesDriveId(self) -> None:
        ddl = m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL
        assert ddl.startswith('ALTER TABLE drive_derived_signals')
        assert f'ADD CONSTRAINT {m0022.DRIVE_DERIVED_SIGNALS_FK_NAME}' in ddl
        assert 'FOREIGN KEY (summary_id)' in ddl
        assert 'REFERENCES drives(drive_id)' in ddl
        assert 'ON DELETE CASCADE' in ddl


# ================================================================================
# apply -- production state (the load-bearing deploy path)
# ================================================================================


class TestApplyProductionState:
    def test_widensCheckThenFlagsThenRepointsBothFks(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        m0022.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            m0022.DROP_DRIVES_CHECK_DDL,
            m0022.ADD_DRIVES_CHECK_DDL,
            f'ALTER TABLE drive_statistics DROP FOREIGN KEY {_STATS_STALE_FK};',
            m0022.ADD_DRIVE_STATISTICS_FK_DDL,
            f'ALTER TABLE drive_derived_signals DROP FOREIGN KEY '
            f'{_DERIVED_STALE_FK};',
            m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL,
        ], '\n  '.join(['unexpected ALTER set:', *alters])

    def test_emitsTheLegacyFlagUpdate(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        m0022.apply(_ctx(runner))
        updates = [
            s for s in runner.emittedSqls
            if s == m0022.FLAG_UNMAPPABLE_LEGACY_DDL
        ]
        assert len(updates) == 1, f'expected one flag UPDATE; got {updates}'

    def test_dropsStaleFkByDiscoveredName(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        m0022.apply(_ctx(runner))
        # The auto-named drive_statistics FK is discovered + dropped by name.
        assert any(
            f'DROP FOREIGN KEY {_STATS_STALE_FK}' in s
            for s in runner.emittedSqls
        )


# ================================================================================
# apply -- fully-migrated / fresh create_all (idempotent no-op)
# ================================================================================


class TestApplyFullyMigrated:
    def test_emitsNoAlterTable(self) -> None:
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0022.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'idempotent re-run must not ALTER; got {alters}'

    def test_emitsNoFkDrop(self) -> None:
        # FKs already reference drives -> no stale FK to drop.  (The flag UPDATE
        # is still emitted; it is idempotent -- matches 0 rows -- so apply()
        # completes without raising.)
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0022.apply(_ctx(runner))
        drops = [s for s in runner.emittedSqls if 'DROP FOREIGN KEY' in s]
        assert drops == [], f'idempotent re-run must not drop an FK; got {drops}'


# ================================================================================
# 3-state summary_id FK re-point (BL-020 / US-461 -- Atlas 3-state ruling)
# ================================================================================


class TestRepointThreeState:
    """``_repointSummaryFk`` branches per the table's APPLIED FK state.

    (1) FK -> drive_summary => drop + re-point;
    (2) FK -> drives        => no-op;
    (3) NO FK               => ADD-only (skip the drop).
    """

    def test_state1_staleFk_dropsThenAdds(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            m0022.DRIVE_DERIVED_SIGNALS_TABLE,
            _singleTableFkHandler(
                m0022.DRIVE_DERIVED_SIGNALS_TABLE,
                m0022.DRIVE_DERIVED_SIGNALS_FK_NAME,
                stale=_DERIVED_STALE_FK,
            ),
        ))
        m0022._repointSummaryFk(
            _ctx(runner),
            m0022.DRIVE_DERIVED_SIGNALS_TABLE,
            m0022.DRIVE_DERIVED_SIGNALS_FK_NAME,
            m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL,
        )
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            f'ALTER TABLE drive_derived_signals DROP FOREIGN KEY '
            f'{_DERIVED_STALE_FK};',
            m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL,
        ], f'state-1 must drop-then-add; got {alters}'

    def test_state2_alreadyDrives_isNoOp(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            m0022.DRIVE_STATISTICS_TABLE,
            _singleTableFkHandler(
                m0022.DRIVE_STATISTICS_TABLE,
                m0022.DRIVE_STATISTICS_FK_NAME,
                hasDrivesFk=True,
            ),
        ))
        m0022._repointSummaryFk(
            _ctx(runner),
            m0022.DRIVE_STATISTICS_TABLE,
            m0022.DRIVE_STATISTICS_FK_NAME,
            m0022.ADD_DRIVE_STATISTICS_FK_DDL,
        )
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'state-2 must be a no-op; got {alters}'

    def test_state3_noFk_addsOnly_noDrop(self) -> None:
        # BL-020 core: drive_statistics carries NO summary_id FK on the drifted
        # prod schema.  The old code fatalled here (line ~343); it must ADD-only.
        runner = FakeRunner()
        runner.handlers.append((
            m0022.DRIVE_STATISTICS_TABLE,
            _singleTableFkHandler(
                m0022.DRIVE_STATISTICS_TABLE,
                m0022.DRIVE_STATISTICS_FK_NAME,
            ),
        ))
        m0022._repointSummaryFk(
            _ctx(runner),
            m0022.DRIVE_STATISTICS_TABLE,
            m0022.DRIVE_STATISTICS_FK_NAME,
            m0022.ADD_DRIVE_STATISTICS_FK_DDL,
        )
        emitted = runner.emittedSqls
        assert m0022.ADD_DRIVE_STATISTICS_FK_DDL in emitted, (
            'state-3 must ADD the drives FK'
        )
        assert not any('DROP FOREIGN KEY' in s for s in emitted), (
            'state-3 must NOT drop (there is no stale FK to drop)'
        )

    def test_state3_orphans_failsLoudWithCount_noAdd(self) -> None:
        # Never ADD an FK that will not validate: orphan summary_id rows vs
        # drives.drive_id => fail loud with the count, before any ADD.
        runner = FakeRunner()
        runner.handlers.append((
            m0022.DRIVE_STATISTICS_TABLE,
            _singleTableFkHandler(
                m0022.DRIVE_STATISTICS_TABLE,
                m0022.DRIVE_STATISTICS_FK_NAME,
                orphans='4\n',
            ),
        ))
        with pytest.raises(asm.MigrationError, match='4'):
            m0022._repointSummaryFk(
                _ctx(runner),
                m0022.DRIVE_STATISTICS_TABLE,
                m0022.DRIVE_STATISTICS_FK_NAME,
                m0022.ADD_DRIVE_STATISTICS_FK_DDL,
            )
        assert not any(
            'ADD CONSTRAINT' in s for s in runner.emittedSqls
        ), 'must not ADD an FK that will not validate'

    def test_state1_orphans_failsLoud_afterDrop(self) -> None:
        # Orphan guard also applies on the state-1 re-point path.
        runner = FakeRunner()
        runner.handlers.append((
            m0022.DRIVE_DERIVED_SIGNALS_TABLE,
            _singleTableFkHandler(
                m0022.DRIVE_DERIVED_SIGNALS_TABLE,
                m0022.DRIVE_DERIVED_SIGNALS_FK_NAME,
                stale=_DERIVED_STALE_FK,
                orphans='7\n',
            ),
        ))
        with pytest.raises(asm.MigrationError, match='7'):
            m0022._repointSummaryFk(
                _ctx(runner),
                m0022.DRIVE_DERIVED_SIGNALS_TABLE,
                m0022.DRIVE_DERIVED_SIGNALS_FK_NAME,
                m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL,
            )
        assert not any(
            'ADD CONSTRAINT' in s for s in runner.emittedSqls
        ), 'must not ADD an FK that will not validate'


class TestApplyDriftedProduction:
    """The real BL-020 prod shape: drive_statistics state-3, derived state-1."""

    def _scriptDriftedProd(self, runner: FakeRunner) -> None:
        # drives.data_quality CHECK: stale then widened (counter, mirrors v0015).
        clauseCalls = {'n': 0}

        def clause(_s: str) -> subprocess.CompletedProcess[str]:
            clauseCalls['n'] += 1
            return _ok(stdout=_DRIVES_CLAUSE_STALE if clauseCalls['n'] == 1
                       else _DRIVES_CLAUSE_WIDE)

        runner.handlers.append(('information_schema.CHECK_CONSTRAINTS', clause))
        runner.handlers.append(('information_schema.TABLES', _tablesHandler()))
        runner.handlers.append((
            'SELECT COUNT(*) FROM drives', lambda _s: _ok(stdout='0\n'),
        ))
        # Orphan probes: 0 for both tables.
        runner.handlers.append(('LEFT JOIN drives', lambda _s: _ok(stdout='0\n')))
        # drive_statistics: state-3 (no FK, flips to present after ADD).
        statsAdded = {'v': False}

        def statsFk(sql: str) -> subprocess.CompletedProcess[str]:
            if 'ADD CONSTRAINT' in sql:
                statsAdded['v'] = True
                return _ok()
            if "REFERENCED_TABLE_NAME='drive_summary'" in sql:
                return _ok(stdout='')
            return _ok(stdout=f'{m0022.DRIVE_STATISTICS_FK_NAME}\n'
                       if statsAdded['v'] else '')

        # drive_derived_signals: state-1 (stale FK, drives-ref after drop+add).
        derivedAdded = {'v': False}

        def derivedFk(sql: str) -> subprocess.CompletedProcess[str]:
            if 'ADD CONSTRAINT' in sql:
                derivedAdded['v'] = True
                return _ok()
            if "REFERENCED_TABLE_NAME='drive_summary'" in sql:
                return _ok(stdout=f'{_DERIVED_STALE_FK}\n'
                           if not derivedAdded['v'] else '')
            return _ok(stdout=f'{m0022.DRIVE_DERIVED_SIGNALS_FK_NAME}\n'
                       if derivedAdded['v'] else '')

        # Route KEY_COLUMN_USAGE by table (needle 'KEY_COLUMN_USAGE' + table).
        def fkRouter(sql: str) -> subprocess.CompletedProcess[str]:
            if "TABLE_NAME='drive_statistics'" in sql:
                return statsFk(sql)
            return derivedFk(sql)

        # ADD CONSTRAINT is table-specific; route by FK name.
        def addRouter(sql: str) -> subprocess.CompletedProcess[str]:
            if m0022.DRIVE_STATISTICS_FK_NAME in sql:
                return statsFk(sql)
            return derivedFk(sql)

        runner.handlers.append(('information_schema.KEY_COLUMN_USAGE', fkRouter))
        runner.handlers.append(('ADD CONSTRAINT fk_drive_statistics_drives', addRouter))
        runner.handlers.append((
            'ADD CONSTRAINT fk_drive_derived_signals_drives', addRouter,
        ))

    def test_statsAddsOnly_derivedDropsThenAdds(self) -> None:
        runner = FakeRunner()
        self._scriptDriftedProd(runner)
        m0022.apply(_ctx(runner))
        drops = [s for s in runner.emittedSqls if 'DROP FOREIGN KEY' in s]
        # Only the state-1 table (drive_derived_signals) drops a stale FK.
        assert drops == [
            f'ALTER TABLE drive_derived_signals DROP FOREIGN KEY '
            f'{_DERIVED_STALE_FK};',
        ], f'only derived (state-1) drops; got {drops}'
        adds = [s for s in runner.emittedSqls if 'ADD CONSTRAINT' in s
                and 'fk_drive_' in s]
        assert m0022.ADD_DRIVE_STATISTICS_FK_DDL in adds
        assert m0022.ADD_DRIVE_DERIVED_SIGNALS_FK_DDL in adds


# ================================================================================
# Failure paths
# ================================================================================


class TestFailureModes:
    def test_drivesTableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            _tablesHandler(missing=frozenset({'drives'})),
        ))
        with pytest.raises(asm.MigrationError, match='drives'):
            m0022.apply(_ctx(runner))

    def test_checkPostProbeStillStaleRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(('information_schema.TABLES', _tablesHandler()))
        # Both entry + post probes return the stale clause -> post-condition trips.
        runner.handlers.append((
            'information_schema.CHECK_CONSTRAINTS',
            lambda _s: _ok(stdout=_DRIVES_CLAUSE_STALE),
        ))
        with pytest.raises(asm.SchemaProbeError, match='unmappable_legacy'):
            m0022.apply(_ctx(runner))

    def test_legacyFlagSurvivorsRaises(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner, legacySurvivorsAfter='3\n')
        with pytest.raises(asm.SchemaProbeError, match='NULL-natural-key'):
            m0022.apply(_ctx(runner))

    def test_addFkFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        runner.handlers.insert(0, (
            f'ADD CONSTRAINT {m0022.DRIVE_STATISTICS_FK_NAME}',
            lambda _s: _fail('Cannot add foreign key constraint'),
        ))
        with pytest.raises(asm.MigrationError, match='fk_drive_statistics_drives'):
            m0022.apply(_ctx(runner))
