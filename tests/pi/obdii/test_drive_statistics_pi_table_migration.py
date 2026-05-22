################################################################################
# File Name: test_drive_statistics_pi_table_migration.py
# Purpose/Description: US-351 / B-104 Step 1b retirement test -- replaces the
#                      V0.27.7 US-328 "Option C table-only" creation test.
#                      Asserts the Pi-side ``drive_statistics`` table is:
#                        (a) NOT in ALL_SCHEMAS,
#                        (b) DROPPED on fresh ObdDatabase initialize() (legacy
#                            DBs lose the table cleanly),
#                        (c) the schema constant SCHEMA_DRIVE_STATISTICS is
#                            removed,
#                        (d) the ensureDriveStatisticsRetired migration is
#                            idempotent across re-runs (first call drops,
#                            subsequent calls are no-ops).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-12
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-12    | Rex (US-328) | Initial -- BL-015 Option C Pi-side table.
# 2026-05-21    | Rex (US-351) | REPURPOSED -- B-104 Step 1b Pi-side retirement.
#                              | Was: assert the table is created and column-shape
#                              | matches server.  Now: assert the table is retired
#                              | (not in ALL_SCHEMAS, schema constant absent,
#                              | DROP TABLE migration idempotent, legacy DB loses
#                              | the table cleanly on next boot).
# ================================================================================
################################################################################

"""Pi-side ``drive_statistics`` table retirement regression test (US-351).

Why this exists
---------------

V0.27.16 sprint 40 wired a Pi-side ``DriveStatisticsRecorder`` to the V0.27.7
Option C table.  Argus's 2026-05-21 drill confirmed the writer never fired
on the sequencer-driven termination path (drive 20 = 3,808 realtime rows but
zero drive_statistics rows -- same shape as the V0.27.7 false-pass class).
CIO ratified full retirement of the Pi-side table for V0.27.17; server is
sole writer now via :mod:`src.server.analytics.drive_statistics_compute`.

This test pins the retirement so a future accidental resurrection (e.g.
someone re-adds the schema constant + ALL_SCHEMAS entry) trips RED here
before it ships.

Discriminators
--------------

* :meth:`TestSchemaConstantRetired.test_schemaConstantIsRemoved` -- the
  ``SCHEMA_DRIVE_STATISTICS`` symbol is gone from ``database_schema``.
* :meth:`TestSchemaConstantRetired.test_notInAllSchemas` -- ``drive_statistics``
  no longer appears in ``ALL_SCHEMAS``, so :meth:`ObdDatabase.initialize`
  does NOT create the table.
* :meth:`TestRetirementMigration.test_legacyDbLosesTableOnNextBoot` -- a
  pre-V0.27.17 legacy DB that already carries the table sees it dropped on
  the next ``initialize()`` call.
* :meth:`TestRetirementMigration.test_secondInitializeIsNoOp` -- the migration
  is idempotent (table absent -> migration returns False quietly).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii import database_schema
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.database_schema import (
    ALL_SCHEMAS,
    ensureDriveStatisticsRetired,
)

DRIVE_STATISTICS_TABLE = "drive_statistics"


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_drivestats_retired.db"), walMode=False)
    db.initialize()
    return db


class TestSchemaConstantRetired:
    """The Pi schema constant + ALL_SCHEMAS entry are gone."""

    def test_schemaConstantIsRemoved(self) -> None:
        """``SCHEMA_DRIVE_STATISTICS`` symbol is gone."""
        assert not hasattr(database_schema, "SCHEMA_DRIVE_STATISTICS"), (
            "SCHEMA_DRIVE_STATISTICS was retired in US-351 -- re-adding the "
            "constant would resurrect the Pi-side writer surface that "
            "shipped three cycles of false-pass behavior"
        )

    def test_notInAllSchemas(self) -> None:
        """``drive_statistics`` no longer appears in ALL_SCHEMAS."""
        names = [name for name, _ in ALL_SCHEMAS]
        assert DRIVE_STATISTICS_TABLE not in names

    def test_freshDbHasNoDriveStatisticsTable(self, freshDb: ObdDatabase) -> None:
        """A fresh Pi DB initialize() does NOT create the table."""
        assert DRIVE_STATISTICS_TABLE not in freshDb.getTableNames()


class TestRetirementMigration:
    """``ensureDriveStatisticsRetired`` is idempotent."""

    def test_legacyDbLosesTableOnNextBoot(self, tmp_path: Path) -> None:
        """Pre-V0.27.17 DB with the table -> next ``initialize()`` drops it."""
        path = tmp_path / "legacy.db"
        legacyConn = sqlite3.connect(str(path))
        legacyConn.execute(
            "CREATE TABLE drive_statistics ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "drive_id INTEGER NOT NULL, "
            "parameter_name TEXT NOT NULL, "
            "min_value REAL, max_value REAL, avg_value REAL, "
            "std_dev REAL, outlier_min REAL, outlier_max REAL, "
            "sample_count INTEGER, "
            "computed_at DATETIME"
            ")"
        )
        # Seed a row so the dropped-row-count log is non-zero (forensic
        # auditability check; production has zero rows but the log line
        # should still fire on row count > 0 when legacy data exists).
        legacyConn.execute(
            "INSERT INTO drive_statistics "
            "(drive_id, parameter_name, sample_count) VALUES (?, ?, ?)",
            (1, "RPM", 42),
        )
        legacyConn.commit()

        # Confirm pre-state.
        probeConn = sqlite3.connect(str(path))
        present = probeConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_statistics'"
        ).fetchone()
        probeConn.close()
        assert present is not None

        # Next boot.
        ObdDatabase(str(path), walMode=False).initialize()

        # Confirm post-state.
        afterConn = sqlite3.connect(str(path))
        absent = afterConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'drive_statistics'"
        ).fetchone()
        afterConn.close()
        assert absent is None, "drive_statistics table must be retired on next boot"

    def test_secondInitializeIsNoOp(self, freshDb: ObdDatabase) -> None:
        """``initialize()`` twice on the same DB is safe and idempotent."""
        with freshDb.connect() as conn:
            assert ensureDriveStatisticsRetired(conn) is False  # absent on fresh
        freshDb.initialize()  # second initialize must not raise
        assert DRIVE_STATISTICS_TABLE not in freshDb.getTableNames()

    def test_ensureDriveStatisticsRetired_returnsTrueOnFirstDrop_falseOnAbsent(
        self, tmp_path: Path,
    ) -> None:
        """Return value pins idempotency: True iff drop occurred."""
        path = tmp_path / "rv.db"
        legacyConn = sqlite3.connect(str(path))
        legacyConn.execute(
            "CREATE TABLE drive_statistics (id INTEGER PRIMARY KEY)"
        )
        legacyConn.commit()
        legacyConn.close()

        with sqlite3.connect(str(path)) as conn:
            assert ensureDriveStatisticsRetired(conn) is True
            assert ensureDriveStatisticsRetired(conn) is False


class TestDoNotResurrectImports:
    """The Pi-side ``drive_statistics`` module is gone -- importing it must fail."""

    def test_piModuleImportFails(self) -> None:
        """``src.pi.obdii.drive_statistics`` no longer exists."""
        with pytest.raises(ImportError):
            import src.pi.obdii.drive_statistics  # noqa: F401
