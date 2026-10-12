################################################################################
# File Name: test_production_schema_snapshot.py
# Purpose/Description: US-807 -- hermetic tests for the pinned PRODUCTION schema
#   snapshot that the A-4 applied-schema parity gate builds its database from,
#   and for the script that regenerates it.
#
# WHY A SNAPSHOT (CIO ruling 2026-10-06)
#   The live gate used to provision with create_all and then compare against
#   the same models -- MariaDB rendering the models back to themselves, which
#   cannot see "a model moved and no migration was written" (BL-019). The CI
#   now builds the database production actually HAS (SHOW CREATE TABLE, read
#   from obd2db), stamps production's own migration ledger, runs every newer
#   migration forward, and only then compares. These tests pin the properties
#   that make that comparison mean something.
#
# Author: Atlas (Architect) -- US-807, CIO-directed build
# Creation Date: 2026-10-06
################################################################################

from __future__ import annotations

import pytest

from scripts import audit_sync_contract_parity as parity
from scripts import snapshot_production_schema as gen
from src.server.migrations import ALL_MIGRATIONS
from tests.server import _mariadb_chain_harness as harness
from tests.server import _production_schema_snapshot as snapshot

# ================================================================================
# The generator -- pure functions, no production access
# ================================================================================


class TestSanitizeCreateTable:

    def test_stripsTheAutoIncrementCounter(self) -> None:
        ddl = (
            'CREATE TABLE `t` (\n  `id` int(11) NOT NULL AUTO_INCREMENT,\n'
            '  PRIMARY KEY (`id`)\n) ENGINE=InnoDB AUTO_INCREMENT=4102148 '
            'DEFAULT CHARSET=utf8mb4'
        )
        out = gen.sanitizeCreateTable(ddl)
        assert 'AUTO_INCREMENT=' not in out
        # The COLUMN attribute is schema, not state -- it must survive.
        assert '`id` int(11) NOT NULL AUTO_INCREMENT,' in out
        assert out.endswith('ENGINE=InnoDB DEFAULT CHARSET=utf8mb4')

    def test_leavesEverythingElseByteIdentical(self) -> None:
        ddl = "CREATE TABLE `t` (\n  `a` varchar(16) DEFAULT 'x'\n) ENGINE=InnoDB"
        assert gen.sanitizeCreateTable(ddl) == ddl


class TestParseShowCreate:

    def test_returnsTheDdlAfterTheTableName(self) -> None:
        stdout = 'drives\tCREATE TABLE `drives` (\n  `id` int(11)\n) ENGINE=InnoDB\n'
        assert gen.parseShowCreate(stdout, 'drives') == (
            'CREATE TABLE `drives` (\n  `id` int(11)\n) ENGINE=InnoDB'
        )

    def test_refusesOutputForADifferentTable(self) -> None:
        with pytest.raises(ValueError, match='expected SHOW CREATE TABLE for drives'):
            gen.parseShowCreate('other\tCREATE TABLE `other` ()\n', 'drives')

    def test_refusesEmptyOutput_neverPinsANothing(self) -> None:
        with pytest.raises(ValueError):
            gen.parseShowCreate('', 'drives')


class TestRenderSnapshotModule:

    def test_renderedModuleRoundTripsTheData(self) -> None:
        tables = {
            'b_table': "CREATE TABLE `b_table` (\n  `x` varchar(4) DEFAULT 'q'\n)",
            'a_table': 'CREATE TABLE `a_table` (\n  `y` int(11)\n)',
        }
        source = gen.renderSnapshotModule(
            tables=tables,
            ledger=('0002', '0001'),
            measuredAt='2026-10-06T00:00:00Z',
            serverVersion='11.8.6-MariaDB',
            database='obd2db',
        )
        namespace: dict = {}
        exec(compile(source, '<snapshot>', 'exec'), namespace)  # noqa: S102
        assert namespace['PRODUCTION_TABLE_DDL'] == tables
        assert list(namespace['PRODUCTION_TABLE_DDL']) == ['a_table', 'b_table']
        assert namespace['PRODUCTION_LEDGER'] == ('0001', '0002')
        assert namespace['MEASURED_AT'] == '2026-10-06T00:00:00Z'
        assert namespace['SERVER_VERSION'] == '11.8.6-MariaDB'

    def test_aBackslashInTheDdlStillRoundTrips(self) -> None:
        tables = {'t': "CREATE TABLE `t` (\n  `p` varchar(8) COMMENT 'a\\\\b'\n)"}
        source = gen.renderSnapshotModule(
            tables=tables, ledger=('0001',), measuredAt='x',
            serverVersion='y', database='obd2db',
        )
        namespace: dict = {}
        exec(compile(source, '<snapshot>', 'exec'), namespace)  # noqa: S102
        assert namespace['PRODUCTION_TABLE_DDL'] == tables


# ================================================================================
# The pinned snapshot -- the properties the live gate relies on
# ================================================================================


class TestPinnedSnapshot:

    def test_itWasMeasuredAndSaysWhere(self) -> None:
        assert snapshot.DATABASE == 'obd2db'
        assert snapshot.SERVER_VERSION.startswith(f'{harness.MARIADB_MAJOR}.')
        assert snapshot.MEASURED_AT.endswith('Z')

    def test_ledgerIsAPrefixOfTheRealMigrations_neverFromTheFuture(self) -> None:
        """Every pinned version must exist in the code. A ledger naming a
        migration the code lacks would make the runner skip nothing and plan
        nothing -- the forward run would test less than it claims."""
        known = [m.version for m in ALL_MIGRATIONS]
        assert snapshot.PRODUCTION_LEDGER, 'an empty ledger replays the whole chain'
        assert list(snapshot.PRODUCTION_LEDGER) == known[: len(snapshot.PRODUCTION_LEDGER)]

    def test_everySyncedTableIsPinned(self) -> None:
        """A synced table missing from the snapshot would read as 'a migration
        never ran' in the live gate -- an artefact of the pin, not drift."""
        missing = sorted(set(parity.syncedTables()) - set(snapshot.PRODUCTION_TABLE_DDL))
        assert not missing, f'synced tables absent from the snapshot: {missing}'

    def test_noRowCounterLeaksIntoTheSchema(self) -> None:
        for name, ddl in snapshot.PRODUCTION_TABLE_DDL.items():
            assert 'AUTO_INCREMENT=' not in ddl, name

    def test_theLedgerTableIsRebuiltByTheHarness_notPinned(self) -> None:
        assert harness.SCHEMA_MIGRATIONS_TABLE not in snapshot.PRODUCTION_TABLE_DDL

    def test_eachEntryCreatesTheTableItIsFiledUnder(self) -> None:
        for name, ddl in snapshot.PRODUCTION_TABLE_DDL.items():
            assert ddl.startswith(f'CREATE TABLE `{name}` ('), name


class TestProductionSnapshotStatements:

    def test_buildsWithForeignKeysOff_andRestoresThem(self) -> None:
        statements = harness.productionSnapshotStatements()
        assert statements[0] == 'SET FOREIGN_KEY_CHECKS=0;'
        assert statements[-1] == 'SET FOREIGN_KEY_CHECKS=1;'

    def test_createsEveryPinnedTable_andStampsTheLedger(self) -> None:
        joined = '\n'.join(harness.productionSnapshotStatements())
        for name in snapshot.PRODUCTION_TABLE_DDL:
            assert f'CREATE TABLE `{name}` (' in joined, name
        for version in snapshot.PRODUCTION_LEDGER:
            assert f"VALUES ('{version}', 'seeded-applied');" in joined, version
