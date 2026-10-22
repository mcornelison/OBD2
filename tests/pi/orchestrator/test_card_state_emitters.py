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
# 2026-10-19    | Ralph (Rex)  | US-897-a2 -- checkedAtTs / pendingCheckedAtTs:
#               |              | the per-boot seed and the publish success rule.
# 2026-10-20    | Ralph (Rex)  | US-897-b2 -- the alerts arbiter wiring.
# 2026-10-21    | Ralph (Rex)  | US-897-e -- the restart seed carries the
#               |              | pending set with its time (VCs 3, 7, 8).
# 2026-10-22    | Ralph (Rex)  | US-876-c -- system-status `link`: the ECU layer
#               |              | from reachability, retry authority (C2) + hold.
# 2026-10-22    | Ralph (Rex)  | US-876-d -- link.adapter from the connection's
#               |              | adapter observation (VCs 1-2, G1, D2, D5).
# 2026-10-22    | Ralph (Rex)  | US-876-e -- link.bt from the BT sampler (VCs
#               |              | 1-2, E2, E4, G1, MAC sources, off-tick thread).
# 2026-10-22    | Ralph (Rex)  | US-732 -- system-status wifi from the WiFi
#               |              | sampler; one lazy HomeNetworkDetector; W4.
# ================================================================================
################################################################################

"""Tests for ``pi.obdii.orchestrator.card_state_emitter``."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.obdii.orchestrator.event_router import EventRouterMixin


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
    # US-752: honest absences, not []/false defaults.
    assert dtc["codes"] is None
    assert dtc["mil"] is None
    assert dtc["lastKnown"] is None  # no database -> nothing remembered
    assert dtc["newSinceTs"] is None  # US-405 takeover NOT triggered


class _RecordingConnection:
    """Records every attribute the boot path reaches for on the OBD connection."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AttributeError(name)


def test_initialize_restingStateCarriesLastKnownFromDtcLog_noEcuQuery(tmp_path):
    """US-752: with codes previously persisted in dtc_log and no live read, the
    boot `dtc` state carries them in lastKnown -- dated from last_seen_timestamp
    -- while the live fields stay null, and the OBD connection is never queried
    to populate it (one acquisition path)."""
    from pi.obdii.database import ObdDatabase

    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO dtc_log (dtc_code, description, status, last_seen_timestamp) "
            "VALUES ('P0443', 'EVAP purge', 'stored', '2026-09-14T09:00:00Z')"
        )
    connection = _RecordingConnection()
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=connection)
    orch._database = db

    orch._initializeCardStateEmitters()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["codes"] is None
    assert dtc["mil"] is None
    assert dtc["newSinceTs"] is None
    assert dtc["lastKnown"]["asOfTs"] == "2026-09-14T09:00:00Z"
    assert dtc["lastKnown"]["source"] == "dtc_log"
    assert dtc["lastKnown"]["mil"] is True
    assert [c["code"] for c in dtc["lastKnown"]["codes"]] == ["P0443"]
    assert not {"query", "obd"} & set(connection.touched), connection.touched


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
    # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
    assert ss["obdLink"] == {"state": "down", "retries": 3}
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


# ---------------------------------------------------------------------------
# US-897-a2 -- states/dtc says when codes were last read successfully this boot
# (ARCH-062 + Atlas Q2/Q3 2026-10-19). Router + card-state mixins composed the
# way the orchestrator composes them, writing through the REAL dtc emitter.
# ---------------------------------------------------------------------------

_T0 = "2026-10-20T15:00:00Z"
_T1 = "2026-10-20T15:02:11Z"
_T2 = "2026-10-20T15:02:41Z"


def _code(code, status):
    return SimpleNamespace(code=code, status=status, description="")


def _read(codes=(), *, frameNull=False, mode07=True, polled=True):
    """A logger result shaped like the a1/a2 result types."""
    return SimpleNamespace(
        storedCount=0, pendingCount=0, inserted=0, updated=0,
        mode07Probe=SimpleNamespace(
            supported=mode07, reason="supported" if mode07 else "unsupported"
        ),
        codes=list(codes), polled=polled, mode03FrameNull=frameNull,
    )


class _ScriptedDtcLogger:
    """Every entry point answers with `self.next` (or raises it)."""

    def __init__(self):
        self.next = _read()

    def _answer(self):
        if isinstance(self.next, Exception):
            raise self.next
        return self.next

    def logKeyOnDtcs(self, *, connection):
        return self._answer()

    def logSessionStartDtcs(self, *, driveId, connection):
        return self._answer()

    def logMilEventDtcs(self, *, driveId, connection):
        return self._answer()

    def maybePeriodicMode03(self, *, driveId, connection):
        return self._answer()


class _DtcOrch(_FakeOrch, EventRouterMixin):
    def __init__(self, config):
        super().__init__(config, connection=object())
        self._dtcLogger = _ScriptedDtcLogger()
        self._dtcCarriedPending = []
        self._dtcCheckedAtTs = None
        self._dtcPendingCheckedAtTs = None


@pytest.fixture()
def clock(monkeypatch):
    """Pin the dtc read-time clock (the router stamps the read with it)."""
    from pi.splash import dtc_emitter

    now = {"iso": _T0}
    monkeypatch.setattr(dtc_emitter, "dtcNowIso", lambda: now["iso"])
    return now


@pytest.fixture()
def driveSeven():
    from pi.obdii.drive_id import setCurrentDriveId

    setCurrentDriveId(7)
    yield
    setCurrentDriveId(None)


def _bootedOrch(tmp_path):
    orch = _DtcOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()
    return orch


def _dtcBytes(tmp_path):
    return (tmp_path / "states" / "dtc").read_bytes()


def test_a2_successfulRead_advancesCheckedAtTs_codesEmpty(tmp_path, clock):
    """VC: Mode 03 returns a non-null frame with no codes -> checkedAtTs = its time."""
    orch = _bootedOrch(tmp_path)
    assert _readState(tmp_path, "dtc")["checkedAtTs"] is None  # nothing read this boot
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([])

    orch._dispatchKeyOnDtcs()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["checkedAtTs"] == _T1
    assert dtc["pendingCheckedAtTs"] == _T1
    assert dtc["codes"] == []
    assert orch._dtcCheckedAtTs == _T1


def test_a2_nullFrame_publishesNothing_storedPairByteIdentical(tmp_path, clock, driveSeven):
    """VC/G1: states/dtc holds P0400 + P0443; a null-frame read changes NOTHING."""
    orch = _bootedOrch(tmp_path)
    orch._driveDetector = None  # key-on is gated on no RUNNING drive
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored"), _code("P0443", "stored")])
    orch._dispatchKeyOnDtcs()
    before = _dtcBytes(tmp_path)

    clock["iso"] = _T2
    for dispatch in (
        orch._dispatchKeyOnDtcs,
        orch._dispatchSessionStartDtcs,
        orch._dispatchMilEventDtcs,
        orch._dispatchPeriodicDtcPoll,
    ):
        orch._dtcLogger.next = _read([], frameNull=True)
        dispatch()

    assert _dtcBytes(tmp_path) == before
    assert orch._dtcCheckedAtTs == _T1
    assert orch._dtcPendingCheckedAtTs == _T1


def test_a2_nullFrameAtKeyOn_leavesTheBootStateUnassessed(tmp_path, clock):
    """G1: a null frame at key-on leaves codes null and source.dtc unavailable."""
    orch = _bootedOrch(tmp_path)
    orch._dtcLogger.next = _read([], frameNull=True)

    orch._dispatchKeyOnDtcs()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["codes"] is None
    assert dtc["source"]["dtc"]["available"] is False
    assert dtc["checkedAtTs"] is None


def test_a2_raisingRead_leavesCheckedAtTs(tmp_path, clock, driveSeven):
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([])
    orch._dispatchKeyOnDtcs()
    before = _dtcBytes(tmp_path)

    clock["iso"] = _T2
    orch._dtcLogger.next = RuntimeError("timeout")
    orch._dispatchPeriodicDtcPoll()
    orch._dispatchMilEventDtcs()

    assert _dtcBytes(tmp_path) == before
    assert orch._dtcCheckedAtTs == _T1


def test_a2_periodicMode03Only_advancesChecked_pendingAndItsTimeUnchanged(
    tmp_path, clock, driveSeven,
):
    """VC: periodic Mode 03-only publish after key-on."""
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0171", "pending")])
    orch._dispatchKeyOnDtcs()

    clock["iso"] = _T2
    orch._dtcLogger.next = _read([_code("P0400", "stored")])
    orch._dispatchPeriodicDtcPoll()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["checkedAtTs"] == _T2
    assert dtc["pendingCheckedAtTs"] == _T1
    assert [(c["code"], c["status"]) for c in dtc["codes"]] == [
        ("P0400", "stored"), ("P0171", "pending"),
    ]


def test_a2_mode07Unsupported_leavesPendingCheckedAtTs(tmp_path, clock):
    """A null Mode 07 frame (unsupported) is not a successful pending read."""
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([], mode07=False)

    orch._dispatchKeyOnDtcs()

    dtc = _readState(tmp_path, "dtc")
    assert dtc["checkedAtTs"] == _T1
    assert dtc["pendingCheckedAtTs"] is None


def test_a2_seedFromThePriorBootFile_initialEmitCarriesIt(tmp_path, clock):
    """VC: orchestrator restarts; tmpfs states/dtc has checkedAtTs T -> initial emit carries T."""
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / "dtc").write_text(
        json.dumps({"codes": [], "checkedAtTs": _T1, "pendingCheckedAtTs": _T0}),
        encoding="utf-8",
    )

    orch = _bootedOrch(tmp_path)

    dtc = _readState(tmp_path, "dtc")
    assert dtc["checkedAtTs"] == _T1
    assert dtc["pendingCheckedAtTs"] == _T0
    assert dtc["codes"] is None  # still the honest unavailable boot state
    assert dtc["source"]["dtc"]["available"] is False
    assert (orch._dtcCheckedAtTs, orch._dtcPendingCheckedAtTs) == (_T1, _T0)
    assert orch._dtcCarriedPending == []  # US-897-e: (T1, T0, []) unchanged


def test_a2_badSeed_seedsNull(tmp_path, clock):
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / "dtc").write_text("{truncated", encoding="utf-8")

    orch = _bootedOrch(tmp_path)

    dtc = _readState(tmp_path, "dtc")
    assert dtc["checkedAtTs"] is None
    assert dtc["pendingCheckedAtTs"] is None
    assert orch._dtcCheckedAtTs is None


def test_a2_seededTime_survivesANullFrameRead(tmp_path, clock):
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / "dtc").write_text(json.dumps({"checkedAtTs": _T1}), encoding="utf-8")
    orch = _bootedOrch(tmp_path)
    before = _dtcBytes(tmp_path)

    orch._dtcLogger.next = _read([], frameNull=True)
    orch._dispatchKeyOnDtcs()

    assert _dtcBytes(tmp_path) == before
    assert _readState(tmp_path, "dtc")["checkedAtTs"] == _T1


# ---------------------------------------------------------------------------
# US-897-e -- the pending set is seeded with the time that dates it
# ---------------------------------------------------------------------------


def test_e_restart_seedsTheCarriedSet_theFirstMode03OnlyReadPublishesIt(
    tmp_path, clock, driveSeven,
):
    """VC 3: states/dtc holds pending P0400 -> restart -> a Mode 03-only read.

    _DtcOrch's __init__ sets ``_dtcCarriedPending = []`` BEFORE
    ``_initializeCardStateEmitters`` runs, the order core.py's initialiser and
    lifecycle's init keep, so this proves the seed survives that initialiser.
    """
    first = _bootedOrch(tmp_path)
    first._driveDetector = None  # key-on is gated on no RUNNING drive
    first._dtcLogger.next = _read([_code("P0400", "pending")])  # Mode 07 answered
    first._dispatchKeyOnDtcs()
    assert _readState(tmp_path, "dtc")["pendingCheckedAtTs"] == _T0

    restarted = _bootedOrch(tmp_path)
    assert [(c.code, c.status) for c in restarted._dtcCarriedPending] == [
        ("P0400", "pending"),
    ]
    clock["iso"] = _T1
    restarted._dtcLogger.next = _read([_code("P0443", "stored")])
    restarted._dispatchPeriodicDtcPoll()

    dtc = _readState(tmp_path, "dtc")
    assert [(c["code"], c["status"]) for c in dtc["codes"]] == [
        ("P0443", "stored"), ("P0400", "pending"),
    ]
    assert dtc["checkedAtTs"] == _T1
    assert dtc["pendingCheckedAtTs"] == _T0


def test_e_restart_untabledPendingCode_keepsItsPythonObdText(tmp_path, clock, driveSeven):
    """VC 7: an un-tabled pending code with python-obd text 'X' survives a restart."""
    first = _bootedOrch(tmp_path)
    first._driveDetector = None
    first._dtcLogger.next = _read(
        [SimpleNamespace(code="P0999", status="pending", description="X")]
    )
    first._dispatchKeyOnDtcs()

    restarted = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    restarted._dtcLogger.next = _read([])
    restarted._dispatchPeriodicDtcPoll()

    (code,) = _readState(tmp_path, "dtc")["codes"]
    assert (code["code"], code["status"], code["long"]) == ("P0999", "pending", "X")


def test_e_doubleRestartBeforeAnyRead_seedsNeither(tmp_path, clock):
    """VC 8 (Atlas (B) 2026-10-21): the second restart reads the unavailable boot
    state (codes null) the first one wrote, so it drops to pending_not_read."""
    first = _bootedOrch(tmp_path)
    first._driveDetector = None
    first._dtcLogger.next = _read([_code("P0400", "pending")])
    first._dispatchKeyOnDtcs()

    once = _bootedOrch(tmp_path)
    assert once._dtcPendingCheckedAtTs == _T0
    assert _readState(tmp_path, "dtc")["codes"] is None  # never published (US-752)

    twice = _bootedOrch(tmp_path)

    assert twice._dtcPendingCheckedAtTs is None
    assert twice._dtcCarriedPending == []
    assert twice._dtcCheckedAtTs == _T0


class _Readback:
    def __init__(self, stored, pending, *, frameNull=False, mode07=True):
        self.stored = stored
        self.pending = pending
        self.frameNull = frameNull
        self.mode07Probe = SimpleNamespace(supported=mode07)


def _clearingOrch(tmp_path, readback):
    """The booted orch plus the core clear hook, bound the way core composes it."""
    import types

    from pi.obdii.orchestrator.core import ApplicationOrchestrator

    orch = _bootedOrch(tmp_path)
    orch._connection = SimpleNamespace(isConnected=lambda: True)
    orch._dtcClearClientFactory = lambda: SimpleNamespace(
        clearDtcs=lambda connection: readback
    )
    for name in ("_maybeServiceDtcClearRequest", "_publishDtcClearOutcome"):
        setattr(orch, name, types.MethodType(getattr(ApplicationOrchestrator, name), orch))
    return orch


def test_a2_postClear_nonNullReRead_advancesBothTimes_replacesBothSets(tmp_path, clock):
    """VC: post-clear re-read with a non-null frame."""
    from pi.splash.dtc_clear_channel import writeRequest

    orch = _clearingOrch(tmp_path, _Readback([], []))
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored"), _code("P0171", "pending")])
    orch._dispatchKeyOnDtcs()

    clock["iso"] = _T2
    writeRequest(str(tmp_path / "states"), "req-1", nowFn=lambda: 1.0)
    assert orch._maybeServiceDtcClearRequest() is True

    dtc = _readState(tmp_path, "dtc")
    assert dtc["codes"] == []
    assert dtc["checkedAtTs"] == _T2
    assert dtc["pendingCheckedAtTs"] == _T2


def test_a2_postClear_nullReRead_publishesNothing_andWarns(tmp_path, clock, caplog):
    from pi.splash.dtc_clear_channel import readOutcome, writeRequest

    orch = _clearingOrch(tmp_path, _Readback([], [], frameNull=True))
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored")])
    orch._dispatchKeyOnDtcs()
    before = _dtcBytes(tmp_path)

    clock["iso"] = _T2
    writeRequest(str(tmp_path / "states"), "req-1", nowFn=lambda: 1.0)
    with caplog.at_level("WARNING"):
        orch._maybeServiceDtcClearRequest()

    assert _dtcBytes(tmp_path) == before
    assert any("Mode 03 null frame" in r.getMessage() for r in caplog.records)
    # The clear itself still happened and its outcome is still published.
    assert readOutcome(str(tmp_path / "states"))["ok"] is True


# ---------------------------------------------------------------------------
# US-897-b2 -- the alerts arbiter joins the card tick AFTER obd-live and reads
# the SAME payload that emit just wrote (Atlas Q18), never a file read-back.
# ---------------------------------------------------------------------------

_B2_T0 = datetime(2026, 10, 20, 15, 12, 25, tzinfo=UTC)


def _coolantReading(value, at):
    return SimpleNamespace(parameterName="COOLANT_TEMP", value=value, unit="C", timestamp=at)


def _alertsOrch(tmp_path, *, database=None):
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._database = database
    now = {"t": _B2_T0}
    orch._obdLiveClock = lambda: now["t"]
    orch._initializeCardStateEmitters()
    return orch, now


def _runUpToRed(orch, now):
    """105 C then 112 C two seconds later: red through the REAL band producer
    (a single >= redC sample after a predecessor >= redGuardPrevMinC)."""
    orch.observeObdLiveReading(_coolantReading(105.0, _B2_T0))
    orch.observeObdLiveReading(_coolantReading(112.0, _B2_T0 + timedelta(seconds=2)))
    now["t"] = _B2_T0 + timedelta(seconds=3)
    assert orch._maybeEmitCardStates() is True


def test_b2_initialize_wiresTheArbiterAndItsEmitter(tmp_path):
    orch, _ = _alertsOrch(tmp_path)

    assert orch._alertsArbiter is not None
    assert orch._alertsEmitter is not None


def test_b2_cardsDisabled_noArbiter_noFile(tmp_path):
    orch = _FakeOrch(_config(tmp_path, stateEmitEnabled=False))
    orch._initializeCardStateEmitters()

    assert orch._maybeEmitCardStates() is False
    assert orch._alertsArbiter is None
    assert not (tmp_path / "states" / "alerts").exists()


def test_b2_emitObdLiveState_returnsThePayloadItWrote(tmp_path):
    orch, now = _alertsOrch(tmp_path)
    orch.observeObdLiveReading(_coolantReading(90.0, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)

    returned = orch._emitObdLiveState()

    assert returned == _readState(tmp_path, "obd-live")


def test_b2_coolantRed_tickWritesTheStop_fromWhatObdLivePublished(tmp_path):
    orch, now = _alertsOrch(tmp_path)

    _runUpToRed(orch, now)

    alerts = _readState(tmp_path, "alerts")
    coolant = _readState(tmp_path, "obd-live")["params"]["COOLANT_TEMP"]
    assert coolant["band"]["band"] == "red"
    entry = alerts["entries"][0]
    assert entry["id"] == "engine:COOLANT_TEMP:stop"
    assert entry["value"] == coolant["value"] == 112.0
    assert entry["firstSeenTs"] == coolant["ts"]
    assert alerts["takeover"]["directive"] == "PULL OVER"
    assert alerts["icon"] == {"state": "stop", "count": 1, "pulse": True}
    assert alerts["sources"]["engine"] == {"assessed": True}
    assert alerts["dataSource"] == _readState(tmp_path, "obd-live")["dataSource"]


def test_b2_arbiterIsHandedTheSamePayloadObdLiveWrote(tmp_path):
    orch, now = _alertsOrch(tmp_path)
    seen = []
    observe = orch._alertsArbiter.observe

    def spy(obdLive, **kw):
        seen.append(obdLive)
        observe(obdLive, **kw)

    orch._alertsArbiter.observe = spy

    _runUpToRed(orch, now)

    assert seen == [_readState(tmp_path, "obd-live")]


def test_b2_obdLiveWriteFails_arbiterSeesNothing_engineUnassessed(tmp_path, monkeypatch):
    orch, now = _alertsOrch(tmp_path)
    orch.observeObdLiveReading(_coolantReading(90.0, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)
    emitter = orch._obdLiveEmitter
    orch._obdLiveEmitter = lambda *a, **k: (emitter(*a, **k), None)[1]

    orch._maybeEmitCardStates()

    assert _readState(tmp_path, "alerts")["sources"]["engine"] == {"assessed": False}


def test_b2_alertLogRow_writtenThroughTheRealWiring(tmp_path, driveSeven):
    from pi.obdii.database import ObdDatabase

    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    orch, now = _alertsOrch(tmp_path, database=db)

    _runUpToRed(orch, now)

    with db.connect() as conn:
        rows = [tuple(r) for r in conn.execute(
            "SELECT alert_type, parameter_name, value, threshold, drive_id FROM alert_log"
        )]
    assert rows == [("coolant_stop", "COOLANT_TEMP", 112.0, 110.0, 7)]


def test_b2_replayDataSource_noAlertLogRow(tmp_path):
    from pi.obdii.database import ObdDatabase

    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    orch, now = _alertsOrch(tmp_path, database=db)
    orch._dataLogger = SimpleNamespace(dataLogger=SimpleNamespace(dataSource="replay"))

    _runUpToRed(orch, now)

    assert _readState(tmp_path, "alerts")["entries"][0]["active"] is True
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0] == 0


def test_b2_clearedStop_survivesAnOrchestratorRestart(tmp_path):
    """VC5: listed active:false, then a restart inside the boot (Atlas G3)."""
    orch, now = _alertsOrch(tmp_path)
    _runUpToRed(orch, now)
    # Red clears only at <= redClearBelowC held redClearHoldSec (US-897-b1).
    for i in range(0, 64, 2):
        orch.observeObdLiveReading(
            _coolantReading(95.0, _B2_T0 + timedelta(seconds=4 + i))
        )
    now["t"] = _B2_T0 + timedelta(seconds=68)
    orch._maybeEmitCardStates()
    cleared = _readState(tmp_path, "alerts")["entries"]
    assert [(e["id"], e["active"]) for e in cleared] == [("engine:COOLANT_TEMP:stop", False)]

    restarted, _ = _alertsOrch(tmp_path)
    restarted._maybeEmitCardStates()

    entries = _readState(tmp_path, "alerts")["entries"]
    assert [(e["id"], e["active"]) for e in entries] == [("engine:COOLANT_TEMP:stop", False)]
    assert entries[0]["firstSeenTs"] == cleared[0]["firstSeenTs"]


def test_b2_noBootIdSurface_bootIdUnknown_noErrorLogged(tmp_path, monkeypatch, caplog):
    """Off-Linux (a desk simulator run) readBootId could only say 'unknown' and
    would log an ERROR; the boot_milestone precedent answers it without the call."""
    import pi.diagnostics.boot_reason as boot_reason

    monkeypatch.setattr(boot_reason, "BOOT_ID_PATH", str(tmp_path / "no-boot-id"))
    with caplog.at_level(logging.ERROR):
        orch, now = _alertsOrch(tmp_path)
        orch._maybeEmitCardStates()

    assert _readState(tmp_path, "alerts")["bootId"] == "unknown"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_b2_bootIdSurfacePresent_publishesTheBootId(tmp_path, monkeypatch):
    import pi.diagnostics.boot_progress as boot_progress
    import pi.diagnostics.boot_reason as boot_reason

    surface = tmp_path / "boot_id"
    surface.write_text("b7", encoding="ascii")
    monkeypatch.setattr(boot_reason, "BOOT_ID_PATH", str(surface))
    monkeypatch.setattr(boot_progress, "readBootId", lambda: "b7c0ffee")

    orch, now = _alertsOrch(tmp_path)
    orch._maybeEmitCardStates()

    assert _readState(tmp_path, "alerts")["bootId"] == "b7c0ffee"


# ---------------------------------------------------------------------------
# US-897-b4 -- the over-rev peak is fed at the READING seam (every RPM reading,
# judged by the real band producer), the end at the alerts tick's own
# recording -> idle edge, and the reset at drive start.
# ---------------------------------------------------------------------------


def _rpmReading(value, at):
    return SimpleNamespace(parameterName="RPM", value=value, unit="rpm", timestamp=at)


class _Driving:
    def __init__(self):
        self.driving = False

    def isDriving(self):
        return self.driving


def _overRevEntry(tmp_path):
    alerts = _readState(tmp_path, "alerts")
    return next((e for e in alerts["entries"] if e["id"] == "engine:RPM:watch"), None)


def _overRevOrch(tmp_path):
    orch, now = _alertsOrch(tmp_path)
    orch._driveDetector = _Driving()
    return orch, now


def test_b4_peakTakenFromReadingsBetweenSnapshots_throughTheRealBandProducer(tmp_path):
    """VC1: 6900, 7150.75, 7020 between two ticks; the snapshot only ever holds
    7020, yet the sentence carries the 7150.75 the seam saw (floored)."""
    orch, now = _overRevOrch(tmp_path)
    orch._driveDetector.driving = True
    for second, rpm in ((0, 6900), (1, 7150.75), (2, 7020)):
        orch.observeObdLiveReading(_rpmReading(rpm, _B2_T0 + timedelta(seconds=second)))
    now["t"] = _B2_T0 + timedelta(seconds=3)

    assert orch._maybeEmitCardStates() is True

    assert _readState(tmp_path, "obd-live")["params"]["RPM"]["value"] == 7020
    entry = _overRevEntry(tmp_path)
    assert entry is not None
    assert entry["title"] == "OVER-REV"
    assert entry["sentence"] == "peak 7,150 rpm (sampled)"
    assert entry["value"] is None
    assert entry["unit"] is None
    assert entry["active"] is True
    # 6900 is amber under the default redRpm 7000 -- the producer's call, not ours.
    assert entry["firstSeenTs"] == "2026-10-20T15:12:26Z"
    assert _readState(tmp_path, "alerts")["icon"]["state"] == "watch"


def test_b4_driveEnd_recordingToIdleEdge_endsTheOverRev(tmp_path):
    """VC2: drive ends -> active false, still listed."""
    orch, now = _overRevOrch(tmp_path)
    orch._driveDetector.driving = True
    orch.observeObdLiveReading(_rpmReading(7200, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)
    orch._maybeEmitCardStates()
    assert _overRevEntry(tmp_path)["active"] is True

    orch._driveDetector.driving = False
    now["t"] = _B2_T0 + timedelta(seconds=3)
    orch._maybeEmitCardStates()

    entry = _overRevEntry(tmp_path)
    assert entry is not None
    assert entry["active"] is False
    assert entry["sentence"] == "peak 7,200 rpm (sampled)"


def test_b4_driveEndEdge_isItsOwnFlag_notTheFuelPersists(tmp_path):
    orch, now = _overRevOrch(tmp_path)
    orch._driveDetector.driving = True
    orch.observeObdLiveReading(_rpmReading(7200, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)
    orch._maybeEmitCardStates()

    assert orch._alertsWasRecording is True
    # Even with the fuel edge already consumed, the alerts edge still fires.
    orch._fuelWasRecording = False
    orch._driveDetector.driving = False
    now["t"] = _B2_T0 + timedelta(seconds=3)
    orch._maybeEmitCardStates()

    assert _overRevEntry(tmp_path)["active"] is False
    assert orch._alertsWasRecording is False


def test_b4_nonRpmReadings_neverReachTheArbiter(tmp_path):
    orch, _ = _overRevOrch(tmp_path)
    seen = []
    orch._alertsArbiter.observeRpmReading = lambda *a: seen.append(a)

    orch.observeObdLiveReading(_coolantReading(90.0, _B2_T0))
    orch.observeObdLiveReading(_rpmReading(800, _B2_T0))

    assert len(seen) == 1
    value, eventUtc, band = seen[0]
    assert value == 800
    assert eventUtc == _B2_T0
    assert band["band"] == "green"


class _DriveStartOrch(_FakeOrch, EventRouterMixin):
    def __init__(self, config):
        from pi.obdii.orchestrator.types import HealthCheckStats

        super().__init__(config)
        self._healthCheckStats = HealthCheckStats()
        self._displayManager = None
        self._milEdgeDetector = None
        self._dtcLogger = None
        self._onDriveStart = None


def test_b4_driveStart_resetsThePeak_throughHandleDriveStart(tmp_path):
    """A pre-drive over-rev still active at the drive start (no recording, no
    green hold yet): the drive start resets its peak, so the drive's own red
    reading is the peak -- a lower one than before."""
    orch = _DriveStartOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._driveDetector = _Driving()
    now = {"t": _B2_T0}
    orch._obdLiveClock = lambda: now["t"]
    orch._initializeCardStateEmitters()
    orch.observeObdLiveReading(_rpmReading(7400, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)
    orch._maybeEmitCardStates()
    assert _overRevEntry(tmp_path)["sentence"] == "peak 7,400 rpm (sampled)"

    orch._handleDriveStart(SimpleNamespace(id=2, startTime=None))
    orch._driveDetector.driving = True
    orch.observeObdLiveReading(_rpmReading(7050, _B2_T0 + timedelta(seconds=3)))
    now["t"] = _B2_T0 + timedelta(seconds=4)
    orch._maybeEmitCardStates()

    entry = _overRevEntry(tmp_path)
    assert entry["active"] is True
    assert entry["sentence"] == "peak 7,050 rpm (sampled)"


def test_b4_newDriveAfterADriveEnd_opensANewEpisode(tmp_path):
    orch, now = _overRevOrch(tmp_path)
    orch._driveDetector.driving = True
    orch.observeObdLiveReading(_rpmReading(7400, _B2_T0))
    now["t"] = _B2_T0 + timedelta(seconds=1)
    orch._maybeEmitCardStates()
    orch._driveDetector.driving = False
    now["t"] = _B2_T0 + timedelta(seconds=2)
    orch._maybeEmitCardStates()

    orch._resetAlertsRpmPeak()
    orch._driveDetector.driving = True
    orch.observeObdLiveReading(_rpmReading(7050, _B2_T0 + timedelta(seconds=30)))
    now["t"] = _B2_T0 + timedelta(seconds=31)
    orch._maybeEmitCardStates()

    entry = _overRevEntry(tmp_path)
    assert entry["active"] is True
    assert entry["sentence"] == "peak 7,050 rpm (sampled)"
    assert entry["firstSeenTs"] == "2026-10-20T15:12:55Z"


def test_b4_aFailingPeakReset_doesNotBlockTheDriveStart(tmp_path):
    orch = _DriveStartOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))

    def _boom():
        raise RuntimeError("boom")

    orch._resetAlertsRpmPeak = _boom
    orch._handleDriveStart(SimpleNamespace(id=2, startTime=None))

    assert orch._healthCheckStats.drivesDetected == 1


# ---------------------------------------------------------------------------
# US-897-b5 -- the dtc payload reaches the alerts arbiter IN-PROCESS (Atlas
# Q6): the router hands it what the dtc emitter returned, the alerts step of
# the card tick publishes it.
# ---------------------------------------------------------------------------


def _alertsAfterTick(orch, tmp_path):
    orch._emitAlertsState(None)
    return _readState(tmp_path, "alerts")


def test_b5_bootState_codesNull_noCodeEntries_codeUnassessed(tmp_path, clock):
    orch = _bootedOrch(tmp_path)

    alerts = _alertsAfterTick(orch, tmp_path)

    assert alerts["entries"] == []
    assert alerts["sources"]["code"] == {"assessed": False, "checkedAtTs": None}
    assert alerts["icon"]["state"] == "not_checked"
    assert alerts["codeAlert"] is None


def test_b5_keyOnRead_theCarsTwoCodes_becomeEntries_andTheCodeAlert(tmp_path, clock):
    """VC1 end to end: through the REAL dtc emitter and the shipped table."""
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored"), _code("P0443", "stored")])

    orch._dispatchKeyOnDtcs()
    alerts = _alertsAfterTick(orch, tmp_path)

    assert [e["id"] for e in alerts["entries"]] == ["code:P0400:watch", "code:P0443:minor"]
    assert alerts["entries"][0]["title"] == "EGR FLOW (P0400)"
    assert alerts["codeAlert"] == {
        "ids": ["code:P0400:watch", "code:P0443:minor"], "tier": "watch", "dismissable": True,
    }
    assert alerts["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}
    assert alerts["icon"] == {"state": "watch", "count": 2, "pulse": False}


def test_b5_arbiterIsHandedTheSamePayloadTheDtcEmitterWrote(tmp_path, clock):
    orch = _bootedOrch(tmp_path)
    seen = []
    observe = orch._alertsArbiter.observeDtc
    orch._alertsArbiter.observeDtc = lambda payload: (seen.append(payload), observe(payload))
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored")])

    orch._dispatchKeyOnDtcs()

    assert seen == [_readState(tmp_path, "dtc")]


def test_b5_nullFrameReadAfterTheTwoCodes_entriesAndCodeAlertUnchanged(tmp_path, clock):
    """VC5: a null-frame read publishes nothing, so the arbiter sees nothing."""
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored"), _code("P0443", "stored")])
    orch._dispatchKeyOnDtcs()
    before = _alertsAfterTick(orch, tmp_path)
    clock["iso"] = _T2
    orch._dtcLogger.next = _read([], frameNull=True)

    orch._dispatchKeyOnDtcs()
    after = _alertsAfterTick(orch, tmp_path)

    assert after["entries"] == before["entries"]
    assert after["codeAlert"] == before["codeAlert"]
    assert after["sources"]["code"] == {"assessed": True, "checkedAtTs": _T1}


def test_b5_newerReadWithoutACode_removesItsEntry(tmp_path, clock):
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored"), _code("P0443", "stored")])
    orch._dispatchKeyOnDtcs()
    clock["iso"] = _T2
    orch._dtcLogger.next = _read([_code("P0400", "stored")])

    orch._dispatchKeyOnDtcs()
    alerts = _alertsAfterTick(orch, tmp_path)

    assert [e["id"] for e in alerts["entries"]] == ["code:P0400:watch"]


def test_b5_carriedPending_isNeverRemovedByAMode03OnlyRead(tmp_path, clock):
    """G1: the Mode 03-only payload carries the last Mode 07 pending set."""
    orch = _bootedOrch(tmp_path)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "pending")])
    orch._dispatchKeyOnDtcs()
    clock["iso"] = _T2

    orch._emitDtcState(_read([]), includesPending=False)
    alerts = _alertsAfterTick(orch, tmp_path)

    (entry,) = alerts["entries"]
    assert entry["id"] == "code:P0400:watch"
    assert entry["codeStatus"] == "pending"
    assert entry["title"] == "EGR FLOW (P0400) \u00b7 pending"
    assert alerts["sources"]["code"]["checkedAtTs"] == _T2


def test_b5_dtcWriteFails_arbiterSeesNothing(tmp_path, clock, monkeypatch):
    import pi.splash.dtc_emitter as mod

    orch = _bootedOrch(tmp_path)

    def _boom(*_a, **_k):
        raise OSError("tmpfs full")

    monkeypatch.setattr(mod, "writeStateAtomic", _boom)
    clock["iso"] = _T1
    orch._dtcLogger.next = _read([_code("P0400", "stored")])

    orch._dispatchKeyOnDtcs()

    assert orch._alertsArbiter.codeSource() == {"assessed": False, "checkedAtTs": None}
    assert [e for e in orch._alertsArbiter.episodes() if e.source == "code"] == []


# ---------------------------------------------------------------------------
# US-876-c -- system-status `link`: the ECU layer live from reachability.
# ---------------------------------------------------------------------------

_LINK_NULL = {"state": None, "ts": None, "lastOkTs": None}


def _isoOf(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _LinkClocks:
    """One monotonic + one wall clock shared by the connection and the provider."""

    def __init__(self):
        self.mono = 5000.0
        self.wall = datetime(2026, 10, 22, 15, 0, 0, tzinfo=UTC)

    def advance(self, seconds):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


class _EcuResponse:
    def __init__(self, null):
        self._null = null
        self.value = None if null else 800

    def is_null(self):
        return self._null


class _LinkObd:
    """A python-obd double: linked, answering whatever `next` says."""

    def __init__(self):
        self.next = _EcuResponse(null=False)

    def is_connected(self):
        return True

    def query(self, command, force=False):
        return self.next

    def close(self):
        pass


class _AliveThread:
    """A retry thread that is alive (the US-301 heartbeat between ticks)."""

    name = "obd-reconnect-heartbeat"

    def is_alive(self):
        return True


def _linkOrch(tmp_path, clocks, *, heartbeat=True):
    from pi.obdii.obd_connection import ObdConnection

    conn = ObdConnection(
        {"pi": {"bluetooth": {"macAddress": "00:11:22:33:44:55"}}},
        monotonicFn=lambda: clocks.mono,
        wallClockFn=lambda: clocks.wall,
    )
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn)
    orch._linkClock = lambda: clocks.mono
    orch._linkWallClock = lambda: clocks.wall
    # US-876-e: this MAC would start the BT sampler once a test gives the host
    # a _shutdownEvent; the double keeps it from ever spawning bluetoothctl.
    orch._btConnectedRunner = _noBluetoothctl
    if heartbeat:
        orch._reconnectHeartbeatThread = _AliveThread()
    orch._initializeCardStateEmitters()
    return orch, conn


def _noBluetoothctl(cmd, **kwargs):
    raise FileNotFoundError(cmd[0])


def _emitLink(orch, tmp_path):
    orch._emitSystemStatusState()
    return _readState(tmp_path, "system-status")["link"]


def _ecuRead(conn, obd, null):
    obd.next = _EcuResponse(null=null)
    conn.query("RPM")


def test_link_ecu_neverUp_up_drop_up_readsConnectingUpRetryingUp(tmp_path):
    """Atlas VC: the reconnect after a drop reads RETRYING, not connecting --
    the drop's generation bump resets reachability to NOT_YET_ATTEMPTED, which
    is why the up-this-session flag lives on the orchestrator side (c-1, c-2)."""
    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    seen = []

    seen.append(_emitLink(orch, tmp_path)["ecu"]["state"])
    conn.obd = obd
    clocks.advance(5)
    _ecuRead(conn, obd, null=False)
    seen.append(_emitLink(orch, tmp_path)["ecu"]["state"])
    clocks.advance(5)
    conn.disconnect()
    seen.append(_emitLink(orch, tmp_path)["ecu"]["state"])
    clocks.advance(5)
    conn.obd = obd  # the reconnect
    seen.append(_emitLink(orch, tmp_path)["ecu"]["state"])
    _ecuRead(conn, obd, null=False)
    seen.append(_emitLink(orch, tmp_path)["ecu"]["state"])

    assert seen == ["connecting", "up", "retrying", "retrying", "up"]


def test_link_ecu_answeredThenDidNotAnswer_upThenRetrying_eachDatedItsTransition(tmp_path):
    """VC 1: ANSWERED then DID_NOT_ANSWER -> up then retrying; ts = each
    transition's UTC time (the answer; the decay instant), never the tick."""
    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd
    window = conn.reachabilityFreshnessSeconds

    clocks.advance(3)
    answeredAt = clocks.wall
    _ecuRead(conn, obd, null=False)
    clocks.advance(2)
    up = _emitLink(orch, tmp_path)["ecu"]
    clocks.advance(window + 120)
    retrying = _emitLink(orch, tmp_path)["ecu"]

    assert up == {"state": "up", "ts": _isoOf(answeredAt), "lastOkTs": _isoOf(answeredAt)}
    assert retrying == {
        "state": "retrying",
        "ts": _isoOf(answeredAt + timedelta(seconds=window)),
        "lastOkTs": _isoOf(answeredAt),
    }


def test_link_obdSourceUnavailable_neverConnected_linkStillPublished(tmp_path):
    """VC 2: source.obd.available false (never connected) -> link present; ecu
    connecting (dated the attempt's start); bt/adapter not read."""
    clocks = _LinkClocks()
    builtAt = clocks.wall
    orch, _conn = _linkOrch(tmp_path, clocks)
    clocks.advance(30)

    orch._emitSystemStatusState()
    ss = _readState(tmp_path, "system-status")

    assert ss["source"]["obd"]["available"] is False
    assert ss["obdLink"] == {"state": None, "retries": 0}
    assert ss["link"] == {
        "bt": _LINK_NULL,
        "adapter": _LINK_NULL,
        "ecu": {"state": "connecting", "ts": _isoOf(builtAt), "lastOkTs": None},
    }


def test_link_couldNotDetermine_beforeAnUpIsNull_afterAnUpIsRetrying(tmp_path):
    """COULD_NOT_DETERMINE (a read that raised) before any up -> null; after
    an up (and a reconnect, so the old answer no longer counts) -> retrying."""
    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd

    def _raise(command, force=False):
        raise RuntimeError("serial read exploded")

    obd.query = _raise
    with pytest.raises(RuntimeError):
        conn.query("RPM")
    before = _emitLink(orch, tmp_path)["ecu"]

    obd.query = lambda command, force=False: _EcuResponse(null=False)
    conn.query("RPM")
    _emitLink(orch, tmp_path)
    clocks.advance(2)
    droppedAt = clocks.wall
    conn.disconnect()
    _emitLink(orch, tmp_path)
    conn.obd = obd
    obd.query = _raise
    clocks.advance(3)
    with pytest.raises(RuntimeError):
        conn.query("RPM")
    after = _emitLink(orch, tmp_path)["ecu"]

    assert before == _LINK_NULL
    # Still retrying -- the unread read is not a new transition, so the state
    # stays dated by the drop that began it.
    assert after == {
        "state": "retrying", "ts": _isoOf(droppedAt), "lastOkTs": after["lastOkTs"],
    }
    assert after["lastOkTs"] is not None


def test_link_statusWithoutReachability_ecuNotRead(tmp_path):
    """C5: a status object with no `reachability` (the card-test fakes) reads
    ecu null -- the provider never invents a layer it cannot see."""
    conn = SimpleNamespace(
        getStatus=lambda: _connectionStatus(connected=True, totalConnections=1)
    )
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn)
    orch._initializeCardStateEmitters()

    assert _emitLink(orch, tmp_path) == {
        "bt": _LINK_NULL, "adapter": _LINK_NULL, "ecu": _LINK_NULL,
    }


def test_link_noConnection_isNull(tmp_path):
    """conn None before any up -> null (all three keys)."""
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0))
    orch._initializeCardStateEmitters()

    assert _emitLink(orch, tmp_path)["ecu"] == _LINK_NULL


def test_link_getStatusRaisingAfterAnUp_isRetrying_notNull(tmp_path):
    """getStatus() raising after an up -> retrying (the layer WAS there; an
    unreadable instant is not evidence it is gone), lastOkTs kept."""
    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd
    answeredAt = clocks.wall
    _ecuRead(conn, obd, null=False)
    _emitLink(orch, tmp_path)

    def _boom():
        raise RuntimeError("status unreadable")

    conn.getStatus = _boom
    clocks.advance(4)
    ecu = _emitLink(orch, tmp_path)["ecu"]

    assert ecu["state"] == "retrying"
    assert ecu["lastOkTs"] == _isoOf(answeredAt)


def test_link_cancelThenALiveHeartbeat_isNotDown(tmp_path):
    """C2: a cancel (cancelPendingConnects) is NOT a down fact -- with the
    heartbeat alive the layer keeps retrying however long it lasts."""
    from pi.obdii.reconnect_loop import HEARTBEAT_TICK_INTERVAL_SEC

    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd
    _ecuRead(conn, obd, null=False)
    _emitLink(orch, tmp_path)
    conn.disconnect()
    conn.cancelPendingConnects()

    states = []
    for _tick in range(4):
        clocks.advance(HEARTBEAT_TICK_INTERVAL_SEC)
        states.append(_emitLink(orch, tmp_path)["ecu"]["state"])

    assert states == ["retrying"] * 4


def test_link_noRetryAuthority_downOnlyAfterOneHeartbeatTick_datedWhenItWent(tmp_path):
    """C2 hold: with no retry thread, no connect in flight and no held link,
    the layer is NOT down at once (the gap before a heartbeat spawns must not
    flash down); after one heartbeat tick without authority it is down, dated
    when the authority was first seen gone. Authority back -> retrying."""
    from pi.obdii.reconnect_loop import HEARTBEAT_TICK_INTERVAL_SEC

    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks, heartbeat=False)
    obd = _LinkObd()
    conn.obd = obd
    _ecuRead(conn, obd, null=False)
    _emitLink(orch, tmp_path)  # up: the held link is itself the authority
    conn.disconnect()

    clocks.advance(2)
    goneAt = clocks.wall
    gap = _emitLink(orch, tmp_path)["ecu"]
    clocks.advance(HEARTBEAT_TICK_INTERVAL_SEC - 1)
    stillGap = _emitLink(orch, tmp_path)["ecu"]
    clocks.advance(1)
    down = _emitLink(orch, tmp_path)["ecu"]
    orch._reconnectHeartbeatThread = _AliveThread()
    clocks.advance(2)
    back = _emitLink(orch, tmp_path)["ecu"]

    assert gap["state"] == "retrying"
    assert stillGap["state"] == "retrying"
    assert down["state"] == "down"
    assert down["ts"] == _isoOf(goneAt)
    assert back["state"] == "retrying"


def test_link_shutdownEventSet_isDownAtOnce(tmp_path):
    """C2: _shutdownEvent set is down by itself -- no hold, even with a live
    heartbeat (it is exiting)."""
    import threading

    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    orch._shutdownEvent = threading.Event()
    _emitLink(orch, tmp_path)

    orch._shutdownEvent.set()
    clocks.advance(1)

    assert _emitLink(orch, tmp_path)["ecu"]["state"] == "down"


def test_link_heldLinkWithASilentEcu_isRetrying_notDown(tmp_path):
    """The known edge (G1): after a drive, key-off silences the ECU while the
    link stays held -- no retry thread runs, the data path re-reads it -- so
    the layer reads retrying until shutdown, never down."""
    from pi.obdii.reconnect_loop import HEARTBEAT_TICK_INTERVAL_SEC

    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks, heartbeat=False)
    obd = _LinkObd()
    conn.obd = obd
    _ecuRead(conn, obd, null=False)
    _emitLink(orch, tmp_path)

    clocks.advance(conn.reachabilityFreshnessSeconds + 1)
    _ecuRead(conn, obd, null=True)
    clocks.advance(HEARTBEAT_TICK_INTERVAL_SEC * 3)

    assert _emitLink(orch, tmp_path)["ecu"]["state"] == "retrying"


def test_link_obdLinkUnchanged_retriesKeepTheirShippedMeaning(tmp_path):
    """C1: obdLink {state, retries} ships unchanged -- link retrying is not
    reflected in obdLink.retries."""
    clocks = _LinkClocks()
    orch, conn = _linkOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd
    conn._status.totalConnections = 1
    _ecuRead(conn, obd, null=False)
    _emitLink(orch, tmp_path)
    conn.disconnect()

    orch._emitSystemStatusState()
    ss = _readState(tmp_path, "system-status")

    assert ss["link"]["ecu"]["state"] == "retrying"
    assert ss["obdLink"] == {"state": "down", "retries": 0}


# ---------------------------------------------------------------------------
# US-876-d -- link.adapter: did the ELM answer (Atlas L4, D2, D5, G1).
# ---------------------------------------------------------------------------


class _AdapterAttempt:
    """One connect attempt's python-obd object: ELM status + whether linked."""

    def __init__(self, status, connected=False):
        self._status = status
        self._connected = connected
        self.next = _EcuResponse(null=False)

    def status(self):
        return self._status

    def is_connected(self):
        return self._connected

    def query(self, command, force=False):
        return self.next

    def close(self):
        pass


def _adapterOrch(tmp_path, clocks, *, heartbeat=True):
    """A provider over a REAL ObdConnection whose attempts a test scripts."""
    from pi.obdii.obd_connection import ObdConnection

    conn = ObdConnection(
        {"pi": {"bluetooth": {"macAddress": "/dev/rfcomm0", "retryDelays": []}}},
        obdFactory=lambda port, timeout: conn.nextAttempt(),
        monotonicFn=lambda: clocks.mono,
        wallClockFn=lambda: clocks.wall,
    )
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn)
    orch._linkClock = lambda: clocks.mono
    orch._linkWallClock = lambda: clocks.wall
    if heartbeat:
        orch._reconnectHeartbeatThread = _AliveThread()
    orch._initializeCardStateEmitters()
    return orch, conn


def _attempt(conn, result):
    """One heartbeat-style attempt; ``result`` is the factory's object or raise."""

    def _next():
        if isinstance(result, BaseException):
            raise result
        return result

    conn.nextAttempt = _next
    return conn.connectOnce()


def test_link_adapter_elmAnswersEcuSilent_adapterUp_ecuConnecting(tmp_path):
    """VC 1 (ARCH-061, key off at home): the ELM answers ATZ, the ECU is
    silent -> link.adapter up dated the attempt, link.ecu connecting."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)

    clocks.advance(3)
    attemptAt = clocks.wall
    assert _attempt(conn, _AdapterAttempt("ELM Connected")) is False
    clocks.advance(2)
    link = _emitLink(orch, tmp_path)

    assert link["adapter"] == {
        "state": "up", "ts": _isoOf(attemptAt), "lastOkTs": _isoOf(attemptAt),
    }
    assert link["ecu"]["state"] == "connecting"
    assert link["bt"] == _LINK_NULL


def test_link_adapter_noObservationFor641s_isNull(tmp_path):
    """VC 2 (D5): no adapter observation for 641 s -> link.adapter all null --
    even after an up while the ECU was up (stale evidence is no evidence)."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)
    car = _AdapterAttempt("Car Connected", connected=True)
    _attempt(conn, car)
    conn.query("RPM")
    assert _emitLink(orch, tmp_path)["adapter"]["state"] == "up"

    clocks.advance(640)
    atBound = _emitLink(orch, tmp_path)["adapter"]["state"]
    clocks.advance(1)
    stale = _emitLink(orch, tmp_path)["adapter"]

    assert atBound == "up"
    assert stale == _LINK_NULL


def test_link_adapter_portOpenFails_beforeAnyUp_isConnecting_neverDown(tmp_path):
    """A failed attempt is connecting before any up (d-1) -- never down."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)

    states = []
    for _ in range(3):
        clocks.advance(320)
        _attempt(conn, OSError("could not open port"))
        states.append(_emitLink(orch, tmp_path)["adapter"]["state"])

    assert states == ["connecting"] * 3


def test_link_adapter_failedAttemptAfterAnUpWithTheEcu_isRetrying(tmp_path):
    """After an up while link.ecu was up, a failed attempt reads retrying,
    dated the failed attempt, with the last up kept."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)
    car = _AdapterAttempt("Car Connected", connected=True)
    _attempt(conn, car)
    okAt = clocks.wall
    conn.query("RPM")
    up = _emitLink(orch, tmp_path)

    conn.disconnect()
    clocks.advance(10)
    failedAt = clocks.wall
    _attempt(conn, OSError("could not open port"))
    adapter = _emitLink(orch, tmp_path)["adapter"]

    assert up["ecu"]["state"] == "up" and up["adapter"]["state"] == "up"
    assert adapter == {
        "state": "retrying", "ts": _isoOf(failedAt), "lastOkTs": _isoOf(okAt),
    }


def test_link_adapter_upOnlyWhileTheEcuWasSilent_thenAFailure_isConnecting(tmp_path):
    """G1: an adapter up does not count as 'up this session' until link.ecu
    is up beside it -- so a failure after a key-off answer reads connecting."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)
    _attempt(conn, _AdapterAttempt("ELM Connected"))
    assert _emitLink(orch, tmp_path)["adapter"]["state"] == "up"

    clocks.advance(320)
    _attempt(conn, _AdapterAttempt("Not Connected"))

    assert _emitLink(orch, tmp_path)["adapter"]["state"] == "connecting"


def test_link_adapter_downOnlyByTheSharedC2Rule(tmp_path):
    """D2: with no retry authority past the one-tick hold the adapter is down
    -- the same verdict as the ECU's, on the same tick."""
    from pi.obdii.reconnect_loop import HEARTBEAT_TICK_INTERVAL_SEC

    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks, heartbeat=False)
    _attempt(conn, OSError("could not open port"))
    first = _emitLink(orch, tmp_path)
    clocks.advance(HEARTBEAT_TICK_INTERVAL_SEC)
    later = _emitLink(orch, tmp_path)

    assert first["adapter"]["state"] == "connecting"
    assert later["adapter"]["state"] == "down"
    assert later["ecu"]["state"] == "down"


def test_link_adapter_simulateStatus_hasNoAdapterFields_isNull(tmp_path):
    """D6: a status with no adapter observation (SimulatedObdConnection's,
    the stub composers') reads adapter null; the ECU is unaffected."""
    from pi.obdii.obd_connection import ConnectionStatus, Reachability

    status = ConnectionStatus(connected=True, reachability=Reachability.ANSWERED)
    conn = SimpleNamespace(getStatus=lambda: status)
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn)
    orch._initializeCardStateEmitters()

    link = _emitLink(orch, tmp_path)

    assert link["adapter"] == _LINK_NULL
    assert link["ecu"]["state"] == "up"


def test_link_adapter_getStatusRaisingAfterAnUp_isRetrying(tmp_path):
    """An unreadable status is the ECU's unread rule: after an up (with the
    ECU) the adapter reads retrying, not null."""
    clocks = _LinkClocks()
    orch, conn = _adapterOrch(tmp_path, clocks)
    _attempt(conn, _AdapterAttempt("Car Connected", connected=True))
    conn.query("RPM")
    _emitLink(orch, tmp_path)

    def _boom():
        raise RuntimeError("status unreadable")

    conn.getStatus = _boom
    clocks.advance(2)

    assert _emitLink(orch, tmp_path)["adapter"]["state"] == "retrying"


# ---------------------------------------------------------------------------
# US-876-e -- link.bt: bluetoothctl 'Connected:', sampled off the tick.
# ---------------------------------------------------------------------------

_BT_MAC = "00:04:3E:85:0D:FB"
_BT_INFO_CONNECTED = f"Device {_BT_MAC} (public)\n\tPaired: yes\n\tConnected: yes\n"


class _FakeBtSampler:
    """Stands in for the sampler thread: the provider only ever calls latest()."""

    def __init__(self):
        self.sample = None

    def latest(self):
        return self.sample


def _btSample(clocks, reading):
    from pi.obdii.bluetooth_helper import BtConnectedSample

    return BtConnectedSample(reading=reading, ts=_isoOf(clocks.wall), monoS=clocks.mono)


def _btOrch(tmp_path, clocks, *, heartbeat=True):
    """A provider over a real ObdConnection with a scripted BT sampler."""
    orch, conn = _linkOrch(tmp_path, clocks, heartbeat=heartbeat)
    sampler = _FakeBtSampler()
    orch._btSampler = sampler
    return orch, conn, sampler


def test_link_bt_connectedYes_isUp_datedTheSample(tmp_path):
    """VC 1: bluetoothctl info shows 'Connected: yes' -> link.bt up, ts and
    lastOkTs the sample's time (never the tick)."""
    from pi.obdii.bluetooth_helper import BT_CONNECTED

    clocks = _LinkClocks()
    orch, _conn, sampler = _btOrch(tmp_path, clocks)
    sampledAt = clocks.wall
    sampler.sample = _btSample(clocks, BT_CONNECTED)
    clocks.advance(2)

    assert _emitLink(orch, tmp_path)["bt"] == {
        "state": "up", "ts": _isoOf(sampledAt), "lastOkTs": _isoOf(sampledAt),
    }


def test_link_bt_timeout_isNull_neverDown_evenAfterAnUp(tmp_path):
    """VC 2: bluetoothctl timed out (2 s) -> link.bt {null, null} -- never
    down, and not retrying either, even after an up with the ECU."""
    from pi.obdii.bluetooth_helper import BT_CONNECTED

    clocks = _LinkClocks()
    orch, conn, sampler = _btOrch(tmp_path, clocks)
    obd = _LinkObd()
    conn.obd = obd
    _ecuRead(conn, obd, null=False)
    sampler.sample = _btSample(clocks, BT_CONNECTED)
    assert _emitLink(orch, tmp_path)["bt"]["state"] == "up"

    clocks.advance(5)
    sampler.sample = _btSample(clocks, None)

    assert _emitLink(orch, tmp_path)["bt"] == _LINK_NULL


@pytest.mark.parametrize("label", ["not-available", "paired-no"])
def test_link_bt_absentDevice_isDown_datedTheSample(tmp_path, label):
    """'Device <MAC> not available' / 'Paired: no' (both parse to absent) ->
    down, with a retry thread alive: bluez says there is nothing to reconnect."""
    from pi.obdii.bluetooth_helper import BT_ABSENT

    clocks = _LinkClocks()
    orch, _conn, sampler = _btOrch(tmp_path, clocks, heartbeat=True)
    sampledAt = clocks.wall
    sampler.sample = _btSample(clocks, BT_ABSENT)
    clocks.advance(2)

    assert _emitLink(orch, tmp_path)["bt"] == {
        "state": "down", "ts": _isoOf(sampledAt), "lastOkTs": None,
    }


def test_link_bt_connectedNo_beforeTheEcuAnswers_isConnecting_afterIsRetrying(tmp_path):
    """G1 (the Atlas key-off example): 'Connected: no' reads connecting until
    BT has been up WHILE the ECU was up; after that it reads retrying."""
    from pi.obdii.bluetooth_helper import BT_CONNECTED, BT_NOT_CONNECTED

    clocks = _LinkClocks()
    orch, conn, sampler = _btOrch(tmp_path, clocks)
    states = []

    sampler.sample = _btSample(clocks, BT_NOT_CONNECTED)
    states.append(_emitLink(orch, tmp_path)["bt"]["state"])
    clocks.advance(5)
    sampler.sample = _btSample(clocks, BT_CONNECTED)  # up, ECU still silent
    states.append(_emitLink(orch, tmp_path)["bt"]["state"])
    clocks.advance(5)
    sampler.sample = _btSample(clocks, BT_NOT_CONNECTED)
    states.append(_emitLink(orch, tmp_path)["bt"]["state"])

    obd = _LinkObd()
    conn.obd = obd
    clocks.advance(5)
    _ecuRead(conn, obd, null=False)
    sampler.sample = _btSample(clocks, BT_CONNECTED)  # up with the ECU
    states.append(_emitLink(orch, tmp_path)["bt"]["state"])
    clocks.advance(5)
    droppedAt = clocks.wall
    sampler.sample = _btSample(clocks, BT_NOT_CONNECTED)
    retrying = _emitLink(orch, tmp_path)["bt"]

    assert states == ["connecting", "up", "connecting", "up"]
    assert retrying["state"] == "retrying"
    assert retrying["ts"] == _isoOf(droppedAt)


def test_link_bt_connectedNo_withNoRetryAuthority_isDownByTheSharedC2Rule(tmp_path):
    """'Connected: no' is down only by the shared C2 verdict (after the hold)."""
    from pi.obdii.bluetooth_helper import BT_NOT_CONNECTED
    from pi.obdii.reconnect_loop import HEARTBEAT_TICK_INTERVAL_SEC

    clocks = _LinkClocks()
    orch, _conn, sampler = _btOrch(tmp_path, clocks, heartbeat=False)
    sampler.sample = _btSample(clocks, BT_NOT_CONNECTED)
    first = _emitLink(orch, tmp_path)
    clocks.advance(HEARTBEAT_TICK_INTERVAL_SEC)
    sampler.sample = _btSample(clocks, BT_NOT_CONNECTED)
    later = _emitLink(orch, tmp_path)

    assert first["bt"]["state"] == "connecting"
    assert later["bt"]["state"] == "down"
    assert later["ecu"]["state"] == "down"


def test_link_bt_sampleOlderThan15s_isNull(tmp_path):
    """E2: a sample older than 3 x the 5 s cadence -> all null (the sampler is
    dead or wedged); at exactly 15 s it still stands."""
    from pi.obdii.bluetooth_helper import BT_CONNECTED, BT_CONNECTED_STALE_AFTER_S

    clocks = _LinkClocks()
    orch, _conn, sampler = _btOrch(tmp_path, clocks)
    sampler.sample = _btSample(clocks, BT_CONNECTED)

    clocks.advance(BT_CONNECTED_STALE_AFTER_S)
    atBound = _emitLink(orch, tmp_path)["bt"]["state"]
    clocks.advance(1)
    stale = _emitLink(orch, tmp_path)["bt"]

    assert BT_CONNECTED_STALE_AFTER_S == 15
    assert atBound == "up"
    assert stale == _LINK_NULL


def test_link_bt_noSampleYet_isNull(tmp_path):
    """Before the sampler's first sample lands the layer is not read."""
    clocks = _LinkClocks()
    orch, _conn, _sampler = _btOrch(tmp_path, clocks)

    assert _emitLink(orch, tmp_path)["bt"] == _LINK_NULL


class _BtRunner:
    """A bluetoothctl double for the real sampler thread."""

    def __init__(self, stdout):
        import threading

        self.stdout = stdout
        self.calls = []
        self.threads = []
        self.called = threading.Event()

    def __call__(self, cmd, **kwargs):
        import subprocess
        import threading

        self.calls.append(list(cmd))
        self.threads.append(threading.current_thread())
        self.called.set()
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


def _stopSampler(orch):
    orch._shutdownEvent.set()
    sampler = getattr(orch, "_btSampler", None)
    if sampler is not None:
        sampler.thread.join(timeout=5.0)
        assert not sampler.thread.is_alive()


def test_link_bt_realSampler_samplesOffTheTickThread_andStopsOnShutdown(tmp_path):
    """The provider starts ONE daemon sampler for the connection's MAC; every
    bluetoothctl call runs on it (never the tick thread); a tick only reads
    its latest sample; _shutdownEvent stops it (E5)."""
    import threading
    import time

    from pi.obdii.bluetooth_helper import BT_CONNECTED_SAMPLE_INTERVAL_S

    conn = SimpleNamespace(macAddress=_BT_MAC, getStatus=lambda: None)
    orch = _FakeOrch(_config(tmp_path, stateEmitIntervalSeconds=0.0), connection=conn)
    orch._shutdownEvent = threading.Event()
    runner = _BtRunner(_BT_INFO_CONNECTED)
    orch._btConnectedRunner = runner
    orch._initializeCardStateEmitters()
    try:
        _emitLink(orch, tmp_path)
        sampler = orch._btSampler
        assert runner.called.wait(timeout=5.0)
        deadline = time.monotonic() + 5.0
        while sampler.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        callsBefore = len(runner.calls)
        bt = _emitLink(orch, tmp_path)["bt"]
        callsDuringTick = len(runner.calls) - callsBefore
        sameSampler = orch._btSampler is sampler
    finally:
        _stopSampler(orch)

    assert bt["state"] == "up"
    assert sameSampler
    assert callsDuringTick == 0
    assert runner.calls[0] == ["bluetoothctl", "info", _BT_MAC]
    assert set(runner.threads) == {sampler.thread}
    assert threading.current_thread() not in runner.threads
    assert sampler.thread.daemon is True
    assert sampler._intervalS == BT_CONNECTED_SAMPLE_INTERVAL_S


def test_link_bt_configuredMac_usedWhenTheConnectionHasNone(tmp_path):
    """MAC source: connection.macAddress, else pi.bluetooth.macAddress."""
    import threading

    config = _config(tmp_path, stateEmitIntervalSeconds=0.0)
    config["pi"]["bluetooth"] = {"macAddress": _BT_MAC}
    orch = _FakeOrch(config)
    orch._shutdownEvent = threading.Event()
    runner = _BtRunner(_BT_INFO_CONNECTED)
    orch._btConnectedRunner = runner
    orch._initializeCardStateEmitters()
    try:
        _emitLink(orch, tmp_path)
        assert runner.called.wait(timeout=5.0)
    finally:
        _stopSampler(orch)

    assert runner.calls[0] == ["bluetoothctl", "info", _BT_MAC]


@pytest.mark.parametrize(
    ("connMac", "configMac", "simulate", "withShutdownEvent"),
    [
        (None, None, False, True),
        ("/dev/rfcomm0", _BT_MAC, False, True),
        ("SIMULATED:00:11:22:33:44:55", _BT_MAC, False, True),
        (None, _BT_MAC, True, True),
        (_BT_MAC, None, False, False),
    ],
    ids=["no-mac", "rfcomm-path", "simulate-mac", "simulate-run", "stub-host-no-event"],
)
def test_link_bt_noUsableMac_startsNoSampler_andIsNull(
    tmp_path, connMac, configMac, simulate, withShutdownEvent
):
    """No MAC, an rfcomm path, the --simulate MAC (Atlas E1) or a host with
    no _shutdownEvent to stop it -> link.bt null and NO sampler thread."""
    import threading

    config = _config(tmp_path, stateEmitIntervalSeconds=0.0)
    if configMac is not None:
        config["pi"]["bluetooth"] = {"macAddress": configMac}
    conn = None
    if connMac is not None:
        conn = SimpleNamespace(macAddress=connMac, getStatus=lambda: None)
    orch = _FakeOrch(config, connection=conn)
    orch._simulate = simulate
    if withShutdownEvent:
        orch._shutdownEvent = threading.Event()
    runner = _BtRunner(_BT_INFO_CONNECTED)
    orch._btConnectedRunner = runner
    orch._initializeCardStateEmitters()
    threadsBefore = {t.name for t in threading.enumerate()}

    bt = _emitLink(orch, tmp_path)["bt"]

    assert bt == _LINK_NULL
    assert getattr(orch, "_btSampler", None) is None
    assert "bt-connected-sampler" not in (
        {t.name for t in threading.enumerate()} - threadsBefore
    )
    assert runner.calls == []


# ---------------------------------------------------------------------------
# US-732 -- system-status wifi from the off-tick WiFi sampler.
# ---------------------------------------------------------------------------

_WIFI_HOME = "DeathStarWiFi"
_WIFI_TS = "2026-10-22T12:00:00Z"


class _FakeWifiSampler:
    """Stands in for the sampler thread: the provider only ever calls latest()."""

    def __init__(self, sample=None):
        self.sample = sample

    def latest(self):
        return self.sample


def _wifiConfig(tmp_path, wifi=None):
    config = _config(tmp_path, stateEmitIntervalSeconds=0.0)
    config["pi"]["homeNetwork"] = {"ssid": _WIFI_HOME, "subnet": "10.27.27.0/24"}
    if wifi is not None:
        config["pi"]["network"] = {"wifi": wifi}
    return config


def _wifiReading(kind, ssid=None, rssi=None):
    from src.pi.network.wifi_reader import WifiReading

    if kind == "associated":
        return WifiReading(True, ssid, rssi, None)
    if kind == "unassociated":
        return WifiReading(False, None, None, None)
    return WifiReading(None, None, None, kind)


def _wifiSample(reading, home):
    from src.pi.network.wifi_reader import WifiSample

    return WifiSample(reading=reading, home=home, ts=_WIFI_TS, monoS=1.0)


def _emitWifi(orch, tmp_path):
    orch._emitSystemStatusState()
    status = _readState(tmp_path, "system-status")
    return status["wifi"], status["source"]["wifi"]


def _wifiOrch(tmp_path, sample=None, wifi=None):
    orch = _FakeOrch(_wifiConfig(tmp_path, wifi))
    orch._initializeCardStateEmitters()
    orch._wifiSampler = _FakeWifiSampler(sample)
    return orch


def _stopWifiSampler(orch):
    orch._shutdownEvent.set()
    sampler = getattr(orch, "_wifiSampler", None)
    if sampler is not None:
        sampler.thread.join(timeout=5.0)
        assert not sampler.thread.is_alive()


_WIFI_READ_OK = {"available": True, "reason": None}


@pytest.mark.parametrize(
    ("reading", "home", "wifi", "source"),
    [
        (("associated", _WIFI_HOME, -50), True,
         {"state": "up", "ssid": _WIFI_HOME, "rssiDbm": -50, "home": True,
          "ts": _WIFI_TS},
         _WIFI_READ_OK),
        (("associated", "CoffeeShop", -60), False,
         {"state": "up", "ssid": "CoffeeShop", "rssiDbm": -60, "home": False,
          "ts": _WIFI_TS},
         _WIFI_READ_OK),
        (("unassociated",), False,
         {"state": "down", "ssid": None, "rssiDbm": None, "home": False,
          "ts": _WIFI_TS},
         _WIFI_READ_OK),
        (("nmcli_absent",), None,
         {"state": None, "ssid": None, "rssiDbm": None, "home": None,
          "ts": _WIFI_TS},
         {"available": False, "reason": "nmcli_absent"}),
        (("read_failed",), None,
         {"state": None, "ssid": None, "rssiDbm": None, "home": None,
          "ts": _WIFI_TS},
         {"available": False, "reason": "read_failed"}),
        (("associated", _WIFI_HOME, None), True,
         {"state": None, "ssid": _WIFI_HOME, "rssiDbm": None, "home": True,
          "ts": _WIFI_TS},
         _WIFI_READ_OK),
        (("associated", _WIFI_HOME, -75), True,
         {"state": "weak", "ssid": _WIFI_HOME, "rssiDbm": -75, "home": True,
          "ts": _WIFI_TS},
         _WIFI_READ_OK),
    ],
    ids=["associated-home", "associated-other", "unassociated", "nmcli-missing",
         "read-failed", "proc-file-missing", "minus75-weak"],
)
def test_wifi_theSamplersLatest_isPublished(tmp_path, reading, home, wifi, source):
    """The provider publishes the sampler's latest sample: association from
    nmcli, rssi from /proc, home from the detector, ts the read time."""
    orch = _wifiOrch(tmp_path, _wifiSample(_wifiReading(*reading), home))

    assert _emitWifi(orch, tmp_path) == (wifi, source)


def test_wifi_noSampleYet_isNotRead_homeAndTsNull(tmp_path):
    orch = _wifiOrch(tmp_path, sample=None)

    wifi, source = _emitWifi(orch, tmp_path)

    assert wifi == {"state": None, "ssid": None, "rssiDbm": None, "home": None, "ts": None}
    assert source == {"available": False, "reason": "not_read"}


def test_wifi_stubHostWithoutShutdownEvent_startsNoSampler(tmp_path):
    """Stub hosts (no _shutdownEvent) publish wifi not read and start nothing."""
    import threading

    orch = _FakeOrch(_wifiConfig(tmp_path))
    orch._initializeCardStateEmitters()
    threadsBefore = {t.name for t in threading.enumerate()}

    _wifi, source = _emitWifi(orch, tmp_path)

    assert source == {"available": False, "reason": "not_read"}
    assert getattr(orch, "_wifiSampler", None) is None
    assert getattr(orch, "_homeNetworkDetector", None) is None
    assert "wifi-link-sampler" not in (
        {t.name for t in threading.enumerate()} - threadsBefore
    )


def test_wifi_thresholds_comeFromPiNetworkWifi(tmp_path):
    """W4: config pi.network.wifi moves the band; -65 is weak under -60."""
    orch = _wifiOrch(
        tmp_path,
        _wifiSample(_wifiReading("associated", _WIFI_HOME, -65), True),
        wifi={"weakRssiDbm": -60, "downRssiDbm": -90},
    )

    assert _emitWifi(orch, tmp_path)[0]["state"] == "weak"


def test_wifi_thresholds_absentConfig_fallBackToTheModuleDefaults(tmp_path):
    orch = _wifiOrch(
        tmp_path, _wifiSample(_wifiReading("associated", _WIFI_HOME, -65), True)
    )

    assert _emitWifi(orch, tmp_path)[0]["state"] == "up"


def test_wifi_realSampler_offTheTick_oneDetector_homeFromTheSameRead(
    tmp_path, monkeypatch
):
    """The provider starts ONE daemon sampler; the read runs on it, never on
    the tick; ONE HomeNetworkDetector (built lazily from self._config) judges
    the sampler's own read -- its ssidReader is the sample, so no second
    nmcli; _shutdownEvent stops the thread."""
    import threading
    import time

    from src.pi.network import home_detector

    monkeypatch.setattr(home_detector, "_readLocalIps", lambda: ["10.27.27.124"])
    reads = []

    def reader():
        reads.append(threading.current_thread())
        return _wifiReading("associated", _WIFI_HOME, -50)

    orch = _FakeOrch(_wifiConfig(tmp_path))
    orch._shutdownEvent = threading.Event()
    orch._wifiReader = reader
    orch._initializeCardStateEmitters()
    try:
        orch._emitSystemStatusState()
        sampler = orch._wifiSampler
        deadline = time.monotonic() + 5.0
        while sampler.latest() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        readsBefore = len(reads)
        wifi, source = _emitWifi(orch, tmp_path)
        readsDuringTick = len(reads) - readsBefore
        detector = orch._homeNetworkDetector
        sameSampler = orch._wifiSampler is sampler
    finally:
        _stopWifiSampler(orch)

    assert (wifi["state"], wifi["home"], wifi["rssiDbm"]) == ("up", True, -50)
    assert source == _WIFI_READ_OK
    assert sameSampler
    assert readsDuringTick == 0
    assert reads and all(t is not threading.main_thread() for t in reads)
    assert detector._ssidReader == sampler.judgedSsid
    assert detector._ssid == _WIFI_HOME


def test_wifi_homeDetector_isBuiltOnce_andCached(tmp_path):
    """W1: one HomeNetworkDetector, getattr + cache (the _getAltitudeAnchor
    pattern)."""
    orch = _FakeOrch(_wifiConfig(tmp_path))

    first = orch._getHomeNetworkDetector(lambda: None)
    second = orch._getHomeNetworkDetector(lambda: "other")

    assert first is not None and first is second
