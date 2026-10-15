################################################################################
# File Name: test_fuel_reset_request_service.py
# Purpose/Description: US-881-d -- the eclipse-obd half of POST /fuel-reset: the
#                      run-loop hook that services a fuel reset request beside
#                      _maybeServiceDtcClearRequest, refusing while a drive is
#                      recording and otherwise resetting through the provider's
#                      resetSinceReset (table, cache and watermark together).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-d) | Initial.
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
    return orch


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
    orch = _orch(tmp_path, database, persistSec=60.0)
    orch.startDrive()
    orch.drive(100.0)  # one periodic persist at 60 s
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


def test_recordingFactIsGatherDriveStates(tmp_path, database, monkeypatch):
    orch = _orch(tmp_path, database)
    monkeypatch.setattr(orch, "_gatherDriveState", lambda: ("recording", 7))
    frc.writeRequest(orch.statesDir, "r3")

    orch._maybeServiceFuelResetRequest()

    assert frc.readOutcome(orch.statesDir)["reason"] == "driving"


def test_noProviderOrDatabase_refusesUnavailable(tmp_path):
    orch = _orch(tmp_path, None)
    frc.writeRequest(orch.statesDir, "r4")

    assert orch._maybeServiceFuelResetRequest() is True

    outcome = frc.readOutcome(orch.statesDir)
    assert (outcome["ok"], outcome["reason"]) == (False, "unavailable")


def test_resetRaises_publishesTheFailure_andNeverPropagates(tmp_path, database, monkeypatch):
    orch = _orch(tmp_path, database)

    def boom(ts: str) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(orch, "resetSinceReset", boom)
    frc.writeRequest(orch.statesDir, "r5")

    assert orch._maybeServiceFuelResetRequest() is True

    outcome = frc.readOutcome(orch.statesDir)
    assert outcome["ok"] is False
    assert "database is locked" in outcome["reason"]
    assert frc.readRequest(orch.statesDir) is None


def test_resetThenNextCardTick_zeroes_thenOnlyPostResetChangePersists(tmp_path, database):
    orch = _orch(tmp_path, database, persistSec=60.0)
    _oneDrive(orch)
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
