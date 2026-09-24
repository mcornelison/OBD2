################################################################################
# File Name: test_sync_history_residual.py
# Purpose/Description: US-795-a -- a completed sync session records what the car
#                      STILL held when it finished, and never the count alone.
#                      Zero, unknown and "at least N" are three distinguishable
#                      states; a bare 0 is none of them.
# Author: Ralph (US-795-a)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-795-a) | Initial -- residual, qualifier, typed
#               |                  | absence, non-destructive migration.
# ================================================================================
################################################################################
"""sync_history records the residual, never the count alone (US-795-a).

THE GAP, exactly: ``sync_history`` carries id, device_id, started_at,
completed_at, rows_synced, status, tables_synced and error_message -- and no
statement of what the car STILL owed when the session closed. That residual is
the only statement about the Pi that stays true after it goes dark.

🔴 WHY THE COUNT MAY NEVER TRAVEL ALONE. ``SyncBacklog.total`` is documented as
a LOWER BOUND whenever ``unreadableTables`` is non-empty -- its own docstring
says so. Persisting the integer without that qualifier would turn a measured
lower bound into an apparent exact count at the moment it is written down, and
nothing downstream could recover the difference.

⚠️ AND WHAT IT STILL CANNOT ANSWER, from the story's own worked proof: at
19:35:30Z session 216962 completed with 216 rows, zero errors, and the Pi
genuinely WAS caught up. The CIO then drove, and the Pi never contacted the
server again. A residual of 0 would have been CORRECT and useless -- the queue
did not exist yet at the last contact. The residual answers "was it current AS
OF t", never "is it current now". US-795-b is where that distinction is spoken
out loud.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from src.server.db.models import Base, SyncHistory


@pytest.fixture()
def engine():
    """A fresh SQLite database carrying the current ORM shape."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return eng


def _row(session: Session) -> SyncHistory:
    return session.query(SyncHistory).one()


class TestTheResidualIsPersisted:
    """Acceptance 1 -- a completed session stores what the car still held."""

    def test_completedSession_storesItsResidual(self, engine) -> None:
        """
        Given: a session closing with a known non-zero backlog
        When:  the row is written
        Then:  residual_rows equals that backlog
        """
        with Session(engine) as session:
            session.add(SyncHistory(
                device_id="chi-eclipse-01", status="completed",
                completed_at=datetime.now(UTC).replace(tzinfo=None),
                rows_synced=216, residual_rows=12, residual_complete=True,
            ))
            session.commit()

        with Session(engine) as session:
            assert _row(session).residual_rows == 12


class TestTheCountNeverTravelsAlone:
    """Acceptance 2 -- the qualifier is stored beside the number."""

    def test_modelCarriesTheCompletenessFlag(self) -> None:
        """
        Given: the SyncHistory model
        When:  its columns are listed
        Then:  a completeness qualifier exists beside the count

        Stated as a schema property, because the story says so: a schema that
        can store the integer WITHOUT the qualifier fails this story. A test
        that only exercised a well-formed write would pass on such a schema.
        """
        columns = {c.name for c in SyncHistory.__table__.columns}

        assert "residual_rows" in columns
        assert "residual_complete" in columns

    def test_unreadableTables_storeTheResidualAsNotComplete(self, engine) -> None:
        """
        Given: a session closed while some tables were unreadable
        When:  the row is written
        Then:  the flag records that the count is NOT complete

        This is the lower-bound case: "at least 12", not "exactly 12".
        """
        with Session(engine) as session:
            session.add(SyncHistory(
                device_id="chi-eclipse-01", status="completed",
                residual_rows=12, residual_complete=False,
            ))
            session.commit()

        with Session(engine) as session:
            row = _row(session)
            assert row.residual_rows == 12
            assert row.residual_complete is False


class TestZeroAndUnknownAreDistinguishable:
    """Acceptance 3 -- three states, and none of them is a bare 0."""

    def test_owedNothing_andCouldNotTell_areDifferentStoredStates(
        self, engine
    ) -> None:
        """
        Given: one session that owed nothing and one that could not be measured
        When:  both rows are read back
        Then:  their stored states differ, and the unknown one is not 0

        'The car owed nothing' is (0, True). 'We could not determine what the
        car owed' is (None, None). Collapsing the second into 0 would report
        a healthy car on the evidence of a failed measurement -- the same
        class of defect as a fabricated timestamp.
        """
        with Session(engine) as session:
            session.add(SyncHistory(
                device_id="owed-nothing", status="completed",
                residual_rows=0, residual_complete=True,
            ))
            session.add(SyncHistory(
                device_id="could-not-tell", status="completed",
            ))
            session.commit()

        with Session(engine) as session:
            owedNothing = session.query(SyncHistory).filter_by(
                device_id="owed-nothing").one()
            couldNotTell = session.query(SyncHistory).filter_by(
                device_id="could-not-tell").one()

            assert (owedNothing.residual_rows, owedNothing.residual_complete) == (0, True)
            assert couldNotTell.residual_rows is None
            assert couldNotTell.residual_complete is None
            assert couldNotTell.residual_rows != 0, "unknown collapsed to zero"


class TestTheMigrationDoesNotRewriteHistory:
    """Acceptance 4 -- pre-migration rows read back as unknown, not 0."""

    def test_preMigrationRow_readsAsUnknown(self) -> None:
        """
        Given: a sync_history row written BEFORE the new columns existed
        When:  the columns are added and the row is read back
        Then:  its values are preserved and the new columns read as unknown

        The old table is built explicitly rather than by mutating the ORM, so
        this exercises the real upgrade path: rows that predate the columns.
        """
        eng = create_engine("sqlite://")
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id VARCHAR(64) NOT NULL,
                    started_at DATETIME NOT NULL,
                    completed_at DATETIME,
                    rows_synced INTEGER,
                    status VARCHAR(32) NOT NULL,
                    tables_synced TEXT,
                    error_message TEXT
                )
            """))
            conn.execute(text(
                "INSERT INTO sync_history "
                "(device_id, started_at, rows_synced, status) "
                "VALUES ('legacy', '2026-09-01 00:00:00', 216, 'completed')"
            ))

            # The migration's DDL, applied to the historical shape.
            conn.execute(text(
                "ALTER TABLE sync_history ADD COLUMN residual_rows INTEGER"))
            conn.execute(text(
                "ALTER TABLE sync_history ADD COLUMN residual_complete BOOLEAN"))

        with Session(eng) as session:
            row = _row(session)
            # Pre-existing values survive untouched ...
            assert row.device_id == "legacy"
            assert row.rows_synced == 216
            assert row.status == "completed"
            # ... and the new columns read as a typed absence, never 0.
            assert row.residual_rows is None
            assert row.residual_complete is None

    def test_theNewColumnsAreNullable_soAbsenceIsRepresentable(self) -> None:
        """
        Given: the SyncHistory table definition
        When:  the new columns are inspected
        Then:  both are nullable and neither defaults to 0

        A NOT NULL column with a 0 default would make 'unknown' unstorable --
        every historical row would claim the car owed nothing. That is the
        specific defect acceptance 4 exists to prevent, and it is a property
        of the SCHEMA, not of any write path.
        """
        columns = {c.name: c for c in SyncHistory.__table__.columns}

        for name in ("residual_rows", "residual_complete"):
            assert columns[name].nullable, f"{name} must be nullable"
            assert columns[name].default is None, f"{name} must not default"
            assert columns[name].server_default is None, f"{name} must not default"

    def test_theMigrationIsRegisteredAndAddsBothColumns(self) -> None:
        """
        Given: the v0028 migration module
        When:  its DDL is applied to a table lacking the columns
        Then:  both columns exist afterwards

        NOTE ON 'REVERSIBLE': this runner ships NO down-migration machinery by
        design -- runner.py says so in as many words, and seven prior versions
        record 'rollback is snapshot + redeploy prior version'. The satisfiable
        reading of the criterion is its own second sentence: the migration is
        NON-DESTRUCTIVE. It adds two nullable columns, backfills nothing and
        rewrites no row, so dropping them restores the previous shape exactly.
        """
        from src.server.migrations.versions.v0028_us795a_sync_history_residual import (
            ADD_RESIDUAL_COMPLETE_DDL,
            ADD_RESIDUAL_ROWS_DDL,
            MIGRATION,
        )

        assert MIGRATION.version == "0028"

        eng = create_engine("sqlite://")
        with eng.begin() as conn:
            conn.execute(text(
                "CREATE TABLE sync_history (id INTEGER PRIMARY KEY, "
                "device_id VARCHAR(64) NOT NULL, started_at DATETIME NOT NULL, "
                "status VARCHAR(32) NOT NULL)"
            ))
            for ddl in (ADD_RESIDUAL_ROWS_DDL, ADD_RESIDUAL_COMPLETE_DDL):
                conn.execute(text(ddl.rstrip(";")))

        names = {c["name"] for c in inspect(eng).get_columns("sync_history")}
        assert {"residual_rows", "residual_complete"} <= names
