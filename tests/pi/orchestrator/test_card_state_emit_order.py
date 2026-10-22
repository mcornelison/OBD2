################################################################################
# File Name: test_card_state_emit_order.py
# Purpose/Description: US-877-b (Atlas P6) -- the card tick's ORDER. The
#                      system-status verdict counts stalled capture feeds, so
#                      capture-health must emit FIRST and hand the payload it
#                      wrote to system-status in-process: never a file
#                      read-back of the previous tick.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-877-b)| Initial -- the order pin, the handoff, and the
#               |              | first-tick join through the real emitters.
# ================================================================================
################################################################################

"""US-877-b: capture-health emits before system-status and feeds its verdict."""

from __future__ import annotations

import json

from pi.obdii.capture_health import makeCaptureHealthEmitter
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.health_monitor import HealthMonitorMixin

_STALL_S = 60.0


class _RecordingHost(CardStateEmitterMixin):
    """Every emit on the tick replaced by a recorder; only the ORDER is real."""

    def __init__(self) -> None:
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._lastCardStateEmitTime = None
        self.calls: list[tuple[str, object]] = []
        self.capturePayload: dict | None = {"state": "ok", "feeds": {}}

    def _emitCaptureHealthState(self):
        self.calls.append(("capture-health", None))
        return self.capturePayload

    def _emitSystemStatusState(self, captureHealth=None):
        self.calls.append(("system-status", captureHealth))

    def _emitBatteryHealthState(self):
        self.calls.append(("battery-health", None))

    def _emitGearState(self):
        self.calls.append(("gear", None))

    def _emitLtftTrendState(self):
        self.calls.append(("ltft-trend", None))

    def _emitObdLiveState(self):
        self.calls.append(("obd-live", None))
        return None

    def _emitAlertsState(self, obdLive):
        self.calls.append(("alerts", None))

    def _emitFuelEconomyState(self):
        self.calls.append(("fuel-economy", None))


def _names(host: _RecordingHost) -> list[str]:
    return [name for name, _arg in host.calls]


def test_captureHealth_emitsBeforeSystemStatus():
    host = _RecordingHost()

    assert host._maybeEmitCardStates() is True

    names = _names(host)
    assert names.index("capture-health") < names.index("system-status")
    assert names.count("capture-health") == 1


def test_systemStatus_isHandedTheVeryPayloadCaptureHealthReturned():
    host = _RecordingHost()

    host._maybeEmitCardStates()

    handed = dict(host.calls)["system-status"]
    assert handed is host.capturePayload


def test_aCaptureHealthEmitThatRaises_stillEmitsSystemStatus_withNone():
    """The verdict then has no capture member; the tick goes on."""

    class _Raising(_RecordingHost):
        def _emitCaptureHealthState(self):
            raise RuntimeError("gather failed")

    host = _Raising()

    host._maybeEmitCardStates()

    assert ("system-status", None) in host.calls


def test_theCaptureEmitter_returnsThePayloadItWrote(tmp_path):
    statesDir = str(tmp_path / "states")
    emit = makeCaptureHealthEmitter(statesDir, nowIsoFn=lambda: "2026-10-22T12:00:00Z")

    returned = emit(
        lastRowSecondsAgo=1.0, freshnessReason=None, powerSource="external",
        stallSeconds=_STALL_S, feedSamples={"obd": ("2026-10-22T11:00:00Z", 1.0)},
    )

    written = json.loads((tmp_path / "states" / "capture-health").read_text(encoding="utf-8"))
    assert returned == written
    assert returned["feeds"]["obd"]["state"] == "ok"


def test_theCaptureEmitter_returnsNone_whenTheWriteFailed(tmp_path):
    blocker = tmp_path / "states"
    blocker.write_text("a file where the states dir should be", encoding="utf-8")
    emit = makeCaptureHealthEmitter(str(blocker))

    returned = emit(
        lastRowSecondsAgo=1.0, freshnessReason=None, powerSource="external",
        stallSeconds=_STALL_S,
    )

    assert returned is None


class _FakePowerSourceProvider:
    """On car power: what `_gatherPowerSource` reads."""

    isAvailable = True

    def isExternalPowerPresent(self) -> bool:
        return True


class _Orch(HealthMonitorMixin, CardStateEmitterMixin):
    """The real mixins in production order, with both real emitters built by
    ``_initializeCardStateEmitters``; only the ECU link and the feed ages are
    seamed (they need a car)."""

    def __init__(self, statesDir: str) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
                "captureHealth": {"enabled": True, "stallSeconds": _STALL_S},
            }
        }
        self._connection = None
        self._driveDetector = None
        self._hardwareManager = None
        self._dataLogger = None
        self._database = None
        self._powerSourceProvider = _FakePowerSourceProvider()
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncRows = 0

    def _gatherLinkChain(self):
        up = {"state": "up", "ts": "2026-10-22T11:00:00Z", "lastOkTs": "2026-10-22T11:00:00Z"}
        return {"bt": dict(up), "adapter": dict(up), "ecu": dict(up)}

    def _gatherCaptureFeedSamples(self):
        # The OBD feed's last sample is far past the stall window.
        return {"obd": ("2026-10-22T11:00:00Z", _STALL_S * 10)}


def test_firstTick_theVerdictCountsThisTicksStall_noPreviousFileExists(tmp_path):
    """On the very first tick there is no capture-health file to read back, so
    a capture member can only come from the in-process handoff."""
    statesDir = tmp_path / "states"
    orch = _Orch(str(statesDir))
    orch._initializeCardStateEmitters()
    assert not (statesDir / "capture-health").exists()

    orch._maybeEmitCardStates()

    capture = json.loads((statesDir / "capture-health").read_text(encoding="utf-8"))
    status = json.loads((statesDir / "system-status").read_text(encoding="utf-8"))
    assert capture["feeds"]["obd"]["state"] == "stalled"
    assert {"key": "capture", "reason": "OBD feed stalled."} in status["verdict"]["members"]
