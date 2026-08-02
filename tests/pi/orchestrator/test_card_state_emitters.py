################################################################################
# File Name: test_card_state_emitters.py
# Purpose/Description: Tests for the US-480-a CardStateEmitterMixin -- the wiring
#   that makes the F-092 system-status / F-097 battery-health / F-111 dtc
#   emitters actually RUN in-process and write their state files. Covers: the
#   initial honest dtc state at boot, the cadence emit of system-status +
#   battery-health with truthful data, the idle-SSOT boolean, honest typed-NA
#   when a source is absent, the cadence gate, sync-outcome caching, and a
#   static guard that this new code opens NO second OBD connection (Atlas Q-1 /
#   A-17 single-ObdConnection invariant, VC3).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-21    | Ralph (Rex)  | Initial -- US-480-a emitter wiring tests.
# ================================================================================
################################################################################

"""Tests for ``pi.obdii.orchestrator.card_state_emitter``."""

import json
from pathlib import Path
from types import SimpleNamespace

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin


def _connectionStatus(*, connected, retryCount=0, totalConnections=0, state="disconnected"):
    return SimpleNamespace(
        connected=connected,
        retryCount=retryCount,
        totalConnections=totalConnections,
        state=state,
    )


class _FakeOrch(CardStateEmitterMixin):
    """Minimal composing object exposing the attrs the mixin reads."""

    def __init__(
        self,
        config,
        *,
        connection=None,
        driveDetector=None,
        powerSourceProvider=None,
        hardwareManager=None,
    ):
        self._config = config
        self._connection = connection
        self._driveDetector = driveDetector
        self._powerSourceProvider = powerSourceProvider
        self._hardwareManager = hardwareManager
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = None
        dash = config.get("pi", {}).get("dashboard", {})
        self._cardStateEmitEnabled = dash.get("stateEmitEnabled", True) is not False
        self._cardStateEmitInterval = float(dash.get("stateEmitIntervalSeconds", 2.0))
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0


def _config(tmp_path, **dashboard):
    return {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": dashboard,
        }
    }


def _readState(tmp_path, name):
    return json.loads((tmp_path / "states" / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _initializeCardStateEmitters -- construction + initial honest dtc state.
# ---------------------------------------------------------------------------


def test_initialize_constructsAllThreeEmitters(tmp_path):
    """All three emitter callables are constructed (F-092/097/111 wired)."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()
    assert orch._systemStatusEmitter is not None
    assert orch._batteryHealthEmitter is not None
    assert orch._dtcEmitter is not None


def test_initialize_writesHonestInitialDtcState_takeoverHidden(tmp_path):
    """AC5: at boot (no KOEO read) the dtc file is written with an HONEST
    unavailable state -- source.dtc.available False, no codes, no takeover
    trigger -- so a parked-from-boot Pi shows 'DTC not read', never a phantom
    Check Engine and never a fabricated all-clear."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["source"]["dtc"]["available"] is False
    assert dtc["codes"] == []
    assert dtc["mil"] is False
    assert dtc["newSinceTs"] is None  # US-405 takeover NOT triggered


def test_initialize_disabled_writesNothing(tmp_path):
    """pi.dashboard.stateEmitEnabled=false -> no emitters, no files."""
    orch = _FakeOrch(_config(tmp_path, stateEmitEnabled=False))
    orch._initializeCardStateEmitters()
    assert orch._dtcEmitter is None
    assert not (tmp_path / "states").exists()


# ---------------------------------------------------------------------------
# _maybeEmitCardStates -- cadence emit of system-status + battery-health.
# ---------------------------------------------------------------------------


def test_maybeEmit_linkedCar_recording_writesRealSystemStatus(tmp_path):
    """A connected car mid-drive -> system-status renders REAL link=linked +
    drive=recording (idle False), not the unavailable wall."""
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=True, totalConnections=2, state="connected"
        )
    )
    dd = SimpleNamespace(isDriving=lambda: True)
    # US-502: the power-source SSOT (PowerSourceProvider over GPIO6), not the
    # never-configured PowerMonitor reader this used to fake.
    psp = SimpleNamespace(isAvailable=True, isExternalPowerPresent=lambda: True)
    orch = _FakeOrch(
        _config(tmp_path, stateEmitIntervalSeconds=0.0),
        connection=conn, driveDetector=dd, powerSourceProvider=psp,
    )
    orch._initializeCardStateEmitters()
    orch._lastSyncOkTsIso = "2026-07-21T19:40:00Z"
    orch._lastSyncRows = 12

    assert orch._maybeEmitCardStates() is True
    ss = _readState(tmp_path, "system-status")
    assert ss["obdLink"]["state"] == "linked"
    assert ss["source"]["obd"]["available"] is True
    assert ss["drive"]["state"] == "recording"
    assert ss["idle"] is False
    assert ss["power"]["source"] == "external"
    assert ss["sync"]["rows"] == 12


def test_maybeEmit_noConnection_parked_idleTrueTypedNa(tmp_path):
    """No connection (car off / bench) + not recording -> OBD source UNAVAILABLE
    (typed NA) and idle True -- the calm parked state US-481 renders."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()

    orch._maybeEmitCardStates()
    ss = _readState(tmp_path, "system-status")
    assert ss["source"]["obd"]["available"] is False
    assert ss["obdLink"]["state"] is None
    assert ss["idle"] is True


def test_maybeEmit_droppedButSeenLink_isDownButAvailable_notIdle(tmp_path):
    """A link that dropped after connecting (totalConnections>0) is `down` but
    still AVAILABLE (we are retrying a real car) -> idle stays False."""
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(
            connected=False, retryCount=3, totalConnections=1, state="error"
        )
    )
    orch = _FakeOrch(
        _config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn,
    )
    orch._initializeCardStateEmitters()

    orch._maybeEmitCardStates()
    ss = _readState(tmp_path, "system-status")
    assert ss["obdLink"] == {"state": "down", "retries": 3, "lastSeenS": None}
    assert ss["source"]["obd"]["available"] is True
    assert ss["idle"] is False


def test_maybeEmit_liveUps_writesRealBatteryValues_healthUnknownNeverGreen(tmp_path):
    """A live MAX17048 -> battery-health renders REAL vcell/soc/crate; with no
    Spool verdict reader the health degrades HONESTLY to 'unknown' (neutral,
    never a fabricated green) and last-health-check is null."""
    ups = SimpleNamespace(
        getBatteryVoltage=lambda: 4.05,
        getBatteryPercentage=lambda: 82,
        getChargeRatePercentPerHour=lambda: -3.2,
    )
    hw = SimpleNamespace(upsMonitor=ups)
    psp = SimpleNamespace(isAvailable=True, isExternalPowerPresent=lambda: False)
    orch = _FakeOrch(
        _config(tmp_path, stateEmitIntervalSeconds=0.0),
        hardwareManager=hw, powerSourceProvider=psp,
    )
    orch._initializeCardStateEmitters()

    orch._maybeEmitCardStates()
    bh = _readState(tmp_path, "battery-health")
    assert bh["source"]["ups"]["available"] is True
    assert bh["vcellV"] == 4.05
    assert bh["soc"] == 82
    assert bh["crate"] == -3.2
    assert bh["draining"] is True  # on battery + negative crate
    assert bh["health"] == "unknown"  # NEVER a fabricated green
    assert bh["lastHealthCheckTs"] is None


def test_maybeEmit_noHardware_batteryTypedNa(tmp_path):
    """No UpsMonitor (bench / hardware disabled) -> battery-health is a typed
    NA (upsAvailable False, every ups reading null) -- honest, never invented."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()

    orch._maybeEmitCardStates()
    bh = _readState(tmp_path, "battery-health")
    assert bh["source"]["ups"]["available"] is False
    assert bh["vcellV"] is None
    assert bh["soc"] is None


def test_maybeEmit_cadenceGate_secondCallNotDue(tmp_path):
    """With a real interval, a second immediate call short-circuits (not due)."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=999.0))
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True   # first tick always fires
    assert orch._maybeEmitCardStates() is False  # not due yet


def test_recordSyncOutcome_cachesTimestampAndRows(tmp_path):
    """The sync-trigger hook caches a fresh ISO ts + row count for the tile."""
    orch = _FakeOrch(_config(tmp_path))
    orch._recordSyncOutcome(7)
    assert orch._lastSyncRows == 7
    assert orch._lastSyncOkTsIso is not None
    assert orch._lastSyncOkTsIso.endswith("Z")


# ---------------------------------------------------------------------------
# VC3 -- the emitter wiring opens NO second OBD connection (Atlas Q-1 / A-17).
# ---------------------------------------------------------------------------


def test_cardStateEmitter_opensNoSecondObdConnection():
    """Static guard: the card-state emitter module never opens its own OBD
    connection -- it is a pure consumer of data the orchestrator already holds.
    Any obd.OBD(/ .connect(/ createConnectionFromConfig here would re-introduce
    the A-17 second-connection race (VC3)."""
    src = (
        Path(__file__).resolve().parents[3]
        / "src" / "pi" / "obdii" / "orchestrator" / "card_state_emitter.py"
    ).read_text(encoding="utf-8")
    assert "obd.OBD(" not in src
    assert "createConnectionFromConfig" not in src
    assert ".connect(" not in src
