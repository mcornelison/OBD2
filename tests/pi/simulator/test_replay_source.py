################################################################################
# File Name: test_replay_source.py
# Purpose/Description: US-857 -- a recorded drive's realtime_data rows replayed
#                      through the --simulate seam on the drive's own timing.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-857) | Initial implementation
# ================================================================================
################################################################################

"""Tests for :mod:`pi.obdii.simulator.replay_source` (US-857)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi.obdii.simulator.replay_source import (
    ReplaySourceError,
    ReplayValueSource,
)
from pi.obdii.simulator.sensor_simulator import SensorSimulator
from pi.obdii.simulator.simulated_connection import (
    SimulatedObdConnection,
    createSimulatedConnectionFromConfig,
)

# ================================================================================
# Fixtures
# ================================================================================

_DRIVE_ID = 117
_T0 = "2026-10-01T12:00:00Z"
_T2 = "2026-10-01T12:00:02Z"
_T4 = "2026-10-01T12:00:04Z"


class _FakeClock:
    """Monotonic stand-in the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _makeSourceDb(path: Path, rows: list[tuple[str, str, float, int]]) -> Path:
    """Write a minimal realtime_data table holding ``rows``.

    Each row is (timestamp, parameter_name, value, drive_id).
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE realtime_data ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " timestamp DATETIME NOT NULL,"
            " parameter_name TEXT NOT NULL,"
            " value REAL NOT NULL,"
            " unit TEXT,"
            " drive_id INTEGER)"
        )
        conn.executemany(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id)"
            " VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def threeRowDb(tmp_path: Path) -> Path:
    """The validation fixture: RPM at t0, t0+2 s, t0+4 s (inserted out of order)."""
    return _makeSourceDb(
        tmp_path / "source.db",
        [
            (_T4, "RPM", 3000.0, _DRIVE_ID),
            (_T0, "RPM", 1000.0, _DRIVE_ID),
            (_T2, "RPM", 2000.0, _DRIVE_ID),
            # Another drive's rows must never be served.
            ("2026-10-01T11:59:59Z", "RPM", 9999.0, 5),
            (_T2, "SPEED", 7777.0, 5),
        ],
    )


def _startedSource(dbPath: Path) -> tuple[ReplayValueSource, _FakeClock]:
    clock = _FakeClock()
    source = ReplayValueSource(str(dbPath), _DRIVE_ID, clock=clock)
    assert source.startEngine() is True
    return source, clock


# ================================================================================
# Value-source contract
# ================================================================================


class TestReplayTiming:
    """getValue answers on the drive's original timing."""

    def test_threeRowDrive_servesEachRowOnItsOwnTime_thenNoneAfterEnd(
        self, threeRowDb: Path
    ) -> None:
        """
        Given: a 3-row RPM drive (t0, t0+2 s, t0+4 s) and a fake clock
        When: getValue('RPM') is read at +0.5 s, +2.5 s, +4.5 s, then later
        Then: rows 1, 2, 3 in turn, and None once the last row was served
        """
        source, clock = _startedSource(threeRowDb)

        clock.now += 0.5
        assert source.getValue("RPM") == 1000.0
        clock.now += 2.0
        assert source.getValue("RPM") == 2000.0
        clock.now += 2.0
        assert source.getValue("RPM") == 3000.0
        clock.now += 0.5
        assert source.getValue("RPM") is None
        assert source.isFinished() is True

    def test_atExactRowTime_servesThatRow(self, threeRowDb: Path) -> None:
        source, clock = _startedSource(threeRowDb)
        assert source.getValue("RPM") == 1000.0
        clock.now += 2.0
        assert source.getValue("RPM") == 2000.0

    def test_beforePidFirstRow_returnsNoneNeverZero(self, tmp_path: Path) -> None:
        """
        Given: SPEED's first row is 2 s into the drive
        When: SPEED is read at +1 s
        Then: None (not read yet), and the recorded value once its time comes
        """
        dbPath = _makeSourceDb(
            tmp_path / "source.db",
            [
                (_T0, "RPM", 1000.0, _DRIVE_ID),
                (_T2, "SPEED", 0.0, _DRIVE_ID),
                (_T4, "RPM", 3000.0, _DRIVE_ID),
            ],
        )
        source, clock = _startedSource(dbPath)

        clock.now += 1.0
        assert source.getValue("SPEED") is None
        clock.now += 1.5
        assert source.getValue("SPEED") == 0.0

    def test_unrecordedPid_returnsNone(self, threeRowDb: Path) -> None:
        source, clock = _startedSource(threeRowDb)
        clock.now += 3.0
        assert source.getValue("COOLANT_TEMP") is None
        assert source.getValue("rpm") == 2000.0  # names are case-insensitive

    def test_beforeStartEngine_returnsNone(self, threeRowDb: Path) -> None:
        source = ReplayValueSource(str(threeRowDb), _DRIVE_ID, clock=_FakeClock())
        assert source.getValue("RPM") is None

    def test_afterStopEngine_returnsNone(self, threeRowDb: Path) -> None:
        source, clock = _startedSource(threeRowDb)
        clock.now += 0.5
        source.stopEngine()
        assert source.getValue("RPM") is None

    def test_restartAfterStop_keepsTheFirstStartTimeline(
        self, threeRowDb: Path
    ) -> None:
        """A reconnect (stop + start) resumes on wall time; it does not rewind."""
        source, clock = _startedSource(threeRowDb)
        source.stopEngine()
        clock.now += 2.5
        assert source.startEngine() is True
        assert source.getValue("RPM") == 2000.0

    def test_update_isANoOp(self, threeRowDb: Path) -> None:
        """Timing comes from the clock; nothing in the orchestrator calls update()."""
        source, clock = _startedSource(threeRowDb)
        source.update(100.0)
        clock.now += 0.5
        assert source.getValue("RPM") == 1000.0

    def test_profile_isPresentForVinQueries(self, threeRowDb: Path) -> None:
        source = ReplayValueSource(str(threeRowDb), _DRIVE_ID, clock=_FakeClock())
        assert source.profile is not None


class TestReplaySourceRefusals:
    """A replay that cannot read its drive fails at construction."""

    def test_missingSourceFile_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ReplaySourceError, match="sourcePath"):
            ReplayValueSource(str(tmp_path / "absent.db"), _DRIVE_ID)

    def test_driveWithNoRows_raises(self, threeRowDb: Path) -> None:
        with pytest.raises(ReplaySourceError, match="drive_id 404"):
            ReplayValueSource(str(threeRowDb), 404)

    def test_sourceIsOpenedReadOnly(self, threeRowDb: Path) -> None:
        before = threeRowDb.read_bytes()
        source, clock = _startedSource(threeRowDb)
        clock.now += 5.0
        source.getValue("RPM")
        assert threeRowDb.read_bytes() == before


# ================================================================================
# The --simulate seam
# ================================================================================


def _replayConfig(sourcePath: Path, dbPath: str = ":memory:") -> dict:
    return {
        "pi": {
            "database": {"path": dbPath},
            "simulator": {"connectionDelaySeconds": 0},
            "replay": {
                "active": True,
                "sourcePath": str(sourcePath),
                "driveId": _DRIVE_ID,
            },
        }
    }


class TestSimulatedConnectionFactory:
    """createSimulatedConnectionFromConfig picks the value source."""

    def test_replayActive_buildsWithReplaySource(self, threeRowDb: Path) -> None:
        conn = createSimulatedConnectionFromConfig(_replayConfig(threeRowDb))
        assert isinstance(conn, SimulatedObdConnection)
        assert isinstance(conn.simulator, ReplayValueSource)

    def test_replayActive_queryThroughConnection_returnsRecordedValue(
        self, threeRowDb: Path
    ) -> None:
        conn = createSimulatedConnectionFromConfig(_replayConfig(threeRowDb))
        assert conn.connect() is True
        response = conn.obd.query("RPM")
        assert response.is_null() is False
        assert response.value == 1000.0
        assert conn.obd.query("COOLANT_TEMP").is_null() is True

    def test_replayInactive_buildsSensorSimulator(self) -> None:
        conn = createSimulatedConnectionFromConfig(
            {"pi": {"replay": {"active": False}}}
        )
        assert type(conn.simulator) is SensorSimulator

    def test_noReplaySection_buildsSensorSimulator(self) -> None:
        conn = createSimulatedConnectionFromConfig({})
        assert type(conn.simulator) is SensorSimulator

    def test_sourcePathIsTheRunDatabase_refused(self, threeRowDb: Path) -> None:
        with pytest.raises(ReplaySourceError, match="pi.database.path"):
            createSimulatedConnectionFromConfig(
                _replayConfig(threeRowDb, dbPath=str(threeRowDb))
            )
