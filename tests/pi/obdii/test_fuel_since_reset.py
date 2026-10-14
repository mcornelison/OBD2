################################################################################
# File Name: test_fuel_since_reset.py
# Purpose/Description: US-881-c -- the Pi-local fuel_since_reset row: its
#                      helpers, its replay-safe ensure step, that it never
#                      syncs, and the provider's watermark persistence behind
#                      states/fuel-economy sinceReset.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-c) | Initial.
# ================================================================================
################################################################################

"""US-881-c: since-reset fuel totals persist in a Pi-local row and publish."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import pytest

from pi.data import sync_log
from pi.obdii import fuel_since_reset as fsr
from pi.obdii.database import ObdDatabase
from pi.obdii.database_schema import ensureFuelSinceResetTable
from pi.obdii.drive.types import DriveSession
from tests.pi.obdii.test_fuel_economy_emitter import _STEP_S, _T0_LOCAL, _Orch

T1 = "2026-10-20T15:02:11Z"
T2 = "2026-10-21T08:00:00Z"

# One steady drive of the US-881-b fixture: MAF 10 g/s, 60 km/h for 360 s.
_DRIVE_S = 360.0
_DRIVE_KM = 6.0
_DRIVE_L = 10 * 360 / 14.7 / 740


@pytest.fixture
def database(tmp_path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    return db


# ================================================================== helpers


def test_read_freshDatabase_none(database):
    with database.connect() as conn:
        assert fsr.read(conn) is None


def test_accumulateTwice_addsTheDeltas_firstUseStampsResetAt(database):
    with database.connect() as conn:
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
        row = fsr.read(conn)

    assert row == {
        "id": 1, "fuel_l": 1.0, "distance_km": 12.0, "open_loop_s": 24.0,
        "reset_at_ts": T1, "updated_at": T1,
    }


def test_accumulate_laterWrite_keepsResetAt_movesUpdatedAt(database):
    with database.connect() as conn:
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T2)
        row = fsr.read(conn)

    assert (row["reset_at_ts"], row["updated_at"]) == (T1, T2)


def test_reset_zeroesTheTotals_andStampsResetAt(database):
    with database.connect() as conn:
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
        fsr.reset(conn, T2)
        row = fsr.read(conn)

    assert (row["fuel_l"], row["distance_km"], row["open_loop_s"]) == (0.0, 0.0, 0.0)
    assert row["reset_at_ts"] == T2


def test_reset_beforeAnyRow_createsAZeroRow(database):
    with database.connect() as conn:
        fsr.reset(conn, T2)
        row = fsr.read(conn)

    assert (row["fuel_l"], row["reset_at_ts"]) == (0.0, T2)


def test_secondRow_violatesTheSingletonCheck(database):
    with database.connect() as conn:
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
    conn = sqlite3.connect(database.dbPath)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO fuel_since_reset (id, fuel_l) VALUES (2, 1.0)"
            )
    finally:
        conn.close()


def test_databaseHelpers_readThroughTheHandle(database):
    assert fsr.readFrom(database) is None
    row = fsr.accumulateAndReadFrom(database, 0.5, 6.0, 12.0, T1)
    assert row["fuel_l"] == 0.5
    assert fsr.resetAndReadFrom(database, T2)["fuel_l"] == 0.0
    assert fsr.readFrom(database)["reset_at_ts"] == T2


# ============================================================== ensure step


def test_schema_isTheAtlasGap3Shape(database):
    with database.connect() as conn:
        cols = [
            (r[1], r[2], r[5])
            for r in conn.execute("PRAGMA table_info(fuel_since_reset)")
        ]

    assert cols == [
        ("id", "INTEGER", 1), ("fuel_l", "REAL", 0), ("distance_km", "REAL", 0),
        ("open_loop_s", "REAL", 0), ("reset_at_ts", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ]


def test_initialize_existingDatabaseWithoutTheTable_gainsIt_noDataLoss(database):
    with database.connect() as conn:
        conn.execute("DROP TABLE fuel_since_reset")
        conn.execute("INSERT INTO pi_state (id, no_new_drives) VALUES (1, 1) "
                     "ON CONFLICT(id) DO UPDATE SET no_new_drives = 1")
        before = conn.execute("SELECT * FROM drive_counter").fetchall()

    database.initialize()

    with database.connect() as conn:
        assert fsr.read(conn) is None
        assert conn.execute("SELECT no_new_drives FROM pi_state").fetchone()[0] == 1
        assert conn.execute("SELECT * FROM drive_counter").fetchall() == before


def test_initialize_secondRun_isANoOp_rowKept(database):
    with database.connect() as conn:
        fsr.accumulate(conn, 0.5, 6.0, 12.0, T1)
    statements: list[str] = []

    database.initialize()

    with database.connect() as conn:
        conn.set_trace_callback(statements.append)
        assert ensureFuelSinceResetTable(conn) is False
        assert fsr.read(conn)["fuel_l"] == 0.5
    assert not [s for s in statements if "CREATE" in s.upper()]


def test_ensure_freshConnection_createsOnce():
    conn = sqlite3.connect(":memory:")
    try:
        assert ensureFuelSinceResetTable(conn) is True
        assert ensureFuelSinceResetTable(conn) is False
    finally:
        conn.close()


def test_fuelSinceReset_isInNoSyncRegistry():
    from common.sync.snapshot_registry import SNAPSHOT_SYNC

    assert "fuel_since_reset" not in sync_log.PK_COLUMN
    assert "fuel_since_reset" not in sync_log.IN_SCOPE_TABLES
    assert "fuel_since_reset" not in SNAPSHOT_SYNC


# ================================================================ provider


class _DbOrch(_Orch):
    """The US-881-b harness with the database handle the emitter holds."""

    def __init__(self, statesDir: str, database: Any, *, persistSec: float = 60.0,
                 **kw: Any) -> None:
        self._database = database
        fuel = {"persistSec": persistSec, **kw.pop("fuel", {})}
        super().__init__(statesDir, fuel=fuel, **kw)

    def tick(self) -> dict:
        return self.state()

    def drive(self, seconds: float, *, tickEvery: bool = True, status: int = 2) -> None:
        """A steady drive from the CURRENT t, ticking after every reading."""
        steps = round(seconds / _STEP_S)
        for i in range(steps + 1):
            if i:
                self.advance(_STEP_S)
            self.read("FUEL_SYSTEM_STATUS", float(status))
            self.read("SPEED", 60.0)
            self.read("MAF", 10.0)
            if tickEvery:
                self.tick()

    def endDrive(self) -> None:
        self._driveDetector.driving = False
        self._handleDriveEnd(DriveSession(startTime=_T0_LOCAL))


def _dbOrch(tmp_path, database, **kw) -> _DbOrch:
    return _DbOrch(str(tmp_path / "states"), database, **kw)


def _oneDrive(orch: _DbOrch, *, tickEvery: bool = True) -> None:
    orch.startDrive()
    orch.drive(_DRIVE_S, tickEvery=tickEvery)
    orch.endDrive()
    orch.advance(_STEP_S)
    orch.tick()
    orch.advance(600.0)


def test_twoDrives_sinceResetSumsThem_andSurvivesARestart(tmp_path, database):
    orch = _dbOrch(tmp_path, database)
    _oneDrive(orch)
    _oneDrive(orch)

    since = orch.tick()["sinceReset"]

    assert since["distanceKm"] == pytest.approx(2 * _DRIVE_KM)
    assert since["fuelL"] == pytest.approx(2 * _DRIVE_L)
    assert since["fuelL"] == pytest.approx(0.66, abs=0.01)
    assert since["mpg"] == pytest.approx(42.65, abs=0.01)
    assert since["resetAtTs"] is not None

    restarted = _dbOrch(tmp_path, database)
    assert restarted.tick()["sinceReset"] == since


def test_threePeriodicPersistsThenDriveEnd_countedOnce(tmp_path, database, monkeypatch):
    writes: list[tuple] = []
    real = fsr.accumulateAndReadFrom

    def spy(db, *args):
        writes.append(args)
        return real(db, *args)

    monkeypatch.setattr(fsr, "accumulateAndReadFrom", spy)
    orch = _dbOrch(tmp_path, database, persistSec=100.0)
    _oneDrive(orch)

    since = orch.tick()["sinceReset"]

    assert len(writes) == 4  # at 100, 200, 300 s and the drive-end remainder
    assert since["distanceKm"] == pytest.approx(_DRIVE_KM)
    assert since["fuelL"] == pytest.approx(_DRIVE_L)
    assert sum(w[0] for w in writes) == pytest.approx(_DRIVE_L)


def test_persist_isAtMostOncePerPersistSec(tmp_path, database, monkeypatch):
    writes: list[tuple] = []
    real = fsr.accumulateAndReadFrom
    monkeypatch.setattr(
        fsr, "accumulateAndReadFrom", lambda db, *a: (writes.append(a), real(db, *a))[1]
    )
    orch = _dbOrch(tmp_path, database, persistSec=60.0)
    orch.startDrive()

    orch.drive(118.0)

    assert len(writes) == 1


def test_crashAfterTheSecondPeriodicPersist_tableHoldsThePersistedPartOnce(
    tmp_path, database
):
    orch = _dbOrch(tmp_path, database, persistSec=60.0)
    orch.startDrive()
    orch.drive(150.0)  # persists at 60 s and 120 s, then 30 s unpersisted
    del orch  # the crash: no drive end, no further tick

    row = fsr.readFrom(database)
    assert row["distance_km"] == pytest.approx(60.0 * 120.0 / 3600.0)
    assert row["fuel_l"] == pytest.approx(10 * 120 / 14.7 / 740)

    restarted = _dbOrch(tmp_path, database, persistSec=60.0)
    since = restarted.tick()["sinceReset"]
    lostKm = 60.0 * 150.0 / 3600.0 - since["distanceKm"]
    assert since["distanceKm"] == pytest.approx(2.0)
    assert 0 < lostKm < 60.0 * 60.0 / 3600.0


def test_openLoopSeconds_accumulate(tmp_path, database):
    orch = _dbOrch(tmp_path, database)
    orch.startDrive()
    orch.drive(_DRIVE_S, status=3)
    orch.endDrive()
    orch.tick()

    assert fsr.readFrom(database)["open_loop_s"] == pytest.approx(_DRIVE_S)


def test_closedLoopDrive_noOpenLoopSeconds(tmp_path, database):
    orch = _dbOrch(tmp_path, database)
    _oneDrive(orch)

    assert fsr.readFrom(database)["open_loop_s"] == 0.0


def test_noDatabase_sinceResetNull_oneWarn(tmp_path, caplog):
    orch = _dbOrch(tmp_path, None)
    orch.startDrive()
    with caplog.at_level(logging.WARNING, logger="pi.obdii.orchestrator"):
        orch.drive(120.0)
        orch.endDrive()
        state = orch.tick()

    assert state["sinceReset"] is None
    assert len([r for r in caplog.records if "fuel_since_reset" in r.getMessage()]) == 1


def test_beforeAnyRow_sinceResetNull(tmp_path, database):
    assert _dbOrch(tmp_path, database).tick()["sinceReset"] is None


def test_persistFailure_isRetried_neverDoubled(tmp_path, database, monkeypatch):
    real = fsr.accumulateAndReadFrom
    calls = {"n": 0}

    def flaky(db, *args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(db, *args)

    monkeypatch.setattr(fsr, "accumulateAndReadFrom", flaky)
    orch = _dbOrch(tmp_path, database)
    _oneDrive(orch)

    row = fsr.readFrom(database)
    assert row["distance_km"] == pytest.approx(_DRIVE_KM)
    assert row["fuel_l"] == pytest.approx(_DRIVE_L)


def test_midDriveProcessStart_countsFromItsFirstReading(tmp_path, database):
    orch = _dbOrch(tmp_path, database, driving=True)
    orch.drive(_DRIVE_S)
    orch.endDrive()
    orch.tick()

    assert fsr.readFrom(database)["fuel_l"] == pytest.approx(_DRIVE_L)


def test_resetSinceReset_zeroesTableCacheAndWatermarkTogether(tmp_path, database):
    orch = _dbOrch(tmp_path, database)
    orch.startDrive()
    orch.drive(100.0)  # one persist at 60 s, then 40 s integrated, unpersisted

    row = orch.resetSinceReset(T2)
    assert (row["fuel_l"], row["reset_at_ts"]) == (0.0, T2)
    assert orch.tick()["sinceReset"]["fuelL"] == 0.0

    orch.advance(_STEP_S)
    orch.drive(60.0)
    orch.endDrive()
    since = orch.tick()["sinceReset"]

    # Only what was integrated AFTER the reset (62 s incl. the joining step).
    assert since["distanceKm"] == pytest.approx(60.0 * 62.0 / 3600.0)
    assert since["resetAtTs"] == T2


def test_resetSinceReset_noDatabase_none(tmp_path):
    assert _dbOrch(tmp_path, None).resetSinceReset(T2) is None
