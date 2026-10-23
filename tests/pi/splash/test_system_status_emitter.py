################################################################################
# File Name: test_system_status_emitter.py
# Purpose/Description: Tests for the F-092 system-status emitter (US-400). The
#   system-status schema builder is pure (Atlas A-3 shape); the emit factory is
#   best-effort (write failures logged, never raised -- same contract as the
#   F-103 emitters). Covers: the A-3 schema shape, honest-instrument
#   serialization (a down/reconnecting link is reported verbatim, never a
#   fabricated `linked`), the stale-while-driving policy (I-033 / I-4), atomic
#   write + states-dir provisioning, and the never-raise guarantee.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-400 system-status card)
# 2026-10-14    | Rex (US-901-b)| runMode: the replay > simulate > live precedence,
#               |              | the emit forwarding, and the orchestrator gather.
# 2026-10-14    | Rex (US-880-a)| the two exact drive pins gain distanceKm /
#               |              | distanceSinceTs (null when not supplied).
# 2026-10-18    | Rex (US-896-b)| the two exact drive pins gain elapsedSec /
#               |              | distancePartial (null when not supplied); the
#               |              | elapsed rule and the partial rule.
# 2026-10-22    | Rex (US-876-c)| the exact pin gains `link`; the shared per-layer
#               |              | state function + tracker (Atlas L1, G1), the
#               |              | link block's shape and the emit forwarding.
# 2026-10-22    | Rex (US-876-d)| LinkLayerTracker.markUnread (stale evidence).
# 2026-10-22    | Rex (US-732) | wifi home + ts, the not_read token, the two
#               |              | VCs and the emit forwarding of the wifi inputs.
# 2026-10-22    | Rex (US-916) | the exact pin gains sync rowsWaiting /
#               |              | edrRowsWaiting / notCounted; their forwarding.
# 2026-10-22    | Rex (US-877-a)| the exact pin gains `pi` (all null); the pi
#               |              | block's normalisation + its emit forwarding.
# 2026-10-22    | Rex (US-877-b)| the exact pin gains `verdict`; the verdict's
#               |              | members, rules, exact reasons and forwarding.
# 2026-10-22    | Rex (US-877-c)| the emit returns the payload it wrote (None on
#               |              | a failed write).
# 2026-10-23    | Rex (US-894-b)| MOVED PIN (US-894-b): obdLink + its two builder /
#               |              | emit parameters are retired (Atlas A2/P6); the
#               |              | exact pin loses the block and the obdLink
#               |              | asserts become "absent" asserts.
# ================================================================================
################################################################################

"""Tests for ``pi.splash.system_status_emitter``."""

import json
import os

import pytest

from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.splash.system_status_emitter import (
    LINK_CONNECTING,
    LINK_DOWN,
    LINK_RETRYING,
    LINK_UP,
    OBD_LINKED,
    RUN_MODE_LIVE,
    RUN_MODE_REPLAY,
    RUN_MODE_SIMULATE,
    SYSTEM_STATUS_FILENAME,
    LinkLayerTracker,
    buildSystemStatusState,
    buildSystemVerdict,
    deriveLinkLayerState,
    deriveRunMode,
    isSyncStaleWhileDriving,
    makeSystemStatusEmitter,
)

_NOW = "2026-06-30T19:42:00Z"
_SYNC_OK = "2026-06-30T19:40:00Z"  # 120s before _NOW


# ---------------------------------------------------------------------------
# buildSystemStatusState -- the pure A-3 schema builder.
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_a3Schema_hasExactShape():
    """Given the Atlas A-3 fields,
    When buildSystemStatusState assembles the payload,
    Then it emits exactly the A-3 nested shape with the supplied values."""
    state = buildSystemStatusState(
        # MOVED PIN (US-894-b): obdLink and its two parameters are retired.
        syncLastOkTs=_SYNC_OK,
        # MOVED PIN (US-894-c): syncRows / syncPending dropped -- sync.rows / sync.pending retired (Atlas P7).
        syncStale=False,
        powerSource="external",
        driveState="recording",
        driveId=27,
        nowIso=_NOW,
    )
    assert state == {
        # MOVED PIN (US-894-b): no `obdLink` key -- `link` is the link fact.
        # US-916: rowsWaiting / edrRowsWaiting / notCounted are always keys;
        # null when not read (a caller that passes none read nothing).
        "sync": {
            # MOVED PIN (US-894-c): no `rows` / `pending` (Atlas P7).
            "lastOkTs": _SYNC_OK, "stale": False,
            "rowsWaiting": None, "edrRowsWaiting": None, "notCounted": None,
        },
        # US-628: `reasons` is ALWAYS a key and is EMPTY here -- this source is
        # a real measurement, and a reason standing beside one would be a
        # second, contradictory account of the same fact.
        "power": {"source": "external", "reasons": {}},
        # US-505 `lastDrive` is ALWAYS a key (null when unknown) -- see the
        # always-present catalog below for why absence is the dangerous shape.
        "drive": {
            "state": "recording", "driveId": 27, "lastDrive": None,
            # US-880-a: always keys; null when nothing integrated this process.
            "distanceKm": None, "distanceSinceTs": None,
            # US-896-b: always keys, null with no distanceSinceTs.
            "elapsedSec": None, "distancePartial": None,
        },
        # US-480-a idle-SSOT (b): recording -> never idle (a drive is active).
        "idle": False,
        # US-728: `priorShutdown` is ALWAYS a key (null when not read).
        "priorShutdown": None,
        # US-901-b: `runMode` is ALWAYS a key; a caller that does not say
        # otherwise is the production orchestrator, which runs live.
        "runMode": "live",
        # ARCH-007: `wifi` joins the A-3 schema per the Atlas contract ruling
        # of 2026-08-20. It defaults to UNAVAILABLE, never to a fabricated link:
        # a caller that has not wired the provider must not publish one.
        # US-732: home and ts are always keys; null when not read.
        "wifi": {"state": None, "ssid": None, "rssiDbm": None, "home": None, "ts": None},
        # US-877-a: `pi` is ALWAYS a key, every key present; unwired is every
        # key null and overLimit [].
        "pi": {
            "cpuTempC": None, "cpuTempTs": None, "cpuTempLimitC": None,
            "throttled": None, "throttledHex": None, "throttledSinceBoot": None,
            "throttledTs": None, "diskFreeBytes": None, "diskThresholdBytes": None,
            "diskVerdict": None, "diskTs": None, "uptimeS": None, "uptimeTs": None,
            "overLimit": [],
        },
        # US-876-c: `link` is ALWAYS a key, every layer always present; a
        # caller that supplies no chain publishes every layer as not read.
        "link": {
            "bt": {"state": None, "ts": None, "lastOkTs": None},
            "adapter": {"state": None, "ts": None, "lastOkTs": None},
            "ecu": {"state": None, "ts": None, "lastOkTs": None},
        },
        "source": {
            "obd": {"available": True, "reason": None},
            # US-732 (Atlas W8): the snake token, not the old prose.
            "wifi": {"available": False, "reason": "not_read"},
        },
        "ts": _NOW,
        # US-877-b: `verdict` is ALWAYS a key; nothing read is no issue.
        "verdict": {"issueCount": 0, "members": []},
    }


def test_buildSystemStatusState_honestInstrument_downLinkIsVerbatim():
    """MOVED PIN (US-894-b): obdLink is retired, so no link state is published
    outside the chain -- nothing here can read 'linked'."""
    state = buildSystemStatusState(
        syncLastOkTs=None,
        syncStale=True,
        powerSource="battery",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
    )
    assert "obdLink" not in state
    assert state["sync"]["lastOkTs"] is None
    assert state["drive"]["driveId"] is None
    # A verbatim `down` link is still an AVAILABLE source (we are talking to /
    # retrying a car) -- distinct from US-429 obd-unavailable (no car at all).
    assert state["source"]["obd"] == {"available": True, "reason": None}
    # US-480-a idle-SSOT (b): the OBD source is AVAILABLE (a car we are retrying),
    # so this is NOT the calm parked/asleep state -- idle stays False even though
    # the drive is idle. Idle requires the OBD source to be ABSENT.
    assert state["idle"] is False


# ---------------------------------------------------------------------------
# US-505 `drive.lastDrive` -- the ALWAYS-PRESENT key (I-041 / US-528).
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_lastDriveKey_isPresentInEveryShape():
    """Given every call shape the emitter supports (arg omitted, explicit None,
    a real summary, and idle-with-no-history),
    When buildSystemStatusState assembles the payload,
    Then `drive.lastDrive` is ALWAYS a key -- null when unknown, never absent.

    This is the assertion I-041 was missing. An exact-shape equality check
    proves the key exists for ONE call shape; a renderer breaks on the shape
    where it goes missing. A sometimes-absent key is the failure mode US-505
    designed against: `undefined` silently falls through to the wrong branch,
    whereas an explicit null is a value the display can test against.
    """
    baseKwargs = {
        "syncLastOkTs": _SYNC_OK,
        "syncStale": False,
        "powerSource": "external",
        "nowIso": _NOW,
    }
    shapes = {
        # The kwarg omitted entirely -- the production default path.
        "omitted": dict(baseKwargs, driveState="recording", driveId=27),
        # Explicitly None -- a caller that has no drive on record.
        "explicitNone": dict(
            baseKwargs, driveState="recording", driveId=27, lastDrive=None
        ),
        # A real US-505 summary while a NEW drive is already recording.
        "populated": dict(
            baseKwargs,
            driveState="recording",
            driveId=28,
            lastDrive={"driveId": 27, "startedAtTs": _SYNC_OK},
        ),
        # Parked with nothing on record -- the coldest branch.
        "idleNoHistory": dict(baseKwargs, driveState="idle", driveId=None),
    }

    for shapeName, kwargs in shapes.items():
        drive = buildSystemStatusState(**kwargs)["drive"]
        assert "lastDrive" in drive, f"lastDrive key vanished in shape: {shapeName}"


def test_buildSystemStatusState_lastDrive_isVerbatimAndDistinctFromDriveId():
    """Given a parked Pi (idle, no active drive) that HAS a completed drive,
    When the payload is assembled,
    Then lastDrive is transported verbatim and driveId stays null.

    `lastDrive` (last COMPLETED drive) and `driveId` (the ACTIVE drive) are
    different facts. Merging them would make a parked Pi read as recording,
    so this pins the separation as well as the no-reformat contract -- the
    emitter transports the producer's fact, it never re-derives it.
    """
    summary = {"driveId": 27, "startedAtTs": _SYNC_OK}
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK,
        syncStale=False,
        powerSource="battery",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        lastDrive=summary,
    )

    assert state["drive"]["lastDrive"] == summary  # verbatim, not reformatted
    assert state["drive"]["driveId"] is None  # a completed drive is NOT active
    assert state["drive"]["state"] == "idle"


# ---------------------------------------------------------------------------
# US-429 honest-availability -- the OBD source's availability (source.obd).
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_obdUnavailable_typedNaNotStaleLink():
    """US-429: on wall power / car off the OBD source is unavailable -> the
    typed reason travels in source.obd. Sync/power/drive stay independent.
    MOVED PIN (US-894-b): the obdLink block it used to blank is retired."""
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK,
        syncStale=False,
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=False,
        obdUnavailableReason="OBD: off",
    )
    assert "obdLink" not in state
    assert state["source"]["obd"] == {"available": False, "reason": "OBD: off"}
    # Other sources are unaffected (one truth per SOURCE).
    # MOVED PIN (US-894-c): sync.rows is retired; the sync block still rides.
    assert state["sync"]["lastOkTs"] == _SYNC_OK
    # US-668: was assert state["power"]["mode"] == "wall". The
    # operator-declared mode is gone; the SENSED source is the
    # surviving power fact and the one worth asserting here.
    assert "mode" not in state["power"]
    assert "source" in state["power"]
    # US-480-a idle-SSOT (b): OBD source ABSENT + not recording -> this IS the
    # calm parked/asleep state -> idle True (US-481 renders the idle home card).
    assert state["idle"] is True


# ---------------------------------------------------------------------------
# US-480-a idle-SSOT (b) -- the emitter OWNS the idle decision (Atlas ruling).
# ---------------------------------------------------------------------------


def test_buildSystemStatusState_idle_trueOnlyWhenObdAbsentAndNotRecording():
    """idle == parked-and-asleep: OBD source ABSENT (no car) AND no drive
    recording. The emitter owns both inputs so the display never re-derives it."""
    state = buildSystemStatusState(
        syncLastOkTs=None,
        syncStale=False,
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=False,
    )
    assert state["idle"] is True


def test_buildSystemStatusState_idle_falseWhenObdAvailable():
    """OBD source present (car awake) -> NOT idle, even with no drive recording
    (Iris AC-4: idle flips false the moment the OBD source wakes)."""
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK,
        syncStale=False,
        powerSource="external",
        driveState="idle",
        driveId=None,
        nowIso=_NOW,
        obdAvailable=True,
    )
    assert state["idle"] is False


def test_buildSystemStatusState_idle_falseWhileRecording():
    """A recording drive -> NOT idle even if the OBD source were reported absent
    (Iris AC-4: idle flips false the moment a drive records). Belt-and-suspenders
    on the driveState half of the SSOT."""
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK,
        syncStale=False,
        powerSource="external",
        driveState="recording",
        driveId=42,
        nowIso=_NOW,
        obdAvailable=False,
    )
    assert state["idle"] is False


# ---------------------------------------------------------------------------
# isSyncStaleWhileDriving -- the stale-while-driving policy (I-4 / I-033).
# ---------------------------------------------------------------------------


def test_isSyncStaleWhileDriving_recordingAndOldSync_isStale():
    """Recording with a last-sync older than the threshold -> stale (amber)."""
    assert (
        isSyncStaleWhileDriving(
            "recording", _SYNC_OK, _NOW, thresholdS=60
        )
        is True
    )


def test_isSyncStaleWhileDriving_recordingAndFreshSync_isNotStale():
    """Recording with a last-sync inside the threshold -> not stale."""
    assert (
        isSyncStaleWhileDriving(
            "recording", _SYNC_OK, _NOW, thresholdS=600
        )
        is False
    )


def test_isSyncStaleWhileDriving_idle_isNeverStale():
    """Parked/idle -> never flagged stale (parked syncs catch up; the flag is
    'stale-WHILE-DRIVING' only)."""
    assert (
        isSyncStaleWhileDriving("idle", _SYNC_OK, _NOW, thresholdS=1)
        is False
    )


def test_isSyncStaleWhileDriving_recordingNeverSynced_isStale():
    """Recording with no successful sync yet -> stale (data at risk, honest)."""
    assert (
        isSyncStaleWhileDriving("recording", None, _NOW, thresholdS=60)
        is True
    )


def test_isSyncStaleWhileDriving_unparseableTimestamp_isStale():
    """An unparseable last-sync while driving -> stale (never claim fresh when we
    cannot prove freshness -- no green-when-broken)."""
    assert (
        isSyncStaleWhileDriving("recording", "not-a-date", _NOW, thresholdS=60)
        is True
    )


# ---------------------------------------------------------------------------
# makeSystemStatusEmitter -- best-effort atomic writer (A-3 ownership).
# ---------------------------------------------------------------------------


def test_emitter_writesSystemStatusFile_andComputesStale(tmp_path):
    """Given a states dir,
    When the emit callable fires while recording with an old sync,
    Then it writes states/system-status with the A-3 payload and the policy
    computes sync.stale=True (provisioning the dir if absent -- C-5)."""
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external",
        driveState="recording",
        driveId=27,
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert "obdLink" not in written  # MOVED PIN (US-894-b): retired
    # MOVED PIN (US-894-c): sync.pending is retired (Atlas P7).
    assert "pending" not in written["sync"] and "rows" not in written["sync"]
    assert written["sync"]["stale"] is True  # recording + 120s-old sync > 60s
    assert written["drive"] == {
        "state": "recording",
        "driveId": 27,
        "lastDrive": None,  # US-505: always a key, even when the caller omits it
        # US-880-a: always keys, null when the caller omits them.
        "distanceKm": None,
        "distanceSinceTs": None,
        # US-896-b: always keys, null when the caller omits distanceSinceTs.
        "elapsedSec": None,
        "distancePartial": None,
    }
    assert written["ts"] == _NOW


def test_emitter_forwardsLastDrive_verbatimThroughTheJsonRoundTrip(tmp_path):
    """Given a caller that supplies a real US-505 last-drive summary,
    When the emit callable fires,
    Then the written JSON carries it verbatim under drive.lastDrive.

    This is the OTHER half of the always-present contract and it cannot be
    proved at the builder. `emit` has its own `lastDrive=None` default, so if
    the emit->build forwarding were dropped the builder default would still
    supply the KEY and every presence assertion above would stay green while
    the real value silently never reached the display. Only a populated value
    observed on the far side of the file write pins the wiring.
    """
    statesDir = str(tmp_path / "states")
    summary = {"driveId": 27, "startedAtTs": _SYNC_OK}
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external",
        driveState="idle",
        driveId=None,
        lastDrive=summary,
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert written["drive"]["lastDrive"] == summary
    assert written["drive"]["driveId"] is None


def test_emitter_neverRaises_onWriteFailure(tmp_path):
    """Best-effort: a write failure is logged but NEVER raised -- the emit hook
    must never block the orchestrator. Point it at an un-creatable path."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    # Must not raise.
    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external",
        driveState="idle",
        driveId=None,
    )
    assert not os.path.exists(statesDir)


# ---------------------------------------------------------------------------
# US-901-b `runMode` -- is the panel showing the live car?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("replayActive", "simulate", "expected"),
    [
        (False, False, RUN_MODE_LIVE),
        (False, True, RUN_MODE_SIMULATE),
        (True, False, RUN_MODE_REPLAY),
        # Replay rides the --simulate seam (US-857), so both are set during a
        # replay and replay must win (Atlas ruling 2026-10-13 on Iris S-2).
        (True, True, RUN_MODE_REPLAY),
    ],
)
def test_deriveRunMode_precedence_replayThenSimulateThenLive(
    replayActive, simulate, expected
):
    """Given the replay flag and the --simulate flag,
    When deriveRunMode resolves them,
    Then replay wins over simulate, and live is only the both-off case."""
    assert deriveRunMode(replayActive=replayActive, simulate=simulate) == expected


def test_buildSystemStatusState_runMode_isCarriedVerbatim():
    """Given a non-live runMode,
    When the payload is built,
    Then `runMode` carries it -- and `power` holds no `mode` key, the name
    US-668 retired and pi.power.mode still owns."""
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK,
        syncStale=False,
        powerSource="external",
        driveState="recording",
        driveId=3,
        nowIso=_NOW,
        runMode=RUN_MODE_REPLAY,
    )
    assert state["runMode"] == "replay"
    assert "mode" not in state
    assert "mode" not in state["power"]


def test_emitter_forwardsRunMode_throughTheJsonRoundTrip(tmp_path):
    """Given a caller that supplies runMode='simulate',
    When the emit callable fires,
    Then the written file carries it. The builder's own default would supply
    the KEY even if emit dropped the value, so only a non-default value seen
    on the far side of the write pins the forwarding."""
    statesDir = str(tmp_path / "states")
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external",
        driveState="idle",
        driveId=None,
        runMode=RUN_MODE_SIMULATE,
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert written["runMode"] == "simulate"


class _StubComposer(CardStateEmitterMixin):
    """The mixin with every OTHER gather stubbed, so only runMode is live."""

    def __init__(self, config: dict, simulate: bool) -> None:
        self._config = config
        self._simulate = simulate
        self._lastSyncOkTsIso = None
        self._lastSyncRows = 0
        self.calls: list[dict] = []
        self._systemStatusEmitter = lambda **kw: self.calls.append(kw)

    def _gatherObdLinkState(self):
        return OBD_LINKED, 0, True, None

    def _gatherPowerState(self):
        return "external", None

    def _gatherDriveState(self):
        return "idle", None

    def _gatherLastDriveSummary(self):
        return None

    def _gatherPriorShutdown(self):
        return None


@pytest.mark.parametrize(
    ("config", "simulate", "expected"),
    [
        ({}, False, "live"),
        ({"pi": {"replay": {"active": False}}}, False, "live"),
        ({}, True, "simulate"),
        ({"pi": {"replay": {"active": True}}}, True, "replay"),
        ({"pi": {"replay": {"active": True}}}, False, "replay"),
    ],
)
def test_orchestratorEmit_passesRunMode_fromReplayConfigAndSimulateFlag(
    config, simulate, expected
):
    """Given the orchestrator's config and its --simulate flag,
    When the system-status tick fires,
    Then the emitter receives the runMode those two facts resolve to."""
    composer = _StubComposer(config, simulate)

    composer._emitSystemStatusState()

    assert len(composer.calls) == 1
    assert composer.calls[0]["runMode"] == expected


def test_orchestratorEmit_noSimulateAttribute_isLive():
    """Given a composer that never set `_simulate` (the standalone composers),
    When the tick fires,
    Then runMode is live -- the attribute is read through getattr, so an
    older composer keeps emitting instead of raising AttributeError."""
    composer = _StubComposer({}, False)
    del composer._simulate

    composer._emitSystemStatusState()

    assert composer.calls[0]["runMode"] == "live"


# ---------------------------------------------------------------------------
# US-896-b: drive.elapsedSec (Atlas Q2/G2) + drive.distancePartial (B-1(b)).
# ---------------------------------------------------------------------------

_SINCE = "2026-06-30T19:19:00Z"  # 23 min before _NOW


def _drive(**kwargs) -> dict:
    return buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="recording", driveId=27,
        nowIso=_NOW, **kwargs,
    )["drive"]


def test_elapsedSec_recording_isPublishTimeNowMinusSince():
    drive = _drive(distanceKm=19.96, distanceSinceTs=_SINCE, distancePartial=False)

    assert drive["elapsedSec"] == 1380
    assert isinstance(drive["elapsedSec"], int)


def test_elapsedSec_afterDriveEnd_isFrozenAtTheEndTs():
    drive = _drive(
        distanceKm=19.96, distanceSinceTs=_SINCE,
        distanceEndTs="2026-06-30T19:30:00Z", distancePartial=False,
    )

    assert drive["elapsedSec"] == 660


def test_elapsedSec_isNull_whenSinceIsNull_evenWithAnEndMark():
    drive = _drive(distanceEndTs="2026-06-30T19:30:00Z", distancePartial=True)

    assert drive["elapsedSec"] is None


@pytest.mark.parametrize("since", ["not-a-ts", "2026-06-30T19:45:00Z"])
def test_elapsedSec_unparseableOrAfterNow_isNull_neverAGuess(since):
    """A since-point after the publish instant is two clocks disagreeing;
    a negative elapsed is not a duration, so it is not published."""
    assert _drive(distanceSinceTs=since, distancePartial=False)["elapsedSec"] is None


@pytest.mark.parametrize("partial", [True, False])
def test_distancePartial_isCarried_whenSinceIsSet(partial):
    drive = _drive(distanceSinceTs=_SINCE, distancePartial=partial)

    assert drive["distancePartial"] is partial


def test_distancePartial_isNull_whenSinceIsNull():
    assert _drive(distancePartial=False)["distancePartial"] is None


def test_emitter_forwardsElapsedAndPartial_throughTheJsonRoundTrip(tmp_path):
    """The emit -> build forwarding of the end mark and the flag: only a
    populated value on the far side of the file write pins it."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external", driveState="idle", driveId=None,
        distanceKm=19.96, distanceSinceTs=_SINCE,
        distanceEndTs="2026-06-30T19:49:00Z", distancePartial=True,
    )

    drive = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )["drive"]
    assert drive["elapsedSec"] == 1800
    assert drive["distancePartial"] is True


# ---------------------------------------------------------------------------
# US-876-c: the link chain {bt, adapter, ecu} (Atlas L1/L5/L6, G1, X1).
# ---------------------------------------------------------------------------

_T0 = "2026-10-22T15:00:00Z"
_T1 = "2026-10-22T15:00:10Z"
_T2 = "2026-10-22T15:01:00Z"
_T3 = "2026-10-22T15:02:00Z"
_T4 = "2026-10-22T15:03:00Z"
_NULL_LAYER = {"state": None, "ts": None, "lastOkTs": None}


@pytest.mark.parametrize(
    ("observedUp", "upEarlier", "authority", "expected"),
    [
        (True, False, True, LINK_UP),
        (True, True, False, LINK_UP),
        (False, False, True, LINK_CONNECTING),
        (False, True, True, LINK_RETRYING),
        (False, False, False, LINK_DOWN),
        (False, True, False, LINK_DOWN),
        (None, False, True, None),
        (None, False, False, None),
        (None, True, True, LINK_RETRYING),
    ],
)
def test_deriveLinkLayerState_theL1Table(observedUp, upEarlier, authority, expected):
    """Atlas L1, exact: up / connecting (never up) / retrying (up earlier) /
    down (no retry authority) / null (not read; retrying once up earlier)."""
    assert deriveLinkLayerState(
        observedUp=observedUp, upEarlierThisSession=upEarlier, retryAuthority=authority
    ) == expected


def test_tracker_neverUp_up_drop_up_readsConnectingUpRetryingUp():
    """Atlas VC: the reconnect after the drop reads retrying, NOT connecting --
    the up-this-session flag survives the drop that reset the observation."""
    tracker = LinkLayerTracker()

    states = [
        tracker.observe(observedUp=False, observedTs=_T0, nowTs=_T1)["state"],
        tracker.observe(observedUp=True, observedTs=_T1, nowTs=_T2)["state"],
        tracker.observe(observedUp=False, observedTs=_T2, nowTs=_T3)["state"],
        tracker.observe(observedUp=True, observedTs=_T3, nowTs=_T4)["state"],
    ]

    assert states == [LINK_CONNECTING, LINK_UP, LINK_RETRYING, LINK_UP]


def test_tracker_notReadBeforeAnUp_isNull_afterAnUp_isRetrying():
    """COULD_NOT_DETERMINE (observedUp None) before any up -> null (all three
    keys); after an up -> retrying."""
    tracker = LinkLayerTracker()

    before = tracker.observe(observedUp=None, observedTs=_T0, nowTs=_T0)
    tracker.observe(observedUp=True, observedTs=_T1, nowTs=_T1)
    after = tracker.observe(observedUp=None, observedTs=_T2, nowTs=_T3)

    assert before == _NULL_LAYER
    assert after["state"] == LINK_RETRYING
    assert after["ts"] == _T2


def test_tracker_markUnread_isNullEvenAfterAnUp_andTheNextObservationIsATransition():
    """US-876-d (D5): a producer that judged its evidence stale publishes the
    layer null -- NOT retrying, as an unread observation after an up would --
    and the next observation re-enters dated its own event, the up-this-session
    flag kept (a later not-up reads retrying)."""
    tracker = LinkLayerTracker()
    tracker.observe(observedUp=True, observedTs=_T0, nowTs=_T0)

    stale = tracker.markUnread()
    back = tracker.observe(observedUp=True, observedTs=_T0, nowTs=_T2)
    dropped = tracker.observe(observedUp=False, observedTs=_T3, nowTs=_T3)

    assert stale == _NULL_LAYER
    assert back["state"] == LINK_UP
    assert back["ts"] == _T0
    assert dropped["state"] == LINK_RETRYING


def test_tracker_ts_isTheTransitionTime_andHoldsWhileTheStateHolds():
    """ts = the last STATE transition's event time (c-6), never the publish
    tick; a repeat observation of the same state does not re-date it."""
    tracker = LinkLayerTracker()

    first = tracker.observe(observedUp=False, observedTs=_T0, nowTs=_T1)
    # Another not-up observation dated later (e.g. NOT_YET_ATTEMPTED ->
    # DID_NOT_ANSWER): still connecting, so still dated the attempt's start.
    second = tracker.observe(observedUp=False, observedTs=_T2, nowTs=_T3)
    up = tracker.observe(observedUp=True, observedTs=_T3, nowTs=_T4)

    assert first["ts"] == _T0
    assert second["ts"] == _T0
    assert up["ts"] == _T3


def test_tracker_lastOkTs_isTheLastUpThisSession_nullUntilThen():
    """X1: lastOkTs = the last time the layer was up THIS session; the
    producer's own last-ok instant wins over the publish tick."""
    tracker = LinkLayerTracker()

    never = tracker.observe(observedUp=False, observedTs=_T0, nowTs=_T0)
    up = tracker.observe(observedUp=True, observedTs=_T1, nowTs=_T2, lastOkTs=_T1)
    upNoProducerTs = tracker.observe(observedUp=True, observedTs=_T1, nowTs=_T3)
    dropped = tracker.observe(observedUp=False, observedTs=_T4, nowTs=_T4)

    assert never["lastOkTs"] is None
    assert up["lastOkTs"] == _T1
    assert upNoProducerTs["lastOkTs"] == _T3
    assert dropped["lastOkTs"] == _T3


def test_tracker_down_onlyWithoutRetryAuthority_datedWhenAuthorityWentAway():
    """C2: not up AND no retry authority -> down, dated when BOTH became true
    (here the authority leaving, after the drop); authority back -> retrying,
    dated when that was seen -- the drop's own time precedes the down, so it
    cannot be the time of this transition."""
    tracker = LinkLayerTracker()
    tracker.observe(observedUp=True, observedTs=_T0, nowTs=_T0)

    down = tracker.observe(
        observedUp=False, observedTs=_T1, nowTs=_T3, noAuthoritySinceTs=_T2
    )
    back = tracker.observe(observedUp=False, observedTs=_T1, nowTs=_T4)

    assert down == {"state": LINK_DOWN, "ts": _T2, "lastOkTs": _T0}
    assert back["state"] == LINK_RETRYING
    assert back["ts"] == _T4


def test_sharedLayerFunction_G1a_keyOff_ecuNeverAnswers_btNeverRetrying():
    """G1 (a): key off, the ECU never answers, 3 attempts each bringing BT up
    then down (rfcomm released after a failed attempt, US-512) -> link.bt reads
    only connecting/up, never retrying: BT was never up WHILE the ECU was."""
    bt = LinkLayerTracker()
    seen = []
    clock = iter(f"2026-10-22T15:{m:02d}:00Z" for m in range(10))

    for _attempt in range(3):
        for btUp in (True, False):
            ts = next(clock)
            seen.append(
                bt.observe(
                    observedUp=btUp, observedTs=ts, nowTs=ts, chainComplete=False
                )["state"]
            )

    assert set(seen) == {LINK_UP, LINK_CONNECTING}
    assert LINK_RETRYING not in seen


def test_sharedLayerFunction_G1b_ecuUp_thenDongleUnplugged_btRetrying():
    """G1 (b): BT up while the ECU is up (the chain was complete), then the
    dongle is unplugged -> link.bt retrying (counted, US-877-b)."""
    bt = LinkLayerTracker()

    bt.observe(observedUp=True, observedTs=_T0, nowTs=_T0, chainComplete=True)
    unplugged = bt.observe(
        observedUp=False, observedTs=_T1, nowTs=_T2, chainComplete=False
    )

    assert unplugged["state"] == LINK_RETRYING
    assert unplugged["ts"] == _T1


def test_buildSystemStatusState_link_isPublished_everyLayerAndKeyPresent():
    """L6: every layer and every key always present; a supplied ECU layer is
    carried verbatim and the unsupplied layers are not read (all three null)."""
    ecu = {"state": LINK_UP, "ts": _T0, "lastOkTs": _T1}

    state = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        link={"ecu": ecu},
    )

    assert state["link"] == {"bt": _NULL_LAYER, "adapter": _NULL_LAYER, "ecu": ecu}


def test_buildSystemStatusState_link_aNullState_publishesAllThreeNull():
    """A layer whose state is null is not read: ts and lastOkTs are null too,
    whatever the caller passed beside it (available = state != null)."""
    state = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        link={"ecu": {"state": None, "ts": _T0, "lastOkTs": _T1}},
    )

    assert state["link"]["ecu"] == _NULL_LAYER


def test_buildSystemStatusState_link_notBlanked_whenObdSourceUnavailable():
    """L6 / ARCH-061: source.obd.available false NEVER blanks link -- blanking
    was the grey this block retired (with obdLink, US-894-b)."""
    ecu = {"state": LINK_CONNECTING, "ts": _T0, "lastOkTs": None}

    state = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        obdAvailable=False, obdUnavailableReason="never connected",
        link={"ecu": ecu},
    )

    assert "obdLink" not in state  # MOVED PIN (US-894-b): retired
    assert state["link"]["ecu"] == ecu


def test_emitter_forwardsLink_throughTheJsonRoundTrip(tmp_path):
    """The wiring trap: a builder parameter emit() does not take is never
    published. link travels builder <- emit() <- orchestrator."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=120.0, nowIsoFn=lambda: _NOW
    )
    ecu = {"state": LINK_RETRYING, "ts": _T0, "lastOkTs": _T0}

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external", driveState="idle", driveId=None,
        link={"ecu": ecu},
    )

    link = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )["link"]
    assert link["ecu"] == ecu
    assert link["bt"] == _NULL_LAYER


def test_orchestratorEmit_passesLink_evenFromAComposerWithNoConnection():
    """Stub hosts: a composer that never set `_connection` (or any new
    attribute) still emits, with every link layer not read."""
    composer = _StubComposer({}, False)

    composer._emitSystemStatusState()

    assert composer.calls[0]["link"] == {
        "bt": _NULL_LAYER, "adapter": _NULL_LAYER, "ecu": _NULL_LAYER,
    }


# ---------------------------------------------------------------------------
# US-732 -- wifi {state, ssid, rssiDbm, home, ts}.
# ---------------------------------------------------------------------------

_WIFI_TS = "2026-06-30T19:41:40Z"


def _wifiState(**wifi):
    return buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        **wifi,
    )


def test_wifi_vc1_associatedHomeAtMinus50_isUpHomeTrue():
    """VC 1: wlan0 associated to the home SSID, level -50."""
    state = _wifiState(wifiAvailable=True, wifiSsid="DeathStarWiFi", wifiRssiDbm=-50,
                       wifiHome=True, wifiTs=_WIFI_TS)

    assert state["wifi"] == {
        "state": "up", "ssid": "DeathStarWiFi", "rssiDbm": -50, "home": True,
        "ts": _WIFI_TS,
    }
    assert state["source"]["wifi"] == {"available": True, "reason": None}


def test_wifi_vc2_nmcliAbsent_allNull_reasonNmcliAbsent():
    """VC 2: nmcli absent (dev box) -> state/ssid/rssiDbm/home null;
    source.wifi.available false, reason nmcli_absent."""
    state = _wifiState(wifiAvailable=False, wifiUnavailableReason="nmcli_absent",
                       wifiTs=_WIFI_TS)

    wifi = state["wifi"]
    assert (wifi["state"], wifi["ssid"], wifi["rssiDbm"], wifi["home"]) == (
        None, None, None, None,
    )
    assert state["source"]["wifi"] == {"available": False, "reason": "nmcli_absent"}


def test_wifi_associatedOther_isUpHomeFalse():
    state = _wifiState(wifiAvailable=True, wifiSsid="CoffeeShop", wifiRssiDbm=-55,
                       wifiHome=False, wifiTs=_WIFI_TS)
    assert state["wifi"]["state"] == "up"
    assert state["wifi"]["home"] is False


def test_wifi_unassociated_isAMeasuredDown_availableNoReason():
    """Atlas 2026-10-22 W3: not associated -> available true, state down,
    reason null."""
    state = _wifiState(wifiAvailable=True, wifiSsid=None, wifiRssiDbm=None,
                       wifiHome=False, wifiTs=_WIFI_TS)
    assert state["wifi"]["state"] == "down"
    assert state["source"]["wifi"] == {"available": True, "reason": None}


def test_wifi_associatedAtMinus75_isWeak_theShippedBandUnchanged():
    state = _wifiState(wifiAvailable=True, wifiSsid="DeathStarWiFi", wifiRssiDbm=-75,
                       wifiHome=True, wifiTs=_WIFI_TS)
    assert state["wifi"]["state"] == "weak"


def test_wifi_notRead_homeIsNull_evenIfTheCallerPassedOne():
    """The detector's bool is not trusted on a failed read."""
    state = _wifiState(wifiAvailable=False, wifiUnavailableReason="read_failed",
                       wifiHome=True, wifiTs=_WIFI_TS)
    assert state["wifi"]["home"] is None
    assert state["wifi"]["ts"] == _WIFI_TS
    assert state["source"]["wifi"]["reason"] == "read_failed"


def test_wifi_neverRead_isNotRead_tsNull():
    state = _wifiState()
    assert state["wifi"]["ts"] is None
    assert state["source"]["wifi"] == {"available": False, "reason": "not_read"}


def test_emitter_forwardsWifi_andItsThresholds_throughTheJsonRoundTrip(tmp_path):
    """Every new builder input travels builder <- emit() <- orchestrator; the
    thresholds too (W4) -- -65 is weak only under the injected -60 band."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=120.0, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external", driveState="idle", driveId=None,
        wifiAvailable=True, wifiUnavailableReason=None, wifiSsid="DeathStarWiFi",
        wifiRssiDbm=-65, wifiHome=True, wifiTs=_WIFI_TS,
        wifiWeakRssiDbm=-60, wifiDownRssiDbm=-90,
    )

    payload = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["wifi"] == {
        "state": "weak", "ssid": "DeathStarWiFi", "rssiDbm": -65, "home": True,
        "ts": _WIFI_TS,
    }
    assert payload["source"]["wifi"] == {"available": True, "reason": None}


def test_orchestratorEmit_stubComposer_wifiNotRead_defaultThresholds():
    """Stub hosts: no _shutdownEvent -> no sampler -> wifi not read, and the
    module defaults stand in for an absent pi.network.wifi."""
    composer = _StubComposer({}, False)

    composer._emitSystemStatusState()

    call = composer.calls[0]
    assert call["wifiAvailable"] is False
    assert call["wifiUnavailableReason"] is None
    assert call["wifiTs"] is None
    assert (call["wifiWeakRssiDbm"], call["wifiDownRssiDbm"]) == (-70, -90)
    assert getattr(composer, "_wifiSampler", None) is None


# ---------------------------------------------------------------------------
# US-916 -- sync rowsWaiting / edrRowsWaiting / notCounted.
# ---------------------------------------------------------------------------


def test_sync_backlogFields_areTransportedVerbatim_zeroIsNotNull():
    state = buildSystemStatusState(
        syncLastOkTs=_SYNC_OK, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        syncRowsWaiting=0, syncEdrRowsWaiting=1771,
        syncNotCounted=["profiles", "vehicle_info"],
    )
    assert state["sync"] == {
        # MOVED PIN (US-894-c): no `rows` / `pending` (Atlas P7).
        "lastOkTs": _SYNC_OK, "stale": False,
        "rowsWaiting": 0, "edrRowsWaiting": 1771,
        "notCounted": ["profiles", "vehicle_info"],
    }


def test_emitter_forwardsTheSyncBacklog_throughTheJsonRoundTrip(tmp_path):
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=120.0, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=_SYNC_OK,
        powerSource="external", driveState="idle", driveId=None,
        syncRowsWaiting=120, syncEdrRowsWaiting=None, syncNotCounted=["profiles"],
    )

    payload = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["sync"]["lastOkTs"] == _SYNC_OK
    assert payload["sync"]["rowsWaiting"] == 120
    assert payload["sync"]["edrRowsWaiting"] is None
    assert payload["sync"]["notCounted"] == ["profiles"]


def test_orchestratorEmit_stubComposer_noDatabase_syncFieldsNull():
    """Stub hosts have no _database: lastOkTs and the backlog are not read."""
    composer = _StubComposer({}, False)
    composer._lastSyncOkTsIso = _SYNC_OK  # the retired stamp is never read

    composer._emitSystemStatusState()

    call = composer.calls[0]
    assert call["syncLastOkTs"] is None
    assert call["syncRowsWaiting"] is None
    assert call["syncEdrRowsWaiting"] is None
    assert call["syncNotCounted"] is None
    # MOVED PIN (US-894-c): the orchestrator passes no syncRows / syncPending.
    assert "syncPending" not in call and "syncRows" not in call


# ---------------------------------------------------------------------------
# US-877-a -- the `pi` health block (Atlas Y-5, P2).
# ---------------------------------------------------------------------------

_PI_BLOCK = {
    "cpuTempC": 52.6, "cpuTempTs": "2026-06-30T19:41:58Z", "cpuTempLimitC": 80.0,
    "throttled": False, "throttledHex": "0x0", "throttledSinceBoot": False,
    "throttledTs": "2026-06-30T19:41:58Z",
    "diskFreeBytes": 102005460992, "diskThresholdBytes": 21474836480,
    "diskVerdict": "healthy", "diskTs": "2026-06-30T19:35:00Z",
    "uptimeS": 3720, "uptimeTs": _NOW, "overLimit": [],
}


def _piState(piHealth):
    return buildSystemStatusState(
        syncLastOkTs=None, syncStale=False,
        powerSource="external", driveState="idle", driveId=None, nowIso=_NOW,
        piHealth=piHealth,
    )


def test_pi_blockKeys_areTheProvidersExactKeySet_noBlockTs():
    from pi.splash.system_status_emitter import PI_HEALTH_BLOCK_KEYS
    from src.pi.hardware.pi_health import PI_HEALTH_KEYS

    assert PI_HEALTH_BLOCK_KEYS == PI_HEALTH_KEYS
    assert "ts" not in PI_HEALTH_BLOCK_KEYS
    assert set(_piState(None)["pi"]) == set(PI_HEALTH_KEYS)


def test_pi_suppliedBlock_isTransportedVerbatim():
    assert _piState(dict(_PI_BLOCK))["pi"] == _PI_BLOCK


def test_pi_unwired_everyKeyNull_overLimitEmpty():
    pi = _piState(None)["pi"]
    assert pi.pop("overLimit") == []
    assert set(pi.values()) == {None}


def test_pi_partialBlock_missingKeysAreNull_neverInvented():
    pi = _piState({"cpuTempC": 81.0, "overLimit": ["cpuTemp"]})["pi"]
    assert pi["cpuTempC"] == 81.0
    assert pi["overLimit"] == ["cpuTemp"]
    assert pi["diskVerdict"] is None and pi["uptimeS"] is None


def test_emitter_forwardsPiHealth_throughTheJsonRoundTrip(tmp_path):
    """Wiring trap: emit() must take and forward piHealth, or it never ships."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=120.0, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=None,
        powerSource="external", driveState="idle", driveId=None,
        piHealth=dict(_PI_BLOCK),
    )

    payload = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["pi"] == _PI_BLOCK


def test_orchestratorEmit_stubComposer_piHealthNone_startsNoSampler():
    """Stub hosts (no _shutdownEvent): piHealth None, no sampler, no thread."""
    import threading

    composer = _StubComposer({}, False)
    threadsBefore = {t.name for t in threading.enumerate()}

    composer._emitSystemStatusState()

    assert composer.calls[0]["piHealth"] is None
    assert getattr(composer, "_piSampler", None) is None
    assert "pi-health-sampler" not in (
        {t.name for t in threading.enumerate()} - threadsBefore
    )


# ---------------------------------------------------------------------------
# US-877-b -- the verdict: every counted issue, named (Atlas Y-6, P4/P6, E3).
# ---------------------------------------------------------------------------

_GIB = 2**30
_DISK_LIMIT_BYTES = 21474836480  # LOW_DISK_THRESHOLD_BYTES: 20 GiB


def _layer(state):
    if state is None:
        return {"state": None, "ts": None, "lastOkTs": None}
    return {"state": state, "ts": _NOW, "lastOkTs": _NOW}


def _chain(bt=LINK_UP, adapter=LINK_UP, ecu=LINK_UP):
    return {"bt": _layer(bt), "adapter": _layer(adapter), "ecu": _layer(ecu)}


def _capture(topState="ok", **feedStates):
    """A capture-health payload; every feed ok unless named."""
    return {
        "state": topState, "lastRowSecondsAgo": 1.0, "stallSeconds": 60.0,
        "reason": None, "ts": _NOW,
        "feeds": {
            name: {
                "state": feedStates.get(name, "ok"),
                "firstSampleTs": _NOW, "lastSampleSecondsAgo": 1.0,
            }
            for name in ("obd", "imu", "light", "ups")
        },
    }


def _pi(**fields):
    return {**_PI_BLOCK, **fields}


def _verdict(**overrides):
    """Everything fine -- every layer up, WiFi read, feeds ok, no limit over,
    recording -- with only the named inputs changed."""
    kwargs = {
        "link": _chain(),
        "wifiSource": {"available": True, "reason": None},
        "captureHealth": _capture(),
        "piHealth": _pi(),
        "driveState": "recording",
    }
    kwargs.update(overrides)
    return buildSystemVerdict(**kwargs)


def _keys(verdict):
    return [m["key"] for m in verdict["members"]]


_REASON_TABLE = [
    # (id, machine-field inputs, the ONE member's key, its exact reason)
    ("bt-retrying-recording", {"link": _chain(bt=LINK_RETRYING, adapter=LINK_RETRYING)},
     "bt", "Link dropped. Retrying."),
    ("bt-down", {"link": _chain(bt=LINK_DOWN, adapter=LINK_DOWN), "driveState": "idle"},
     "bt", "Not linked. Check the OBD dongle."),
    ("adapter-retrying", {"link": _chain(adapter=LINK_RETRYING)},
     "adapter", "Bluetooth up; adapter not answering."),
    ("adapter-down", {"link": _chain(adapter=LINK_DOWN)},
     "adapter", "Bluetooth up; adapter not answering."),
    ("capture-obd", {"captureHealth": _capture(obd="stalled")},
     "capture", "OBD feed stalled."),
    ("capture-light-capitalised", {"captureHealth": _capture(light="stalled")},
     "capture", "Light feed stalled."),
    ("capture-two", {"captureHealth": _capture(ups="stalled", imu="stalled")},
     "capture", "IMU and UPS feeds stalled."),
    ("capture-three-obd-imu-ups",
     {"captureHealth": _capture(ups="stalled", imu="stalled", obd="stalled")},
     "capture", "OBD, IMU and UPS feeds stalled."),
    ("capture-three-light-before-imu",
     {"captureHealth": _capture(imu="stalled", light="stalled", obd="stalled")},
     "capture", "OBD, light and IMU feeds stalled."),
    ("capture-all-4",
     {"captureHealth": _capture(obd="stalled", imu="stalled", light="stalled", ups="stalled")},
     "capture", "All 4 feeds stalled."),
    ("wifi-read-failed", {"wifiSource": {"available": False, "reason": "read_failed"}},
     "wifi", "WiFi couldn't be read."),
    ("pi-cpu", {"piHealth": _pi(cpuTempC=80.2, overLimit=["cpuTemp"])},
     "pi", "CPU 80.2 °C, limit 80 °C."),
    ("pi-cpu-at-limit-prints-0.1", {"piHealth": _pi(cpuTempC=80.0, overLimit=["cpuTemp"])},
     "pi", "CPU 80.0 °C, limit 80 °C."),
    ("pi-cpu-fractional-limit",
     {"piHealth": _pi(cpuTempC=81.0, cpuTempLimitC=80.5, overLimit=["cpuTemp"])},
     "pi", "CPU 81.0 °C, limit 80.5 °C."),
    ("pi-under-voltage-bit0",
     {"piHealth": _pi(throttled=True, throttledHex="0x50005", overLimit=["throttled"])},
     "pi", "Under-voltage now. Check the 5 V supply."),
    ("pi-bit0-wins-over-bits-1-3",
     {"piHealth": _pi(throttled=True, throttledHex="0xf", overLimit=["throttled"])},
     "pi", "Under-voltage now. Check the 5 V supply."),
    ("pi-throttling-bits-1-3-only",
     {"piHealth": _pi(throttled=True, throttledHex="0x4", overLimit=["throttled"])},
     "pi", "Throttling now. CPU slowed."),
    ("pi-disk-19.9",
     {"piHealth": _pi(diskFreeBytes=int(19.95 * _GIB), diskVerdict="breached",
                      overLimit=["disk"])},
     "pi", "Disk 19.9 GiB free, limit 20 GiB."),
    ("pi-disk-floored-never-20.0",
     {"piHealth": _pi(diskFreeBytes=_DISK_LIMIT_BYTES - 1, diskVerdict="breached",
                      overLimit=["disk"])},
     "pi", "Disk 19.9 GiB free, limit 20 GiB."),
    ("pi-two-over",
     {"piHealth": _pi(cpuTempC=85.0, diskVerdict="breached", diskFreeBytes=1,
                      overLimit=["cpuTemp", "disk"])},
     "pi", "Over limit: CPU temp, disk."),
    ("pi-three-over",
     {"piHealth": _pi(cpuTempC=85.0, throttled=True, throttledHex="0x1",
                      diskVerdict="breached", diskFreeBytes=1,
                      overLimit=["cpuTemp", "throttled", "disk"])},
     "pi", "Over limit: CPU temp, throttling, disk."),
]


@pytest.mark.parametrize(
    ("inputs", "key", "reason"),
    [row[1:] for row in _REASON_TABLE],
    ids=[row[0] for row in _REASON_TABLE],
)
def test_verdict_eachMemberAlone_theExactReasonTable(inputs, key, reason):
    """Each member alone, from its machine field, with Iris's exact words."""
    assert _verdict(**inputs) == {
        "issueCount": 1, "members": [{"key": key, "reason": reason}],
    }


def test_verdict_everythingFine_isZeroIssues():
    assert _verdict() == {"issueCount": 0, "members": []}


def test_verdict_nullsNeverCount():
    """Nothing read -- every layer null, WiFi not read, no capture payload,
    pi unread -- is no issue."""
    verdict = _verdict(
        link=_chain(bt=None, adapter=None, ecu=None),
        wifiSource={"available": False, "reason": "not_read"},
        captureHealth=None,
        piHealth={"overLimit": []},
    )
    assert verdict == {"issueCount": 0, "members": []}
    assert _verdict(link=None, wifiSource=None, piHealth=None)["issueCount"] == 0


def test_verdict_connectingNeverCounts():
    """Key off at home (ARCH-061): ECU, adapter and BT connecting -- 0 issues."""
    for chain in (
        _chain(bt=LINK_CONNECTING, adapter=LINK_CONNECTING, ecu=LINK_CONNECTING),
        _chain(adapter=LINK_CONNECTING, ecu=LINK_CONNECTING),
        _chain(ecu=LINK_CONNECTING),
    ):
        assert _verdict(link=chain, driveState="idle")["members"] == [], chain


def test_verdict_wifiAbsenceNeverCounts_onlyReadFailed():
    """nmcli absent, not read, and a measured WiFi down are not issues (b-2)."""
    for source in (
        {"available": False, "reason": "nmcli_absent"},
        {"available": False, "reason": "not_read"},
        {"available": True, "reason": None},  # down / away from home: measured
    ):
        assert _verdict(wifiSource=source)["members"] == [], source


def test_verdict_captureStalled_withEcuNotUp_neverCounts():
    """Atlas P6: a parked car's idle-stalled feed is not an issue."""
    stalled = _capture(obd="stalled", imu="stalled")
    for ecu in (LINK_CONNECTING, LINK_RETRYING, LINK_DOWN, None):
        verdict = _verdict(link=_chain(ecu=ecu), captureHealth=stalled)
        assert verdict["members"] == [], ecu


def test_verdict_captureTopLevelStateIsNeverRead_noFeedsOrNoneIsNoMember():
    """The top-level never_written/stalled is never a member; a missing feeds
    block or a None payload is no member (b-3)."""
    neverWritten = _capture(topState="stalled")
    neverWritten["reason"] = "never_written"
    assert _verdict(captureHealth=neverWritten)["members"] == []
    noFeeds = _capture(obd="stalled")
    del noFeeds["feeds"]
    assert _verdict(captureHealth=noFeeds)["members"] == []
    assert _verdict(captureHealth=None)["members"] == []
    assert _verdict(captureHealth={"feeds": None})["members"] == []


def test_verdict_btRetrying_driveNotRecording_neverCounts():
    """Atlas E3: a parked car after a drive reads retrying but is NOT a member;
    bt down still counts parked (no retry authority is a real fault)."""
    retrying = _chain(bt=LINK_RETRYING, adapter=LINK_RETRYING, ecu=LINK_RETRYING)
    assert _verdict(link=retrying, driveState="idle")["members"] == []
    assert _keys(_verdict(link=retrying, driveState="recording")) == ["bt"]
    assert _keys(_verdict(link=_chain(bt=LINK_DOWN), driveState="idle")) == ["bt"]


def test_verdict_btRetrying_isEvaluatedEachCall_neverLatched():
    retrying = _chain(bt=LINK_RETRYING, adapter=LINK_RETRYING)
    assert _keys(_verdict(link=retrying, driveState="recording")) == ["bt"]
    assert _keys(_verdict(link=retrying, driveState="idle")) == []
    assert _keys(_verdict(link=retrying, driveState="recording")) == ["bt"]


def test_verdict_adapter_onlyWhileBtUp():
    """The adapter not answering is the adapter's issue only while BT is up."""
    for bt in (LINK_CONNECTING, LINK_RETRYING, LINK_DOWN, None):
        keys = _keys(_verdict(link=_chain(bt=bt, adapter=LINK_DOWN), driveState="idle"))
        assert "adapter" not in keys, bt
    assert _keys(_verdict(link=_chain(adapter=LINK_CONNECTING))) == []


def test_verdict_fixedOrder_countIsLen_andNoSyncKeyEver():
    """Every member at once, in the fixed order; issueCount == len(members);
    no sync member exists (Atlas 877-b-1) however bad sync is."""
    everything = {
        "captureHealth": _capture(obd="stalled"),
        "wifiSource": {"available": False, "reason": "read_failed"},
        "piHealth": _pi(cpuTempC=90.0, overLimit=["cpuTemp"]),
    }
    btSide = _verdict(link=_chain(bt=LINK_RETRYING), **everything)
    adapterSide = _verdict(link=_chain(adapter=LINK_RETRYING), **everything)

    assert _keys(btSide) == ["bt", "capture", "wifi", "pi"]
    assert _keys(adapterSide) == ["adapter", "capture", "wifi", "pi"]
    for verdict in (btSide, adapterSide):
        assert verdict["issueCount"] == len(verdict["members"])
        assert all(set(m) == {"key", "reason"} for m in verdict["members"])
        assert "sync" not in _keys(verdict)


def test_builder_noSyncMember_evenWithASyncThatNeverSucceeded():
    state = _verdictState(
        syncLastOkTs=None, syncStale=True, syncRowsWaiting=99999,
        syncEdrRowsWaiting=99999,
    )
    assert "sync" not in _keys(state["verdict"])


def test_verdict_memberOrderConstant_isBtAdapterCaptureWifiPi():
    from pi.splash.system_status_emitter import VERDICT_MEMBER_ORDER

    assert VERDICT_MEMBER_ORDER == ("bt", "adapter", "capture", "wifi", "pi")


def test_verdict_aMembersKeyStaysPut_whenItsReasonChangesMidEpisode():
    first = _verdict(piHealth=_pi(cpuTempC=80.2, overLimit=["cpuTemp"]))
    second = _verdict(piHealth=_pi(
        cpuTempC=80.4, diskVerdict="breached", diskFreeBytes=1,
        overLimit=["cpuTemp", "disk"],
    ))
    assert _keys(first) == _keys(second) == ["pi"]
    assert first["members"][0]["reason"] != second["members"][0]["reason"]


def test_verdict_mirroredVocabularies_matchTheirProducers():
    """The verdict reads producer tokens it cannot import (circular); pin them."""
    from pi.obdii import capture_health
    from pi.splash import system_status_emitter as sse
    from src.pi.hardware import pi_health
    from src.pi.network import wifi_reader

    assert sse._CAPTURE_STATE_STALLED == capture_health.STATE_STALLED
    assert {n for n, _w in sse._CAPTURE_FEED_WORDS} == set(capture_health.FEED_NAMES)
    assert [w for _n, w in sse._CAPTURE_FEED_WORDS] == ["OBD", "light", "IMU", "UPS"]
    assert sse._WIFI_REASON_READ_FAILED == wifi_reader.WIFI_REASON_READ_FAILED
    assert set(sse._PI_OVER_LIMIT_WORDS) == {
        pi_health.OVER_LIMIT_CPU_TEMP, pi_health.OVER_LIMIT_THROTTLED,
        pi_health.OVER_LIMIT_DISK,
    }


def test_verdict_vc1_btRetrying_everythingElseFine_isOneBtIssue():
    verdict = _verdict(link=_chain(bt=LINK_RETRYING))
    assert verdict["issueCount"] == 1
    assert _keys(verdict) == ["bt"]


def test_verdict_vc2_wifiNotRead_ecuConnecting_isZeroIssues():
    verdict = _verdict(
        link=_chain(ecu=LINK_CONNECTING),
        wifiSource={"available": False, "reason": "not_read"},
    )
    assert verdict == {"issueCount": 0, "members": []}


def _verdictState(**kw):
    base = {
        "syncLastOkTs": None, "syncStale": False,
        "powerSource": "external", "driveState": "recording", "driveId": 7,
        "nowIso": _NOW,
    }
    base.update(kw)
    return buildSystemStatusState(**base)


def test_builder_verdict_isComputedFromItsOwnPublishedBlocks():
    """The builder judges what it publishes: link, source.wifi, pi -- plus the
    capture payload handed in."""
    state = _verdictState(
        link=_chain(),
        captureHealth=_capture(ups="stalled"),
        wifiAvailable=False, wifiUnavailableReason="read_failed",
        piHealth=_pi(throttled=True, throttledHex="0x4", overLimit=["throttled"]),
    )
    assert state["verdict"] == {
        "issueCount": 3,
        "members": [
            {"key": "capture", "reason": "UPS feed stalled."},
            {"key": "wifi", "reason": "WiFi couldn't be read."},
            {"key": "pi", "reason": "Throttling now. CPU slowed."},
        ],
    }


def test_builder_captureHealthNone_verdictZero_whenNothingElseIsAnIssue():
    assert _verdictState(link=_chain(), captureHealth=None)["verdict"] == {
        "issueCount": 0, "members": [],
    }


def test_builder_wifiNotRead_withNoReason_isNotAnIssue():
    """The builder's own not_read default never counts."""
    assert _verdictState(wifiAvailable=False)["verdict"]["members"] == []


def test_emitter_forwardsCaptureHealth_theVerdictShipsInTheFile(tmp_path):
    """Wiring trap: emit() must take and forward captureHealth."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=120.0, nowIsoFn=lambda: _NOW
    )

    emit(
        syncLastOkTs=None,
        powerSource="external", driveState="recording", driveId=7,
        link=_chain(), captureHealth=_capture(obd="stalled"),
    )

    payload = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["verdict"] == {
        "issueCount": 1, "members": [{"key": "capture", "reason": "OBD feed stalled."}],
    }


def test_orchestratorEmit_forwardsTheCaptureHealthItWasHanded():
    composer = _StubComposer({}, False)
    handed = _capture(obd="stalled")

    composer._emitSystemStatusState(handed)
    composer._emitSystemStatusState()

    assert composer.calls[0]["captureHealth"] is handed
    assert composer.calls[1]["captureHealth"] is None


# ---------------------------------------------------------------------------
# US-877-c -- the emit returns what it wrote, for the alerts arbiter.
# ---------------------------------------------------------------------------


def test_emitter_returnsThePayloadItWrote(tmp_path):
    """Given a states dir, When the emit fires, Then it returns the very
    payload on disk -- the in-process hand-off to the alerts arbiter."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=60, nowIsoFn=lambda: _NOW
    )

    returned = emit(
        syncLastOkTs=None,
        powerSource="external", driveState="idle", driveId=None,
        piHealth={"overLimit": ["cpuTemp"], "cpuTempC": 85.0, "cpuTempLimitC": 80},
    )

    written = json.loads(
        (tmp_path / "states" / SYSTEM_STATUS_FILENAME).read_text(encoding="utf-8")
    )
    assert returned == written
    assert {"key": "pi", "reason": "CPU 85.0 °C, limit 80 °C."} in returned["verdict"]["members"]


def test_emitter_returnsNone_whenTheWriteFailed(tmp_path):
    blocker = tmp_path / "states"
    blocker.write_text("a file where the states dir should be", encoding="utf-8")
    emit = makeSystemStatusEmitter(str(blocker), syncStaleThresholdS=60, nowIsoFn=lambda: _NOW)

    returned = emit(
        syncLastOkTs=None,
        powerSource="external", driveState="idle", driveId=None,
    )

    assert returned is None
