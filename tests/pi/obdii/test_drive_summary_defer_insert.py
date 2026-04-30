################################################################################
# File Name: test_drive_summary_defer_insert.py
# Purpose/Description: Tests for SummaryRecorder Option (a) defer-INSERT
#                      semantics (US-236).  Sprint 18's US-228 shipped Option
#                      (b) backfill-UPDATE; empirically across drives 3, 4, 5
#                      every row had ambient/battery/baro NULL.  Option (a)
#                      defers the INSERT until the first IAT/BATTERY_V/BARO
#                      reading arrives, eliminating the "INSERT-then-never-
#                      fill" failure mode by construction.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-236) | Initial -- defer-INSERT semantics + 60s timeout
#                               + warm-restart + re-entry + runtime-validation
#                               discriminator (must FAIL against Sprint 18 code).
# ================================================================================
################################################################################

"""Tests for :meth:`SummaryRecorder.captureDriveStart` defer-INSERT (US-236).

Scenario under test: ``drive_start`` fires before ANY IAT / BATTERY_V /
BAROMETRIC_KPA reading is cached (Drive 3 / 4 / 5 production timing).
Option (a) defers the INSERT until the first relevant reading arrives;
on 60s timeout, INSERTs an explicit-NULL row tagged with
``reason='no_readings_within_timeout'``.

**Runtime-validation discriminator** (per
``feedback_runtime_validation_required``): the test
``test_emptySnapshotProducesNoRowAndNoInsert`` MUST fail against
Sprint 18's Option (b) code path.  Sprint 18 always INSERTs at
drive_start (Drive 3's bug); Sprint 19 never does on an empty
snapshot.  A passing run of this test against pre-US-236 code
indicates the test is too weak.

The recorder itself is **stateless across calls** -- there is no
in-memory "pending listener" object.  Re-entry safety (test case 5)
falls out: each call decides INSERT-vs-no-op based purely on (row
exists for driveId) AND (snapshot has relevant data) AND
(forceInsert flag).  The detector tracks per-drive deferred state
externally; integration-level re-entry is covered in
``tests/pi/integration/test_drive_summary_backfill.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import clearCurrentDriveId
from src.pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    SummaryRecorder,
)
from src.pi.obdii.engine_state import EngineState


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "defer_insert.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


def _readSummaryRow(
    db: ObdDatabase, driveId: int
) -> tuple[object, ...] | None:
    with db.connect() as conn:
        row = conn.execute(
            f"SELECT ambient_temp_at_start_c, starting_battery_v, "
            f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
            f"WHERE drive_id = ?",
            (driveId,),
        ).fetchone()
    return tuple(row) if row is not None else None


def _countSummaryRows(db: ObdDatabase) -> int:
    with db.connect() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM {DRIVE_SUMMARY_TABLE}"
        ).fetchone()[0]


# ================================================================================
# Acceptance #1 case 1 -- empty snapshot at drive_start does NOT INSERT
# ================================================================================


class TestCase1EmptySnapshotProducesNoRow:
    """Acceptance #1, case 1: drive_start with empty snapshot writes NO row.

    **Runtime-validation discriminator**: this test FAILS against
    Sprint 18's Option (b) code (which INSERTs at drive_start with
    NULLs).  Passing requires the Option (a) defer-INSERT change.
    """

    def test_emptySnapshotProducesNoRowAndNoInsert(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=3,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        # No row written -> inserted=False, deferred=True.
        assert result.inserted is False
        assert result.deferred is True
        assert result.reason is None
        # Most importantly: no row in DB.
        row = _readSummaryRow(freshDb, driveId=3)
        assert row is None, (
            "drive_summary row should NOT exist after empty-snapshot "
            "drive_start.  This assertion is the Option-(a) defer-INSERT "
            "discriminator -- Sprint 18 code INSERTs NULLs here (the bug)."
        )

    def test_snapshotWithUnrelatedReadingsDoesNotInsert(
        self, freshDb: ObdDatabase
    ) -> None:
        """RPM/SPEED in snapshot but no IAT/BATTERY_V/BARO -> still no INSERT."""
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=3,
            snapshot={'RPM': 2500.0, 'SPEED': 35.0},
            fromState=EngineState.UNKNOWN,
        )
        assert result.inserted is False
        assert result.deferred is True
        assert _readSummaryRow(freshDb, driveId=3) is None


# ================================================================================
# Acceptance #1 case 1 (continued) -- first IAT triggers INSERT
# ================================================================================


class TestCase1FirstIatTriggersInsert:
    """Acceptance #1: 5s later the first IAT reading INSERTs the row."""

    def test_firstIatTriggersInsertWithNonNullAmbient(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        # First call: empty snapshot -> deferred (no row).
        first = recorder.captureDriveStart(
            driveId=3,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        assert first.inserted is False
        assert _readSummaryRow(freshDb, driveId=3) is None

        # Second call (simulated 5s later): IAT in snapshot -> INSERT.
        second = recorder.captureDriveStart(
            driveId=3,
            snapshot={'INTAKE_TEMP': 19.0},
            fromState=EngineState.UNKNOWN,
        )
        assert second.inserted is True
        assert second.deferred is False
        # Row now exists with non-NULL ambient.
        row = _readSummaryRow(freshDb, driveId=3)
        assert row is not None
        assert row[0] == 19.0    # ambient
        assert row[1] is None    # battery still missing
        assert row[2] is None    # baro still missing

    def test_firstBatteryTriggersInsert(self, freshDb: ObdDatabase) -> None:
        """First reading is BATTERY_V instead of IAT -> still triggers INSERT."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=4, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        result = recorder.captureDriveStart(
            driveId=4,
            snapshot={'BATTERY_V': 13.4},
            fromState=EngineState.UNKNOWN,
        )
        assert result.inserted is True
        row = _readSummaryRow(freshDb, driveId=4)
        assert row == (None, 13.4, None)

    def test_firstBaroTriggersInsert(self, freshDb: ObdDatabase) -> None:
        """First reading is BAROMETRIC_KPA -> triggers INSERT."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=5, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        result = recorder.captureDriveStart(
            driveId=5,
            snapshot={'BAROMETRIC_KPA': 100.2},
            fromState=EngineState.UNKNOWN,
        )
        assert result.inserted is True
        row = _readSummaryRow(freshDb, driveId=5)
        assert row == (None, None, 100.2)


# ================================================================================
# Acceptance #2 -- interleaved readings across 30s -> all 3 fields populated
# ================================================================================


class TestCase2InterleavedReadingsFillAllThreeFields:
    """Acceptance #2: readings arrive interleaved -> row gets all 3 populated."""

    def test_interleavedReadingsFillAllThreeFields(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        # Drive start: no readings.
        recorder.captureDriveStart(
            driveId=6, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        assert _readSummaryRow(freshDb, driveId=6) is None

        # +5s: IAT arrives -> INSERT with IAT only.
        recorder.captureDriveStart(
            driveId=6,
            snapshot={'INTAKE_TEMP': 19.0},
            fromState=EngineState.UNKNOWN,
        )
        assert _readSummaryRow(freshDb, driveId=6) == (19.0, None, None)

        # +15s: BATTERY_V arrives -> backfill UPDATE.
        backfill1 = recorder.backfillFromSnapshot(
            driveId=6,
            snapshot={'INTAKE_TEMP': 19.0, 'BATTERY_V': 13.4},
            fromState=EngineState.UNKNOWN,
        )
        assert 'battery' in backfill1.filled
        assert backfill1.complete is False  # baro still missing
        assert _readSummaryRow(freshDb, driveId=6) == (19.0, 13.4, None)

        # +30s: BARO arrives -> backfill complete.
        backfill2 = recorder.backfillFromSnapshot(
            driveId=6,
            snapshot={
                'INTAKE_TEMP': 19.0,
                'BATTERY_V': 13.4,
                'BAROMETRIC_KPA': 100.2,
            },
            fromState=EngineState.UNKNOWN,
        )
        assert 'baro' in backfill2.filled
        assert backfill2.complete is True
        assert _readSummaryRow(freshDb, driveId=6) == (19.0, 13.4, 100.2)


# ================================================================================
# Acceptance #3 -- 60s timeout INSERTs row with NULLs + reason
# ================================================================================


class TestCase3TimeoutForcesInsertWithReason:
    """Acceptance #3: no readings within 60s -> forced INSERT with NULLs."""

    def test_forceInsertOnTimeoutInsertsRowWithNullsAndReason(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        # +0s: empty snapshot -> deferred.
        first = recorder.captureDriveStart(
            driveId=7, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        assert first.inserted is False
        assert _readSummaryRow(freshDb, driveId=7) is None

        # +60s: still empty -> forceInsert + reason.
        timeoutResult = recorder.captureDriveStart(
            driveId=7,
            snapshot={},
            fromState=EngineState.UNKNOWN,
            forceInsert=True,
            reason='no_readings_within_timeout',
        )
        assert timeoutResult.inserted is True
        assert timeoutResult.deferred is False
        assert timeoutResult.reason == 'no_readings_within_timeout'
        # Row exists with all 3 sensor columns NULL.
        row = _readSummaryRow(freshDb, driveId=7)
        assert row == (None, None, None)

    def test_forceInsertWithLateReadingStillInsertsThatReading(
        self, freshDb: ObdDatabase
    ) -> None:
        """forceInsert + non-empty snapshot -> INSERT with what's available.

        Edge case: a single reading arrives EXACTLY at the deadline.
        The detector calls forceInsert=True with the snapshot it has;
        the row gets the late reading, not all NULLs.  Reason still
        propagates so operators see the timeout signal.
        """
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=8, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        result = recorder.captureDriveStart(
            driveId=8,
            snapshot={'BATTERY_V': 12.9},
            fromState=EngineState.UNKNOWN,
            forceInsert=True,
            reason='no_readings_within_timeout',
        )
        assert result.inserted is True
        assert result.reason == 'no_readings_within_timeout'
        row = _readSummaryRow(freshDb, driveId=8)
        assert row == (None, 12.9, None)


# ================================================================================
# Acceptance #4 -- warm restart preserves ambient=NULL even when IAT arrives
# ================================================================================


class TestCase4WarmRestartAmbientStaysNull:
    """Acceptance #4: warm restart -> ambient NULL even if IAT arrives.

    Defer-INSERT decision uses **post-cold-start-rule** payload:
    a warm restart with IAT-only would yield an all-NULL row, so
    INSERT defers until BATTERY_V or BAROMETRIC_KPA arrives.  Once
    INSERTed, ambient stays NULL forever (US-206 invariant).
    """

    def test_warmRestartIatOnlyDoesNotInsert(
        self, freshDb: ObdDatabase
    ) -> None:
        """Warm restart + IAT only -> all-NULL row would result -> defer."""
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=9,
            snapshot={'INTAKE_TEMP': 85.0},
            fromState=EngineState.RUNNING,
        )
        # IAT is filtered by warm-restart rule, no other field present
        # -> defer-INSERT no-op.
        assert result.inserted is False
        assert result.deferred is True
        assert _readSummaryRow(freshDb, driveId=9) is None

    def test_warmRestartBatteryArrivalInsertsRowAmbientNull(
        self, freshDb: ObdDatabase
    ) -> None:
        """Warm restart + BATTERY_V arrives -> INSERT, ambient stays NULL."""
        recorder = SummaryRecorder(database=freshDb)
        # IAT-only snapshot defers.
        recorder.captureDriveStart(
            driveId=10,
            snapshot={'INTAKE_TEMP': 85.0},
            fromState=EngineState.RUNNING,
        )
        # BATTERY_V joins -> INSERT triggers.
        result = recorder.captureDriveStart(
            driveId=10,
            snapshot={'INTAKE_TEMP': 85.0, 'BATTERY_V': 13.7},
            fromState=EngineState.RUNNING,
        )
        assert result.inserted is True
        row = _readSummaryRow(freshDb, driveId=10)
        # ambient NULL (warm restart), battery captured.
        assert row[0] is None
        assert row[1] == 13.7
        assert row[2] is None


# ================================================================================
# Acceptance #5 -- re-entry: ANOTHER drive_start before first INSERT
# ================================================================================


class TestCase5ReentrySafety:
    """Acceptance #5: re-entry doesn't double-INSERT, doesn't leak listener.

    SummaryRecorder is stateless: each call's INSERT decision is local
    to its driveId.  Two pending defer-INSERTs for different driveIds
    don't interfere -- a reading arrival for driveId=11 INSERTs only
    that drive's row.  driveId=10's row never appears.
    """

    def test_twoPendingDefersDoNotDoubleInsert(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        # First drive: empty snapshot -> deferred.
        recorder.captureDriveStart(
            driveId=10, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        # Second drive starts before first INSERT completes.
        recorder.captureDriveStart(
            driveId=11, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        # No rows yet for either drive.
        assert _countSummaryRows(freshDb) == 0

        # Reading arrives that maps to driveId=11 only.
        recorder.captureDriveStart(
            driveId=11,
            snapshot={'INTAKE_TEMP': 19.0},
            fromState=EngineState.UNKNOWN,
        )
        # Exactly one row exists (driveId=11), driveId=10 stays absent.
        assert _countSummaryRows(freshDb) == 1
        assert _readSummaryRow(freshDb, driveId=10) is None
        assert _readSummaryRow(freshDb, driveId=11) == (19.0, None, None)

    def test_reentrySameDriveIdIsIdempotentDeferred(
        self, freshDb: ObdDatabase
    ) -> None:
        """Repeated empty-snapshot calls for the same driveId stay no-op."""
        recorder = SummaryRecorder(database=freshDb)
        for _ in range(5):
            result = recorder.captureDriveStart(
                driveId=12, snapshot={}, fromState=EngineState.UNKNOWN,
            )
            assert result.inserted is False
            assert result.deferred is True
        assert _countSummaryRows(freshDb) == 0


# ================================================================================
# Idempotency on re-call after INSERT (existing UPSERT semantic preserved)
# ================================================================================


class TestPostInsertIdempotency:
    """Pre-existing UPSERT semantics preserved: re-call after INSERT UPDATEs."""

    def test_postInsertCallReturnsInsertedFalse(
        self, freshDb: ObdDatabase
    ) -> None:
        """captureDriveStart on an existing row returns inserted=False."""
        recorder = SummaryRecorder(database=freshDb)
        first = recorder.captureDriveStart(
            driveId=13,
            snapshot={'BATTERY_V': 12.3},
            fromState=EngineState.UNKNOWN,
        )
        assert first.inserted is True
        # Re-call (e.g. detector replay) -> UPDATE not double-INSERT.
        second = recorder.captureDriveStart(
            driveId=13,
            snapshot={'BATTERY_V': 12.9},
            fromState=EngineState.UNKNOWN,
        )
        assert second.inserted is False
        assert second.deferred is False  # row exists, this was an UPDATE
        # Latest value won (UPSERT semantic).
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT starting_battery_v FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 13"
            ).fetchone()
        assert row[0] == 12.9
