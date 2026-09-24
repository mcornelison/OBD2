################################################################################
# File Name: test_realtime_written_at_crosses_tiers.py
# Purpose/Description: US-809-b1 -- the write-time column exists on BOTH tiers
#                      and a row carrying it syncs without raising. A Pi-only
#                      column would stop realtime_data sync on the first batch.
# Author: Ralph (US-809-b1)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-09-23    | Ralph (US-809-b1) | Initial -- both tiers, sync, typed absence.
# ================================================================================
################################################################################
"""The write time is SAVED, not merely displaced (US-809-b1).

US-809-a moved the CAPTURE instant into ``timestamp``. Keeping the write
instant is the reason for touching the column at all -- A-double-prime says
two honest columns beat one ambiguous one, and it ADDS a requirement without
removing anything.

🔴 WHY THIS IS NOT OPTIONAL POLITENESS. ``src/server/api/sync.py`` RAISES
ValueError on any Pi column the server model lacks -- US-689 made it do that
deliberately, because the alternative was a SILENT DROP (SQLAlchemy's
executemany ignores surplus keys, so the row still inserted and the value just
vanished). ``realtime_data`` takes that delta path and is the highest-volume
table on the car, so a Pi-only column would stop its sync on the FIRST batch.

This story adds the column on both tiers and proves it crosses. It does NOT
set how either column is filled -- nullability and the DDL default are
US-809-b2.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from sqlalchemy import create_engine

from src.pi.data.sync_log import _WIRE_STRIPPED_COLUMNS
from src.server.db.models import Base, RealtimeData

WRITTEN_AT = "written_at"


class TestTheColumnExistsOnBothTiers:
    """Acceptance 1, first half -- both sides declare it."""

    def test_serverModelDeclaresIt(self) -> None:
        """
        Given: the server RealtimeData model
        When:  its columns are listed
        Then:  the write-time column is present

        Without this the sync of the highest-volume table on the car raises on
        the first batch carrying it.
        """
        assert WRITTEN_AT in {c.name for c in RealtimeData.__table__.columns}

    def test_piSchemaDeclaresIt(self) -> None:
        """
        Given: the Pi realtime_data DDL
        When:  a fresh table is created from it
        Then:  the write-time column is present
        """
        from src.pi.obdii.database_schema import SCHEMA_REALTIME_DATA

        conn = sqlite3.connect(":memory:")
        conn.execute(SCHEMA_REALTIME_DATA)

        names = {r[1] for r in conn.execute("PRAGMA table_info(realtime_data)")}
        assert WRITTEN_AT in names

    def test_itIsNotStrippedFromTheWire(self) -> None:
        """
        Given: the wire-stripping set
        When:  the write-time column is checked against it
        Then:  it is NOT stripped

        The Pi-local forensic columns (_sync_modified_at, data_quality,
        observed_by, observer_state) are stripped because the server has no
        such columns. This one is the opposite case: the server HAS it, and
        the whole point is that it crosses. Stripping it would make the
        column exist on both tiers and still never travel -- which would pass
        a naive 'column exists' test and fail the story.
        """
        assert WRITTEN_AT not in _WIRE_STRIPPED_COLUMNS


class TestARowCarryingItSyncsWithoutRaising:
    """Acceptance 1, second half -- the US-689 unknown-column raise."""

    def test_piColumnIsAcceptedByTheServerModel(self) -> None:
        """
        Given: a Pi payload carrying the write-time column
        When:  it is checked against the server model's accepted columns
        Then:  it is accepted

        This mirrors the guard US-689 installed: every column the Pi SENDS
        must exist on the server under the IDENTICAL spelling. Case and
        underscores both count -- engines differ on case folding.
        """
        from src.server.api.sync import _modelColumnNames

        serverColumns = _modelColumnNames(RealtimeData)

        assert WRITTEN_AT in serverColumns

    def test_aRowWithTheColumnRoundTripsThroughTheOrm(self) -> None:
        """
        Given: a realtime_data row carrying both instants
        When:  it is written and read back
        Then:  both survive, distinctly
        """
        from sqlalchemy.orm import Session

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)

        captured = datetime(2026, 9, 23, 18, 0, 0)
        written = datetime(2026, 9, 23, 18, 0, 47)

        with Session(engine) as session:
            session.add(RealtimeData(
                source_id=1, source_device="chi-eclipse-01",
                timestamp=captured, parameter_name="RPM", value=3500.0,
                written_at=written,
            ))
            session.commit()

        with Session(engine) as session:
            row = session.query(RealtimeData).one()
            assert row.timestamp == captured
            assert row.written_at == written


class TestCaptureAndWriteDifferOnAQueuedReading:
    """Acceptance 2 -- the 47 seconds the old design erased."""

    def test_aQueuedReadingKeepsBothInstants(self) -> None:
        """
        Given: a reading captured at 18:00:00 and written 47 s later
        When:  the row is read back
        Then:  the two instants differ by exactly that queueing delay

        Spec A-double-prime's worked case. Under the old single-column design
        those 47 seconds read as 47 seconds of driving; with both columns the
        queueing is visible AS queueing.
        """
        from sqlalchemy.orm import Session

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)

        captured = datetime(2026, 9, 23, 18, 0, 0, tzinfo=UTC).replace(tzinfo=None)
        written = datetime(2026, 9, 23, 18, 0, 47, tzinfo=UTC).replace(tzinfo=None)

        with Session(engine) as session:
            session.add(RealtimeData(
                source_id=2, source_device="chi-eclipse-01",
                timestamp=captured, parameter_name="RPM", value=3500.0,
                written_at=written,
            ))
            session.commit()

        with Session(engine) as session:
            row = session.query(RealtimeData).one()
            assert row.written_at > row.timestamp
            assert (row.written_at - row.timestamp).total_seconds() == 47


class TestTheMigrationDoesNotRewriteHistory:
    """Acceptance 3 -- pre-migration rows read as a typed absence."""

    def test_preMigrationPiRow_readsAsAbsent_notZero_andNotTheCaptureTime(
        self,
    ) -> None:
        """
        Given: a Pi realtime_data row written before the column existed
        When:  the column is added and the row is read back
        Then:  the write time is NULL -- not 0, and not a copy of the capture
               time

        BACKFILLING THE CAPTURE TIME WOULD BE THE WORST AVAILABLE CHOICE: it
        would assert that every historical row was written the instant it was
        captured, which is precisely the false continuity A-double-prime
        exists to remove -- and it would be indistinguishable from a genuinely
        prompt write.
        """
        from src.pi.obdii.data_source import ensureWrittenAtColumn

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME NOT NULL, "
            "parameter_name TEXT NOT NULL, value REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES ('2026-09-01T10:00:00Z', 'RPM', 3500.0)"
        )

        assert ensureWrittenAtColumn(conn, "realtime_data") is True

        row = conn.execute(
            f"SELECT timestamp, {WRITTEN_AT} FROM realtime_data"
        ).fetchone()

        assert row[0] == "2026-09-01T10:00:00Z"   # untouched
        assert row[1] is None                      # typed absence
        assert row[1] != 0
        assert row[1] != row[0]

    def test_addingTheColumnIsIdempotent(self) -> None:
        """
        Given: a table that already has the column
        When:  the helper runs again
        Then:  it reports no change rather than raising

        Mirrors ensureDataSourceColumn: the Pi has no migration ledger, so
        every schema step has to be safe to re-run on every boot.
        """
        from src.pi.obdii.data_source import ensureWrittenAtColumn

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, "
            "timestamp DATETIME NOT NULL)"
        )

        assert ensureWrittenAtColumn(conn, "realtime_data") is True
        assert ensureWrittenAtColumn(conn, "realtime_data") is False

    def test_absentTable_isANoOp(self) -> None:
        """
        Given: a database where realtime_data does not exist yet
        When:  the helper runs
        Then:  it is a no-op rather than an error (first-boot ordering)
        """
        from src.pi.obdii.data_source import ensureWrittenAtColumn

        conn = sqlite3.connect(":memory:")

        assert ensureWrittenAtColumn(conn, "realtime_data") is False

    def test_theServerMigrationIsRegisteredAndAddsTheColumn(self) -> None:
        """
        Given: the v0029 migration
        When:  its DDL is applied to a table lacking the column
        Then:  the column exists afterwards, nullable

        Same reversibility reading as v0028: this runner ships no
        down-migration machinery by design, so 'reversible' is satisfied as
        NON-DESTRUCTIVE -- one nullable column, no backfill, no row rewritten.
        """
        from sqlalchemy import inspect, text

        from src.server.migrations.versions.v0029_us809b1_realtime_written_at import (
            ADD_WRITTEN_AT_DDL,
            MIGRATION,
        )

        assert MIGRATION.version == "0029"

        eng = create_engine("sqlite://")
        with eng.begin() as conn:
            conn.execute(text(
                "CREATE TABLE realtime_data (id INTEGER PRIMARY KEY, "
                "timestamp DATETIME NOT NULL)"
            ))
            conn.execute(text(ADD_WRITTEN_AT_DDL.rstrip(";")))

        columns = {c["name"]: c for c in inspect(eng).get_columns("realtime_data")}
        assert WRITTEN_AT in columns
        assert columns[WRITTEN_AT]["nullable"]


class TestScopeFence:
    """b1 adds the column; b2 owns how each is filled."""

    def test_b1_leavesTheWriteColumnNullable(self) -> None:
        """
        Given: the server model after b1
        When:  the write column is inspected
        Then:  it is still nullable

        Deliberate: US-809-b2 makes it NOT NULL DEFAULT the system clock and
        moves the DDL default onto it. Anticipating that here would land two
        stories in one and make the b2 diff unreviewable.
        """
        column = RealtimeData.__table__.columns[WRITTEN_AT]

        assert column.nullable
