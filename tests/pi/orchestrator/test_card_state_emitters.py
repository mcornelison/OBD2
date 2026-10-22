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
