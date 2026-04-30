################################################################################
# File Name: test_drive_summary.py
# Purpose/Description: Tests for SummaryRecorder + buildSummaryFromSnapshot
#                      (US-206 / Spool Data v2 Story 4).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.drive_summary` recorder + cold-start rule."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.drive_id import clearCurrentDriveId, setCurrentDriveId
from src.pi.obdii.drive_summary import (
    DRIVE_SUMMARY_TABLE,
    DriveSummary,
    SummaryRecorder,
    buildSummaryFromSnapshot,
)
from src.pi.obdii.engine_state import EngineState


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "ds.db"), walMode=False)
    db.initialize()
    yield db
    clearCurrentDriveId()


# ================================================================================
# Pure helper: buildSummaryFromSnapshot
# ================================================================================


class TestBuildSummaryFromSnapshotColdStartRule:
    """Cold-start rule: ambient captured on UNKNOWN / KEY_OFF; NULL otherwise."""

    def test_coldStartFromUnknown_capturesAmbient(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={
                'INTAKE_TEMP': 18.5,
                'BATTERY_V': 12.4,
                'BAROMETRIC_KPA': 101.2,
            },
            fromState=EngineState.UNKNOWN,
        )
        assert summary.ambientTempAtStartC == 18.5
        assert summary.startingBatteryV == 12.4
        assert summary.barometricKpaAtStart == 101.2

    def test_coldStartFromKeyOff_capturesAmbient(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={'INTAKE_TEMP': 22.0},
            fromState=EngineState.KEY_OFF,
        )
        assert summary.ambientTempAtStartC == 22.0

    def test_warmRestartFromRunning_nullsAmbient(self) -> None:
        """Invariant #2: warm restart (fromState=RUNNING) must NULL ambient."""
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={
                'INTAKE_TEMP': 85.0,
                'BATTERY_V': 13.7,
                'BAROMETRIC_KPA': 100.4,
            },
            fromState=EngineState.RUNNING,
        )
        assert summary.ambientTempAtStartC is None
        # battery + baro still captured (warm-restart NULL rule is ambient-only)
        assert summary.startingBatteryV == 13.7
        assert summary.barometricKpaAtStart == 100.4

    def test_fromStateCranking_nullsAmbient(self) -> None:
        """CRANKING is not in the cold-start set either."""
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={'INTAKE_TEMP': 25.0},
            fromState=EngineState.CRANKING,
        )
        assert summary.ambientTempAtStartC is None

    def test_fromStateNone_treatedAsWarmRestart(self) -> None:
        """None is conservative -- warm restart semantics."""
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={'INTAKE_TEMP': 30.0},
            fromState=None,
        )
        assert summary.ambientTempAtStartC is None

    def test_fromStateAsStringUnknown_capturesAmbient(self) -> None:
        """String form should be coerced to EngineState."""
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={'INTAKE_TEMP': 10.0},
            fromState='unknown',
        )
        assert summary.ambientTempAtStartC == 10.0

    def test_fromStateAsUnrecognizedString_nullsAmbient(self) -> None:
        """An unrecognized string value falls back to warm semantics."""
        summary = buildSummaryFromSnapshot(
            driveId=42,
            snapshot={'INTAKE_TEMP': 10.0},
            fromState='bogus',
        )
        assert summary.ambientTempAtStartC is None


class TestBuildSummaryFromSnapshotMissingValues:
    """Missing / malformed snapshot keys produce NULL columns, not crashes."""

    def test_missingKeyProducesNull(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=1,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        assert summary.ambientTempAtStartC is None
        assert summary.startingBatteryV is None
        assert summary.barometricKpaAtStart is None

    def test_noneSnapshotProducesAllNull(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=1, snapshot=None, fromState=EngineState.KEY_OFF,
        )
        assert summary.ambientTempAtStartC is None

    def test_nanValuesAreFilteredToNull(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=1,
            snapshot={'INTAKE_TEMP': math.nan, 'BATTERY_V': 12.0},
            fromState=EngineState.UNKNOWN,
        )
        assert summary.ambientTempAtStartC is None
        assert summary.startingBatteryV == 12.0

    def test_nonNumericValuesAreFilteredToNull(self) -> None:
        summary = buildSummaryFromSnapshot(
            driveId=1,
            snapshot={'INTAKE_TEMP': 'garbage', 'BATTERY_V': 12.0},
            fromState=EngineState.UNKNOWN,
        )
        assert summary.ambientTempAtStartC is None
        assert summary.startingBatteryV == 12.0


# ================================================================================
# SummaryRecorder -- live DB writes
# ================================================================================


class TestSummaryRecorderCapture:
    """SummaryRecorder.captureDriveStart writes one row per drive_id."""

    def test_coldStartWritesAllMetadata(self, freshDb: ObdDatabase) -> None:
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=7,
            snapshot={
                'INTAKE_TEMP': 18.5,
                'BATTERY_V': 12.4,
                'BAROMETRIC_KPA': 101.2,
            },
            fromState=EngineState.KEY_OFF,
        )
        assert result.inserted is True
        assert result.coldStart is True
        assert result.driveId == 7
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start, data_source "
                f"FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = 7"
            ).fetchone()
        assert row[0] == 18.5
        assert row[1] == 12.4
        assert row[2] == 101.2
        assert row[3] == 'real'

    def test_warmRestartNullsAmbientButKeepsOthers(
        self, freshDb: ObdDatabase
    ) -> None:
        recorder = SummaryRecorder(database=freshDb)
        recorder.captureDriveStart(
            driveId=8,
            snapshot={
                'INTAKE_TEMP': 85.0,
                'BATTERY_V': 13.6,
                'BAROMETRIC_KPA': 100.4,
            },
            fromState=EngineState.RUNNING,
        )
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start "
                f"FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = 8"
            ).fetchone()
        assert row[0] is None
        assert row[1] == 13.6
        assert row[2] == 100.4

    def test_rewriteSameDriveIdIsIdempotentUpsert(
        self, freshDb: ObdDatabase
    ) -> None:
        """Acceptance #4: UPSERT on re-call with same driveId."""
        recorder = SummaryRecorder(database=freshDb)
        first = recorder.captureDriveStart(
            driveId=9,
            snapshot={'BATTERY_V': 12.3},
            fromState=EngineState.UNKNOWN,
        )
        assert first.inserted is True

        # Second call with updated battery -- should UPDATE, not INSERT.
        second = recorder.captureDriveStart(
            driveId=9,
            snapshot={'BATTERY_V': 12.9},
            fromState=EngineState.UNKNOWN,
        )
        assert second.inserted is False

        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT starting_battery_v FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 9"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 12.9

    def test_emptySnapshotDefersInsert(
        self, freshDb: ObdDatabase
    ) -> None:
        """US-236: empty snapshot defers INSERT (no row written).

        Sprint 18 (Option b) INSERTed an all-NULL row here; Sprint 19's
        Option (a) defers until the first IAT/BATTERY_V/BARO arrives
        OR the detector forces an explicit-NULL INSERT at the 60s
        deadline (covered separately in
        :mod:`tests.pi.obdii.test_drive_summary_defer_insert`).
        """
        recorder = SummaryRecorder(database=freshDb)
        result = recorder.captureDriveStart(
            driveId=10,
            snapshot={},
            fromState=EngineState.UNKNOWN,
        )
        assert result.inserted is False
        assert result.deferred is True
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT 1 FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = 10"
            ).fetchone()
        assert row is None

    def test_fallsBackToCurrentDriveIdContext(
        self, freshDb: ObdDatabase
    ) -> None:
        """captureDriveStart(driveId=None) uses process-wide getCurrentDriveId()."""
        recorder = SummaryRecorder(database=freshDb)
        setCurrentDriveId(77)
        try:
            result = recorder.captureDriveStart(
                snapshot={'BATTERY_V': 12.5},
                fromState=EngineState.KEY_OFF,
            )
        finally:
            clearCurrentDriveId()
        assert result.driveId == 77
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT starting_battery_v FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = 77"
            ).fetchone()
        assert row[0] == 12.5

    def test_missingDriveIdRaisesValueError(
        self, freshDb: ObdDatabase
    ) -> None:
        """driveId=None and no current-drive context -> ValueError."""
        recorder = SummaryRecorder(database=freshDb)
        clearCurrentDriveId()
        with pytest.raises(ValueError):
            recorder.captureDriveStart(
                snapshot={'BATTERY_V': 12.0},
                fromState=EngineState.UNKNOWN,
            )


class TestDriveSummaryDataclass:
    """Shape sanity on the frozen DriveSummary dataclass."""

    def test_defaultsAreNullExceptDataSource(self) -> None:
        summary = DriveSummary(driveId=1)
        assert summary.ambientTempAtStartC is None
        assert summary.startingBatteryV is None
        assert summary.barometricKpaAtStart is None
        assert summary.dataSource == 'real'

    def test_isFrozen(self) -> None:
        summary = DriveSummary(driveId=1)
        with pytest.raises((AttributeError, Exception)):
            summary.driveId = 2  # type: ignore[misc]
