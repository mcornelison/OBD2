################################################################################
# File Name: test_data_source_foreign_marker.py
# Purpose/Description: US-424 (F-116) foreign-vehicle contamination marker --
#                      data_source='foreign' axis.  Pins the SSOT propagation
#                      (every Pi capture-table CHECK derives from
#                      DATA_SOURCE_VALUES, A-4), the Pi<->server no-drift
#                      invariant, and the forward-only SQLite CHECK-widen
#                      table-rebuild migration (rows + indexes preserved,
#                      idempotent).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-424) | Initial -- foreign-vehicle data_source marker.
# ================================================================================
################################################################################

"""US-424 / F-116 -- ``data_source='foreign'`` marker + CHECK-widen migration."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Generator

import pytest

from src.pi.obdii import (
    database_schema,
    dtc_freeze_frame_schema,
    dtc_log_schema,
)
from src.pi.obdii import (
    drive_summary as drive_summary_schema,
)
from src.pi.obdii.data_source import (
    DATA_SOURCE_CHECK_CLAUSE,
    DATA_SOURCE_COLUMN_DDL,
    DATA_SOURCE_VALUES,
    ensureDataSourceCheckWidened,
)
from src.pi.power import battery_health as battery_health_schema
from src.server.db.models import DATA_SOURCE_VALUES as SERVER_DATA_SOURCE_VALUES

# Every production schema string that carries a data_source CHECK.  The A-4
# guard below asserts each one's enum list equals the SSOT tuple.
_SCHEMAS_WITH_DATA_SOURCE_CHECK: dict[str, str] = {
    'profiles': database_schema.SCHEMA_PROFILES,
    'realtime_data': database_schema.SCHEMA_REALTIME_DATA,
    'statistics': database_schema.SCHEMA_STATISTICS,
    'calibration_sessions': database_schema.SCHEMA_CALIBRATION_SESSIONS,
    'connection_log': database_schema.SCHEMA_CONNECTION_LOG,
    'drive_summary': drive_summary_schema.SCHEMA_DRIVE_SUMMARY,
    'dtc_log': dtc_log_schema.SCHEMA_DTC_LOG,
    'dtc_freeze_frame': dtc_freeze_frame_schema.SCHEMA_DTC_FREEZE_FRAME,
    'battery_health_log': battery_health_schema.SCHEMA_BATTERY_HEALTH_LOG,
}

_CHECK_LIST_RE = re.compile(r"data_source\s+IN\s*\(([^)]*)\)")


def _checkEnumValues(schemaSql: str) -> tuple[str, ...]:
    """Extract the ``data_source IN (...)`` value tuple from a schema DDL."""
    match = _CHECK_LIST_RE.search(schemaSql)
    assert match is not None, "schema has no data_source CHECK list"
    raw = match.group(1)
    return tuple(v.strip().strip("'") for v in raw.split(','))


# ================================================================================
# Enum SSOT + cross-tier no-drift (A-4)
# ================================================================================


def test_foreignIsInEnum():
    """'foreign' is a member of the closed data_source set."""
    assert 'foreign' in DATA_SOURCE_VALUES


def test_foreignIsAppendedNotReplacing():
    """Adding 'foreign' preserves the prior Spool CR #4 order + values."""
    assert DATA_SOURCE_VALUES == (
        'real', 'replay', 'physics_sim', 'fixture', 'foreign',
    )


def test_piAndServerEnumsDoNotDrift():
    """A-4: the Pi and server data_source enums are pinned equal.

    They live in two modules (src/pi/obdii/data_source.py +
    src/server/db/models.py); this test is the single enforced contract that
    prevents them from silently diverging -- add a value to one, add it to both.
    """
    assert tuple(DATA_SOURCE_VALUES) == tuple(SERVER_DATA_SOURCE_VALUES)


# ================================================================================
# Derived DDL propagates the SSOT (define-once)
# ================================================================================


def test_checkClauseDerivesFromSsot():
    """DATA_SOURCE_CHECK_CLAUSE lists exactly the SSOT tuple, in order."""
    expected = "data_source IN (" + ",".join(
        f"'{v}'" for v in DATA_SOURCE_VALUES
    ) + ")"
    assert DATA_SOURCE_CHECK_CLAUSE == expected
    assert "'foreign'" in DATA_SOURCE_CHECK_CLAUSE


def test_columnDdlCarriesForeign():
    """The reusable column DDL (used by the ALTER migration) carries 'foreign'."""
    assert "'foreign'" in DATA_SOURCE_COLUMN_DDL
    assert DATA_SOURCE_CHECK_CLAUSE in DATA_SOURCE_COLUMN_DDL


@pytest.mark.parametrize('tableName', sorted(_SCHEMAS_WITH_DATA_SOURCE_CHECK))
def test_everySchemaCheckMatchesSsot(tableName):
    """A-4: every capture-table CHECK literal equals DATA_SOURCE_VALUES.

    This is the single enforced definition -- a hand-edit that widens one
    schema's CHECK but forgets another (or forgets DATA_SOURCE_VALUES) fails
    here rather than silently rejecting a 'foreign' write at runtime.
    """
    values = _checkEnumValues(_SCHEMAS_WITH_DATA_SOURCE_CHECK[tableName])
    assert values == tuple(DATA_SOURCE_VALUES)


# ================================================================================
# Fresh schema accepts 'foreign'
# ================================================================================


def test_freshRealtimeDataAcceptsForeign():
    """A fresh realtime_data (from the production schema) accepts 'foreign'."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(database_schema.SCHEMA_REALTIME_DATA)
        conn.execute(
            "INSERT INTO realtime_data "
            "(parameter_name, value, data_source, drive_id) "
            "VALUES (?, ?, ?, ?)",
            ("RPM", 3000.0, "foreign", 33),
        )
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM realtime_data WHERE data_source='foreign'",
        ).fetchone()
        assert count == 1
    finally:
        conn.close()


def test_freshRealtimeDataStillRejectsGarbage():
    """The CHECK still fails an unknown value -- it widened, it did not open."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(database_schema.SCHEMA_REALTIME_DATA)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO realtime_data "
                "(parameter_name, value, data_source) VALUES (?, ?, ?)",
                ("RPM", 3000.0, "martian"),
            )
    finally:
        conn.close()


# ================================================================================
# Forward-only CHECK-widen migration (table rebuild)
# ================================================================================

_NARROW_REALTIME_DDL = """
CREATE TABLE realtime_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    profile_id TEXT,
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture')),
    drive_id INTEGER
);
"""


@pytest.fixture
def narrowDb() -> Generator[sqlite3.Connection, None, None]:
    """A pre-US-424 realtime_data (narrow CHECK) with rows + an index."""
    conn = sqlite3.connect(":memory:")
    conn.execute(_NARROW_REALTIME_DDL)
    conn.execute(
        "CREATE INDEX IX_realtime_data_drive_id ON realtime_data(drive_id)",
    )
    conn.executemany(
        "INSERT INTO realtime_data "
        "(parameter_name, value, data_source, drive_id) VALUES (?, ?, ?, ?)",
        [
            ("RPM", 800.0, "real", 33),
            ("SPEED", 0.0, "real", 33),
            ("RPM", 900.0, "physics_sim", 33),
        ],
    )
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def test_widenRejectsForeignBeforeMigration(narrowDb):
    """Sanity: the narrow CHECK rejects 'foreign' until the migration runs."""
    with pytest.raises(sqlite3.IntegrityError):
        narrowDb.execute(
            "UPDATE realtime_data SET data_source='foreign' WHERE drive_id=33",
        )
    narrowDb.rollback()


def test_widenRunsAndAcceptsForeign(narrowDb):
    """After the migration, the open drive's rows can be retro-tagged 'foreign'."""
    changed = ensureDataSourceCheckWidened(narrowDb, "realtime_data")
    assert changed is True

    # The retro-tag the ingest guard performs now succeeds.
    narrowDb.execute(
        "UPDATE realtime_data SET data_source='foreign' "
        "WHERE drive_id=33 AND data_source='real'",
    )
    (foreignCount,) = narrowDb.execute(
        "SELECT COUNT(*) FROM realtime_data WHERE data_source='foreign'",
    ).fetchone()
    assert foreignCount == 2  # the two 'real' rows; the physics_sim row untouched


def test_widenPreservesRowsAndIndexes(narrowDb):
    """The rebuild copies every row verbatim and recreates named indexes."""
    before = narrowDb.execute(
        "SELECT id, parameter_name, value, data_source, drive_id "
        "FROM realtime_data ORDER BY id",
    ).fetchall()

    ensureDataSourceCheckWidened(narrowDb, "realtime_data")

    after = narrowDb.execute(
        "SELECT id, parameter_name, value, data_source, drive_id "
        "FROM realtime_data ORDER BY id",
    ).fetchall()
    assert after == before

    indexes = {
        r[0]
        for r in narrowDb.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='realtime_data' AND sql IS NOT NULL",
        ).fetchall()
    }
    assert "IX_realtime_data_drive_id" in indexes


def test_widenIsIdempotent(narrowDb):
    """A second run is a no-op (returns False) and does not error."""
    assert ensureDataSourceCheckWidened(narrowDb, "realtime_data") is True
    assert ensureDataSourceCheckWidened(narrowDb, "realtime_data") is False


def test_widenNoOpOnFreshSchema():
    """A table already CREATEd from the widened schema is a no-op."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(database_schema.SCHEMA_REALTIME_DATA)
        assert ensureDataSourceCheckWidened(conn, "realtime_data") is False
    finally:
        conn.close()


def test_widenNoOpOnMissingTable():
    """A missing table is a graceful no-op, not an error."""
    conn = sqlite3.connect(":memory:")
    try:
        assert ensureDataSourceCheckWidened(conn, "realtime_data") is False
    finally:
        conn.close()
