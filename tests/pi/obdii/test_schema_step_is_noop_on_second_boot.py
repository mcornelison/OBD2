################################################################################
# File Name: test_schema_step_is_noop_on_second_boot.py
# Purpose/Description: HOTFIX US-809-b2 -- the Pi schema step must be a clean
#                      no-op on every boot after the first. The car's
#                      realtime_data carries a QUOTED table name in its stored
#                      DDL, which the rebuild's rename helper did not match, so
#                      the rebuild re-created the live table and eclipse-obd
#                      could not start.
# Author: Ralph (HOTFIX US-809-b2)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-09-24    | Ralph (HOTFIX)     | Initial -- double-run, fresh path, the
#               |                    | car's exact shape, no data movement.
# ================================================================================
################################################################################
"""The schema step is a no-op on the second boot (HOTFIX US-809-b2).

**PRODUCTION FAILURE, 2026-09-24 07:55Z on chi-eclipse-01**::

    Failed to initialize database: Database connection error:
    table "realtime_data" already exists

🔴 **ROOT CAUSE, and it is NOT what the first reading suggested.**
``_renameCreateTarget`` rewrites ``CREATE TABLE <name>`` to target a temp table
before the rebuild copies rows into it.  Its regex matched a BARE identifier
only.  The car's stored DDL carries the name **double-quoted** --
``CREATE TABLE "realtime_data" (`` -- which is what SQLite writes after an
``ALTER TABLE ... RENAME TO``.  Against that, the rewrite is a **silent no-op**:
``re.sub`` returns the string unchanged, so the rebuild executes a CREATE for
the LIVE table and SQLite refuses it.

⚠️ **THE QUOTED NAME WAS NOT LEFT BY THIS STORY.**  It is the fingerprint of the
US-424 CHECK-widen rebuild, which renamed the table long before US-809-b2
existed.  **The defect has been latent in the shared helper ever since**; b2 is
simply the first caller to run against a table that had already been renamed
once.  ``ensureDataSourceCheckWidened`` uses the same helper and would fail the
same way if it ever needed to run on the car again.

🔴 **AND THE MIGRATION NEVER SUCCEEDED ON THE CAR -- the story's premise that it
"ran correctly ONCE" is wrong, measured.**  The car's ``written_at`` has **no
DEFAULT**.  What succeeded was ``ensureWrittenAtColumn`` (a plain, genuinely
idempotent ``ALTER TABLE ADD COLUMN``); the rebuild that adds the default has
failed on **every** boot including the first.  So this is not a second-boot
idempotency bug -- it fires on every boot against a renamed table.  The fix
therefore has to make the rebuild WORK, not make the detection skip it.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from src.pi.obdii.data_source import _renameCreateTarget, ensureAllCaptureTables
from src.pi.obdii.database_schema import SCHEMA_REALTIME_DATA

#: The car's realtime_data DDL, read read-only from chi-eclipse-01 on
#: 2026-09-24 -- the exact state eclipse-obd could not start on. Note the
#: QUOTED table name and the absence of a DEFAULT on written_at.
CAR_DDL: str = '''CREATE TABLE "realtime_data" (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Timestamp with millisecond precision
    timestamp DATETIME NOT NULL,

    -- Parameter data
    parameter_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,

    -- Profile association
    profile_id TEXT, data_source TEXT NOT NULL DEFAULT 'real' CHECK (data_source IN ('real','replay','physics_sim','fixture','foreign')), drive_id INTEGER, written_at DATETIME,

    -- Constraints
    CONSTRAINT FK_realtime_data_profile FOREIGN KEY (profile_id)
        REFERENCES profiles(id)
        ON DELETE SET NULL
)'''


def _storedDdl(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='realtime_data'"
    ).fetchone()
    return row[0] if row else ""


def _seed(conn: sqlite3.Connection, count: int = 50) -> None:
    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value) VALUES (?,?,?)",
        [(f"2026-04-23T03:00:{i % 60:02d}Z", "RPM", float(i)) for i in range(count)],
    )
    conn.commit()


def _carDatabase(rows: int = 50) -> sqlite3.Connection:
    """A database in the exact shape the car was in when the collector died."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE profiles (id TEXT PRIMARY KEY)")
    conn.execute(CAR_DDL)
    conn.execute(
        "CREATE INDEX IX_realtime_data_timestamp ON realtime_data(timestamp)"
    )
    _seed(conn, rows)
    return conn


def _bootSchemaStep(conn: sqlite3.Connection) -> list[str]:
    """One boot: CREATE TABLE IF NOT EXISTS, then the migration sweep."""
    conn.execute(SCHEMA_REALTIME_DATA)
    return ensureAllCaptureTables(conn)


class TestTheCarsExactShape:
    """Acceptance 3 -- the state the collector currently cannot start on."""

    def test_initialisationSucceedsOnTheCarsShape(self) -> None:
        """
        Given: realtime_data exactly as measured on the car 2026-09-24
        When:  the schema step runs
        Then:  it completes without raising

        🔴 THIS IS THE PRODUCTION FAILURE. Against V0.29.66 this raises
        `table "realtime_data" already exists` and eclipse-obd exits 2.
        """
        conn = _carDatabase()

        _bootSchemaStep(conn)  # must not raise

        assert conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0] == 50

    def test_theFixtureReallyCarriesTheQuotedName(self) -> None:
        """
        Given: the car fixture
        When:  its stored DDL is read
        Then:  the table name is QUOTED

        Pinned so the fixture cannot be "tidied" into a bare name later --
        the quoting IS the trigger, and a fixture without it tests nothing.
        """
        conn = _carDatabase()

        assert '"realtime_data"' in _storedDdl(conn)

    def test_noLeftoverTempTable(self) -> None:
        """
        Given: the car fixture, which had no leftover _tmp table
        When:  tables are listed
        Then:  only realtime_data matches -- the rebuild did not die half-way
        """
        conn = _carDatabase()
        _bootSchemaStep(conn)

        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE '%realtime%'"
            )
        }
        assert names == {"realtime_data"}


class TestTheSecondRunIsACleanNoOp:
    """Acceptance 1 -- run twice against the same POPULATED database."""

    def test_secondRunRaisesNothingAndChangesNothing(self) -> None:
        """
        Given: a populated database that has already been migrated once
        When:  the schema step runs a second time
        Then:  no exception, the row count is unchanged, the DDL is unchanged

        The Pi has no migration ledger: every schema step runs on EVERY boot,
        so "already applied" has to be detectable from the schema itself.
        """
        conn = _carDatabase()
        _bootSchemaStep(conn)

        ddlAfterFirst = _storedDdl(conn)
        rowsAfterFirst = conn.execute(
            "SELECT COUNT(*) FROM realtime_data"
        ).fetchone()[0]

        migrated = _bootSchemaStep(conn)  # must not raise

        assert migrated == [], f"second run still migrated: {migrated}"
        assert _storedDdl(conn) == ddlAfterFirst
        assert conn.execute(
            "SELECT COUNT(*) FROM realtime_data"
        ).fetchone()[0] == rowsAfterFirst

    def test_aThirdRunIsAlsoANoOp(self) -> None:
        """
        Given: a database the schema step has already run against twice
        When:  it runs a third time
        Then:  still a clean no-op

        The car restarted eleven times. Two runs is the minimum that proves
        idempotency; it is not the number production will do.
        """
        conn = _carDatabase()
        for _ in range(3):
            _bootSchemaStep(conn)

        assert conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0] == 50


class TestNoDataIsMovedWhenAlreadyApplied:
    """Acceptance 4 -- 400,755 rows and no undo on the Pi."""

    def test_theSecondRunIssuesNoDropAndNoRename(self) -> None:
        """
        Given: an already-migrated database
        When:  the schema step runs again
        Then:  no DROP TABLE and no RENAME touches realtime_data

        Asserted on the STATEMENTS ACTUALLY EXECUTED, via sqlite3's trace
        callback, rather than on the outcome. An outcome check cannot tell a
        rebuild that happened to reproduce the same rows from one that never
        ran -- and on 400,755 rows with no undo, "it looked the same
        afterwards" is not the property we need.
        """
        conn = _carDatabase()
        _bootSchemaStep(conn)

        executed: list[str] = []
        conn.set_trace_callback(executed.append)
        try:
            _bootSchemaStep(conn)
        finally:
            conn.set_trace_callback(None)

        destructive = [
            sql for sql in executed
            if re.search(r"\bDROP\s+TABLE\b", sql, re.IGNORECASE)
            or re.search(r"\bRENAME\s+TO\b", sql, re.IGNORECASE)
        ]
        assert not destructive, f"second run moved data: {destructive}"

    def test_theFirstRunDoesRebuild_soTheFixIsNotASkip(self) -> None:
        """
        Given: the car's shape, where the default has NOT yet been applied
        When:  the schema step runs for the first time
        Then:  it DOES rebuild, and the default lands

        🔴 The counterpart to the test above, and the reason this fix is not
        a skip. The car's written_at has NO default -- measured -- so the
        rebuild has never succeeded there. Making the detection treat that as
        "already applied" would start the collector and silently abandon
        US-809-b2's whole point.
        """
        conn = _carDatabase()

        migrated = _bootSchemaStep(conn)

        assert any("written_at" in entry for entry in migrated), migrated
        assert "strftime" in _storedDdl(conn), "the write-time default did not land"


class TestTheTargetDdlIsUnchanged:
    """Acceptance 2 -- the fresh path still reaches the V0.29.66 target."""

    def test_aFreshDatabaseReachesTheTargetShape(self) -> None:
        """
        Given: a database that has NEVER been migrated
        When:  the schema step runs
        Then:  timestamp is NOT NULL with no DEFAULT and written_at is
               nullable WITH one -- the V0.29.66 target, unchanged

        The fix may not change what the schema converges on, only how
        "already applied" is detected. The server is already on V0.29.66 with
        v0028-v0030 applied; a different target would diverge the tiers.
        """
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE profiles (id TEXT PRIMARY KEY)")
        _bootSchemaStep(conn)

        columns = {
            row[1]: row for row in conn.execute("PRAGMA table_info(realtime_data)")
        }

        assert columns["timestamp"][3] == 1        # NOT NULL
        assert columns["timestamp"][4] is None     # no DEFAULT
        assert columns["written_at"][3] == 0       # nullable
        assert columns["written_at"][4] is not None  # DEFAULT present

    def test_theFreshPathIsAlsoIdempotent(self) -> None:
        """
        Given: a fresh database migrated once
        When:  the schema step runs again
        Then:  a clean no-op

        The bench only ever exercised this path, which is exactly why the
        car's failure was invisible to every gate.
        """
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE profiles (id TEXT PRIMARY KEY)")
        _bootSchemaStep(conn)
        _seed(conn)

        assert _bootSchemaStep(conn) == []


class TestTheRenameHelperHandlesEveryIdentifierForm:
    """The unit-level cause, pinned directly."""

    @pytest.mark.parametrize(
        "target",
        ['realtime_data', '"realtime_data"', '[realtime_data]', '`realtime_data`'],
        ids=["bare", "double-quoted", "bracketed", "backticked"],
    )
    def test_everyQuotingFormIsRewritten(self, target: str) -> None:
        """
        Given: a CREATE TABLE using each identifier form SQLite accepts
        When:  the create target is rewritten
        Then:  it points at the new name in every case

        🔴 SQLite writes the DOUBLE-QUOTED form itself after an
        ALTER TABLE ... RENAME TO, so any table that has ever been rebuilt
        carries it. Brackets and backticks are accepted too; covering all
        four costs nothing and removes the next variant of this outage.
        """
        sql = f"CREATE TABLE {target} (\n    id INTEGER PRIMARY KEY\n)"

        out = _renameCreateTarget(sql, "realtime_data", "realtime_data__tmp")

        assert "realtime_data__tmp" in out, out
        assert out != sql

    def test_aNonMatchingNameRAISESRatherThanReturningUnchanged(self) -> None:
        """
        Given: a CREATE for a DIFFERENT table
        When:  the rewrite runs
        Then:  it RAISES

        🔴 THIS IS THE CONTRACT CHANGE THAT PREVENTS THE NEXT OUTAGE, and my
        first draft of this test asserted the opposite. Returning the input
        unchanged is indistinguishable from "no rename was needed" -- and
        that ambiguity is precisely what turned a pattern gap into a
        production failure: the caller took the unchanged statement and
        executed a CREATE for the LIVE table. A caller that asks for a rename
        it cannot get must hear about it, loudly, BEFORE it drops anything.
        """
        sql = 'CREATE TABLE "connection_log" (id INTEGER PRIMARY KEY)'

        with pytest.raises(ValueError, match="realtime_data"):
            _renameCreateTarget(sql, "realtime_data", "x")

    def test_foreignKeyReferencesAreNotRewritten(self) -> None:
        """
        Given: a CREATE whose FK references another table
        When:  the create target is rewritten
        Then:  only the target changes; the reference is untouched

        The original helper's docstring promises this. Keeping it under the
        widened regex is the point of the test.
        """
        sql = (
            'CREATE TABLE "realtime_data" (id INTEGER, profile_id TEXT, '
            'CONSTRAINT FK FOREIGN KEY (profile_id) REFERENCES profiles(id))'
        )

        out = _renameCreateTarget(sql, "realtime_data", "realtime_data__tmp")

        assert "REFERENCES profiles(id)" in out
        assert out.count("realtime_data__tmp") == 1
