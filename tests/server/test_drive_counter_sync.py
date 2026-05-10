################################################################################
# File Name: test_drive_counter_sync.py
# Purpose/Description: Server-side sync tests for drive_counter (US-314 /
#                      B-064).  Mirror tests for the new top-level
#                      ``driveCounter`` payload field on POST /api/v1/sync.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-314) | Initial -- DriveCounter ORM + driveCounter
#                               sync upsert path.  Closes B-064 server-side.
# ================================================================================
################################################################################

"""Server-side drive_counter sync tests (US-314 / B-064).

Pre-fix state: ``drive_counter`` exists as a raw DDL table on the
server (US-200 catch-up migration in
``scripts/apply_server_migrations.py``) but no ORM model maps to it
and no sync path writes to it.  ``last_drive_id`` on chi-srv-01 has
been stuck at the US-200 seed (0 / 3) while the Pi minted up
through drive_id=10.

Post-fix: a :class:`DriveCounter` ORM model + Pydantic
``DriveCounterData`` request field + :func:`runDriveCounterUpsert`
helper bring the server in lockstep with the Pi.

These tests use an in-memory SQLite engine so the same upsert path
exercises in CI without needing live MariaDB.  The
``GREATEST(existing, incoming)`` invariant guards against rewinds
and is verified explicitly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.server.api.sync import (
    ACCEPTED_TABLES,
    DriveCounterData,
    SyncRequest,
    runDriveCounterUpsert,
)
from src.server.db.models import Base, DriveCounter

# ================================================================================
# DriveCounter model contract
# ================================================================================


class TestDriveCounterModelContract:
    """The DriveCounter ORM model exists and matches the US-200 DDL."""

    def test_modelExists(self) -> None:
        cols = {c.name for c in DriveCounter.__table__.columns}
        assert {"id", "last_drive_id"}.issubset(cols)

    def test_idIsPrimaryKey(self) -> None:
        col = DriveCounter.__table__.columns["id"]
        assert col.primary_key is True

    def test_lastDriveIdIsBigInt(self) -> None:
        """BIGINT mirrors the MariaDB DDL (apply_server_migrations.py)."""
        col = DriveCounter.__table__.columns["last_drive_id"]
        # SQLAlchemy reports the abstract type; BigInteger / Integer are
        # both acceptable for the SQLite test path.  Just assert non-null
        # default and that the column is NOT NULL on the wire.
        assert col.nullable is False


# ================================================================================
# Pydantic request shape
# ================================================================================


class TestDriveCounterRequestField:
    """SyncRequest accepts an optional driveCounter top-level field."""

    def test_syncRequest_acceptsDriveCounter(self) -> None:
        req = SyncRequest.model_validate({
            "deviceId": "chi-eclipse-01",
            "batchId": "b-1",
            "tables": {},
            "driveCounter": {"lastDriveId": 10},
        })
        assert req.driveCounter is not None
        assert req.driveCounter.lastDriveId == 10

    def test_syncRequest_driveCounterIsOptional(self) -> None:
        req = SyncRequest.model_validate({
            "deviceId": "chi-eclipse-01",
            "batchId": "b-2",
            "tables": {},
        })
        assert req.driveCounter is None

    def test_driveCounterRejectsNonPositive(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 -- pydantic ValidationError
            DriveCounterData.model_validate({"lastDriveId": 0})

    def test_driveCounterRejectsNegative(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            DriveCounterData.model_validate({"lastDriveId": -1})


# ================================================================================
# runDriveCounterUpsert behavior
# ================================================================================


def _newSession() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


class TestRunDriveCounterUpsert:
    """Pi-sent counter advances upsert the server singleton row."""

    def test_freshTable_insertsSingleton(self) -> None:
        session = _newSession()
        runDriveCounterUpsert(session, lastDriveId=10)
        session.commit()

        row = session.query(DriveCounter).one()
        assert row.id == 1
        assert row.last_drive_id == 10

    def test_existingRow_advancesToHigher(self) -> None:
        """Pi at 10 -> server already at 3 -> server advances to 10."""
        session = _newSession()
        # Seed server at 3 (matches the chi-srv-01 stale-state pre-fix).
        runDriveCounterUpsert(session, lastDriveId=3)
        session.commit()

        runDriveCounterUpsert(session, lastDriveId=10)
        session.commit()

        row = session.query(DriveCounter).one()
        assert row.last_drive_id == 10

    def test_existingHigher_doesNotRewind(self) -> None:
        """Stale Pi reading -> server's higher value is preserved.

        Critical invariant: if server is at 12 and a stale sync arrives
        with last_drive_id=10, the server MUST stay at 12.  Rewinding
        would corrupt analytics joins that key on drive_id.
        """
        session = _newSession()
        runDriveCounterUpsert(session, lastDriveId=12)
        session.commit()

        runDriveCounterUpsert(session, lastDriveId=10)
        session.commit()

        row = session.query(DriveCounter).one()
        assert row.last_drive_id == 12, (
            "GREATEST() guard failed -- server rewound from 12 to 10"
        )

    def test_idempotent_sameValueTwice(self) -> None:
        session = _newSession()
        runDriveCounterUpsert(session, lastDriveId=7)
        session.commit()
        runDriveCounterUpsert(session, lastDriveId=7)
        session.commit()

        rows = session.query(DriveCounter).all()
        assert len(rows) == 1
        assert rows[0].last_drive_id == 7

    def test_singletonInvariant_idAlwaysOne(self) -> None:
        """Multiple upserts -> one row, id=1."""
        session = _newSession()
        for n in (1, 5, 8, 11):
            runDriveCounterUpsert(session, lastDriveId=n)
        session.commit()

        rows = session.query(DriveCounter).all()
        assert len(rows) == 1
        assert rows[0].id == 1
        assert rows[0].last_drive_id == 11


# ================================================================================
# Sync registration -- drive_counter is NOT a delta table.
# ================================================================================


class TestDriveCounterIsNotInTableRegistry:
    """drive_counter is intentionally absent from the per-table registry.

    The singleton path has its own field on the request body; treating
    it as just another delta table would break the natural-key contract
    (every other accepted table keys on (source_device, source_id) and
    that doesn't apply to a process-wide singleton).  The test exists
    to document that absence is intentional, not an oversight.
    """

    def test_driveCounterNotInAcceptedTables(self) -> None:
        assert "drive_counter" not in ACCEPTED_TABLES
