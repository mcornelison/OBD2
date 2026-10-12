################################################################################
# File Name: test_carousel_last_drive_cause.py
# Purpose/Description: US-698 -- the MEASUREMENT that settles which of two
#   causes made the startup card's LAST DRIVE tile read "unavailable", made
#   repeatable so the answer cannot rot.
#
#   The story names two candidates needing OPPOSITE repairs:
#     A -- the system-status payload had not ARRIVED yet (the CIO's photo was
#          taken seconds after a reboot).
#     B -- the producer is not populating `drive.lastDrive`.
#
#   B IS FALSIFIED BY A READING OF THE CIO'S OWN PI.  Atlas's punch list
#   (offices/architect/reports/2026-08-29-v029-punch-list-seven-surfaces-33-
#   items.md section 3.4) read the live `system-status` payload off the car and
#   recorded `drive.state:"idle"`, `lastDrive.driveId:51` -- "correct and
#   current".  The producer was populating the block the whole time.  The tile's
#   ONLY route to "unavailable" is the payload or its `drive` block being
#   ABSENT, so what the CIO photographed was cause A, which US-700 fixed.
#
#   SO WHY DOES THIS FILE EXIST IF THE STORY RE-HOMES?  Atlas attached one
#   condition to the re-homing (2026-09-10): the measurement must still be RUN,
#   because "if US-700 lands and LAST DRIVE still reads wrong, the cause is a
#   FOURTH thing and re-homing would BURY it."  A re-homed story that leaves
#   nothing behind is a measurement nobody can repeat.  These tests are that
#   measurement, and they are NOT a second copy of US-700's:
#
#     * US-700's suite hands `waitedMs` to the tile builder as a LITERAL.  That
#       proves the builder branches correctly; it proves NOTHING about whether
#       the panel's waiting-room ledger ever hands this tile a real wait, or
#       ever stops.  Two individually-correct halves that never agree is this
#       repo's most-repeated defect (US-494/499/502/503/505).  The boot-timeline
#       tests below drive the SHIPPED `feedObserved` + `feedWaitedMs` and thread
#       the ledger through, so the JOIN is what is under test.
#     * The real-Pi payload is assembled by the SHIPPED emitter from Atlas's
#       measured facts rather than hand-typed, so the fixture cannot drift from
#       the schema it claims to be.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-698 cause measurement + re-home pin.
# ================================================================================
################################################################################

"""US-698: measure which cause made LAST DRIVE read "unavailable"."""

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_SRC = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi",
)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# The emit instant every age below is measured against.
_TS = "2026-08-29T21:00:00Z"

# --- Atlas's measured facts, punch list section 3, read off the live Pi -------
# Only these are MEASURED. Everything else in the payload comes from the shipped
# emitter, which is the point: a hand-typed fixture would be a claim about the
# schema rather than a reading of it.
_MEASURED_DRIVE_ID = 51           # 3.4 `lastDrive.driveId:51` -- "correct and current"
_MEASURED_DRIVE_STATE = "idle"    # 3.4 `drive.state:"idle"`
_MEASURED_POWER_SOURCE = "unknown"  # 3.3 unresolved
_MEASURED_SYNC_PENDING = None     # 3.2 never computed
_MEASURED_OBD_AVAILABLE = False   # 3.1 `available:false, reason:"OBD: off"`

# Atlas recorded the drive ID but NOT its start timestamp, so this stays None --
# the honest unmeasured half. The tile then reads "Drive 51 / age unknown",
# which is enough to settle the story: the question is whether it says
# "unavailable", not what the age is.
_MEASURED_STARTED_AT = None

# The panel's poll clock. `feedStartedMs` is when THIS PAGE started asking.
_PAGE_START_MS = 0
# The real Pi's card emitter republishes system-status every ~2 s
# (orchestrator/types.py stateEmitIntervalSeconds), so this is when the first
# payload actually lands after a page load.
_FIRST_PAYLOAD_MS = 2000


def _view(fn: str, *args: object) -> object:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    # encoding pinned: the card's copy carries "·" and "—", which mojibake
    # through the Windows locale codec and turn a real assertion into noise.
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _realPiPayload(lastDrive: object = "measured") -> dict:
    """The live Pi's system-status, assembled by the SHIPPED emitter.

    Args:
        lastDrive: the block to carry. Defaults to Atlas's measured drive 51;
            pass None to model the never-driven Pi.
    """
    from pi.splash.system_status_emitter import buildSystemStatusState

    if lastDrive == "measured":
        lastDrive = {
            "driveId": _MEASURED_DRIVE_ID,
            "startedAtTs": _MEASURED_STARTED_AT,
        }
    return buildSystemStatusState(
        obdLinkState="down",
        obdRetries=0,
        obdLastSeenS=None,
        syncLastOkTs=None,
        syncRows=0,
        syncPending=_MEASURED_SYNC_PENDING,
        syncStale=False,
        powerSource=_MEASURED_POWER_SOURCE,
        driveState=_MEASURED_DRIVE_STATE,
        driveId=None,
        nowIso=_TS,
        obdAvailable=_MEASURED_OBD_AVAILABLE,
        obdUnavailableReason="OBD: off",
        lastDrive=lastDrive,
    )


# ---------------------------------------------------------------------------
# STEP ONE: the measurement. Candidate B, falsified against the real Pi.
# ---------------------------------------------------------------------------


def test_measuredRealPiPayload_carriesTheLastDriveBlock_soCandidateBIsFalse():
    """Candidate B says the producer is not populating `drive.lastDrive`.

    Atlas read the live payload off the car and found `lastDrive.driveId:51`.
    Pinned here as an assertion about the SHIPPED emitter's output so the claim
    is re-measured on every run rather than quoted from a four-week-old report.
    """
    payload = _realPiPayload()

    assert payload["drive"]["lastDrive"]["driveId"] == _MEASURED_DRIVE_ID
    assert payload["drive"]["state"] == _MEASURED_DRIVE_STATE


def test_measuredRealPiPayload_rendersTheRecordedDrive_notUnavailable():
    """THE STORY'S QUESTION, ANSWERED.

    Fed the payload the CIO's own Pi was publishing, the shipped tile renders
    the drive. It cannot reach the "unavailable" branch, because that branch
    requires the payload or its `drive` block to be ABSENT -- which is cause A,
    not cause B.
    """
    fact = _view("idleLastDriveFact", _realPiPayload(), None)

    assert fact["value"] == f"Drive {_MEASURED_DRIVE_ID}"
    assert fact["detail"] != "unavailable"
    assert fact["level"] == "neutral"


@pytest.mark.parametrize(
    "waitedMs",
    [None, 0, 1, 2999, 5999, 6000, 6001, 3600000],
)
def test_measuredRealPiPayload_isNeverUnavailable_atAnyWait(waitedMs):
    """An ARRIVED payload outranks the clock, at every wait the panel can hand
    it -- inside the grace window, at the bound, and an hour past it.

    This is the claim the story's END STATE actually makes: "'unavailable' must
    not be the resting state". A tile that fell through to `unavailable` once
    the window expired *despite holding a payload* would satisfy every
    literal-waitedMs test in US-700's suite and still be the reported defect.
    """
    fact = _view("idleLastDriveFact", _realPiPayload(), waitedMs)

    assert fact["level"] == "neutral"
    assert fact["value"] == f"Drive {_MEASURED_DRIVE_ID}"


def test_neverDrivenPi_saysNoRecentDrive_notUnavailable():
    """The OTHER half of the falsification, and the one that makes it sharp.

    Had cause B been real -- payload present, `lastDrive` empty -- the tile
    would read "No recent drive", a DIFFERENT string which the CIO did not
    photograph. Measured here so the discriminator is a run rather than an
    argument.
    """
    fact = _view("idleLastDriveFact", _realPiPayload(lastDrive=None), None)

    assert fact["value"] == "No recent drive"
    assert fact["level"] == "neutral"


def test_theOnlyRouteToUnavailable_isAnAbsentPayload():
    """Names the cause positively rather than by elimination: "unavailable" is
    what this tile says when NOTHING arrived and the grace window has expired.

    That is cause A, and it is the state US-700 gave a word of its own.
    """
    fact = _view("idleLastDriveFact", None, 60000)

    assert fact["detail"] == "unavailable"
    assert fact["level"] == "unavailable"


# ---------------------------------------------------------------------------
# THE PHOTOGRAPH (validationCriterion 1), run through the REAL ledger.
#
# The story asks for the startup card at 5 s, 30 s and 60 s after boot. That
# needs a car; this is the same measurement a keyboard can make, and it is
# stronger in one respect -- it is repeatable, and it drives `feedObserved` and
# `feedWaitedMs` for real instead of hand-passing the wait, so a ledger that
# never marks this feed answered is a FAILURE here rather than an invisibility.
# ---------------------------------------------------------------------------


def _tileAt(nowMs: int, *, firstPayloadMs: int | None) -> dict:
    """Render LAST DRIVE at `nowMs`, driving the shipped waiting-room ledger.

    Args:
        nowMs: the tick clock, relative to page start.
        firstPayloadMs: when the first real payload lands, or None for a feed
            that never answers.
    """
    payload = None
    seen: object = {}
    if firstPayloadMs is not None and nowMs >= firstPayloadMs:
        payload = _realPiPayload()
        # The SHIPPED ledger, not a boolean this test made up.
        seen = _view("feedObserved", seen, "system-status", payload)
    waitedMs = _view(
        "feedWaitedMs", seen, "system-status", _PAGE_START_MS, nowMs
    )
    return _view("idleLastDriveFact", payload, waitedMs)


@pytest.mark.parametrize("nowMs", [5000, 30000, 60000])
def test_bootTimeline_realPi_showsTheRealDriveByFiveSeconds(nowMs):
    """validationCriterion 1's outcome: "by 60 s the tile shows a real drive id".

    It shows one by 5 s, because the emitter republishes every ~2 s. Nothing on
    this timeline reads "unavailable" -- so it is not the resting state, and
    cause B is not confirmed.
    """
    fact = _tileAt(nowMs, firstPayloadMs=_FIRST_PAYLOAD_MS)

    assert fact["value"] == f"Drive {_MEASURED_DRIVE_ID}"
    assert fact["level"] == "neutral"


def test_bootTimeline_theFirstMomentAfterAReload_saysLoadingNotUnavailable():
    """t=0, the instant the CIO's photo was taken relative to the PANEL's clock.

    This is US-700 reaching THIS tile through the real ledger. Before US-700 the
    same instant painted "unavailable" -- a confident claim that the feed was
    broken, made before anyone had answered.
    """
    fact = _tileAt(0, firstPayloadMs=_FIRST_PAYLOAD_MS)

    assert fact["value"] == "LOADING"
    assert fact["level"] == "loading"


def test_bootTimeline_deadFeed_saysLoadingThenSettlesOnUnavailable():
    """The negative arm, and it is what stops the loading word from becoming a
    blanket excuse: a feed that NEVER answers gets the grace window and then the
    honest "unavailable".

    Without this, an implementation that reported "loading" forever would pass
    every other test in this file and hide a genuinely dead producer.
    """
    early = _tileAt(1000, firstPayloadMs=None)
    late = _tileAt(60000, firstPayloadMs=None)

    assert early["value"] == "LOADING"
    assert late["detail"] == "unavailable"
    assert late["level"] == "unavailable"


def test_bootTimeline_theLedgerHandsThisTileARealWait_notAConstantNull():
    """THE JOIN, stated as its own claim.

    `feedWaitedMs` returning a constant null -- the shape a broken ledger takes
    -- would send an unanswered feed straight to "unavailable" and quietly
    restore the reported defect, while every literal-`waitedMs` test in US-700's
    suite stayed green. So assert the ledger's two ends directly: a finite wait
    while unanswered, null once answered.
    """
    unanswered = _view("feedWaitedMs", {}, "system-status", _PAGE_START_MS, 4000)
    answered = _view(
        "feedWaitedMs",
        _view("feedObserved", {}, "system-status", _realPiPayload()),
        "system-status",
        _PAGE_START_MS,
        4000,
    )

    assert unanswered == 4000
    assert answered is None


# ---------------------------------------------------------------------------
# validationCriteria 2 + 3: the payload's block matches the newest REAL row in
# drive_summary, end to end -- real producer, real emitter, real carousel.js.
# ---------------------------------------------------------------------------


def _driveSummaryDb(rows: list[tuple[int, str | None, str]]):
    from pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SCHEMA_DRIVE_SUMMARY)
    conn.executemany(
        "INSERT INTO drive_summary "
        "(drive_id, drive_start_timestamp, data_source) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()

    class _Database:
        @contextmanager
        def connect(self):
            yield conn

    return conn, _Database()


def _emitThrough(tmp_path, database) -> dict:
    """Drive the REAL card emitter and return the REAL emitted state file."""
    from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

    class _Orch(CardStateEmitterMixin):
        def __init__(self):
            self._config = {
                "pi": {
                    "splash": {"statesDir": str(tmp_path / "states")},
                    "dashboard": {"stateEmitIntervalSeconds": 0.0},
                }
            }
            self._connection = None
            self._driveDetector = None
            self._powerSourceProvider = None
            self._hardwareManager = None
            self._database = database
            self._systemStatusEmitter = None
            self._batteryHealthEmitter = None
            self._dtcEmitter = None
            self._cardPowerModeProvider = None
            self._cardStateEmitEnabled = True
            self._cardStateEmitInterval = 0.0
            self._cardSyncStaleThresholdS = 120.0
            self._lastCardStateEmitTime = None
            self._lastSyncOkTsIso = None
            self._lastSyncRows = 0

    orch = _Orch()
    orch._initializeCardStateEmitters()
    orch._maybeEmitCardStates()
    return json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )


def test_chain_theTileRendersTheNewestRealRow_andNotADifferentDrive(tmp_path):
    """validationCriteria 2 + 3 in one run: the emitted block, and the rendered
    tile, both name the newest REAL row in `drive_summary`.

    The sim row is the load-bearing fixture and it carries a HIGHER id than the
    real one. "The tile is not showing a different drive" is trivially satisfied
    when only one drive exists; it is only a measurement when a wrong answer is
    available to be given.
    """
    conn, database = _driveSummaryDb(
        [
            (50, "2026-08-28T09:00:00Z", "real"),
            (51, "2026-08-29T18:00:00Z", "real"),
            (52, "2026-08-29T20:00:00Z", "physics_sim"),
        ]
    )
    newestReal = conn.execute(
        "SELECT drive_id FROM drive_summary WHERE data_source = 'real' "
        "ORDER BY drive_id DESC LIMIT 1"
    ).fetchone()[0]

    emitted = _emitThrough(tmp_path, database)
    fact = _view("idleLastDriveFact", emitted, None)

    assert newestReal == _MEASURED_DRIVE_ID       # the fixture models Atlas's read
    assert emitted["drive"]["lastDrive"]["driveId"] == newestReal
    assert fact["value"] == f"Drive {newestReal}"


def test_chain_emptyDriveLog_stillPublishesTheDriveBlock_soTheTileIsNotUnavailable(
    tmp_path,
):
    """The FOURTH-CAUSE PIN Atlas's re-homing condition asks for.

    A Pi with nothing to report must still publish `drive`, because the tile's
    "unavailable" branch keys on that block's ABSENCE. An emitter that dropped
    the key when it had no drive to name would re-create the reported symptom
    on exactly the machine least able to explain it -- and would look like a
    tidy-up in review.
    """
    _, database = _driveSummaryDb([])

    emitted = _emitThrough(tmp_path, database)
    fact = _view("idleLastDriveFact", emitted, None)

    assert "drive" in emitted
    assert emitted["drive"]["lastDrive"] is None
    assert fact["value"] == "No recent drive"
    assert fact["level"] != "unavailable"


# ---------------------------------------------------------------------------
# validationCriterion 4: exactly one producer. The fix added no second read.
# ---------------------------------------------------------------------------


def _srcFiles() -> list[str]:
    found = []
    for root, _dirs, names in os.walk(_SRC):
        if "__pycache__" in root:
            continue
        for name in names:
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    assert found, "src/pi walk found no python files -- the subject is wrong"
    return found


def test_lastDriveHasExactlyOneProducer_andNoSecondAcquisition():
    """One read, persisted, published, subscribed -- never a second derivation.

    Scoped to the ACQUISITION (`readLastDriveSummary`) and to the emitter
    hand-off (`lastDrive=`), not to the string "lastDrive", which legitimately
    appears in docstrings and in the transport's own signature.
    """
    definitions = []
    acquisitions = []
    for path in _srcFiles():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if "def readLastDriveSummary" in text:
            definitions.append(path)
        if "readLastDriveSummary(" in text and "def readLastDriveSummary" not in text:
            acquisitions.append(path)

    assert len(definitions) == 1, f"more than one last-drive producer: {definitions}"
    assert len(acquisitions) == 1, f"more than one acquisition: {acquisitions}"
    assert acquisitions[0].endswith(
        os.path.join("orchestrator", "card_state_emitter.py")
    ), acquisitions[0]


def test_theDisplayReadsThePublishedFact_andDerivesNoDriveIdOfItsOwn():
    """The consumer half of validationCriterion 4.

    A fix that reached into another payload for a drive id would be a second
    acquisition on the display side, which is the shape this project's
    read-once/publish/subscribe rule exists to forbid.
    """
    jsPath = os.path.join(_SRC, "ui", "dashboard", "carousel.js")
    with open(jsPath, encoding="utf-8") as fh:
        js = fh.read()

    start = js.index("function idleLastDriveFact")
    body = js[start:js.index("\n  }", start)]

    assert "drive.lastDrive" in body
    assert "drive_summary" not in body
    assert "fetch" not in body
