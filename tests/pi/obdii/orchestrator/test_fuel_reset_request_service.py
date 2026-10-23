################################################################################
# File Name: test_fuel_reset_request_service.py
# Purpose/Description: US-881-d -- the eclipse-obd half of POST /fuel-reset: the
#                      run-loop hook that services a fuel reset request beside
#                      _maybeServiceDtcClearRequest, re-checking the US-923
#                      gate (fuel_reset_gate.resetAllowed: parked, or fresh
#                      SPEED <= 8 km/h) and otherwise resetting through the
#                      provider's resetSinceReset (table, cache and watermark
#                      together).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-d) | Initial.
# 2026-10-22    | Rex (US-923)   | MOVED PIN: the gate is resetAllowed, not
#                                "recording -> driving"; each reset case feeds
#                                the gear/speed it is allowed on.
# ================================================================================
################################################################################

"""US-881-d: eclipse-obd services the fuel reset request."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import threading
import time
import types
import urllib.request
from typing import Any

import pytest

from common.time.helper import toCanonicalIso
from pi.obdii import fuel_since_reset as fsr
from pi.obdii.database import ObdDatabase
from pi.obdii.gear_derivation import GearReading, Reading
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.splash import fuel_reset_channel as frc
from pi.splash.states_http_server import StatesHttpServer
from tests.pi.obdii.test_fuel_economy_emitter import _STEP_S
from tests.pi.obdii.test_fuel_since_reset import _DRIVE_KM, _DRIVE_L, _DbOrch, _oneDrive

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


@pytest.fixture
def database(tmp_path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    return db


def _orch(tmp_path, database, **kw: Any) -> _DbOrch:
    orch = _DbOrch(str(tmp_path / "states"), database, **kw)
    orch._maybeServiceFuelResetRequest = types.MethodType(
        ApplicationOrchestrator._maybeServiceFuelResetRequest, orch
    )
    # US-923: the gate's ONE clock is _gearNowS (Atlas GAP 2), driven here by
    # the harness's monotonic t like the trip clock.
    orch._gearClock = lambda: orch.t
    return orch


def _parkedGear(orch: _DbOrch, gear: str = "P") -> None:
    """What _emitGearState caches when it publishes P/N at the current t."""
    orch._lastGearReading = GearReading(available=True, gear=gear, reason="park")
    orch._lastGearAtS = orch.t


def _inGear(orch: _DbOrch, gear: int = 3) -> None:
    orch._lastGearReading = GearReading(available=True, gear=gear, reason="engaged")
    orch._lastGearAtS = orch.t


def _speed(orch: _DbOrch, kph: float, ageS: float = 0.0) -> None:
    """The deriver's SPEED reading, stamped on the gear clock."""
    orch._lastSpeedReading = Reading(value=kph, tsS=orch.t - ageS)


def _nowTs(orch: _DbOrch) -> str:
    return toCanonicalIso(orch._obdLiveNowUtc())


def test_noRequest_isANoOp(tmp_path, database):
    orch = _orch(tmp_path, database)

    assert orch._maybeServiceFuelResetRequest() is False
    assert frc.readOutcome(orch.statesDir) is None


def test_parked_resetsTheTotals_publishesOkWithResetAtTs(tmp_path, database):
    orch = _orch(tmp_path, database)
    _oneDrive(orch)
    assert fsr.readFrom(database)["fuel_l"] == pytest.approx(_DRIVE_L)
    _parkedGear(orch)  # MOVED PIN (US-923): allowed because parked
    frc.writeRequest(orch.statesDir, "r1")

    assert orch._maybeServiceFuelResetRequest() is True

    row = fsr.readFrom(database)
    assert (row["fuel_l"], row["distance_km"], row["open_loop_s"]) == (0.0, 0.0, 0.0)
    assert row["reset_at_ts"] == _nowTs(orch)
    outcome = frc.readOutcome(orch.statesDir)
    assert (outcome["requestId"], outcome["ok"], outcome["reason"]) == ("r1", True, None)
    assert outcome["resetAtTs"] == _nowTs(orch)
    assert frc.readRequest(orch.statesDir) is None  # consumed


def test_driving_refusesWithReasonDriving_totalsUnchanged(tmp_path, database, monkeypatch):
    """MOVED PIN (US-923): refused because a fresh SPEED (60 km/h) is over
    pi.fuel.resetMaxSpeedKph in gear -- not because a drive is recording."""
    orch = _orch(tmp_path, database, persistSec=60.0)
    orch.startDrive()
    orch.drive(100.0)  # one periodic persist at 60 s
    _inGear(orch, 4)
    _speed(orch, 60.0)
    before = fsr.readFrom(database)
    calls: list[str] = []
    monkeypatch.setattr(orch, "resetSinceReset", lambda ts: calls.append(ts))
    frc.writeRequest(orch.statesDir, "r2")

    assert orch._maybeServiceFuelResetRequest() is True

    assert calls == []
    assert fsr.readFrom(database) == before
    outcome = frc.readOutcome(orch.statesDir)
    assert (outcome["requestId"], outcome["ok"], outcome["reason"]) == ("r2", False, "driving")
    assert outcome["resetAtTs"] is None
    assert frc.readRequest(orch.statesDir) is None


def test_recordingAlone_noLongerRefuses_theGateDoes(tmp_path, database, monkeypatch):
    """MOVED PIN (US-923): was test_recordingFactIsGatherDriveStates (recording
    -> driving). A recording drive at walking pace is allowed (Atlas C3)."""
    orch = _orch(tmp_path, database)
    monkeypatch.setattr(orch, "_gatherDriveState", lambda: ("recording", 7))
    _inGear(orch, 1)
    _speed(orch, 5.0)
    frc.writeRequest(orch.statesDir, "r3")

    orch._maybeServiceFuelResetRequest()

    outcome = frc.readOutcome(orch.statesDir)
    assert (outcome["ok"], outcome["reason"]) == (True, None)


def test_noProviderOrDatabase_refusesUnavailable(tmp_path):
    orch = _orch(tmp_path, None)
    _parkedGear(orch)  # MOVED PIN (US-923): past the gate, to reach the provider
    frc.writeRequest(orch.statesDir, "r4")

    assert orch._maybeServiceFuelResetRequest() is True

    outcome = frc.readOutcome(orch.statesDir)
    assert (outcome["ok"], outcome["reason"]) == (False, "unavailable")


def test_resetRaises_publishesTheFailure_andNeverPropagates(tmp_path, database, monkeypatch):
    orch = _orch(tmp_path, database)

    def boom(ts: str) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(orch, "resetSinceReset", boom)
    _parkedGear(orch)  # MOVED PIN (US-923)
    frc.writeRequest(orch.statesDir, "r5")

    assert orch._maybeServiceFuelResetRequest() is True

    outcome = frc.readOutcome(orch.statesDir)
    assert outcome["ok"] is False
    assert "database is locked" in outcome["reason"]
    assert frc.readRequest(orch.statesDir) is None


def test_resetThenNextCardTick_zeroes_thenOnlyPostResetChangePersists(tmp_path, database):
    orch = _orch(tmp_path, database, persistSec=60.0)
    _oneDrive(orch)
    _parkedGear(orch)  # MOVED PIN (US-923)
    frc.writeRequest(orch.statesDir, "r6")
    orch._maybeServiceFuelResetRequest()
    resetAt = _nowTs(orch)

    since = orch.tick()["sinceReset"]
    assert (since["fuelL"], since["distanceKm"], since["resetAtTs"]) == (0.0, 0.0, resetAt)

    # The next drive's first periodic persist (at 60 s) adds only its own change.
    orch.startDrive()
    orch.drive(60.0)
    since = orch.tick()["sinceReset"]
    assert since["distanceKm"] == pytest.approx(60.0 * 60.0 / 3600.0)
    assert since["fuelL"] == pytest.approx(10 * 60 / 14.7 / 740)
    assert since["distanceKm"] < _DRIVE_KM
    assert since["resetAtTs"] == resetAt


def test_postFuelReset_endToEnd_parked_200_andTotalsZero(tmp_path, database):
    """The route, the real bridge and the real hook in a service thread."""
    orch = _orch(tmp_path, database)
    _oneDrive(orch)
    orch.advance(_STEP_S)
    _parkedGear(orch, "N")  # MOVED PIN (US-923)
    stop = threading.Event()

    def obdLoop() -> None:
        while not stop.is_set():
            orch._maybeServiceFuelResetRequest()
            time.sleep(0.01)

    service = threading.Thread(target=obdLoop, daemon=True)
    service.start()
    srv = StatesHttpServer(
        statesDir=orch.statesDir, token=_TOKEN, port=0,
        fuelResetRunner=frc.makeBridgeResetRunner(orch.statesDir, timeoutSeconds=5.0),
    )
    http = threading.Thread(target=srv.serveForever, daemon=True)
    http.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.actualPort}/fuel-reset", data=b"{}", method="POST"
        )
        req.add_header("X-Splash-Token", _TOKEN)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, body = resp.status, json.loads(resp.read())
    finally:
        srv.shutdown()
        http.join(timeout=5)
        stop.set()
        service.join(timeout=5)

    assert (status, body) == (200, {"ok": True, "resetAtTs": _nowTs(orch)})
    row = fsr.readFrom(database)
    assert (row["fuel_l"], row["distance_km"]) == (0.0, 0.0)


# ============================================ US-923 the service-time gate


def _serve(orch: _DbOrch, requestId: str = "g1") -> dict:
    frc.writeRequest(orch.statesDir, requestId)
    assert orch._maybeServiceFuelResetRequest() is True
    return frc.readOutcome(orch.statesDir)


_GATE_ROWS = {
    "P": (lambda o: _parkedGear(o, "P"), (True, None)),
    "N-speed0": (lambda o: (_parkedGear(o, "N"), _speed(o, 0.0)), (True, None)),
    "gear3-5kph": (lambda o: (_inGear(o), _speed(o, 5.0)), (True, None)),
    "gear3-8kph": (lambda o: (_inGear(o), _speed(o, 8.0)), (True, None)),
    "gear3-9kph": (lambda o: (_inGear(o), _speed(o, 9.0)), (False, "driving")),
    "speed-stale": (lambda o: (_inGear(o), _speed(o, 0.0, ageS=3.5)),
                    (False, "speed_unknown")),
    "speed-missing": (lambda o: _inGear(o), (False, "speed_unknown")),
}


@pytest.mark.parametrize("row", sorted(_GATE_ROWS))
def test_vc_theServiceGate_perValidationRow(tmp_path, database, row):
    setup, expected = _GATE_ROWS[row]
    orch = _orch(tmp_path, database)
    setup(orch)

    outcome = _serve(orch)

    assert (outcome["ok"], outcome["reason"]) == expected
    if not expected[0]:
        assert outcome["resetAtTs"] is None


def test_vc_aStaleCachedP_atFreshSpeed40_isRefusedDriving(tmp_path, database):
    """GAP 1: the P cached before the car moved off ages out after maxAgeS."""
    orch = _orch(tmp_path, database)
    _parkedGear(orch)
    orch.advance(3.5)
    _speed(orch, 40.0)

    assert _serve(orch)["reason"] == "driving"


def test_vc_aSpeedReadingTwoSecondsOldOnTheGearClock_isFresh(tmp_path, database):
    """GAP 2: one clock. The trip clock is far off; only _gearNowS counts."""
    orch = _orch(tmp_path, database)
    _inGear(orch)
    _speed(orch, 8.0, ageS=2.0)
    orch._tripClock = lambda: orch.t + 10_000.0

    assert _serve(orch)["ok"] is True


def test_theRefusal_isThePublishedReason(tmp_path, database):
    """The page word and the outcome cannot disagree: one predicate."""
    orch = _orch(tmp_path, database)
    for kph, age in ((40.0, 0.0), (0.0, 9.0)):
        _inGear(orch)
        _speed(orch, kph, ageS=age)
        published = orch.tick()["resetAllowed"]
        outcome = _serve(orch)
        assert published["value"] is False
        assert outcome["reason"] == published["reason"]


def test_vc_resetMidRecording_thenAPersist_onlyPostResetDeltas(tmp_path, database):
    """Atlas C3: a walking-pace reset mid-drive moves the watermark; the next
    persist adds only what came after it, and thisDrive is untouched."""
    orch = _orch(tmp_path, database, persistSec=60.0)
    orch.startDrive()
    orch.drive(30.0)
    thisDriveBefore = orch.tick()["thisDrive"]["fuelL"]
    _inGear(orch, 1)
    _speed(orch, 5.0)

    assert _serve(orch)["ok"] is True
    assert orch.tick()["thisDrive"]["fuelL"] == pytest.approx(thisDriveBefore)

    orch.drive(60.0)
    orch.endDrive()  # the drive-end persist
    orch.advance(_STEP_S)
    state = orch.tick()
    thisDrive = state["thisDrive"]["fuelL"]
    assert state["sinceReset"]["fuelL"] == pytest.approx(thisDrive - thisDriveBefore)
    assert 0.0 < state["sinceReset"]["fuelL"] < thisDrive


def test_vc_resetInTheSameTickAsADriveStart_theGenerationGuardHolds(
        tmp_path, database, monkeypatch):
    """A drive start landing inside the reset owns the watermark: the reset
    must not write the old drive's totals over the new drive's zero."""
    orch = _orch(tmp_path, database)
    _oneDrive(orch)
    orch.startDrive()
    orch.drive(10.0)
    _parkedGear(orch, "N")
    real = fsr.resetAndReadFrom

    def resetWithADriveStart(db: Any, ts: str) -> Any:
        row = real(db, ts)
        orch._resetFuelEconomy()  # the drive start, between snapshot and set
        return row

    monkeypatch.setattr(fsr, "resetAndReadFrom", resetWithADriveStart)

    assert _serve(orch)["ok"] is True
    assert orch._fuelWatermark == (0.0, 0.0, 0.0)


def test_runLoop_callsTheHook_besideTheDtcClearHook():
    tree = ast.parse(textwrap.dedent(inspect.getsource(ApplicationOrchestrator.runLoop)))
    called = [
        attr
        for _, attr in sorted(
            (node.lineno, node.func.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        )
    ]

    assert "_maybeServiceFuelResetRequest" in called
    assert called.index("_maybeServiceFuelResetRequest") == (
        called.index("_maybeServiceDtcClearRequest") + 1
    )
