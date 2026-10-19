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
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the idleLastDriveFact cases retire
#                               with the idle face; the producer cases stay.
# ================================================================================
################################################################################

"""US-698: measure which cause made LAST DRIVE read "unavailable"."""

import json
import os
import shutil
import subprocess

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


# ---------------------------------------------------------------------------
# THE PHOTOGRAPH (validationCriterion 1), run through the REAL ledger.
#
# The story asks for the startup card at 5 s, 30 s and 60 s after boot. That
# needs a car; this is the same measurement a keyboard can make, and it is
# stronger in one respect -- it is repeatable, and it drives `feedObserved` and
# `feedWaitedMs` for real instead of hand-passing the wait, so a ledger that
# never marks this feed answered is a FAILURE here rather than an invisibility.
# ---------------------------------------------------------------------------


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
