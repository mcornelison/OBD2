################################################################################
# File Name: test_carousel_last_drive.py
# Purpose/Description: US-505 tests for the idle-home card's LAST DRIVE tile --
#   the display half of the last-drive producer, plus the END-TO-END chain.
#
#   Iris's idle spec (offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-
#   full-bleed.md, "Last drive") pins the shape: `Drive 35 · 2 h ago`, with
#   `no drive recorded` when unknown -- "never a guess".
#
#   The chain test is the load-bearing one.  US-494 / US-499 / US-502 / US-503
#   all shipped two individually-correct halves that simply never agreed, and a
#   per-half test stays green straight through that.  So the last test here
#   drives the REAL emitter, reads the REAL state file, and feeds it to the REAL
#   carousel.js under node.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Ralph (Rex)  | Initial -- US-505 LAST DRIVE tile + chain.
# ================================================================================
################################################################################

"""US-505: the idle card renders a real last drive, or an honest absence."""

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "specs", "UI", "dist", "dashboard-pi", "carousel.js",
)

# The emit instant every fixture's age is measured against.
_TS = "2026-08-02T12:00:00Z"

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, *args: object) -> object:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    # encoding pinned: the card's copy carries "·" and "—", which mojibake
    # through the Windows locale codec and turn a real assertion into noise.
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _status(lastDrive: object = None, **extra: object) -> dict:
    payload: dict = {
        "drive": {"state": "idle", "driveId": None, "lastDrive": lastDrive},
        "idle": True,
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _lastDrive(driveId: int | None = 35, startedAtTs: str | None = None) -> dict:
    return {"driveId": driveId, "startedAtTs": startedAtTs}


# ---------------------------------------------------------------------------
# The tile renders the real drive + its age (Iris: "Drive 35 · 2 h ago").
# ---------------------------------------------------------------------------


def test_idleLastDriveFact_realDriveHoursAgo_rendersIdAndHourAge():
    """The story's whole point: a real recorded drive replaces 'No recent
    drive'."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-08-02T10:00:00Z")),
    )

    assert fact["value"] == "Drive 35"
    assert fact["detail"] == "2 h ago"


def test_idleLastDriveFact_minutesAgo_rendersMinuteAge():
    """Sub-hour ages read in minutes -- 'today' (the pre-existing day-grain
    vocabulary) would throw away the useful signal for a just-finished drive."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-08-02T11:35:00Z")),
    )

    assert fact["detail"] == "25 min ago"


def test_idleLastDriveFact_secondsAgo_rendersJustNow():
    """Under a minute is 'just now' -- never '0 min ago'."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-08-02T11:59:30Z")),
    )

    assert fact["detail"] == "just now"


def test_idleLastDriveFact_daysAgo_reusesTheDayGrainVocabulary():
    """At a day and beyond the tile speaks the SAME words the battery card's
    data-age line already uses -- one age vocabulary, not two for one fact."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-07-30T12:00:00Z")),
    )

    assert fact["detail"] == "3 days ago"


def test_idleLastDriveFact_exactlyOneDay_readsSingular():
    """Boundary: the day-grain vocabulary's singular form is reached through the
    new sub-day tiers, not bypassed by them."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-08-01T12:00:00Z")),
    )

    assert fact["detail"] == "1 day ago"


# ---------------------------------------------------------------------------
# Honest degradation -- never a guess (Iris).
# ---------------------------------------------------------------------------


def test_idleLastDriveFact_noLastDrive_keepsTheHonestAbsence():
    """No drive ever recorded -> the honest absence stays. The fix must not
    invent a drive to fill the tile."""
    fact = _view("idleLastDriveFact", _status(None))

    assert fact["value"] == "No recent drive"


def test_idleLastDriveFact_nullStartTimestamp_saysAgeUnknownNotAFakeAge():
    """A real drive with no usable start time shows the drive and admits the
    missing half. A fabricated age would be the exact lie this card exists to
    avoid."""
    fact = _view("idleLastDriveFact", _status(_lastDrive(51, None)))

    assert fact["value"] == "Drive 51"
    assert fact["detail"] == "age unknown"


def test_idleLastDriveFact_unparseableStartTimestamp_saysAgeUnknown():
    """Garbage in the timestamp column degrades the age only -- it never throws
    and never renders NaN."""
    fact = _view("idleLastDriveFact", _status(_lastDrive(51, "not-a-date")))

    assert fact["value"] == "Drive 51"
    assert fact["detail"] == "age unknown"


def test_idleLastDriveFact_futureTimestamp_neverRendersANegativeAge():
    """Clock skew (the Pi has no RTC battery and boots before NTP) must not
    produce '-5 min ago'."""
    fact = _view(
        "idleLastDriveFact",
        _status(_lastDrive(35, "2026-08-02T12:30:00Z")),
    )

    assert fact["detail"] == "just now"


def test_idleLastDriveFact_missingDriveBlock_isUnavailable():
    """No drive block at all is an unavailable SOURCE, which is a different
    claim from 'no drive has happened'."""
    fact = _view("idleLastDriveFact", {"idle": True, "ts": _TS})

    assert fact["level"] == "unavailable"


def test_idleLastDriveFact_recording_stillReportsREC():
    """The pre-existing recording disposition is untouched: a live drive
    outranks the remembered one on this tile."""
    fact = _view(
        "idleLastDriveFact",
        {
            "drive": {
                "state": "recording",
                "driveId": 36,
                "lastDrive": _lastDrive(35, "2026-08-02T10:00:00Z"),
            },
            "ts": _TS,
        },
    )

    assert fact["value"] == "REC"
    assert fact["detail"] == "drive 36"


# ---------------------------------------------------------------------------
# Idle render-safety invariant: the idle card shows no green (except battery).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lastDrive",
    [
        None,
        {"driveId": 35, "startedAtTs": "2026-08-02T10:00:00Z"},
        {"driveId": 35, "startedAtTs": None},
        {"driveId": None, "startedAtTs": "2026-08-02T10:00:00Z"},
    ],
)
def test_idleLastDriveFact_neverGoesGreenOrAlarms(lastDrive):
    """Locked idle invariant: the battery line is the ONLY line allowed green at
    idle, and nothing on a parked card may alarm. A last drive is neither good
    news nor a fault."""
    fact = _view("idleLastDriveFact", _status(lastDrive))

    assert fact["level"] in ("neutral", "unavailable")


def test_idleCardView_carriesTheLastDriveFactToTheRenderer():
    """The assembled view the DOM renderer consumes must carry the tile -- a
    correct fact the renderer never receives paints nothing."""
    view = _view(
        "idleCardView",
        _status(_lastDrive(35, "2026-08-02T10:00:00Z")),
        None,
        None,
    )

    assert view["facts"]["lastDrive"]["value"] == "Drive 35"
    assert view["facts"]["lastDrive"]["detail"] == "2 h ago"


# ---------------------------------------------------------------------------
# END-TO-END: real emitter -> real state file -> real carousel.js.
# This is the test that catches two correct halves that never agree.
# ---------------------------------------------------------------------------


def test_chain_realEmitterToRealRenderer_showsTheRealDrive(tmp_path):
    """Drive the REAL card emitter against a REAL drive_summary table, then feed
    the REAL emitted state file to the REAL carousel.js.

    Both halves of US-505 can be individually correct and still not agree on the
    key name, the nesting, or the timestamp format; a test on either half alone
    stays green through exactly that (US-494/US-499/US-502/US-503).
    """
    from pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY
    from pi.obdii.orchestrator.card_state_emitter import CardStateEmitterMixin

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SCHEMA_DRIVE_SUMMARY)
    conn.execute(
        "INSERT INTO drive_summary "
        "(drive_id, drive_start_timestamp, data_source) VALUES (?, ?, 'real')",
        (35, "2026-08-02T09:15:00Z"),
    )
    conn.commit()

    class _Database:
        @contextmanager
        def connect(self):
            yield conn

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
            self._database = _Database()
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

    emitted = json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )

    # The REAL emitted payload, through the REAL renderer -- no hand-built
    # fixture in between to paper over a key-name disagreement.
    fact = _view("idleLastDriveFact", emitted)

    assert fact["value"] == "Drive 35"
    assert fact["detail"].endswith("ago") or fact["detail"] == "just now"
    assert fact["level"] == "neutral"


def test_shippedArtifact_domRendererStillPaintsTheLastDriveTile():
    """The browser-only DOM block is invisible to the node probe, so pin against
    the shipped artifact that the renderer still appends this tile (US-503's
    lesson: a relocated/renamed fact silently stops being painted)."""
    with open(_JS, encoding="utf-8") as fh:
        js = fh.read()

    assert "view.facts.lastDrive" in js
