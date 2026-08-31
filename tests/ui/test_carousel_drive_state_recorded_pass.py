################################################################################
# File Name: test_carousel_drive_state_recorded_pass.py
# Purpose/Description: US-638 (F-138, punch-list 3.4) -- RECORD THE PASS on drive
#   state AND last-drive identity, ON THE RENDERED PANEL and through the REAL
#   acquisition path, and record the finding the recording exposed.
#
#   WHY THIS FILE EXISTS WHEN THE BEHAVIOUR IS "ALREADY TESTED". The two facts
#   this story names live on TWO DIFFERENT TILES, and their coverage is lopsided
#   in opposite directions:
#     * `drive.state` / `drive.driveId` -> the System card's DRIVE tile.
#       `driveTile` is referenced by ZERO tests in the repository. The only
#       assertion on it anywhere is an incidental one-liner inside a test whose
#       SUBJECT is the POWER tile
#       (test_carousel_pi_local_cards.py:213, `tiles["drive"]["value"] ==
#       "IDLE"`), fed by a HAND-WRITTEN dict, on the pure view, on one branch.
#       The recording branch, the unreadable branch and the unknown-state branch
#       had never been asserted at all, and none of them had ever been RENDERED.
#     * `drive.lastDrive` -> the idle face's LAST DRIVE tile. Well covered by
#       US-505's tests/ui/test_carousel_last_drive.py -- but every one of them
#       calls `idleLastDriveFact` through the pure-function probe, so not one
#       paints a pixel, and that file's own DOM guard is a STRING GREP
#       (`assert "view.facts.lastDrive" in js`), which a renderer that appended
#       the tile to a display:none container would sail straight past.
#   So this file asserts both facts where the driver reads them: REAL producer /
#   REAL orchestrator -> state file -> SHIPPED carousel.js -> SHIPPED markup +
#   stylesheet at 480x320.
#
#   THE PASS IS REAL AND IS RECORDED BELOW. Atlas's punch-list 3.4 observation
#   (`state:"idle"`, `lastDrive.driveId:51`) is CORRECT, and correct all the way
#   to the panel: the DRIVE tile paints IDLE / "not recording" at the `neutral`
#   level -- nominal-but-inactive, so it does NOT block the card's green and does
#   NOT appear in the drill-down as a fabricated fault -- while the LAST DRIVE
#   tile paints "Drive 51" beside a real age. An UNREADABLE drive block paints a
#   typed absence on both tiles and DOES block green, and a state file that
#   VANISHES mid-session takes both tiles with it rather than leaving a REC
#   lingering over a drive that ended.
#
#   THE LOAD-BEARING PIN IS THE INDEPENDENCE OF THE TWO FACTS. `drive.state` and
#   `drive.lastDrive` sit in one block and are read by two renderers, so the
#   tempting simplification -- gate one on the other -- would look right in every
#   healthy payload. It is wrong: an unreadable STATE must not erase a completed
#   drive that genuinely happened, and a never-driven Pi must not be able to
#   suppress the live REC. Both directions are asserted on one payload where the
#   two halves DISAGREE, which is the only shape that can tell them apart.
#
#   FINDING RECORDED, NOT FIXED (sprint contract: a VERIFY story that finds a
#   defect RECORDS it and FILES a fix story -- it must NEVER quietly become the
#   fix, because that hides the defect rate the sweep exists to measure). The
#   LAST DRIVE tile exists ONLY on the idle fallback face, and under US-541
#   IMU-always-on that face fires ONLY when the motion feed is dead. MEASURED
#   here: with a live states/imu payload the tile is ABSENT FROM THE PANEL
#   ENTIRELY -- no other surface renders `drive.lastDrive`, and the DRIVE tile
#   never prints a drive id at idle. The IMU ships dark today
#   (`pi.sensors.imu.enabled` defaults false), so the tile is visible on the
#   current Pi and Atlas could read it; the day the CIO wires the sensor bus,
#   US-505's producer keeps running and nothing shows its answer. Filed as
#   offices/pm/issues/I-us638-last-drive-identity-has-no-surface-on-the-live-face.md
#   and held by the characterisation tests at the foot of this file.
#
#   AND THE FIRST DRAFT OF THAT MEASUREMENT WAS AN ARTEFACT, which is the method
#   note worth carrying forward. `mini_dom.js` had no `createElementNS`, and
#   `svgEl` is the FIRST call `renderLiveBody` makes -- so the live face did not
#   render imperfectly, it THREW, leaving an empty card body. The absence the
#   characterisation was reading was the CRASH, not the panel. NO TEST IN THIS
#   REPOSITORY HAD EVER RENDERED THE LIVE FACE, so nothing had ever hit it. Fixed
#   by implementing `createElementNS` (additive; the full tests/ui collection is
#   unchanged at 1073 with the 28 here added), and the finding is now measured on
#   a live face that demonstrably paints -- with a negative control asserting so,
#   because an absence test whose subject failed to render is not a measurement.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-638 punch-list 3.4 recorded pass +
#               |              | the live-face reachability finding (I-us638).
# ================================================================================
################################################################################

"""US-638 tests: drive state and last-drive identity, as the panel renders them."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
    ),
)

import render_harness as rh  # noqa: E402

from pi.obdii.drive_summary import SCHEMA_DRIVE_SUMMARY  # noqa: E402
from pi.obdii.orchestrator.card_state_emitter import (  # noqa: E402
    CardStateEmitterMixin,
)
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default. Measuring the 3.5in kit at
# 1920x1080 resolves media queries the operator never sees.
PANEL = (480, 320)

# Spelled as a named constant, never inline -- this file is written and re-read
# on a Windows SMB share where a raw em-dash has been mangled before (the same
# precaution test_carousel_sync_stamp.py and US-633's file both take).
EM_DASH = "—"

# Design tokens, resolved through the REAL cascade rather than asserted as a
# colour name -- a stylesheet that repainted `neutral` green must fail here
# rather than pass on a string comparison.
GREEN = "var(--green-ok)"

_NOW = "2026-08-31T14:46:00Z"
_FRESH_SYNC = "2026-08-31T14:45:22Z"

# Atlas's punch-list 3.4 reading, verbatim: drive 51, started two hours before
# the emit instant above.
_ATLAS_DRIVE_ID = 51
_ATLAS_DRIVE_STARTED = "2026-08-31T12:46:00Z"


# ---------------------------------------------------------------------------
# Fixtures -- assembled by the SHIPPED emitter's own builder, never by hand.
# ---------------------------------------------------------------------------


def _systemStatus(**overrides: Any) -> dict:
    """A system-status payload from the shipped producer.

    Defaults describe Atlas's punch-list 3.4 Pi as far as the DRIVE facts go --
    parked, not recording, drive 51 on record -- but with EVERY OTHER SOURCE
    DELIBERATELY HEALTHY, OBD link included. That is not cosmetic: the card's
    summary line is a compression of all four tiles, so with any other source
    degraded "SYSTEM . OK" would be unreachable and the assertion that DRIVE=IDLE
    does not block green would pass for the wrong reason (it would never be the
    thing under test). Any non-green this file observes can only have come from
    the drive block.
    """
    args: dict[str, Any] = {
        "obdLinkState": "linked",
        "obdRetries": 0,
        "obdLastSeenS": 1,
        "syncLastOkTs": _FRESH_SYNC,
        "syncRows": 1204,
        "syncPending": 0,
        "syncStale": False,
        "powerMode": "wall",
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": _NOW,
        "obdAvailable": True,
        "obdUnavailableReason": None,
        "lastDrive": {
            "driveId": _ATLAS_DRIVE_ID,
            "startedAtTs": _ATLAS_DRIVE_STARTED,
        },
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


def _withoutDriveBlock() -> dict:
    """A payload whose `drive` block is GONE.

    Reached by deleting the key from the real producer's output rather than by
    hand-writing a payload without it: the shape every other key is in stays the
    producer's, so this models an OLD or TRUNCATED state file and not a fixture
    the renderer has never seen the rest of.
    """
    payload = _systemStatus()
    del payload["drive"]
    return payload


# ---------------------------------------------------------------------------
# The REAL acquisition path. `buildSystemStatusState` is only the second link in
# the chain; both facts this story names are decided one layer UP, in the
# orchestrator -- `_gatherDriveState` for the state, `_gatherLastDriveSummary`
# for the identity -- and that layer reads a real SQLite table.
# ---------------------------------------------------------------------------


class _Orch(CardStateEmitterMixin):
    """The minimal composing object the mixin reads, as the orchestrator does.

    Mirrors tests/pi/orchestrator/test_card_state_emitters.py::_FakeOrch. Using
    the mixin rather than calling the emitter directly is the whole point: the
    last-drive fact is READ FROM A DATABASE at emit time (deliberately via
    `getattr` per tick -- see the docstring on `_gatherLastDriveSummary`), and a
    test that starts at the builder cannot see that read at all.
    """

    def __init__(
        self,
        statesDir: str,
        *,
        database: Any = None,
        driveDetector: Any = None,
    ) -> None:
        self._config = {
            "pi": {
                "splash": {"statesDir": statesDir},
                "dashboard": {"stateEmitIntervalSeconds": 0.0},
            }
        }
        self._connection = None
        self._driveDetector = driveDetector
        self._powerSourceProvider = SimpleNamespace(
            isAvailable=True, isExternalPowerPresent=lambda: True
        )
        self._hardwareManager = None
        self._database = database
        self._systemStatusEmitter = None
        self._batteryHealthEmitter = None
        self._dtcEmitter = None
        self._cardPowerModeProvider = SimpleNamespace(getPowerMode=lambda: "wall")
        self._cardStateEmitEnabled = True
        self._cardStateEmitInterval = 0.0
        self._cardSyncStaleThresholdS = 120.0
        self._lastCardStateEmitTime = None
        self._lastSyncOkTsIso = _FRESH_SYNC
        self._lastSyncRows = 1204


def _driveSummaryDb(rows: list[tuple[int, str | None, str]]) -> Any:
    """An in-memory Pi-local DB carrying `drive_summary` rows.

    `rows` are (drive_id, drive_start_timestamp, data_source) -- the data_source
    is a REAL parameter and not always 'real', because the producer's sim-row
    filter is one of the things reaching the panel.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SCHEMA_DRIVE_SUMMARY)
    for driveId, startedAt, source in rows:
        conn.execute(
            "INSERT INTO drive_summary "
            "(drive_id, drive_start_timestamp, data_source) VALUES (?, ?, ?)",
            (driveId, startedAt, source),
        )
    conn.commit()

    class _Database:
        @contextmanager
        def connect(self):
            yield conn

    return _Database()


def _emitToStateFile(tmp_path, **kwargs: Any) -> dict:
    """Run the REAL orchestrator emit and return what it wrote to disk."""
    statesDir = str(tmp_path / "states")
    orch = _Orch(statesDir, **kwargs)
    orch._initializeCardStateEmitters()
    assert orch._maybeEmitCardStates() is True, "the emitter wrote nothing"
    return json.loads(
        (tmp_path / "states" / "system-status").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(payload: Any, steps: list[dict[str, Any]] | None = None, imu: Any = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet.

    `imu` is left ABSENT by default, which is the shipped Pi today:
    `pi.sensors.imu.enabled` defaults false, so states/imu does not exist and the
    home slot falls back to the idle face -- the only face that renders LAST
    DRIVE. Supplying one is how the finding at the foot of this file is measured.
    """
    routes: dict[str, Any] = {} if payload is None else {"/system-status": payload}
    if imu is not None:
        routes["/imu"] = imu
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


# The drill-down is rendered only while the overlay is OPEN, so reaching it means
# TAPPING the summary line the way the operator does. The line is built by
# carousel.js and carries no id, so it is reached by class via the `clickNth`
# step US-635 added for exactly this reason.
_OPEN_DRILL = [
    {"flush": 4},
    {"clickNth": {"selector": ".sys-summary", "index": 0}},
    {"flush": 1},
]

# A state file that is read once and then DISAPPEARS -- the emitter dying, or
# /run being cleared under a running kiosk.
_THEN_VANISH = [{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}]

# The control for the above: the same two-step render with the file left in
# place, so a harness whose second step reset everything unconditionally cannot
# pass the vanish tests while proving nothing.
_THEN_KEPT = [{"flush": 4}, {"flush": 4}]


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _tileByLabel(surface, label: str) -> dict | None:
    """The rendered `.tile` whose own label reads `label`, as the operator sees it.

    Found by its PRINTED LABEL rather than by grid position, so a tile that moved
    in the layout still resolves and a tile that VANISHED returns None instead of
    silently matching its neighbour. Returns the printed value/detail, the level
    the stylesheet is keyed on, and the COLOUR that level actually resolves to --
    because "not green" is a claim about the panel, and a level token only means
    not-green while the sheet agrees.
    """
    for path in surface.pathsByClass("tile"):
        printed = _textOf(path[-1])
        if not printed or printed[0] != label:
            continue
        if not surface.rendered(path):
            continue
        value = ""
        detail = ""
        valuePath = None
        for child in path[-1].get("children", []):
            classes = (child.get("attrs", {}).get("class") or "").split()
            if "tile-value" in classes:
                value = " ".join(_textOf(child))
                valuePath = path + [child]
            elif "tile-detail" in classes:
                detail = " ".join(_textOf(child))
        declaration = (
            surface.winningDeclaration(valuePath, "color") if valuePath else None
        )
        return {
            "value": value,
            "detail": detail,
            "level": path[-1].get("attrs", {}).get("data-level"),
            "colour": declaration[0] if declaration else "",
            "texts": printed,
        }
    return None


def _driveTile(payload: Any, **kwargs: Any) -> dict | None:
    return _tileByLabel(_surface(payload, **kwargs), "DRIVE")


def _lastDriveTile(payload: Any, **kwargs: Any) -> dict | None:
    return _tileByLabel(_surface(payload, **kwargs), "LAST DRIVE")


def _systemCardText(payload: Any, **kwargs: Any) -> list[str]:
    """The whole System Status card's rendered text, in reading order."""
    surface = _surface(payload, **kwargs)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            return _textOf(path[-1])
    return []


def _drillRows(payload: Any) -> list[str]:
    """The drill-down's issue rows, as printed, with the overlay OPEN."""
    surface = _surface(payload, steps=_OPEN_DRILL)
    return [
        " ".join(_textOf(path[-1]))
        for path in surface.pathsByClass("sys-issue-row")
    ]


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. A large share of the assertions in this file are
# absence-shaped ("never green", "no fabricated id", "no digit"), and every one
# of them passes vacuously if the harness reads nothing at all. A renamed class
# or a probe crash would turn the whole file green while pinning nothing.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsBothTiles_negativeControl():
    """
    Given: every "must not" assertion below fails open if a tile is unreadable
    When: an unmistakably ACTIVE drive with a remembered predecessor is rendered
    Then: the harness reads a real value, a real level and a real colour on the
          DRIVE tile, and a real value on the LAST DRIVE tile.
    """
    payload = _systemStatus(driveState="recording", driveId=52)
    tile = _driveTile(payload)
    assert tile is not None, "no DRIVE tile in the rendered DOM"
    assert tile["value"] == "REC", f"harness read no tile value: {tile!r}"
    assert tile["level"] == "ok", f"harness read no tile level: {tile!r}"
    assert tile["colour"] == GREEN, f"harness read no tile colour: {tile!r}"

    last = _lastDriveTile(payload)
    assert last is not None, "no LAST DRIVE tile in the rendered DOM"
    assert last["value"] != "", f"harness read no last-drive value: {last!r}"


def test_theStylesheetPaintsGreenOnlyForTheOkLevel():
    """
    Given: this file repeatedly claims the IDLE tile is "not green"
    When: the shipped stylesheet is resolved for each tile level in turn
    Then: `ok` is the ONLY level that resolves to the green token.

          Without this, "not green" only means "the token is not the string ok",
          and a sheet that painted `neutral` green would leave this file passing
          while a parked Pi claimed an active recording.
    """
    surface = _surface(_systemStatus())
    path = None
    for candidate in surface.pathsByClass("tile"):
        printed = _textOf(candidate[-1])
        if printed and printed[0] == "DRIVE":
            path = candidate
    assert path is not None
    valuePath = None
    for child in path[-1].get("children", []):
        if "tile-value" in (child.get("attrs", {}).get("class") or "").split():
            valuePath = path + [child]
    assert valuePath is not None

    resolved = {}
    for level in ("ok", "amber", "down", "neutral", "unavailable"):
        path[-1]["attrs"]["data-level"] = level
        declaration = surface.winningDeclaration(valuePath, "color")
        resolved[level] = declaration[0] if declaration else ""

    assert resolved["ok"] == GREEN, resolved
    greens = [level for level, colour in resolved.items() if colour == GREEN]
    assert greens == ["ok"], f"more than one level paints green: {resolved!r}"


# ---------------------------------------------------------------------------
# SURFACE A -- the DRIVE tile (`drive.state`, `drive.driveId`).
#
# `driveTile` is referenced by ZERO tests in the repository. Everything below is
# new coverage, not a duplicate.
# ---------------------------------------------------------------------------


def test_atlasIdleObservation_paintsIdleNotRecording_andIsNotGreen():
    """
    Given: Atlas's punch-list 3.4 reading -- `drive.state: "idle"`
    When: the shipped panel renders it
    Then: the DRIVE tile reads IDLE / "not recording" at the `neutral` level, and
          is NOT green.

          THE RECORDED PASS for the drive-state half. Green here would be a
          claim that a drive is being captured, which is the one thing a parked
          Pi must not say.
    """
    tile = _driveTile(_systemStatus())

    assert tile is not None
    assert tile["value"] == "IDLE", tile
    assert tile["detail"] == "not recording", tile
    assert tile["level"] == "neutral", tile
    assert tile["colour"] != GREEN, tile


def test_idleIsNominalNotAFault_soTheCardStillReadsSystemOk():
    """
    Given: a parked Pi with every other source healthy
    When: the summary line compresses the four tiles
    Then: it reads SYSTEM . OK.

          `neutral` is the third bucket in SYS_LEVEL_RANK and it exists FOR this
          tile: DRIVE=IDLE means "not recording", not "broken". Ranked as a
          fault it would make green unreachable in the commonest state there is
          (key on, no drive started) -- crying wolf, which is its own dishonesty.
          Nothing pinned that ranking on a rendered card until now.
    """
    printed = _systemCardText(_systemStatus())

    assert "SYSTEM · OK" in printed, printed
    assert "IDLE" in printed, printed


def test_idleIsNeverListedAsAnIssueInTheDrillDown():
    """
    Given: the drill-down lists every source at or above the `unavailable` floor
    When: the overlay is opened on a parked but otherwise healthy Pi
    Then: no DRIVE row appears.

          The other half of the ranking: a green source in a fault list is a
          FABRICATED fault. Asserted on the OPENED overlay rather than on the
          view object, because the row could equally be dropped by the renderer.
    """
    rows = _drillRows(_systemStatus())

    assert [row for row in rows if "DRIVE" in row] == [], rows


def test_recordingPaintsRecWithTheActiveDriveId():
    """
    Given: a drive is actively recording as drive 52
    When: the shipped panel renders it
    Then: the DRIVE tile reads REC / "drive 52" and IS green.

          The positive branch. Without it every "not green" assertion in this
          file could be satisfied by a tile that is never green.
    """
    tile = _driveTile(_systemStatus(driveState="recording", driveId=52))

    assert tile is not None
    assert tile["value"] == "REC", tile
    assert tile["detail"] == "drive 52", tile
    assert tile["level"] == "ok", tile
    assert tile["colour"] == GREEN, tile


def test_recordingWithNoMintedId_saysQuestionMarkNeverAFabricatedNumber():
    """
    Given: a drive is recording but the id could not be read (the orchestrator
           reaches this whenever `getCurrentDriveId()` returns None -- a drive
           past its US-625 bounded idle, or a counter not yet ensured)
    When: the shipped panel renders it
    Then: the detail reads "drive ?" and carries NO DIGIT.

          Asserted as "no digit" rather than "not drive 0", because the family of
          wrong answers here is bigger than zero: the last known id, the row
          count, and 0 are all plausible-looking numbers, and every one of them
          would attribute the recording to a drive nobody minted.
    """
    tile = _driveTile(_systemStatus(driveState="recording", driveId=None))

    assert tile is not None
    assert tile["value"] == "REC", tile
    assert tile["detail"] == "drive ?", tile
    assert not any(ch.isdigit() for ch in tile["detail"]), tile


def test_absentDriveBlock_paintsATypedAbsence_notIdle():
    """
    Given: a state file with NO drive block at all (an old or truncated file)
    When: the shipped panel renders it
    Then: the DRIVE tile reads the em-dash / "unavailable" -- and specifically
          NOT "IDLE".

          THE STORY'S NEGATIVE CASE for this half, and the sharp edge of it.
          "IDLE" is a MEASUREMENT -- we looked, and nothing is recording.
          Painting it over a block nobody could read is the unread-as-settled
          defect class the whole punch list is chasing (2.1), one field across.
    """
    tile = _driveTile(_withoutDriveBlock())

    assert tile is not None
    assert tile["value"] == EM_DASH, tile
    assert tile["detail"] == "unavailable", tile
    assert tile["level"] == "unavailable", tile
    assert "IDLE" not in tile["texts"], tile
    assert "REC" not in tile["texts"], tile


def test_unrecognisedStateString_paintsTheTypedAbsence_neverGuessesIdle():
    """
    Given: `drive.state` carries a word this renderer has not been taught
           ("starting"), as a future producer or a partially-deployed Pi could
    When: the shipped panel renders it
    Then: the tile falls to the typed absence -- never to IDLE, never to REC.

          The default is load-bearing (US-634's lesson): `driveTile` matches
          "recording" and "idle" EXACTLY and falls through otherwise, and a
          fall-through that landed on either real state would be a confident
          reading manufactured out of an unrecognised one.
    """
    payload = _systemStatus()
    payload["drive"]["state"] = "starting"
    tile = _driveTile(payload)

    assert tile is not None
    assert tile["value"] == EM_DASH, tile
    assert tile["level"] == "unavailable", tile


def test_unreadableDriveBlock_blocksTheCardsGreenAndIsListed():
    """
    Given: the drive source cannot be read while every other source is healthy
    When: the summary line and the drill-down are rendered
    Then: the card refuses to say OK, names DRIVE, and lists it as a row.

          The counterweight to the two IDLE tests above. Those assert that a
          nominal-inactive source does NOT raise an alarm; this asserts the
          `neutral` bucket did not swallow the UNKNOWN one with it. Without it, a
          renderer that ranked every non-fault drive state as neutral would pass
          this file while claiming OK over a source nobody read.
    """
    payload = _withoutDriveBlock()
    printed = _systemCardText(payload)

    assert "SYSTEM · OK" not in printed, printed
    assert "SYSTEM · 1 UNAVAILABLE" in printed, printed
    assert "DRIVE · " + EM_DASH in printed, printed

    rows = _drillRows(payload)
    driveRows = [row for row in rows if "DRIVE" in row]
    assert len(driveRows) == 1, rows
    # The drive source publishes no `lastSeenS`, so the row must SAY the age was
    # not reported. "seen 0s ago" would claim we had just read a source we never
    # timed -- an unmeasured quantity rendered as a zero (US-508's class).
    assert "age not reported" in driveRows[0], driveRows
    assert "seen" not in driveRows[0], driveRows


# ---------------------------------------------------------------------------
# SURFACE B -- the LAST DRIVE tile (`drive.lastDrive`).
#
# US-505 covers `idleLastDriveFact` thoroughly as a FUNCTION. None of it renders,
# and its DOM guard is a string grep over carousel.js. Everything below is on the
# painted tile.
# ---------------------------------------------------------------------------


def test_atlasLastDriveObservation_paintsTheDriveAndItsAge():
    """
    Given: Atlas's punch-list 3.4 reading -- `lastDrive.driveId: 51`
    When: the shipped panel renders it
    Then: the LAST DRIVE tile reads "Drive 51" beside a real age.

          THE RECORDED PASS for the identity half. The age is asserted as the
          computed value, not merely as non-empty: the whole reason US-505 ships
          a TIMESTAMP rather than a pre-formatted "2 h ago" is that the display
          must age it against its own read instant, and an age frozen at emit
          time would still look plausible here.
    """
    tile = _lastDriveTile(_systemStatus())

    assert tile is not None
    assert tile["value"] == "Drive " + str(_ATLAS_DRIVE_ID), tile
    assert tile["detail"] == "2 h ago", tile
    assert tile["level"] == "neutral", tile


def test_noDriveEverRecorded_paintsTheTypedAbsence_withNoDigitAnywhere():
    """
    Given: no real drive is on record -- a fresh Pi, or a simulator-only bench
    When: the shipped panel renders it
    Then: the tile reads "No recent drive" / "since key-off", and NOTHING on it
          is a digit or a blank.

          THE STORY'S STATED NEGATIVE CASE, asserted the way it is worded
          ("a typed absence rather than a zero or a blank"). The digit sweep is
          the load-bearing half: "Drive 0" is the exact fabrication a `!= null`
          check written as a truthiness check would produce, and it reads as a
          real drive on a 3.5in panel.
    """
    tile = _lastDriveTile(_systemStatus(lastDrive=None))

    assert tile is not None
    assert tile["value"] == "No recent drive", tile
    assert tile["detail"] == "since key-off", tile
    assert tile["value"] != "", tile
    assert not any(ch.isdigit() for ch in " ".join(tile["texts"])), tile


def test_lastDriveBlockWithNoId_keepsTheHonestAbsence():
    """
    Given: a `lastDrive` block that is PRESENT but carries no drive id
    When: the shipped panel renders it
    Then: it reads the same honest absence -- never "Drive null", never a tile
          built out of the half that did arrive.

          A different input shape from the test above (block absent vs. block
          empty) reaching the same disposition, which is the property the
          producer's own `toStatePayload` docstring argues for: the display keys
          on ABSENCE, so a null-filled block must not read as a drive whose
          every detail failed to load.
    """
    tile = _lastDriveTile(
        _systemStatus(lastDrive={"driveId": None, "startedAtTs": _ATLAS_DRIVE_STARTED})
    )

    assert tile is not None
    assert tile["value"] == "No recent drive", tile
    assert "null" not in " ".join(tile["texts"]).lower(), tile


def test_realDriveWithNoStartTime_showsTheDriveAndAdmitsTheMissingAge():
    """
    Given: drive 51 genuinely happened but its start column is NULL
    When: the shipped panel renders it
    Then: the drive is still shown and the AGE alone degrades to "age unknown".

          Per-HALF degradation, on the painted tile. The drive is a real fact and
          hiding it to protect a cosmetic one would lose more than it saves; a
          fabricated age would be the exact lie the tile exists to avoid. Both
          failure directions are wrong, so both are pinned in one assertion.
    """
    tile = _lastDriveTile(
        _systemStatus(lastDrive={"driveId": _ATLAS_DRIVE_ID, "startedAtTs": None})
    )

    assert tile is not None
    assert tile["value"] == "Drive " + str(_ATLAS_DRIVE_ID), tile
    assert tile["detail"] == "age unknown", tile


def test_absentDriveBlock_isUnavailable_notNoRecentDrive():
    """
    Given: no drive block at all
    When: the shipped panel renders it
    Then: the tile reads the em-dash / "unavailable" -- NOT "No recent drive".

          Two different claims that a lazier renderer would merge: "no drive has
          ever happened" is a MEASUREMENT over a log we read, and "we could not
          read the log" is not. Distinguishing them on the panel is what makes an
          empty tile actionable.
    """
    tile = _lastDriveTile(_withoutDriveBlock())

    assert tile is not None
    assert tile["value"] == EM_DASH, tile
    assert tile["detail"] == "unavailable", tile
    assert tile["level"] == "unavailable", tile
    assert "No recent drive" not in " ".join(tile["texts"]), tile


def test_activeDriveOutranksTheRememberedOneOnTheLastDriveTile():
    """
    Given: drive 52 is recording while drive 51 sits in the completed log
    When: the shipped panel renders it
    Then: the LAST DRIVE tile reports the LIVE drive, not the remembered one.

          A live drive is the more useful fact and the two must never be shown as
          if the older one were current. Asserted by NAME on both ids, because
          "shows 52" alone is also satisfied by a tile that shows both.
    """
    tile = _lastDriveTile(_systemStatus(driveState="recording", driveId=52))

    assert tile is not None
    assert tile["value"] == "REC", tile
    assert tile["detail"] == "drive 52", tile
    assert str(_ATLAS_DRIVE_ID) not in " ".join(tile["texts"]), tile


# ---------------------------------------------------------------------------
# THE INDEPENDENCE OF THE TWO FACTS. One block, two renderers -- so the
# tempting simplification is to gate one on the other, and it would look right in
# every healthy payload. Only a payload whose two halves DISAGREE can tell.
# ---------------------------------------------------------------------------


def test_anUnreadableStateDoesNotEraseACompletedDrive():
    """
    Given: `drive.state` is a word nobody can read, but drive 51 IS on record
    When: the shipped panel renders that one payload
    Then: the DRIVE tile goes unavailable AND the LAST DRIVE tile still shows
          drive 51.

          A drive that finished is not un-finished by a state field going bad.
          Gate the identity on the state and a single unreadable string erases a
          real, independently-sourced fact.
    """
    payload = _systemStatus()
    payload["drive"]["state"] = "starting"

    drive = _driveTile(payload)
    last = _lastDriveTile(payload)

    assert drive is not None and drive["level"] == "unavailable", drive
    assert last is not None
    assert last["value"] == "Drive " + str(_ATLAS_DRIVE_ID), last


def test_aNeverDrivenPiStillShowsTheLiveRecording():
    """
    Given: a drive is recording on a Pi whose completed-drive log is EMPTY (the
           first drive this Pi has ever taken)
    When: the shipped panel renders it
    Then: the DRIVE tile still reads REC / "drive 52".

          The other direction. Gate the state on the identity and the very first
          drive -- the one where a driver is most likely to be watching the
          panel -- would render as if nothing were being captured.
    """
    tile = _driveTile(
        _systemStatus(driveState="recording", driveId=52, lastDrive=None)
    )

    assert tile is not None
    assert tile["value"] == "REC", tile
    assert tile["detail"] == "drive 52", tile


# ---------------------------------------------------------------------------
# NO LINGERING. A tile that keeps its last good reading after the producer dies
# is indistinguishable from a healthy one, so the failure is invisible on the
# panel by construction -- a test has to catch it because an operator cannot.
# ---------------------------------------------------------------------------


def test_stateFileVanishesMidRecording_noLingeringRecOnEitherTile():
    """
    Given: the panel has read a healthy REC payload
    When: the state file DISAPPEARS and the panel keeps polling
    Then: the DRIVE tile is gone with its card, and the LAST DRIVE tile falls to
          the typed absence -- no REC survives anywhere.

          A frozen REC is the worst lingering value this pair can take: it claims
          the vehicle is being recorded, right at the moment the thing doing the
          recording has stopped.
    """
    payload = copy.deepcopy(_systemStatus(driveState="recording", driveId=52))
    surface = _surface(payload, steps=_THEN_VANISH)

    assert _tileByLabel(surface, "DRIVE") is None, "the DRIVE tile outlived its state"
    last = _tileByLabel(surface, "LAST DRIVE")
    assert last is not None
    assert last["value"] == EM_DASH, last
    assert last["level"] == "unavailable", last

    printed: list[str] = []
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            printed = _textOf(path[-1])
    assert "REC" not in printed, printed
    assert "drive 52" not in printed, printed


def test_stateFileKeptAfterAGoodRead_stillShowsRec_control():
    """
    Given: the same two-step render, but the file does NOT vanish
    When: the second poll returns the same recording payload
    Then: REC is still on both tiles.

          The control for the test above: without it, a harness whose second step
          reset everything unconditionally would pass the no-lingering test while
          proving nothing.
    """
    payload = copy.deepcopy(_systemStatus(driveState="recording", driveId=52))
    surface = _surface(payload, steps=_THEN_KEPT)

    drive = _tileByLabel(surface, "DRIVE")
    assert drive is not None and drive["value"] == "REC", drive
    last = _tileByLabel(surface, "LAST DRIVE")
    assert last is not None and last["value"] == "REC", last


# ---------------------------------------------------------------------------
# THE CHAIN, END TO END. Everything above starts at `buildSystemStatusState`.
# The last-drive fact is decided one layer UP by a SQL read, and the state fact
# by the drive detector, so this is where a producer rename or a re-shape at any
# link actually fails. US-505's own chain test stops at the pure probe.
# ---------------------------------------------------------------------------


def test_realOrchestratorWithARealDriveLog_paintsThatDriveOnThePanel(tmp_path):
    """
    Given: the REAL orchestrator over a REAL drive_summary table holding drives
           50 and 51
    When: it emits system-status to a real file and the SHIPPED dashboard reads
          that file
    Then: the panel paints "Drive 51" -- the NEWEST drive -- and the DRIVE tile
          reads IDLE.

          SQL -> producer -> orchestrator -> state file -> renderer -> DOM, in
          one assertion, with no hand-written JSON anywhere in it. Two rows, not
          one, so "the newest wins" is under test rather than "the only row is
          shown".
    """
    emitted = _emitToStateFile(
        tmp_path,
        database=_driveSummaryDb(
            [
                (50, "2026-08-30T09:15:00Z", "real"),
                (_ATLAS_DRIVE_ID, "2026-08-31T12:46:00Z", "real"),
            ]
        ),
    )

    assert emitted["drive"]["state"] == "idle", emitted["drive"]
    assert emitted["drive"]["lastDrive"]["driveId"] == _ATLAS_DRIVE_ID, emitted["drive"]

    last = _lastDriveTile(emitted)
    assert last is not None
    assert last["value"] == "Drive " + str(_ATLAS_DRIVE_ID), last
    assert "50" not in " ".join(last["texts"]), last

    drive = _driveTile(emitted)
    assert drive is not None and drive["value"] == "IDLE", drive


def test_realOrchestratorWithOnlySimulatedDrives_paintsTheHonestAbsence(tmp_path):
    """
    Given: the REAL orchestrator over a drive_summary holding ONLY a
           `physics_sim` row -- a simulator-only bench
    When: the panel renders what it emitted
    Then: the tile reads "No recent drive".

          The producer filters on `data_source = 'real'` because presenting a
          bench run as "your last drive" would be a fabrication in the only terms
          the panel has. That filter is three layers away from the tile; this is
          the only test that watches it reach the glass. It also protects the
          test above from passing for the wrong reason -- without it, a producer
          that ignored `data_source` entirely would look identical.
    """
    emitted = _emitToStateFile(
        tmp_path,
        database=_driveSummaryDb([(9, "2026-08-31T10:00:00Z", "physics_sim")]),
    )

    assert emitted["drive"]["lastDrive"] is None, emitted["drive"]

    tile = _lastDriveTile(emitted)
    assert tile is not None
    assert tile["value"] == "No recent drive", tile


def test_realOrchestratorWhileDriving_paintsRecWithNoFabricatedId(tmp_path):
    """
    Given: the REAL orchestrator with a detector reporting a drive in progress
           and no id minted in this process
    When: the panel renders what it emitted
    Then: the DRIVE tile reads REC / "drive ?".

          Exercises `_gatherDriveState`'s second branch on the production path:
          `getCurrentDriveId()` legitimately returns None (US-625 bounded idle,
          or a counter this process never ensured) and the emitter must publish
          `driveId: null` rather than an id it does not have. The renderer's "?"
          then carries that absence to the glass instead of a number.
    """
    emitted = _emitToStateFile(
        tmp_path,
        database=_driveSummaryDb([(_ATLAS_DRIVE_ID, _ATLAS_DRIVE_STARTED, "real")]),
        driveDetector=SimpleNamespace(isDriving=lambda: True),
    )

    assert emitted["drive"]["state"] == "recording", emitted["drive"]
    assert emitted["drive"]["driveId"] is None, emitted["drive"]

    tile = _driveTile(emitted)
    assert tile is not None
    assert tile["value"] == "REC", tile
    assert tile["detail"] == "drive ?", tile


def test_realOrchestratorWithNoDatabase_paintsTheHonestAbsence(tmp_path):
    """
    Given: the REAL orchestrator with no database handle at all -- the boot-order
           window `_gatherLastDriveSummary` re-reads per tick to survive
    When: the panel renders what it emitted
    Then: the tile reads "No recent drive", and the emitted block is null rather
          than a dict of nulls.

          Both halves matter: the payload SHAPE is what the renderer branches on,
          and a producer that started emitting `{"driveId": null}` would still
          render correctly today while being one truthiness check away from
          "Drive null".
    """
    emitted = _emitToStateFile(tmp_path, database=None)

    assert "lastDrive" in emitted["drive"], emitted["drive"]
    assert emitted["drive"]["lastDrive"] is None, emitted["drive"]

    tile = _lastDriveTile(emitted)
    assert tile is not None
    assert tile["value"] == "No recent drive", tile


# ---------------------------------------------------------------------------
# CHARACTERISATION -- the finding, recorded and NOT fixed.
#
# offices/pm/issues/I-us638-last-drive-identity-has-no-surface-on-the-live-face.md
#
# These are NOT approvals. Whoever gives the last-drive fact a surface on the
# live face will fail them ON PURPOSE; the correct response is to read the issue
# and DELETE them deliberately, re-recording the new behaviour -- never to relax
# them. A stale measurement sitting green in a suite is worse than none, because
# it looks authoritative.
# ---------------------------------------------------------------------------


def _liveImu() -> dict:
    """A states/imu payload the shipped `imuView` accepts as LIVE.

    Stamped from the wall clock rather than a fixed instant because `imuView`
    ages the reading against `Date.now()` inside node, and a frozen ISO stamp
    would go stale on its own and send the home slot back to the idle face -- the
    branch this trio exists to distinguish. The negative control below is what
    proves the payload really did flip the face.
    """
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "ts": now,
        "available": True,
        "gLat": 0.01,
        "gLon": 0.02,
        "gMag": 0.03,
        "pitchDeg": 0.5,
        "rollDeg": 0.2,
        "headingDeg": 180.0,
    }


def test_lastDriveTileIsPresentWhileTheMotionFeedIsDead_control():
    """
    Given: no states/imu at all -- the shipped Pi today, where
           `pi.sensors.imu.enabled` defaults false
    When: the panel renders
    Then: the LAST DRIVE tile is on the panel showing drive 51.

          The CONTROL for the characterisation below. Without it, "the tile is
          absent" would also pass on a harness that had stopped rendering the
          home card at all, and the finding would be an artefact.
    """
    tile = _lastDriveTile(_systemStatus(), imu=None)

    assert tile is not None
    assert tile["value"] == "Drive " + str(_ATLAS_DRIVE_ID), tile


def test_theLiveFaceActuallyRenders_negativeControlForTheFinding():
    """
    Given: the finding below is an ABSENCE claim about the live face
    When: the live face is rendered
    Then: its own tiles are really on the panel.

          THE MOST IMPORTANT CONTROL IN THIS FILE, and it is here because the
          first draft of the finding was WRONG WITHOUT IT. `mini_dom.js` had no
          `createElementNS`, and `svgEl` is the first call `renderLiveBody`
          makes, so the live face THREW and left an empty card body -- and the
          characterisation below read that emptiness as evidence that the tile is
          not on the live face. The claim happens to be true, but the test was
          measuring the harness. `createElementNS` is now implemented (additively
          -- no existing behaviour changed) and this control is what stops the
          same crash being mistaken for a measurement again.
    """
    surface = _surface(_systemStatus(), imu=_liveImu())

    assert _tileByLabel(surface, "G-FORCE") is not None, (
        "the live face rendered NOTHING -- every absence claim below is an "
        "artefact of the harness, not a fact about the panel"
    )
    assert _tileByLabel(surface, "HEADING") is not None


def test_liveMotionFeedRemovesTheLastDriveTileFromThePanel_characterisation():
    """
    Given: a LIVE states/imu payload -- the Pi once the sensor bus is wired
    When: the panel renders the same system-status carrying drive 51
    Then: the LAST DRIVE tile is ABSENT FROM THE PANEL ENTIRELY, and no surface
          prints the drive id.

          MEASURED, NOT INFERRED (and see the control above for how nearly it was
          neither), and recorded as a finding rather than fixed (I-us638).
          `idleCardView` is the only builder of the fact and `renderIdleBody` its
          only consumer, so the tile lives on the idle FALLBACK face -- which
          under US-541 IMU-always-on fires only when the motion feed is dead. The
          System card's DRIVE tile prints no id at idle, so US-505's producer
          keeps reading the drive log and nothing shows the answer.

          Asserted across the WHOLE rendered body, not just the home card: the
          claim is "nowhere on the panel", and a check scoped to one card would
          be satisfied by a tile that had merely moved.
    """
    surface = _surface(_systemStatus(), imu=_liveImu())

    # Re-stated locally rather than left to the control above: this test must
    # not be able to pass on a blank face even if it is run alone.
    assert _tileByLabel(surface, "G-FORCE") is not None, "the live face is blank"

    assert _tileByLabel(surface, "LAST DRIVE") is None, (
        "the LAST DRIVE tile is on the live face -- the finding in I-us638 has "
        "been fixed; re-record this measurement and delete this test on purpose"
    )
    body = " ".join(_textOf(surface.tree))
    assert "LAST DRIVE" not in body, body
    assert "Drive " + str(_ATLAS_DRIVE_ID) not in body, body


def test_theDriveTileNeverPrintsADriveIdWhileIdle_characterisation():
    """
    Given: a parked Pi with drive 51 on record
    When: the System card's DRIVE tile is rendered
    Then: it prints no digit at all.

          The second half of I-us638, and the reason the first half MATTERS: the
          System card is reachable on every face, so if the DRIVE tile carried
          the completed-drive id the live-face gap would be cosmetic. It does
          not, so the identity has exactly one surface and that surface is
          conditional. Whoever closes the finding by surfacing the id HERE will
          fail this test -- which is the intended moment to read the issue.
    """
    tile = _driveTile(_systemStatus())

    assert tile is not None
    assert not any(ch.isdigit() for ch in " ".join(tile["texts"])), tile
