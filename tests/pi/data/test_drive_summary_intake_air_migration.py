# ==============================================================================
# File:    tests/pi/data/test_drive_summary_intake_air_migration.py
# Purpose: Guard the Pi half of the A-4 intake-air rename against the A-10 class.
# Author:  Atlas (Architect) -- CIO-directed, 2026-08-27
#
# Why this file exists, and why a fresh-DB test would NOT do
# ----------------------------------------------------------
# `ensureDriveSummaryTable` is the only schema-evolution path this table has,
# and it is `CREATE TABLE IF NOT EXISTS`.  On a database where the table
# ALREADY EXISTS that statement is a silent no-op.  So renaming the column in
# SCHEMA_DRIVE_SUMMARY and nothing else produces:
#
#   fresh DB   -> new column created, every test green, looks finished
#   live Pi    -> table untouched, still `ambient_temp_at_start_c`, and every
#                 renamed read/write raises `sqlite3.OperationalError:
#                 no such column` -> drive-summary capture DIES on the car
#
# Verified on the live Pi 2026-08-27: `PRAGMA table_info(drive_summary)` showed
# `ambient_temp_at_start_c` over 38 real rows.
#
# That is the A-10 class -- schema-constant vs APPLIED-schema divergence -- which
# has fired four times server-side on this project (BL-019/020/021, and the
# US-459 mocked-green trap).  Its signature every time: the suite builds its
# schema from the constant, so it goes green over a database that does not
# match.  Therefore every test here seeds the OLD shape explicitly and asserts
# against `PRAGMA table_info`, never against the constant.
# ==============================================================================

from __future__ import annotations

import sqlite3

import pytest

from pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    ensureDriveSummaryTable,
)

# The pre-rename shape, spelled out literally rather than imported. Importing
# it would couple this guard to the very constant it exists to distrust.
LEGACY_SCHEMA = """
CREATE TABLE drive_summary (
    drive_id INTEGER PRIMARY KEY,
    drive_start_timestamp DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ambient_temp_at_start_c REAL,
    starting_battery_v REAL,
    barometric_kpa_at_start REAL,
    data_source TEXT NOT NULL DEFAULT 'real',
    _sync_modified_at TEXT
)
"""

OLD_COLUMN = 'ambient_temp_at_start_c'
NEW_COLUMN = 'intake_air_temp_at_start_c'


def appliedColumns(conn: sqlite3.Connection) -> list[str]:
    """Column names as the DATABASE reports them -- never from the constant."""
    rows = conn.execute(f'PRAGMA table_info({DRIVE_SUMMARY_TABLE})').fetchall()
    return [r[1] for r in rows]


@pytest.fixture
def legacyDb() -> sqlite3.Connection:
    """A database in the pre-rename shape, carrying real rows."""
    conn = sqlite3.connect(':memory:')
    conn.execute(LEGACY_SCHEMA)
    conn.executemany(
        'INSERT INTO drive_summary '
        '(drive_id, ambient_temp_at_start_c, starting_battery_v, data_source) '
        'VALUES (?, ?, ?, ?)',
        [
            (42, 26.0, 14.2, 'real'),
            (43, 32.0, 13.9, 'real'),
            (44, 34.0, 13.8, 'real'),
            (45, None, 12.7, 'real'),
        ],
    )
    conn.commit()
    return conn


class TestAppliedSchemaMigration:
    """The load-bearing case: an EXISTING table in the OLD shape."""

    def test_legacyTable_isMigratedToTheNewColumn(
        self, legacyDb: sqlite3.Connection
    ) -> None:
        """
        Given: a live database whose drive_summary predates the rename
        When: ensureDriveSummaryTable runs (as it does on every boot)
        Then: the APPLIED schema carries the new column and not the old

        This is the test that `CREATE TABLE IF NOT EXISTS` alone cannot pass.
        """
        assert OLD_COLUMN in appliedColumns(legacyDb), 'fixture must start legacy'

        ensureDriveSummaryTable(legacyDb)
        legacyDb.commit()

        applied = appliedColumns(legacyDb)
        assert NEW_COLUMN in applied, (
            f'{NEW_COLUMN} missing from the APPLIED schema -- '
            'CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so a '
            'rename of the schema constant alone leaves the live Pi behind and '
            'every renamed read raises "no such column". A migration is required.'
        )
        assert OLD_COLUMN not in applied, (
            f'{OLD_COLUMN} still present -- the rename must MOVE the column, '
            'not add a second one. Two columns for one fact is the A-4 disease.'
        )

    def test_migration_preservesExistingValues(
        self, legacyDb: sqlite3.Connection
    ) -> None:
        """
        Given: 4 real rows, one with a NULL reading
        When: the migration runs
        Then: every value survives under the new name, NULL included

        RENAME COLUMN preserves data; ADD+COPY+DROP might not. Assert the
        outcome rather than trusting the mechanism.
        """
        ensureDriveSummaryTable(legacyDb)
        legacyDb.commit()

        rows = legacyDb.execute(
            f'SELECT drive_id, {NEW_COLUMN} FROM drive_summary ORDER BY drive_id'
        ).fetchall()

        assert rows == [(42, 26.0), (43, 32.0), (44, 34.0), (45, None)], (
            'values did not survive the rename -- a migration that loses the '
            'reading is worse than the drift it fixes'
        )

    def test_migration_isIdempotent(self, legacyDb: sqlite3.Connection) -> None:
        """
        Given: a database already migrated
        When: ensureDriveSummaryTable runs again (every boot does)
        Then: it is a clean no-op, not an error

        A migration that throws on second run turns every reboot after the
        first into a crash-loop.
        """
        ensureDriveSummaryTable(legacyDb)
        legacyDb.commit()

        ensureDriveSummaryTable(legacyDb)  # must not raise
        ensureDriveSummaryTable(legacyDb)
        legacyDb.commit()

        applied = appliedColumns(legacyDb)
        assert applied.count(NEW_COLUMN) == 1
        assert OLD_COLUMN not in applied

    def test_freshDatabase_getsTheNewColumnDirectly(self) -> None:
        """
        Given: no table at all
        When: ensureDriveSummaryTable runs
        Then: the new column exists and the old never does

        The easy case. Kept because it must not regress -- but note it passes
        even WITHOUT the migration, which is exactly why it cannot be the only
        test. See this file's header.
        """
        conn = sqlite3.connect(':memory:')

        created = ensureDriveSummaryTable(conn)
        conn.commit()

        assert created is True
        applied = appliedColumns(conn)
        assert NEW_COLUMN in applied
        assert OLD_COLUMN not in applied

    def test_writePathWorksAgainstAMigratedLegacyDatabase(
        self, legacyDb: sqlite3.Connection
    ) -> None:
        """
        Given: a migrated legacy database
        When: a row is written the way the production code writes it
        Then: it succeeds

        The end-to-end shape of the failure this file guards: the migration
        could rename the column and still leave the write path broken if the
        two disagree. Bind them together in one assertion.
        """
        ensureDriveSummaryTable(legacyDb)
        legacyDb.commit()

        legacyDb.execute(
            'INSERT INTO drive_summary '
            f'(drive_id, {NEW_COLUMN}, starting_battery_v, data_source) '
            'VALUES (?, ?, ?, ?)',
            (46, 24.5, 12.6, 'real'),
        )
        legacyDb.commit()

        stored = legacyDb.execute(
            f'SELECT {NEW_COLUMN} FROM drive_summary WHERE drive_id = 46'
        ).fetchone()
        assert stored == (24.5,)
