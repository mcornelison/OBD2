################################################################################
# File Name: test_drive_statistics_pi_table_migration.py
# Purpose/Description: Sprint 33 US-328 / I-028 / BL-015 Option C regression test
#                      -- the Pi-side SQLite schema must ship an idempotent
#                      ``CREATE TABLE IF NOT EXISTS drive_statistics`` whose
#                      column shape mirrors the server-side ``drive_statistics``
#                      table (src/server/db/models.py:DriveStatistic).  No
#                      Pi-side writer is wired (Option C hybrid -- the table
#                      ships empty, ready for the V0.28 B-075 Pi-side
#                      compute-at-drive-end work); this story only stops the Pi
#                      diagnostic query ``SELECT * FROM drive_statistics`` from
#                      erroring with "no such table".
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-328) | Initial -- BL-015 Option C Pi-side table.
# ================================================================================
################################################################################

"""Pi-side ``drive_statistics`` table migration regression test (US-328 / I-028).

Why this exists
---------------

Spool's Drive 11 validation hit ``Error: no such table: drive_statistics``
running a diagnostic query against the Pi DB -- the Pi schema never carried the
table (``src/pi/obdii/drive_id.py`` explicitly calls it a "server-side
addition").  BL-015 resolved this as **Option C (hybrid)**: ship a thin
idempotent Pi-side ``CREATE TABLE IF NOT EXISTS drive_statistics`` in
:mod:`src.pi.obdii.database_schema` that columns-match the server-side
``drive_statistics`` table, with **no** Pi-side writer and **no** sync change.
The full Approach-2 redesign (Pi computes at drive_end + sync pushes the rows)
is deferred to B-075 for the V0.28.0 feature sprint per the V0.27.X =
bug-fixes-only standing rule.

Discriminator
-------------

:meth:`TestFreshSchema.test_tableIsCreated` is RED against pre-fix code
(the table is absent from ``ALL_SCHEMAS``) and GREEN once
``SCHEMA_DRIVE_STATISTICS`` is added.  :meth:`TestFreshSchema
.test_selectCountReturnsZeroNotNoSuchTable` is the literal acceptance criterion
("the Pi diagnostic query stops erroring").
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii import database_schema
from src.pi.obdii.database import DatabaseConnectionError, ObdDatabase
from src.pi.obdii.database_schema import ALL_SCHEMAS

DRIVE_STATISTICS_TABLE = "drive_statistics"

# The server-side column shape this Pi table mirrors.  Source of truth:
# ``src/server/db/models.py:DriveStatistic`` (US-324 / I-024).  Pinned as a
# literal here so the Pi test does not import SQLAlchemy (a server-only dep
# absent on the Pi); ``TestColumnsMatchServerOrm`` cross-checks it against the
# live ORM model when SQLAlchemy is available.
_SERVER_DRIVE_STATISTICS_COLUMNS = {
    "id",
    "drive_id",
    "parameter_name",
    "min_value",
    "max_value",
    "avg_value",
    "std_dev",
    "outlier_min",
    "outlier_max",
    "sample_count",
    "computed_at",
}


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_drivestats.db"), walMode=False)
    db.initialize()
    return db


class TestFreshSchema:
    """After initialize(), drive_statistics exists with the server column shape."""

    def test_tableIsCreated(self, freshDb: ObdDatabase) -> None:
        assert DRIVE_STATISTICS_TABLE in freshDb.getTableNames()

    def test_columnShapeMirrorsServer(self, freshDb: ObdDatabase) -> None:
        cols = {c["name"] for c in freshDb.getTableInfo(DRIVE_STATISTICS_TABLE)}
        assert cols == _SERVER_DRIVE_STATISTICS_COLUMNS

    def test_idIsPrimaryKey(self, freshDb: ObdDatabase) -> None:
        cols = {c["name"]: c for c in freshDb.getTableInfo(DRIVE_STATISTICS_TABLE)}
        assert cols["id"]["pk"] == 1

    def test_driveIdAndParameterNameAreNotNull(self, freshDb: ObdDatabase) -> None:
        cols = {c["name"]: c for c in freshDb.getTableInfo(DRIVE_STATISTICS_TABLE)}
        assert cols["drive_id"]["notnull"] == 1
        assert cols["parameter_name"]["notnull"] == 1

    def test_aggregateColumnsAreNullable(self, freshDb: ObdDatabase) -> None:
        cols = {c["name"]: c for c in freshDb.getTableInfo(DRIVE_STATISTICS_TABLE)}
        for name in (
            "min_value", "max_value", "avg_value", "std_dev",
            "outlier_min", "outlier_max", "sample_count",
        ):
            assert cols[name]["notnull"] == 0, f"{name} must be nullable"

    def test_selectCountReturnsZeroNotNoSuchTable(self, freshDb: ObdDatabase) -> None:
        """The literal acceptance criterion -- the Pi diagnostic query works."""
        with freshDb.connect() as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {DRIVE_STATISTICS_TABLE}"
            ).fetchone()[0]
        assert count == 0

    def test_tableShipsEmpty_noWriterWired(self, freshDb: ObdDatabase) -> None:
        """Option C: the Pi-side table is created but stays empty (no writer)."""
        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {DRIVE_STATISTICS_TABLE}"
            ).fetchall()
        assert rows == []

    def test_computedAtDefaultsToCanonicalIsoUtc(self, freshDb: ObdDatabase) -> None:
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {DRIVE_STATISTICS_TABLE} "
                "(drive_id, parameter_name) VALUES (1, 'RPM')"
            )
            stored = conn.execute(
                f"SELECT computed_at FROM {DRIVE_STATISTICS_TABLE} "
                "WHERE drive_id = 1"
            ).fetchone()[0]
        # Canonical ISO-8601 UTC: YYYY-MM-DDTHH:MM:SSZ (20 chars).
        assert stored.endswith("Z")
        assert "T" in stored
        assert len(stored) == 20


class TestMigrationIdempotency:
    """The CREATE TABLE IF NOT EXISTS is idempotent across re-initialisation."""

    def test_initializeTwiceDoesNotRaise(self, tmp_path: Path) -> None:
        db = ObdDatabase(str(tmp_path / "twice.db"), walMode=False)
        assert db.initialize() is True
        assert db.initialize() is True  # no exception = pass
        assert DRIVE_STATISTICS_TABLE in db.getTableNames()

    def test_reInitOnExistingDbPreservesRows(self, tmp_path: Path) -> None:
        """A pre-existing drive_statistics row survives a re-run of initialize()."""
        path = tmp_path / "existing.db"
        db = ObdDatabase(str(path), walMode=False)
        db.initialize()
        with db.connect() as conn:
            conn.execute(
                f"INSERT INTO {DRIVE_STATISTICS_TABLE} "
                "(drive_id, parameter_name, avg_value, sample_count) "
                "VALUES (?, ?, ?, ?)",
                (7, "COOLANT_TEMP", 85.0, 120),
            )

        # Re-open + re-initialize (simulates the next Pi boot).
        db2 = ObdDatabase(str(path), walMode=False)
        db2.initialize()
        with db2.connect() as conn:
            rows = conn.execute(
                f"SELECT drive_id, parameter_name, avg_value, sample_count "
                f"FROM {DRIVE_STATISTICS_TABLE}"
            ).fetchall()
        assert [tuple(r) for r in rows] == [(7, "COOLANT_TEMP", 85.0, 120)]

    def test_legacyDbMissingTablePicksItUpOnInitialize(self, tmp_path: Path) -> None:
        """A legacy Pi DB without drive_statistics gains it on the next boot.

        Simulates a pre-US-328 production DB: it has the rest of the schema but
        not ``drive_statistics``.  ``ObdDatabase.initialize`` iterates
        ``ALL_SCHEMAS`` with ``CREATE TABLE IF NOT EXISTS``, so the table
        appears without disturbing anything else.
        """
        path = tmp_path / "legacy.db"
        legacyConn = sqlite3.connect(str(path))
        # A representative slice of the pre-US-328 schema (the bits a real
        # legacy DB would already have) -- intentionally NOT drive_statistics.
        legacyConn.execute(
            "CREATE TABLE drive_counter ("
            "id INTEGER PRIMARY KEY CHECK (id=1), "
            "last_drive_id INTEGER NOT NULL DEFAULT 0)"
        )
        legacyConn.execute("INSERT INTO drive_counter (id, last_drive_id) VALUES (1, 11)")
        legacyConn.commit()
        legacyConn.close()

        # Before: table missing.
        probeConn = sqlite3.connect(str(path))
        missing = probeConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_statistics'"
        ).fetchone()
        probeConn.close()
        assert missing is None

        # Next boot.
        ObdDatabase(str(path), walMode=False).initialize()

        afterConn = sqlite3.connect(str(path))
        present = afterConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_statistics'"
        ).fetchone()
        counter = afterConn.execute(
            "SELECT last_drive_id FROM drive_counter WHERE id = 1"
        ).fetchone()
        afterConn.close()
        assert present is not None
        assert counter == (11,), "the migration must not disturb existing tables"


class TestRegisteredInAllSchemas:
    """drive_statistics is wired into ALL_SCHEMAS so initialize() creates it."""

    def test_driveStatisticsInAllSchemas(self) -> None:
        names = [name for name, _ in ALL_SCHEMAS]
        assert DRIVE_STATISTICS_TABLE in names

    def test_schemaConstantUsesCreateIfNotExists(self) -> None:
        ddl = database_schema.SCHEMA_DRIVE_STATISTICS
        assert "CREATE TABLE IF NOT EXISTS drive_statistics" in ddl

    def test_schemaConstantUsesCanonicalStrftimeDefault(self) -> None:
        ddl = database_schema.SCHEMA_DRIVE_STATISTICS
        assert "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')" in ddl

    def test_schemaConstantHasNoWriterSideColumns(self) -> None:
        """Option C ships the table only -- no data_source / sync columns."""
        ddl = database_schema.SCHEMA_DRIVE_STATISTICS
        # data_source is a writer concern; the server drive_statistics has no
        # such column either, and there is no Pi-side writer in Option C.
        assert "data_source" not in ddl


class TestColumnsMatchServerOrm:
    """Cross-check the literal column set against the live server ORM model."""

    def test_piColumnSetEqualsServerOrmColumnSet(self) -> None:
        pytest.importorskip("sqlalchemy")
        from src.server.db.models import DriveStatistic

        serverCols = {c.name for c in DriveStatistic.__table__.columns}
        assert serverCols == _SERVER_DRIVE_STATISTICS_COLUMNS, (
            "the pinned _SERVER_DRIVE_STATISTICS_COLUMNS set has drifted from "
            "src/server/db/models.py:DriveStatistic -- update both together"
        )


class TestSchemaDdlRejectsMissingNotNull:
    """The DDL's NOT NULL constraints behave (drive_id + parameter_name)."""

    def test_insertWithoutParameterNameRaises(self, freshDb: ObdDatabase) -> None:
        with pytest.raises((sqlite3.IntegrityError, DatabaseConnectionError)):
            with freshDb.connect() as conn:
                conn.execute(
                    f"INSERT INTO {DRIVE_STATISTICS_TABLE} (drive_id) VALUES (1)"
                )
