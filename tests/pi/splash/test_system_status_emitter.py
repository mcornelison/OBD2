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
# 2026-10-27    | Rex (US-917-a)| MOVED PIN: the two exact sync pins gain
#               |              | inProgress; sync.inProgress follows the lock.
# 2026-10-27    | Rex (US-917-b)| MOVED PIN: the two exact sync pins gain
#               |              | priorCustody + syncedThisBoot; the relay tests.
# 2026-10-27    | Rex (US-917-c)| MOVED PIN: VERDICT_MEMBER_ORDER ends in sync;
#               |              | the sync member's S1-S3 cases (A1-A6).
# ================================================================================
################################################################################

"""Tests for ``pi.splash.system_status_emitter``."""

import json
import os
from datetime import timedelta, timezone

import pytest

from pi.diagnostics import boot_progress
from pi.diagnostics.prior_shutdown_summary import (
    VERDICT_CLEAN,
    VERDICT_NO_RECORD,
    VERDICT_UNGRACEFUL,
)
from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin
from pi.power.power_watch.contract import OutcomeKind
from pi.power.power_watch.sync_custody import CUSTODY_RECORD_FILENAME
from pi.splash.system_status_emitter import (
    LINK_CONNECTING,
    LINK_DOWN,
    LINK_RETRYING,
    LINK_UP,
    OBD_LINKED,
    PRIOR_CUSTODY_AWAY_KINDS,
    PRIOR_CUSTODY_VERDICTS,
    RUN_MODE_LIVE,
    RUN_MODE_REPLAY,
    RUN_MODE_SIMULATE,
    SYSTEM_STATUS_FILENAME,
    VERDICT_SYNC,
    LinkLayerTracker,
    buildSystemStatusState,
    buildSystemVerdict,
    deriveLinkLayerState,
    deriveRunMode,
    isSyncStaleWhileDriving,
    makeSystemStatusEmitter,
)
from pi.sync import push_lock
from pi.sync.backlog import BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, BACKLOG_UNKNOWN

_NOW ="2026-06-30T19:42:00Z"
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
            # MOVED PIN (US-917-a): inProgress is always a key (false unprobed).
            "inProgress": False,
            # MOVED PIN (US-917-b): priorCustody (null = not read) and
            # syncedThisBoot (false unread) are always keys.
            "priorCustody": None, "syncedThisBoot": False,
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
        # MOVED PIN (US-917-a): inProgress is always a key (false unprobed).
        "inProgress": False,
        # MOVED PIN (US-917-b): always keys.
        "priorCustody": None, "syncedThisBoot": False,
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


def _faultedCapture(faults, topState="ok", **feedStates):
    """A capture-health payload whose named feeds are faulted with a reason."""
    payload = _capture(topState, **feedStates)
    for name, reason in faults.items():
        payload["feeds"][name]["state"] = "faulted"
        payload["feeds"][name]["reason"] = reason
    return payload


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
    no sync member without a sync input (US-917-c: the S1-S3 tests below)."""
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
        # MOVED PIN (US-869-c): a sensor member also carries `feeds`.
        assert all(
            set(m) == ({"key", "reason", "feeds"} if m["key"] == "sensor" else {"key", "reason"})
            for m in verdict["members"]
        )
        assert "sync" not in _keys(verdict)

    withSensor = _verdict(
        link=_chain(bt=LINK_RETRYING),
        captureHealth=_faultedCapture({"imu": "sensor_absent"}, obd="stalled"),
        wifiSource=everything["wifiSource"], piHealth=everything["piHealth"],
    )
    assert _keys(withSensor) == ["bt", "capture", "sensor", "wifi", "pi"]
    assert set(withSensor["members"][2]) == {"key", "reason", "feeds"}


def test_builder_noSyncMember_evenWithASyncThatNeverSucceeded():
    state = _verdictState(
        syncLastOkTs=None, syncStale=True, syncRowsWaiting=99999,
        syncEdrRowsWaiting=99999,
    )
    assert "sync" not in _keys(state["verdict"])


def test_verdict_memberOrderConstant_isBtAdapterCaptureSensorWifiPiSync():
    from pi.splash.system_status_emitter import (
        VERDICT_MEMBER_ORDER,
        VERDICT_SENSOR,
        VERDICT_SYNC,
    )

    # MOVED PIN (US-869-c): `sensor` sits after `capture` (Atlas R2).
    assert VERDICT_SENSOR == "sensor"
    # MOVED PIN (US-917-c): `sync` is appended last.
    assert VERDICT_SYNC == "sync"
    assert VERDICT_MEMBER_ORDER == (
        "bt", "adapter", "capture", "sensor", "wifi", "pi", "sync",
    )


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
    # US-869-c (Atlas R1): the fault state and the two feed fault tokens.
    assert sse._CAPTURE_STATE_FAULTED == capture_health.STATE_FAULTED
    assert sse._FEED_REASON_SENSOR_ABSENT == capture_health.FEED_REASON_SENSOR_ABSENT
    assert sse._FEED_REASON_READ_FAILED == capture_health.FEED_REASON_READ_FAILED
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


# ---------------------------------------------------------------------------
# US-869-c -- a faulted feed is ONE `sensor` member (Atlas R1-R8, C-Atlas-1).
# ---------------------------------------------------------------------------


def _sensorMembers(verdict):
    return [m for m in verdict["members"] if m["key"] == "sensor"]


@pytest.mark.parametrize(
    ("faults", "feeds", "reason"),
    [
        ({"imu": "sensor_absent"}, ["imu"], "IMU sensor not found."),
        ({"light": "sensor_absent"}, ["light"], "Light sensor not found."),
        ({"ups": "sensor_absent"}, ["ups"], "UPS gauge not found."),
        ({"ups": "read_failed"}, ["ups"], "UPS gauge read failed."),
        ({"imu": "sensor_absent", "ups": "read_failed"}, ["imu", "ups"],
         "IMU sensor not found. UPS gauge read failed."),
        ({"ups": "sensor_absent", "imu": "sensor_absent"}, ["imu", "ups"],
         "IMU sensor not found. UPS gauge not found."),
        ({"ups": "read_failed", "imu": "sensor_absent", "light": "sensor_absent"},
         ["light", "imu", "ups"],
         "Light sensor not found. IMU sensor not found. UPS gauge read failed."),
        # Unknown or absent reasons: the generic fault word (Iris).
        ({"light": "something_else"}, ["light"], "Light sensor fault."),
        ({"imu": None}, ["imu"], "IMU sensor fault."),
        ({"ups": "bogus"}, ["ups"], "UPS gauge fault."),
        # C-Atlas-1 dropped the IMU/LIGHT read-failed words.
        ({"imu": "read_failed"}, ["imu"], "IMU sensor fault."),
        ({"light": "read_failed"}, ["light"], "Light sensor fault."),
    ],
)
def test_verdict_sensorMember_oneMemberNamesEveryFaultedFeed(faults, feeds, reason):
    verdict = _verdict(captureHealth=_faultedCapture(faults))

    assert verdict["members"] == [{"key": "sensor", "reason": reason, "feeds": feeds}]
    assert verdict["issueCount"] == 1


def test_verdict_sensorMember_isUngated_ecuDown_captureAbsent():
    """Atlas R3: the sensor member is evaluated on every call; capture stays gated."""
    payload = _faultedCapture({"imu": "sensor_absent"}, obd="stalled")
    for ecu in (LINK_DOWN, LINK_CONNECTING, LINK_RETRYING, None):
        verdict = _verdict(link=_chain(ecu=ecu), captureHealth=payload, driveState="idle")
        assert "capture" not in _keys(verdict), ecu
        assert _sensorMembers(verdict) == [
            {"key": "sensor", "reason": "IMU sensor not found.", "feeds": ["imu"]}
        ], ecu


def test_verdict_sensorMember_negatives():
    """All ok: byte-identical to today. A stalled feed is capture only. An obd
    fault is never a sensor feed."""
    assert _verdict() == {"issueCount": 0, "members": []}
    stalled = _verdict(captureHealth=_capture(imu="stalled"))
    assert _keys(stalled) == ["capture"]
    assert _verdict(captureHealth=_faultedCapture({"obd": "sensor_absent"}))["members"] == []
    assert _verdict(captureHealth=None)["members"] == []
    noFeeds = _faultedCapture({"imu": "sensor_absent"})
    del noFeeds["feeds"]
    assert _verdict(captureHealth=noFeeds)["members"] == []


def test_verdict_stalledAndFaulted_areTwoMembers_eachNamingItsOwnFeeds():
    verdict = _verdict(captureHealth=_faultedCapture({"imu": "sensor_absent"}, light="stalled"))
    assert verdict["members"] == [
        {"key": "capture", "reason": "Light feed stalled."},
        {"key": "sensor", "reason": "IMU sensor not found.", "feeds": ["imu"]},
    ]


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


# ---------------------------------------------------------------------------
# US-917-a -- sync.inProgress: a pusher named in sync-activity AND the push
# lock (US-871-a) actually held. A crashed holder frees the lock, so it can
# never leave the glyph blue.
# ---------------------------------------------------------------------------


def _lockPaths(tmp_path):
    return str(tmp_path / "run" / "sync.lock"), str(tmp_path / "states")


def _emitInProgress(statesDir: str, lockPath: str) -> bool:
    emit = makeSystemStatusEmitter(
        statesDir, syncStaleThresholdS=60, nowIsoFn=lambda: _NOW, syncLockPath=lockPath
    )
    payload = emit(syncLastOkTs=None, powerSource="external", driveState="idle", driveId=None)
    assert payload is not None
    return payload["sync"]["inProgress"]


def test_system_status_sync_in_progress_follows_the_lock(tmp_path):
    """Given a live holder (sync-activity names it, the flock is held),
    When system-status is emitted, Then sync.inProgress is true -- and false
    again once the holder releases."""
    lockPath, statesDir = _lockPaths(tmp_path)

    with push_lock.holdPushLock(
        push_lock.DRAIN_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ):
        held = _emitInProgress(statesDir, lockPath)
    released = _emitInProgress(statesDir, lockPath)

    assert held is True
    assert released is False


def test_syncInProgress_isFalse_whenActivityNamesAPusherButTheLockIsFree(tmp_path):
    """A crashed holder: sync-activity still names it, the kernel freed the lock."""
    lockPath, statesDir = _lockPaths(tmp_path)
    os.makedirs(statesDir)
    with open(os.path.join(statesDir, push_lock.SYNC_ACTIVITY_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"pusher": push_lock.DRAIN_PUSHER, "pid": 99999,
                   "startedTs": _NOW, "ts": _NOW}, f)
    os.makedirs(os.path.dirname(lockPath))
    open(lockPath, "w").close()

    assert _emitInProgress(statesDir, lockPath) is False


def test_syncInProgress_isFalse_withNoActivityFile_evenWithTheLockHeld(tmp_path):
    lockPath, statesDir = _lockPaths(tmp_path)
    os.makedirs(os.path.dirname(lockPath))
    fd = os.open(lockPath, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert push_lock._tryLock(fd)
        assert _emitInProgress(statesDir, lockPath) is False
    finally:
        push_lock._unlock(fd)
        os.close(fd)


def test_syncInProgress_isFalse_withNoLockFile(tmp_path):
    """An absent lock file is free; the probe never creates it (or its dir)."""
    lockPath, statesDir = _lockPaths(tmp_path)

    assert push_lock.isPushLockHeld(lockPath) is False
    assert not os.path.exists(os.path.dirname(lockPath))
    assert _emitInProgress(statesDir, lockPath) is False


def test_syncInProgress_isPublishedFalse_byDefault():
    """Always a key: a caller that probed nothing publishes false, never absent."""
    state = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
    )
    assert state["sync"]["inProgress"] is False


def test_isPushLockHeld_neverBlocks_andLeavesTheHolderHoldingIt(tmp_path):
    """Given a held lock, the probe answers at once and does not take it over."""
    import time

    lockPath, statesDir = _lockPaths(tmp_path)
    with push_lock.holdPushLock(
        push_lock.INTERVAL_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ):
        started = time.monotonic()
        held = push_lock.isPushLockHeld(lockPath)
        elapsed = time.monotonic() - started
        # Still held after the probe: a non-waiting pusher is still refused.
        with pytest.raises(push_lock.PushLockHeld):
            with push_lock.holdPushLock(
                push_lock.DRIVE_END_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
            ):
                pass

    assert held is True
    assert elapsed < 1.0
    # Free again: the probe on a free lock took and dropped it, leaving it free.
    assert push_lock.isPushLockHeld(lockPath) is False
    assert push_lock.isPushLockHeld(lockPath) is False


# ---------------------------------------------------------------------------
# US-917-b -- sync.priorCustody relays the last key-off's custody record
# (powerwatch writes it; the emitter only reads it once, at start), and
# sync.syncedThisBoot follows states/sync-activity's lastDeliveredTs.
# ---------------------------------------------------------------------------

_PRIOR_BOOT_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_OLDER_BOOT_ID = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_THIS_BOOT_ID = "cccccccccccccccccccccccccccccccc"
_CUSTODY_TS = "2026-10-26T22:10:00Z"
_PRIOR_IDS_FILENAME = os.path.basename(boot_progress.DEFAULT_PRIOR_FILE_PATH)


def _writeJson(path, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _keyOffRecords(
    dataDir: str,
    *,
    outcomeBootId: str = _PRIOR_BOOT_ID,
    kind: str = OutcomeKind.AT_HOME_SERVER_DOWN.value,
    priorIds: list[str] | None = None,
    priorWriter: str = _THIS_BOOT_ID,
) -> None:
    """Lay down what powerwatch and boot_progress.arm() leave in data/."""
    _writeJson(os.path.join(dataDir, CUSTODY_RECORD_FILENAME), {
        "schema": 2, "verdict": BACKLOG_OUTSTANDING, "outstandingRows": 240,
        "countIsComplete": True, "perTable": {"realtime_data": 240},
        "unreadableTables": [], "error": None, "edrOutstandingRows": None,
        "ownDrainCloseExcluded": None, "ownTrajectoryExcluded": None,
        "ts": _CUSTODY_TS,
    })
    _writeJson(os.path.join(dataDir, boot_progress.OUTCOME_RECORD_FILENAME), {
        "schema": 1, "kind": kind, "detail": "", "task": "sync",
        "ts": _CUSTODY_TS, "boot_id": outcomeBootId,
    })
    _writeJson(os.path.join(dataDir, _PRIOR_IDS_FILENAME), {
        "schema": 1, "boot_id": priorWriter,
        "prior_boot_ids": [_PRIOR_BOOT_ID] if priorIds is None else priorIds,
        "written_at": "2026-10-27T07:00:00Z",
    })


def _custodyEmitter(tmp_path, dataDir: str, statesDir: str | None = None):
    return makeSystemStatusEmitter(
        statesDir or str(tmp_path / "states"), syncStaleThresholdS=60,
        nowIsoFn=lambda: _NOW, syncLockPath=str(tmp_path / "run" / "sync.lock"),
        dataDir=dataDir, bootIdFn=lambda: _THIS_BOOT_ID,
    )


def _sync(emit) -> dict:
    payload = emit(syncLastOkTs=None, powerSource="external", driveState="idle", driveId=None)
    assert payload is not None
    return payload["sync"]


def test_system_status_relays_prior_custody(tmp_path):
    """Given the key-off at home with the server down left custody OUTSTANDING
    240 (complete) and an outcome stamped by the prior boot,
    When system-status is emitted, Then sync.priorCustody relays those values
    with current true."""
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir)

    sync = _sync(_custodyEmitter(tmp_path, dataDir))

    assert sync["priorCustody"] == {
        "verdict": BACKLOG_OUTSTANDING,
        "outstandingRows": 240,
        "countIsComplete": True,
        "kind": "at_home_server_down",
        "ts": _CUSTODY_TS,
        "current": True,
    }


def test_priorCustody_outcomeFromAnOlderBoot_isCurrentFalse(tmp_path):
    """A valid prior-id set with no match is positive proof of an OLDER record."""
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir, outcomeBootId=_OLDER_BOOT_ID)

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"]["current"] is False


@pytest.mark.parametrize("missing", [
    CUSTODY_RECORD_FILENAME,
    boot_progress.OUTCOME_RECORD_FILENAME,
    _PRIOR_IDS_FILENAME,
])
def test_priorCustody_anyFileMissing_isNull(tmp_path, missing):
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir)
    os.remove(os.path.join(dataDir, missing))

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"] is None


def test_priorCustody_noDataDirAtAll_isNull_andTheEmitStillWrites(tmp_path):
    assert _sync(_custodyEmitter(tmp_path, str(tmp_path / "absent")))["priorCustody"] is None


def test_priorCustody_noRecords_neverAsksForTheBootId(tmp_path):
    """Off-Linux readBootId logs an ERROR; with nothing to match, do not ask."""
    asked: list[bool] = []

    def bootId() -> str:
        asked.append(True)
        return _THIS_BOOT_ID

    makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=60,
        dataDir=str(tmp_path / "absent"), bootIdFn=bootId,
    )

    assert asked == []


@pytest.mark.parametrize("record", ["{torn", "[1, 2]"])
def test_priorCustody_unreadableCustodyRecord_isNull(tmp_path, record):
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir)
    with open(os.path.join(dataDir, CUSTODY_RECORD_FILENAME), "w", encoding="utf-8") as f:
        f.write(record)

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"] is None


def test_priorCustody_priorIdsFileFromAnotherBoot_isNull_neverCurrentFalse(tmp_path):
    """A stale prior-ids file (an older boot's, its next arm failed) proves nothing."""
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir, priorWriter=_OLDER_BOOT_ID)

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"] is None


def test_priorCustody_emptyPriorIdSet_isNull(tmp_path):
    """First boot / trail lost: no set is no proof."""
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir, priorIds=[])

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"] is None


def test_priorCustody_isReadOnceAtEmitterStart(tmp_path):
    """A relay of the boot-time record: a later file change does not move it."""
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir)
    emit = _custodyEmitter(tmp_path, dataDir)
    os.remove(os.path.join(dataDir, CUSTODY_RECORD_FILENAME))

    assert _sync(emit)["priorCustody"]["outstandingRows"] == 240


def test_priorCustody_malformedFields_landNull_notCoerced(tmp_path):
    dataDir = str(tmp_path / "data")
    _keyOffRecords(dataDir)
    _writeJson(os.path.join(dataDir, CUSTODY_RECORD_FILENAME), {
        "verdict": "MAYBE", "outstandingRows": -1, "countIsComplete": "yes", "ts": 5,
    })

    assert _sync(_custodyEmitter(tmp_path, dataDir))["priorCustody"] == {
        "verdict": None, "outstandingRows": None, "countIsComplete": None,
        "kind": "at_home_server_down", "ts": None, "current": True,
    }


def test_priorCustody_verdictVocabulary_isTheBacklogsOwn():
    assert PRIOR_CUSTODY_VERDICTS == frozenset(
        {BACKLOG_DELIVERED, BACKLOG_OUTSTANDING, BACKLOG_UNKNOWN}
    )


def test_priorCustody_awayKinds_areTheContractsOwn():
    """Exposed for US-917-c; imported from contract.py, never copied."""
    assert PRIOR_CUSTODY_AWAY_KINDS == frozenset(
        {OutcomeKind.AWAY.value, OutcomeKind.SERVER_UNAVAILABLE.value}
    )


def test_priorCustody_andSyncedThisBoot_areAlwaysKeys_byDefault():
    state = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
    )
    assert state["sync"]["priorCustody"] is None
    assert state["sync"]["syncedThisBoot"] is False


def test_syncedThisBoot_falseUntilTheFirstDelivery_trueAfter_falseAfterAReboot(tmp_path):
    """
    Given: a fresh boot (empty tmpfs states/)
    When:  a push holds the lock and delivers rows, then releases
    Then:  syncedThisBoot is false before it, true after it -- and false again
           on the next boot, whose tmpfs is fresh. No clock is compared.
    """
    lockPath = str(tmp_path / "run" / "sync.lock")
    statesDir = str(tmp_path / "boot1" / "states")
    dataDir = str(tmp_path / "data")
    emit = _custodyEmitter(tmp_path, dataDir, statesDir)

    before = _sync(emit)["syncedThisBoot"]
    with push_lock.holdPushLock(
        push_lock.INTERVAL_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ) as session:
        duringFirst = _sync(emit)["syncedThisBoot"]
        session.rowsDelivered = 12
    after = _sync(emit)["syncedThisBoot"]
    # A later push in flight: its acquire record carries no lastDeliveredTs,
    # yet this boot HAS delivered -- the published fact must not flicker.
    with push_lock.holdPushLock(
        push_lock.INTERVAL_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ):
        duringSecond = _sync(emit)["syncedThisBoot"]
    rebooted = _custodyEmitter(tmp_path, dataDir, str(tmp_path / "boot2" / "states"))

    assert (before, duringFirst, after, duringSecond) == (False, False, True, True)
    assert _sync(rebooted)["syncedThisBoot"] is False


def test_syncedThisBoot_aPushThatDeliveredNothing_staysFalse(tmp_path):
    lockPath = str(tmp_path / "run" / "sync.lock")
    statesDir = str(tmp_path / "states")
    with push_lock.holdPushLock(
        push_lock.INTERVAL_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ):
        pass

    assert _sync(_custodyEmitter(tmp_path, str(tmp_path / "data"), statesDir))[
        "syncedThisBoot"] is False


# --------------------------------------------------------------------------
# US-917-c: the `sync` verdict member, cases S1-S3 (specs/v030-system-page-
# design.md s4.3.1). A fixed -05:00 zone stands in for the Pi's local time, so
# a UTC day boundary and the local one differ in these fixtures.
# --------------------------------------------------------------------------

_LOCAL = timezone(timedelta(hours=-5))
_THRESHOLD_S = 120.0
# lastOkTs 9:14:00 PM local on Oct 26 == 02:14:00Z on Oct 27.
_S3_LAST_OK = "2026-10-27T02:14:00Z"
_S3_NOW_121 = "2026-10-27T02:16:01Z"  # 121 s later, the same local day
_S3_NOW_60 = "2026-10-27T02:15:00Z"   # 60 s later


def _priorShutdown(verdict: str) -> dict:
    return {"verdict": verdict, "reason": None, "lastStage": None, "label": "x"}


def _custody(**overrides) -> dict:
    """The S1 block: the last key-off at home, server down, 240 rows kept."""
    block = {
        "verdict": BACKLOG_OUTSTANDING, "outstandingRows": 240, "countIsComplete": True,
        "kind": OutcomeKind.AT_HOME_SERVER_DOWN.value, "ts": "2026-10-26T23:00:00Z",
        "current": True,
    }
    block.update(overrides)
    return block


def _syncState(**overrides) -> dict:
    """Parked at home, everything synced and fresh: no member -- only the
    named inputs changed."""
    kwargs = {
        "syncLastOkTs": _S3_LAST_OK, "syncStale": False, "powerSource": "external",
        "driveState": "idle", "driveId": None, "nowIso": _S3_NOW_60,
        "link": _chain(), "captureHealth": _capture(), "piHealth": _pi(),
        "wifiAvailable": True, "wifiSsid": "HomeNet", "wifiRssiDbm": -50,
        "wifiHome": True, "wifiTs": _S3_NOW_60,
        "syncRowsWaiting": 0, "syncEdrRowsWaiting": 0, "syncNotCounted": [],
        "priorShutdown": _priorShutdown(VERDICT_CLEAN),
        "syncStaleThresholdS": _THRESHOLD_S, "localZone": _LOCAL,
    }
    kwargs.update(overrides)
    return buildSystemStatusState(**kwargs)


def _syncMembers(state: dict) -> list[dict]:
    return [m for m in state["verdict"]["members"] if m["key"] == VERDICT_SYNC]


def _syncReason(state: dict) -> str | None:
    members = _syncMembers(state)
    assert len(members) <= 1
    return members[0]["reason"] if members else None


_S1_STATE = {"syncPriorCustody": _custody()}
_S2_STATE = {
    "priorShutdown": _priorShutdown(VERDICT_UNGRACEFUL), "syncRowsWaiting": 240,
    "syncPriorCustody": _custody(verdict=BACKLOG_DELIVERED),
}
_S3_STATE = {"syncRowsWaiting": 300, "nowIso": _S3_NOW_121}


def test_syncMember_everythingFine_noMember():
    state = _syncState()
    assert _syncMembers(state) == []
    assert state["verdict"]["issueCount"] == 0


def test_syncMember_a1_s1_lastKeyOffDidNotFinish_countsOne():
    state = _syncState(**_S1_STATE)

    assert state["verdict"] == {
        "issueCount": 1,
        "members": [{"key": "sync", "reason": "Last sync didn't finish · 240 rows kept"}],
    }


def test_syncMember_s1_countIsCommaGrouped():
    state = _syncState(syncPriorCustody=_custody(outstandingRows=1240))
    assert _syncReason(state) == "Last sync didn't finish · 1,240 rows kept"


def test_syncMember_s1_countIncomplete_rowCountUnknown():
    for custody in (_custody(countIsComplete=False), _custody(outstandingRows=None)):
        state = _syncState(syncPriorCustody=custody)
        assert _syncReason(state) == "Last sync didn't finish · row count unknown", custody


def test_syncMember_s1_unknownVerdict_isAlsoNotFinished():
    state = _syncState(syncPriorCustody=_custody(verdict=BACKLOG_UNKNOWN, countIsComplete=False))
    assert _syncReason(state) == "Last sync didn't finish · row count unknown"


@pytest.mark.parametrize("custody", [
    pytest.param(_custody(verdict=BACKLOG_DELIVERED), id="delivered"),
    pytest.param(_custody(verdict=None), id="verdict-not-read"),
    pytest.param(_custody(kind=OutcomeKind.AWAY.value), id="away-skip"),
    pytest.param(_custody(kind=OutcomeKind.SERVER_UNAVAILABLE.value), id="legacy-away-skip"),
    pytest.param(_custody(current=False), id="an-older-boots-record"),
    pytest.param(None, id="no-custody-on-record"),
])
def test_syncMember_s1_negatives_noMember(custody):
    assert _syncMembers(_syncState(syncPriorCustody=custody)) == []


@pytest.mark.parametrize("prior", [
    pytest.param(_priorShutdown(VERDICT_NO_RECORD), id="no-record"),
    pytest.param(None, id="prior-shutdown-not-read"),
])
def test_syncMember_s1_needsACleanPriorShutdown(prior):
    assert _syncMembers(_syncState(priorShutdown=prior, **_S1_STATE)) == []


def test_syncMember_a2_s2_cutOff_custodyVerdictNotUsed():
    """The custody record says DELIVERED -- from an OLDER shutdown -- and is
    not used: the cut-off stop's words, with the live rows waiting."""
    state = _syncState(**_S2_STATE)

    assert state["verdict"]["members"] == [{
        "key": "sync",
        "reason": "Last stop was cut off · sync result unknown · 240 rows waiting",
    }]
    assert state["verdict"]["issueCount"] == 1


def test_syncMember_s2_rowsNotRead_andCommaGrouped():
    notRead = _syncState(**{**_S2_STATE, "syncRowsWaiting": None})
    many = _syncState(**{**_S2_STATE, "syncRowsWaiting": 12345})

    assert _syncReason(notRead) == "Last stop was cut off · sync result unknown · rows not read"
    assert _syncReason(many) == (
        "Last stop was cut off · sync result unknown · 12,345 rows waiting"
    )


def test_syncMember_s2_nothingWaiting_noMember_evenWithAnOutstandingCustody():
    state = _syncState(**{
        **_S2_STATE, "syncRowsWaiting": 0, "syncPriorCustody": _custody(),
    })
    assert _syncMembers(state) == []


def test_sync_member_s3_at_home_not_getting_through():
    """Exit test (A3): parked at home, 300 rows, last sent 121 s ago -> S3;
    60 s ago -> no member."""
    stuck = _syncState(**_S3_STATE)
    fresh = _syncState(syncRowsWaiting=300, nowIso=_S3_NOW_60)

    assert stuck["verdict"] == {
        "issueCount": 1,
        "members": [{
            "key": "sync",
            "reason": "Not syncing at home · 300 rows waiting · last sent 9:14 PM",
        }],
    }
    assert _syncMembers(fresh) == []


def test_syncMember_s3_exactlyTheThreshold_isNotOlder():
    state = _syncState(syncRowsWaiting=300, nowIso="2026-10-27T02:16:00Z")
    assert _syncMembers(state) == []


@pytest.mark.parametrize(("lastOkTs", "nowIso", "lastSent"), [
    pytest.param("2026-10-27T02:14:00Z", "2026-10-27T13:00:00Z", "yesterday",
                 id="a3b-yesterday-local-same-utc-day"),
    pytest.param("2026-10-12T19:40:00Z", "2026-10-27T13:00:00Z", "Oct 12", id="older"),
    pytest.param("2026-10-02T19:40:00Z", "2026-10-27T13:00:00Z", "Oct 02", id="older-padded"),
    pytest.param("2026-10-27T05:05:00Z", "2026-10-27T13:00:00Z", "12:05 AM", id="after-midnight"),
    pytest.param("2026-10-27T17:00:00Z", "2026-10-27T17:30:00Z", "12:00 PM", id="noon"),
    pytest.param(None, "2026-10-27T13:00:00Z", "never", id="never"),
])
def test_syncMember_s3_lastSent_followsTheDataRowDateRule(lastOkTs, nowIso, lastSent):
    state = _syncState(syncLastOkTs=lastOkTs, nowIso=nowIso, syncRowsWaiting=300)
    assert _syncReason(state) == f"Not syncing at home · 300 rows waiting · last sent {lastSent}"


def test_syncMember_s3_rowsCommaGrouped():
    state = _syncState(**{**_S3_STATE, "syncRowsWaiting": 91234})
    assert _syncReason(state) == (
        "Not syncing at home · 91,234 rows waiting · last sent 9:14 PM"
    )


def test_syncMember_a4_recording_neverACase():
    """Driving is never a case -- away or at home, however old the sync."""
    thirtyMin = "2026-10-27T02:44:00Z"
    away = _syncState(
        driveState="recording", driveId=7, wifiHome=False, syncRowsWaiting=300,
        nowIso=thirtyMin, syncStale=True,
    )
    home = _syncState(
        driveState="recording", driveId=7, syncRowsWaiting=300, nowIso=thirtyMin,
        syncStale=True,
    )
    assert _syncMembers(away) == []
    assert _syncMembers(home) == []
    # The stale flag is left as the caller judged it, not a member input.
    assert away["sync"]["stale"] is True


@pytest.mark.parametrize(("wifi", "rows"), [
    pytest.param({"wifiHome": False}, 900, id="a5-parked-away"),
    pytest.param({"wifiHome": None}, 900, id="home-not-read"),
    pytest.param({"wifiAvailable": False}, 900, id="wifi-not-read"),
    pytest.param({}, 0, id="nothing-waiting"),
    pytest.param({}, None, id="rows-not-read"),
])
def test_syncMember_s3_negatives(wifi, rows):
    state = _syncState(**{**_S3_STATE, **wifi, "syncRowsWaiting": rows})
    assert _syncMembers(state) == []


def test_syncMember_s3_noThresholdSupplied_isNotJudged():
    state = _syncState(**{**_S3_STATE, "syncStaleThresholdS": None})
    assert _syncMembers(state) == []


def test_syncMember_a6_s1AndS2_clearOnSyncedThisBoot():
    assert _syncMembers(_syncState(**_S1_STATE, syncedThisBoot=True)) == []
    assert _syncMembers(_syncState(**_S2_STATE, syncedThisBoot=True)) == []


def test_syncMember_a6_s3_clearsOnAFreshLastOkTs():
    stuck = _syncState(**_S3_STATE)
    delivered = _syncState(**{**_S3_STATE, "syncLastOkTs": "2026-10-27T02:16:00Z"})

    assert _syncMembers(stuck) != []
    assert _syncMembers(delivered) == []


def test_syncMember_s3_stillShows_afterS1ClearedOnADelivery_ifStuckAgain():
    """syncedThisBoot clears S1/S2 only; S3 is judged on its own facts."""
    state = _syncState(**_S1_STATE, **_S3_STATE, syncedThisBoot=True)
    assert _syncReason(state) == "Not syncing at home · 300 rows waiting · last sent 9:14 PM"


def test_syncMember_oneMember_s1WinsOverS3():
    state = _syncState(**_S1_STATE, **_S3_STATE)

    assert [m["key"] for m in state["verdict"]["members"]] == ["sync"]
    assert _syncReason(state) == "Last sync didn't finish · 240 rows kept"


def test_syncMember_sitsLast_afterEveryOtherMember():
    state = _syncState(
        **_S1_STATE,
        wifiAvailable=False, wifiUnavailableReason="read_failed",
        piHealth=_pi(cpuTempC=90.0, overLimit=["cpuTemp"]),
    )
    assert [m["key"] for m in state["verdict"]["members"]] == ["wifi", "pi", "sync"]
    assert state["verdict"]["issueCount"] == 3


def test_syncMember_edrRowsNeverCount():
    state = _syncState(**{**_S3_STATE, "syncRowsWaiting": 0, "syncEdrRowsWaiting": 5000})
    assert _syncMembers(state) == []


def test_syncMember_awayKindsAreThePublishedSet():
    for kind in PRIOR_CUSTODY_AWAY_KINDS:
        assert _syncMembers(_syncState(syncPriorCustody=_custody(kind=kind))) == []


def test_emitter_forwardsTheThresholdAndZone_s3ShipsInTheFile(tmp_path):
    """Wiring trap: the emitter's own threshold reaches the member."""
    emit = makeSystemStatusEmitter(
        str(tmp_path / "states"), syncStaleThresholdS=_THRESHOLD_S,
        nowIsoFn=lambda: _S3_NOW_121, syncLockPath=str(tmp_path / "run" / "sync.lock"),
        dataDir=str(tmp_path / "data"), bootIdFn=lambda: "boot", localZone=_LOCAL,
    )

    payload = emit(
        syncLastOkTs=_S3_LAST_OK, powerSource="external", driveState="idle", driveId=None,
        wifiAvailable=True, wifiSsid="HomeNet", wifiRssiDbm=-50, wifiHome=True,
        syncRowsWaiting=300,
    )

    assert payload is not None
    assert _syncReason(payload) == (
        "Not syncing at home · 300 rows waiting · last sent 9:14 PM"
    )
    with open(tmp_path / "states" / SYSTEM_STATUS_FILENAME, encoding="utf-8") as fh:
        assert json.load(fh)["verdict"] == payload["verdict"]


def test_emitter_s1_fromTheRecordsOnDisk_clearsAfterTheFirstDelivery(tmp_path):
    """The key-off left OUTSTANDING 240 (prior boot) after a clean prior
    shutdown -> S1; a delivery this boot clears it."""
    dataDir = str(tmp_path / "data")
    statesDir = str(tmp_path / "states")
    lockPath = str(tmp_path / "run" / "sync.lock")
    _keyOffRecords(dataDir)
    emit = _custodyEmitter(tmp_path, dataDir, statesDir)

    def reason():
        payload = emit(
            syncLastOkTs=None, powerSource="external", driveState="idle", driveId=None,
            priorShutdown=_priorShutdown(VERDICT_CLEAN),
        )
        assert payload is not None
        return _syncReason(payload)

    before = reason()
    with push_lock.holdPushLock(
        push_lock.INTERVAL_PUSHER, wait=False, lockPath=lockPath, statesDir=statesDir
    ) as session:
        session.rowsDelivered = 240
    after = reason()

    assert before == "Last sync didn't finish · 240 rows kept"
    assert after is None
