################################################################################
# File Name: test_drive_summary_cold_start.py
# Purpose/Description: Tests for SummaryRecorder cold-start backfill semantics
#                      (US-228 -- Drive 3 shipped NULL ambient/battery/baro
#                      because drive_start fires before first IAT/BATT/BARO
#                      arrives).  Covers the backfillFromSnapshot API that
#                      UPDATEs NULL fields without clobbering already-set
#                      values.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-228) | Initial -- backfill semantics unit tests.
# 2026-04-29    | Rex (US-236) | Sprint 19: Sprint 18's INSERT-immediately bug
#                               is now defer-INSERT (Option a).  TestColdStart
#                               BugReproduces renamed to TestDeferInsertReplaces
#                               Sprint18Bug; backfill tests adjusted to feed a
#                               valid row (via partial captureDriveStart OR
#                               forceInsert=True at "timeout").
# ================================================================================
################################################################################

"""Tests for :meth:`SummaryRecorder.backfillFromSnapshot` (US-228).

Scenario under test: ``drive_start`` fires before the first IAT /
BATTERY_V / BAROMETRIC_KPA reading is cached.  The INSERT at drive-
start writes NULLs; subsequent ticks need to UPDATE the row once the
readings arrive -- without clobbering already-captured non-NULL
values, and without re-enabling ambient capture on a warm restart.
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
    db = ObdDatabase(str(tmp_path / "backfill.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


# ================================================================================
# US-236: defer-INSERT replaces Sprint 18's INSERT-immediately bug class
# ================================================================================


class TestDeferInsertReplacesSprint18Bug:
    """Sprint 19 fix: empty-snapshot drive_start no longer creates an all-NULL row.

    Sprint 18's US-228 INSERTed the row at drive_start with NULLs and
    relied on UPDATE-backfill to fill them; this empirically failed
    on drives 3, 4, 5.  Sprint 19's US-236 defer-INSERT moves the
    INSERT to the first-reading-arrival point, eliminating the
    "row exists but stays empty" failure mode by construction.
    """

    def test_emptySnapshotAtDriveStartProducesNoRow(
        self, freshDb: ObdDatabase
    ) -> None:
        """Drive 3's bug timing: empty snapshot at drive_start -> no row (Option a)."""
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=3,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        assert result.inserted is False
        assert result.deferred is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = 3"
            ).fetchone()
        assert row is None


# ================================================================================
# backfillFromSnapshot: fills NULL columns POST-INSERT (US-236 phase 2)
# ================================================================================


class TestBackfillFillsNullColumns:
    """backfillFromSnapshot populates NULL columns once row exists.

    US-236 flow: defer-INSERT phase creates the row when first
    reading arrives; backfill phase fills remaining NULLs from
    subsequent ticks.  These tests exercise the backfill phase by
    INSERTing the row via captureDriveStart with a partial snapshot,
    then calling backfillFromSnapshot to fill the rest.
    """

    def test_backfillFillsRemainingNullColumns(
        self, freshDb: ObdDatabase
    ) -> None:
        """INSERT with one reading; backfill fills the other two."""
        recorder = SummaryRecorder(database=freshDb)
        # Phase 1: defer-INSERT triggered by IAT only.
        recorder.captureDriveStart(
            driveId=3,
            snapshot={'INTAKE_TEMP': 19.0},
            fromState=EngineState.UNKNOWN,
        )

        # Phase 2: backfill BATTERY_V + BARO.
        result = recorder.backfillFromSnapshot(
            driveId=3,
            snapshot={
                'INTAKE_TEMP': 19.0,
                'BATTERY_V': 13.4,
                'BAROMETRIC_KPA': 100.2,
            },
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == {'battery', 'baro'}
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 3"
            ).fetchone()
        assert row[0] == 19.0
        assert row[1] == 13.4
        assert row[2] == 100.2

    def test_backfillFillsOnlyWhatsAvailable(
        self, freshDb: ObdDatabase
    ) -> None:
        """Only columns with snapshot values (and still NULL in DB) get filled."""
        recorder = SummaryRecorder(database=freshDb)
        # Force INSERT via timeout path so backfill has a row to UPDATE.
        recorder.captureDriveStart(
            driveId=4, snapshot={}, fromState=EngineState.UNKNOWN,
            forceInsert=True, reason='no_readings_within_timeout',
        )

        result = recorder.backfillFromSnapshot(
            driveId=4,
            snapshot={'BATTERY_V': 13.4},  # IAT + BARO still missing
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == {'battery'}
        assert result.complete is False  # ambient + baro still NULL
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 4"
            ).fetchone()
        assert row[0] is None
        assert row[1] == 13.4
        assert row[2] is None

    def test_backfillOnAlreadyFullRowIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        """All three columns already set -> backfill writes nothing + returns complete."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=5,
            snapshot={
                'INTAKE_TEMP': 18.0,
                'BATTERY_V': 12.5,
                'BAROMETRIC_KPA': 101.0,
            },
            fromState=EngineState.UNKNOWN,
        )

        result = recorder.backfillFromSnapshot(
            driveId=5,
            snapshot={
                'INTAKE_TEMP': 25.0,  # different value -- MUST NOT overwrite
                'BATTERY_V': 13.9,
                'BAROMETRIC_KPA': 99.0,
            },
            fromState=EngineState.UNKNOWN,
        )

        assert result.filled == set()
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 5"
            ).fetchone()
        # Original INSERT values preserved (invariant: never clobber non-NULL).
        assert row[0] == 18.0
        assert row[1] == 12.5
        assert row[2] == 101.0


# ================================================================================
# Warm restart: ambient stays NULL even if IAT arrives
# ================================================================================


class TestBackfillWarmRestartRule:
    """Invariant: warm-restart ambient stays NULL forever, regardless of IAT."""

    def test_warmRestartBackfillDoesNotFillAmbient(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        # Force-INSERT a warm-restart row at the deadline so backfill
        # has a row to UPDATE.  Without forceInsert, warm + empty
        # would defer.
        recorder.captureDriveStart(
            driveId=6, snapshot={}, fromState=EngineState.RUNNING,
            forceInsert=True, reason='no_readings_within_timeout',
        )

        result = recorder.backfillFromSnapshot(
            driveId=6,
            snapshot={
                'INTAKE_TEMP': 85.0,
                'BATTERY_V': 13.7,
                'BAROMETRIC_KPA': 100.4,
            },
            fromState=EngineState.RUNNING,
        )

        # ambient is NOT in filled because warm-restart rule -- but battery +
        # baro are.  complete=True because ambient is "not applicable" on
        # warm restart.
        assert 'ambient' not in result.filled
        assert 'battery' in result.filled
        assert 'baro' in result.filled
        assert result.complete is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 6"
            ).fetchone()
        assert row[0] is None  # ambient stays NULL
        assert row[1] == 13.7
        assert row[2] == 100.4


# ================================================================================
# Edge cases
# ================================================================================


class TestBackfillEdgeCases:
    """Missing rows, None snapshots, nonsense values."""

    def test_backfillOnMissingDriveIdReturnsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        """backfill for a drive_id with no row yet is a no-op + complete=False."""
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.backfillFromSnapshot(
            driveId=99,
            snapshot={'BATTERY_V': 12.5},
            fromState=EngineState.UNKNOWN,
        )
        assert result.filled == set()
        assert result.complete is False

    def test_backfillWithEmptySnapshotIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        """US-236: empty snapshot on a deferred (no-row) drive is a no-op."""
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=10, snapshot={}, fromState=EngineState.UNKNOWN,
        )  # deferred -- no row created
        result = recorder.backfillFromSnapshot(
            driveId=10, snapshot={}, fromState=EngineState.UNKNOWN,
        )
        assert result.filled == set()
        assert result.complete is False  # no row exists, so cannot complete

    def test_backfillWithNoneSnapshotIsNoOp(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=11, snapshot={}, fromState=EngineState.KEY_OFF,
        )  # deferred -- no row created
        result = recorder.backfillFromSnapshot(
            driveId=11, snapshot=None, fromState=EngineState.KEY_OFF,
        )
        assert result.filled == set()
        assert result.complete is False
