################################################################################
# File Name: test_pi_state_no_new_drives.py
# Purpose/Description: Schema + get/set + DriveDetector-gate tests for the
#                      pi_state singleton table's no_new_drives flag.
#                      US-225 / TD-034 close (US-216 WARNING stage gate).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""US-225 pi_state singleton + no_new_drives gate.

Covers three layers:

1. Schema / migration -- ensurePiStateTable is idempotent; the
   singleton row is seeded once + survives reboot; the flag is
   INTEGER 0/1.
2. Accessors -- getNoNewDrives / setNoNewDrives / clearNoNewDrives
   normalize to Python bool + round-trip.
3. DriveDetector cranking-gate -- when the flag is set, a new
   drive transition proceeds id-less (no counter increment, no
   drive_id published); when clear, the legacy mint path runs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive.detector import DriveDetector
from src.pi.obdii.drive_id import getCurrentDriveId, setCurrentDriveId
from src.pi.obdii.pi_state import (
    PI_STATE_TABLE,
    clearNoNewDrives,
    ensurePiStateTable,
    getNoNewDrives,
    setNoNewDrives,
)


@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    # Ensure process-wide drive_id context doesn't leak across tests.
    setCurrentDriveId(None)
    yield db
    setCurrentDriveId(None)


@pytest.fixture
def rawConn(tmp_path) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(tmp_path / "obd.db"))
    try:
        yield conn
    finally:
        conn.close()


# ================================================================================
# Schema / migration
# ================================================================================


class TestEnsurePiStateTable:
    def test_ensurePiStateTable_onFreshDb_createsTable(self, rawConn) -> None:
        created = ensurePiStateTable(rawConn)

        assert created is True
        # Singleton seed row present.
        row = rawConn.execute(
            f"SELECT id, no_new_drives FROM {PI_STATE_TABLE}"
        ).fetchone()
        assert row == (1, 0)

    def test_ensurePiStateTable_secondCall_isIdempotentNoop(
        self, rawConn
    ) -> None:
        assert ensurePiStateTable(rawConn) is True
        # Set the flag so we can verify the second ensure does not
        # reset it.
        setNoNewDrives(rawConn, True)
        rawConn.commit()

        created = ensurePiStateTable(rawConn)

        assert created is False
        assert getNoNewDrives(rawConn) is True

    def test_fullDbInitialize_producesPiStateTable(self, freshDb) -> None:
        names = freshDb.getTableNames()
        assert 'pi_state' in names
        info = freshDb.getTableInfo('pi_state')
        # Columns: id + no_new_drives.
        columnNames = {col['name'] for col in info}
        assert columnNames == {'id', 'no_new_drives'}

    def test_ensurePiStateTable_singletonCheckConstraint(
        self, rawConn
    ) -> None:
        ensurePiStateTable(rawConn)

        # Second row with id=2 violates CHECK (id = 1).
        with pytest.raises(sqlite3.IntegrityError):
            rawConn.execute(
                "INSERT INTO pi_state (id, no_new_drives) VALUES (2, 0)"
            )


# ================================================================================
# Accessors
# ================================================================================


class TestAccessors:
    def test_getNoNewDrives_defaultsToFalse(self, rawConn) -> None:
        ensurePiStateTable(rawConn)
        assert getNoNewDrives(rawConn) is False

    def test_setNoNewDrivesTrue_roundTrips(self, rawConn) -> None:
        ensurePiStateTable(rawConn)
        setNoNewDrives(rawConn, True)
        assert getNoNewDrives(rawConn) is True

    def test_clearNoNewDrives_returnsToFalse(self, rawConn) -> None:
        ensurePiStateTable(rawConn)
        setNoNewDrives(rawConn, True)
        clearNoNewDrives(rawConn)
        assert getNoNewDrives(rawConn) is False

    def test_setNoNewDrives_beforeEnsureTable_stillWorks(
        self, rawConn
    ) -> None:
        # A call before the migration -- the UPSERT in setNoNewDrives
        # reconstructs the singleton row so the caller never gets a
        # silent failure from a pre-init order bug.
        ensurePiStateTable(rawConn)  # table exists but we'll DELETE row.
        rawConn.execute("DELETE FROM pi_state")
        setNoNewDrives(rawConn, True)
        assert getNoNewDrives(rawConn) is True

    def test_getNoNewDrives_missingRow_returnsFalse(self, rawConn) -> None:
        ensurePiStateTable(rawConn)
        rawConn.execute("DELETE FROM pi_state")
        # No row present -> not gated (default-off posture).
        assert getNoNewDrives(rawConn) is False


# ================================================================================
# DriveDetector cranking-gate
# ================================================================================


class TestDriveDetectorGate:
    @pytest.fixture
    def detector(self, freshDb) -> DriveDetector:
        config = {
            'pi': {
                'analysis': {
                    'driveStartRpmThreshold': 500,
                    'driveStartDurationSeconds': 0.01,
                    'driveEndRpmThreshold': 200,
                    'driveEndDurationSeconds': 0.01,
                    'triggerAfterDrive': False,
                },
                'profiles': {
                    'activeProfile': 'daily',
                },
            },
        }
        return DriveDetector(config, statisticsEngine=None, database=freshDb)

    def test_gateClear_normalDriveMintsNewId(self, detector, freshDb) -> None:
        # Flag defaults to False -> legacy mint path.
        detector.start()
        driveId = detector._openDriveId()

        assert driveId is not None
        assert driveId >= 1
        # Counter incremented.
        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT last_drive_id FROM drive_counter WHERE id = 1"
            ).fetchone()
            assert row[0] == driveId

    def test_gateSet_openDriveIdReturnsNoneAndDoesNotIncrementCounter(
        self, detector, freshDb
    ) -> None:
        # Set the gate before attempting a mint.
        with freshDb.connect() as conn:
            setNoNewDrives(conn, True)

        detector.start()
        driveId = detector._openDriveId()

        assert driveId is None
        assert getCurrentDriveId() is None
        # Critical invariant: counter did NOT increment.
        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT last_drive_id FROM drive_counter WHERE id = 1"
            ).fetchone()
            assert row[0] == 0

    def test_gateSetThenCleared_nextMintResumes(self, detector, freshDb) -> None:
        with freshDb.connect() as conn:
            setNoNewDrives(conn, True)
        detector.start()
        assert detector._openDriveId() is None

        # Clear the gate -- AC restore path.
        with freshDb.connect() as conn:
            clearNoNewDrives(conn)
        driveId = detector._openDriveId()

        assert driveId == 1  # first successful mint
        assert getCurrentDriveId() == 1


# ================================================================================
# Reboot persistence
# ================================================================================


class TestRebootPersistence:
    def test_gateSetSurvivesReopen(self, tmp_path) -> None:
        dbPath = str(tmp_path / 'obd.db')

        db = ObdDatabase(dbPath, walMode=False)
        db.initialize()
        with db.connect() as conn:
            setNoNewDrives(conn, True)

        # Re-open -- simulates reboot.  initialize() is idempotent.
        db2 = ObdDatabase(dbPath, walMode=False)
        db2.initialize()
        with db2.connect() as conn:
            assert getNoNewDrives(conn) is True

    def test_ensureOnExistingTable_preservesFlagValue(
        self, tmp_path
    ) -> None:
        dbPath = str(tmp_path / 'obd.db')
        db = ObdDatabase(dbPath, walMode=False)
        db.initialize()
        with db.connect() as conn:
            setNoNewDrives(conn, True)
            # Explicit re-call of the migration on an existing table.
            created = ensurePiStateTable(conn)
            assert created is False
            assert getNoNewDrives(conn) is True
