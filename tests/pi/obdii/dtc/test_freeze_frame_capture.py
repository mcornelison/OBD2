################################################################################
# File Name: test_freeze_frame_capture.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109) -- Pi-side Mode 02
#                      freeze-frame capture tests (V-2 / V-5 / V-6).  A MIL_ON
#                      rising edge triggers a Mode 02 enumeration of 16 PIDs
#                      (mirroring the project's Mode 01 set); the capture writes
#                      a single dtc_freeze_frame row keyed by (dtc_log_id,
#                      captured_at) with the active vehicle_info row resolved.
#                      When Mode 02 is unavailable the row is still written with
#                      pid_responses_json={} + a notes gap explanation (graceful
#                      degradation).  Real ObdDatabase + fake OBD connection.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 Pi Mode 02 freeze-frame capture.
# ================================================================================
################################################################################

"""US-368 / F-109 Pi-side Mode 02 freeze-frame capture tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.dtc_freeze_frame_schema import (
    DTC_FREEZE_FRAME_TABLE,
    ensureDtcFreezeFrameTable,
)
from src.pi.obdii.freeze_frame import (
    FREEZE_FRAME_PARAMETERS,
    FreezeFrameCapture,
    Mode02Client,
)
from src.pi.obdii.obd_parameters import REALTIME_PARAMETERS

# ================================================================================
# Fakes
# ================================================================================


class _FakeResponse:
    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _FakeConnection:
    """Returns scripted Mode 02 (DTC_<NAME>) responses; null for the rest."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self._responses = responses or {}
        self.obd = SimpleNamespace(query=self._query)

    def _query(self, cmd: Any) -> Any:
        name = cmd if isinstance(cmd, str) else getattr(cmd, "name", str(cmd))
        return self._responses.get(name) or _FakeResponse(value=None, null=True)

    def isConnected(self) -> bool:
        return True


def _factory(name: str) -> str:
    return name


def _all16Mode02Responses() -> dict[str, _FakeResponse]:
    """One healthy Mode 02 response per freeze-frame PID (DTC_<NAME>)."""
    return {
        f"DTC_{name}": _FakeResponse(value=float(i + 1))
        for i, name in enumerate(FREEZE_FRAME_PARAMETERS)
    }


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_freeze_frame.db"), walMode=False)
    db.initialize()
    return db


def _seedVehicle(db: ObdDatabase, vin: str = "4A3AK34T0XE000000") -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vehicle_info (vin, make, model, year) "
            "VALUES (?, ?, ?, ?)",
            (vin, "Mitsubishi", "Eclipse", 1998),
        )
        conn.commit()
    return vin


def _readFreezeFrames(db: ObdDatabase) -> list[dict[str, Any]]:
    with db.connect() as conn:
        cursor = conn.execute(
            f"SELECT id, dtc_log_id, captured_at_timestamp_utc, "
            f"pid_responses_json, vehicle_info_vin, notes "
            f"FROM {DTC_FREEZE_FRAME_TABLE} ORDER BY id"
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]


def _capture(db: ObdDatabase) -> FreezeFrameCapture:
    return FreezeFrameCapture(
        database=db, mode02Client=Mode02Client(commandFactory=_factory),
    )


# ================================================================================
# Grounding -- the 16-PID set
# ================================================================================


def test_freezeFrameParameters_areExactly16():
    assert len(FREEZE_FRAME_PARAMETERS) == 16


def test_freezeFrameParameters_areAllRealRealtimeParameters():
    """Grounding (Refusal Rule 2): each PID is a real project Mode 01 parameter."""
    for name in FREEZE_FRAME_PARAMETERS:
        assert name in REALTIME_PARAMETERS, f"{name!r} is not a REALTIME parameter"


def test_freezeFrameParameters_haveNoDuplicates():
    assert len(set(FREEZE_FRAME_PARAMETERS)) == len(FREEZE_FRAME_PARAMETERS)


# ================================================================================
# Schema
# ================================================================================


def test_ensureDtcFreezeFrameTable_isIdempotent(freshDb: ObdDatabase):
    with freshDb.connect() as conn:
        # initialize() already created it -> second ensure is a no-op (False).
        assert ensureDtcFreezeFrameTable(conn) is False


# ================================================================================
# V-2 -- MIL_ON triggers Mode 02, writes a row with 16 PIDs + resolved vehicle
# ================================================================================


def test_milEvent_captures16Pids_resolvesActiveVehicle(freshDb: ObdDatabase):
    vin = _seedVehicle(freshDb)
    conn = _FakeConnection(responses=_all16Mode02Responses())

    result = _capture(freshDb).captureOnMilEvent(
        connection=conn, dtcLogId=42,
    )

    rows = _readFreezeFrames(freshDb)
    assert len(rows) == 1
    row = rows[0]
    assert row["dtc_log_id"] == 42
    assert row["vehicle_info_vin"] == vin
    pids = json.loads(row["pid_responses_json"])
    assert len(pids) == 16
    assert set(pids) == set(FREEZE_FRAME_PARAMETERS)
    assert result.pidCount == 16


# ================================================================================
# V-6 -- Mode 02 unavailable -> {} + notes, no crash
# ================================================================================


def test_milEvent_mode02Unavailable_writesEmptyJsonWithNotes(freshDb: ObdDatabase):
    _seedVehicle(freshDb)
    conn = _FakeConnection(responses={})  # every DTC_<NAME> query returns null

    result = _capture(freshDb).captureOnMilEvent(connection=conn, dtcLogId=7)

    rows = _readFreezeFrames(freshDb)
    assert len(rows) == 1
    row = rows[0]
    assert json.loads(row["pid_responses_json"]) == {}
    assert row["notes"]  # a non-empty gap explanation
    assert "unavailable" in row["notes"].lower()
    assert result.pidCount == 0


def test_milEvent_noVehicleInfoRow_stillWritesWithNullVin(freshDb: ObdDatabase):
    """No vehicle_info row seeded -> capture still writes (vehicle_info_vin NULL).

    The Pi may capture a freeze-frame before VIN decode lands; the server
    writer-path resolves the ECU on sync (US-369).
    """
    conn = _FakeConnection(responses=_all16Mode02Responses())
    _capture(freshDb).captureOnMilEvent(connection=conn, dtcLogId=1)
    rows = _readFreezeFrames(freshDb)
    assert len(rows) == 1
    assert rows[0]["vehicle_info_vin"] is None


# ================================================================================
# Mode02Client enumeration
# ================================================================================


def test_milEvent_dtcLogIdNone_bindsToLatestDtcLogRow(freshDb: ObdDatabase):
    """dtcLogId=None (orchestrator path) -> binds to the most-recent dtc_log row."""
    with freshDb.connect() as conn:
        conn.execute(
            "INSERT INTO dtc_log (dtc_code, status) VALUES (?, ?)", ("P0301", "stored"),
        )
        conn.execute(
            "INSERT INTO dtc_log (dtc_code, status) VALUES (?, ?)", ("P0302", "stored"),
        )
        conn.commit()
        latestId = conn.execute("SELECT MAX(id) FROM dtc_log").fetchone()[0]

    conn = _FakeConnection(responses=_all16Mode02Responses())
    _capture(freshDb).captureOnMilEvent(connection=conn, dtcLogId=None)

    rows = _readFreezeFrames(freshDb)
    assert len(rows) == 1
    assert rows[0]["dtc_log_id"] == latestId


def test_milEvent_dtcLogIdNone_noDtcRows_bindsNull(freshDb: ObdDatabase):
    """dtcLogId=None with an empty dtc_log -> freeze-frame dtc_log_id is NULL."""
    conn = _FakeConnection(responses=_all16Mode02Responses())
    _capture(freshDb).captureOnMilEvent(connection=conn, dtcLogId=None)
    rows = _readFreezeFrames(freshDb)
    assert rows[0]["dtc_log_id"] is None


def test_mode02Client_enumerate_returnsAvailablePidsOnly(freshDb: ObdDatabase):
    # Only two PIDs respond; the rest are null -> dict has exactly those two.
    partial = {
        "DTC_RPM": _FakeResponse(value=3500.0),
        "DTC_COOLANT_TEMP": _FakeResponse(value=88.0),
    }
    client = Mode02Client(commandFactory=_factory)
    pids = client.enumerate(_FakeConnection(responses=partial))
    assert pids == {"RPM": 3500.0, "COOLANT_TEMP": 88.0}
