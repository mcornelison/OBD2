################################################################################
# File Name: test_two_columns_each_filled_where_correct.py
# Purpose/Description: US-809-b2 -- the capture column is Python-supplied with
#                      NO default (omitting it RAISES), and the write column is
#                      filled by the schema's own clock. At INSERT time "now"
#                      IS the write instant; on the capture column it is a guess
#                      about the past.
# Author: Ralph (US-809-b2)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-09-24    | Ralph (US-809-b2) | Initial -- CIO ruled resolution (A):
#               |                   | drop NOT NULL, keep the auto-fill.
# ================================================================================
################################################################################
"""Two columns, each filled where it is correct (US-809-b2).

**The default was never the problem -- its LOCATION was.**  A default of "now"
is exactly right on the WRITE column, because at the instant of INSERT *now IS
the write time*.  On the CAPTURE column the same default is a fabrication: it
guesses about the past, and produces a plausible value that is wrong by however
long the row waited.

    capture (`timestamp`)   NOT NULL, NO DEFAULT  -- Python supplies it;
                                                     omitting it RAISES
    write   (`written_at`)  nullable, DEFAULT now -- the schema supplies it

🔴 **WHY THE WRITE COLUMN IS NULLABLE, ruled by the CIO 2026-09-24.**  The story
as written asked for `NOT NULL`.  That is unsatisfiable on a database that
already has rows: the car holds 405,536 realtime_data rows over five months
whose write time was never recorded and cannot be recovered, so `NOT NULL`
could only be met by inventing one -- either the migration clock (claiming every
row was written that afternoon) or the capture time (claiming every row was
written the instant it was measured, which is the exact false continuity
A-double-prime exists to remove, and indistinguishable afterwards from a
genuinely prompt write).  Sprint constraint 4 governs: *a typed absence beats a
fabricated value, every time.*

🟢 **Dropping NOT NULL is what makes the migration SAFE**, and that is the point
rather than a concession.  A rebuild can now put the DEFAULT on the column while
leaving historical rows genuinely blank.  Nothing observable is lost: every new
row is still filled by the schema, and nothing can write a blank one because the
default fires on every INSERT that omits it.  What is given up is only the
constraint's *proof* that no future row is blank.

⚠️ **AN OMITTED CAPTURE TIME STILL RAISES.**  That half is unchanged and is the
half that matters: a missing capture time is a CODE DEFECT, not a data state.
Python always has a clock at receipt, so absence there is a programming error to
be caught loudly -- never a state to represent, and never a sentinel.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.pi.obdii.data_source import (
    WRITTEN_AT_COLUMN,
    ensureWrittenAtColumn,
    ensureWrittenAtDefault,
)
from src.pi.obdii.database_schema import SCHEMA_REALTIME_DATA

_CAPTURED = "2026-09-23T18:00:00Z"


def _freshTable() -> sqlite3.Connection:
    """A realtime_data built from the shipped DDL."""
    conn = sqlite3.connect(":memory:")
    conn.execute(SCHEMA_REALTIME_DATA)
    return conn


def _insert(conn: sqlite3.Connection, *, withCapture: bool = True) -> None:
    if withCapture:
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES (?, 'RPM', 3500.0)",
            (_CAPTURED,),
        )
    else:
        conn.execute(
            "INSERT INTO realtime_data (parameter_name, value) "
            "VALUES ('RPM', 3500.0)"
        )


class TestEachColumnIsFilledWhereItIsCorrect:
    """Acceptance (a) and (b)."""

    def test_anInsertSupplyingOnlyCapture_landsAWriteTimeFromTheDefault(
        self,
    ) -> None:
        """
        Given: an INSERT that supplies the capture time and nothing else
        When:  the row is read back
        Then:  the write column carries a value the SCHEMA supplied

        This is the half the story is named for: at INSERT time "now" IS the
        write instant, so the schema is the right place to get it.
        """
        conn = _freshTable()
        _insert(conn)

        captured, written = conn.execute(
            f"SELECT timestamp, {WRITTEN_AT_COLUMN} FROM realtime_data"
        ).fetchone()

        assert captured == _CAPTURED
        assert written is not None, "the schema did not supply a write time"

    def test_anInsertOmittingTheCaptureTime_raises(self) -> None:
        """
        Given: an INSERT with no capture time
        When:  it is executed
        Then:  it RAISES

        A missing capture time is a CODE DEFECT, not a data state. Python
        always has a clock at receipt, so absence here is a programming error
        to be caught loudly. This is the half that is unchanged by the
        nullable ruling, and it is the half that matters.
        """
        conn = _freshTable()

        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, withCapture=False)

    def test_theCaptureColumnHasNoDefault(self) -> None:
        """
        Given: the shipped DDL
        When:  the capture column is inspected
        Then:  it is NOT NULL and carries NO default

        Asserted on the SCHEMA, not only through a failing INSERT: a default
        re-added later would make the raise above stop firing, and an INSERT
        test alone would then silently start passing for the wrong reason.
        """
        conn = _freshTable()
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(realtime_data)")
        }

        _, _, _, notNull, default, _ = columns["timestamp"]
        assert notNull == 1, "the capture column must stay NOT NULL"
        assert default is None, "the capture column must carry NO default"

    def test_theWriteColumnIsNullableAndHasADefault(self) -> None:
        """
        Given: the shipped DDL
        When:  the write column is inspected
        Then:  it is NULLABLE and carries a default

        Both halves matter. Nullable is what lets history stay honestly
        blank; the default is what fills every new row.
        """
        conn = _freshTable()
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(realtime_data)")
        }

        _, _, _, notNull, default, _ = columns[WRITTEN_AT_COLUMN]
        assert notNull == 0, "the write column must stay nullable (CIO 2026-09-24)"
        assert default is not None, "the schema must supply the write instant"


class TestTheTwoValuesDifferOnAQueuedReading:
    """Acceptance (c)."""

    def test_aQueuedReadingHasAWriteTimeLaterThanItsCapture(self) -> None:
        """
        Given: a reading captured well before it is written
        When:  the row is read back
        Then:  the write instant is LATER than the capture instant

        The capture time is in the past, so the schema's "now" cannot
        coincide with it. Under the old single-column design this gap was
        invisible: the row reported the write time and the queueing read as
        driving.
        """
        conn = _freshTable()
        _insert(conn)

        captured, written = conn.execute(
            f"SELECT timestamp, {WRITTEN_AT_COLUMN} FROM realtime_data"
        ).fetchone()

        assert written > captured

    def test_anExplicitWriteTimeIsNotOverriddenByTheDefault(self) -> None:
        """
        Given: an INSERT that supplies BOTH instants
        When:  the row is read back
        Then:  the supplied write time is kept

        The bus path carries a measured write instant; a default that
        overrode it would discard a real measurement in favour of a
        convenient one.
        """
        conn = _freshTable()
        conn.execute(
            f"INSERT INTO realtime_data (timestamp, {WRITTEN_AT_COLUMN}, "
            "parameter_name, value) VALUES (?, ?, 'RPM', 3500.0)",
            (_CAPTURED, "2026-09-23T18:00:47Z"),
        )

        written = conn.execute(
            f"SELECT {WRITTEN_AT_COLUMN} FROM realtime_data"
        ).fetchone()[0]

        assert written == "2026-09-23T18:00:47Z"


class TestTheMigrationKeepsHistoryHonest:
    """What dropping NOT NULL bought: a safe migration."""

    def test_theRebuildAddsTheDefaultAndLeavesOldRowsBlank(self) -> None:
        """
        Given: a pre-b2 table whose write column exists WITHOUT a default
        When:  the default is migrated onto it
        Then:  old rows keep NULL and new rows are filled by the schema

        🔴 THIS IS THE WHOLE POINT OF THE NULLABLE RULING. The rebuild can
        set the default precisely because it does not have to invent a value
        for the 405,536 rows whose write time was never recorded. Their NULL
        is the truth about them.
        """
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME NOT NULL, parameter_name TEXT NOT NULL, "
            "value REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES ('2026-04-23T03:14:40Z', 'RPM', 3500.0)"
        )
        ensureWrittenAtColumn(conn, "realtime_data")

        assert ensureWrittenAtDefault(conn, "realtime_data") is True

        historical = conn.execute(
            f"SELECT {WRITTEN_AT_COLUMN} FROM realtime_data WHERE id = 1"
        ).fetchone()[0]
        assert historical is None, "a historical write time was INVENTED"

        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES ('2026-09-24T10:00:00Z', 'RPM', 3600.0)"
        )
        fresh = conn.execute(
            f"SELECT {WRITTEN_AT_COLUMN} FROM realtime_data WHERE id = 2"
        ).fetchone()[0]
        assert fresh is not None, "the migrated table does not fill new rows"

    def test_theRebuildPreservesEveryRow(self) -> None:
        """
        Given: a table with rows
        When:  the default is migrated onto the write column
        Then:  every row survives with its values intact

        A rebuild that loses a row is worse than no default at all, and this
        one runs against 405,536 rows on the car.
        """
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE realtime_data ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME NOT NULL, parameter_name TEXT NOT NULL, "
            "value REAL NOT NULL)"
        )
        for i in range(25):
            conn.execute(
                "INSERT INTO realtime_data (timestamp, parameter_name, value) "
                "VALUES (?, 'RPM', ?)",
                (f"2026-04-2{i % 10}T03:00:00Z", float(i)),
            )
        ensureWrittenAtColumn(conn, "realtime_data")
        before = conn.execute(
            "SELECT id, timestamp, value FROM realtime_data ORDER BY id"
        ).fetchall()

        ensureWrittenAtDefault(conn, "realtime_data")

        after = conn.execute(
            "SELECT id, timestamp, value FROM realtime_data ORDER BY id"
        ).fetchall()
        assert after == before

    def test_theMigrationIsIdempotent(self) -> None:
        """
        Given: a table that already carries the default
        When:  the migration runs again
        Then:  it reports no change rather than rebuilding

        The Pi has no migration ledger: every schema step runs on every boot,
        so rebuilding a 191 MB table repeatedly is not an option.
        """
        conn = _freshTable()

        assert ensureWrittenAtDefault(conn, "realtime_data") is False

    def test_anAbsentTableIsANoOp(self) -> None:
        conn = sqlite3.connect(":memory:")

        assert ensureWrittenAtDefault(conn, "realtime_data") is False


class TestNoSentinelAndNoThreeValuedCaptureColumn:
    """The design decisions the story states in the negative."""

    def test_thereIsNoNullableCaptureColumn(self) -> None:
        """
        Given: the shipped DDL
        When:  the capture column is inspected
        Then:  it is NOT NULL

        There is no typed absence and no three-valued logic on the capture
        side. Absence there is a programming error, not a state.
        """
        conn = _freshTable()
        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(realtime_data)")
        }

        assert columns["timestamp"][3] == 1

    def test_theRetentionPredicateStillWorksUnchanged(self) -> None:
        """
        Given: rows with and without a write time
        When:  the retention predicate runs against the CAPTURE column
        Then:  it deletes by capture time exactly as before

        doNoHarm names this: the nightly sweep is UNCHANGED by this design.
        `DELETE FROM realtime_data WHERE timestamp < ?` is unaffected by NULLs
        in the write column, because it never reads that column. NULL < ? is
        NULL, so a predicate on a nullable column WOULD leak -- which is
        exactly why the capture column, the one retention reads, stays NOT
        NULL.
        """
        conn = _freshTable()
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value) "
            "VALUES ('2026-01-01T00:00:00Z', 'RPM', 1.0)"
        )
        conn.execute(
            f"INSERT INTO realtime_data (timestamp, {WRITTEN_AT_COLUMN}, "
            "parameter_name, value) VALUES ('2026-09-01T00:00:00Z', NULL, 'RPM', 2.0)"
        )

        conn.execute("DELETE FROM realtime_data WHERE timestamp < ?", ("2026-06-01",))

        remaining = conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0]
        assert remaining == 1
