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
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the idle face LAST DRIVE cases
#                               retire (LAST DRIVE is on NAV, US-896-b); the
#                               System card cases stay.
# 2026-10-23    | Ralph (Rex)  | US-894-b -- MOVED PIN: the 2x2 grid and the
#                               `SYSTEM · …` summary are retired, and the DRIVE
#                               tile is not painted until its DATA row lands
#                               (US-894-c). The DRIVE cases now read the tile the
#                               VIEW still builds (it feeds the drill), resolve
#                               its colour through the shipped `.tile` cascade,
#                               and open the drill from the verdict line
#                               (parked-only). The summary-count assertions retire.
# 2026-10-23    | Ralph (Rex)  | US-894-c -- MOVED PIN: the DRIVE tile is RETIRED
#                               (spec s4.3, Iris I3: the DATA row's capture word
#                               comes from capture-health, NEVER from the drive
#                               state). Its tile cases are deleted; what survives
#                               is pinned on the DATA row: the drive state does
#                               not decide the word, an unreadable drive block
#                               moves nothing and lists no row, and the page
#                               prints no drive id.
# 2026-10-23    | Ralph (Rex)  | US-894-f -- MOVED PIN: the issue list behind the
#                               verdict is deleted (US-759 closed by the design);
#                               the verdict opens the Pi detail. The idle case
#                               reads that OPENED detail (asserted open, never
#                               vacuous), and the view carries no drill/tiles.
# ================================================================================
################################################################################

"""US-638 tests: drive state and last-drive identity, as the panel renders them."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
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
from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading  # noqa: E402
from pi.obdii.gear_state_emitter import buildGearState  # noqa: E402
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
        # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
        "syncLastOkTs": _FRESH_SYNC,
        # MOVED PIN (US-894-c): syncRows / syncPending dropped -- sync.rows / sync.pending retired (Atlas P7).
        "syncStale": False,
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


def _surface(
    payload: Any,
    steps: list[dict[str, Any]] | None = None,
    imu: Any = None,
    parked: bool = False,
):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet.

    `imu` is left ABSENT by default, which is the shipped Pi today:
    `pi.sensors.imu.enabled` defaults false, so states/imu does not exist and the
    home slot falls back to the idle face -- the only face that renders LAST
    DRIVE. Supplying one is how the finding at the foot of this file is measured.
    """
    routes: dict[str, Any] = {} if payload is None else {"/system-status": payload}
    if imu is not None:
        routes["/imu"] = imu
    if parked:
        # US-894-b: System taps are parked-only -- gear P held past the 8 s hold.
        routes["/gear"] = buildGearState(
            GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW
        )
    tree = rh.runDashboard(
        routes=routes, steps=steps, viewport=PANEL,
        nowMs=_NOW_MS if parked else None,
    )["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


_NOW_MS = 1788187560000  # _NOW as epoch ms

# The detail is rendered only while the overlay is OPEN, so reaching it means
# TAPPING the line the way the operator does. MOVED PIN (US-894-b): that line is
# the verdict (`.sys-verdict`), and the tap only works parked.
# MOVED PIN (US-894-f): the verdict opens the Pi detail; the issue list is gone.
_OPEN_DRILL = [
    {"flush": 4},
    {"advanceMs": 9000, "flush": 4},
    {"clickNth": {"selector": ".sys-verdict", "index": 0}},
    {"flush": 1},
]

def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _view(payload: Any, capture: Any = None) -> dict:
    """systemStatusView through the shipped carousel.js (node probe)."""
    probe = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
    args = [json.dumps(payload)] + ([json.dumps(capture)] if capture is not None else [])
    proc = subprocess.run(
        [_NODE, probe, "systemStatusView", *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _dataRow(payload: Any, capture: Any = None) -> dict:
    """The DATA row (US-894-c), the surface that replaced the DRIVE tile."""
    rows = [r for r in _view(payload, capture)["rows"] if r["key"] == "data"]
    assert len(rows) == 1
    return rows[0]


def _captureHealth(state: str) -> dict:
    """A capture-health payload in the shape the REAL emitter writes."""
    return {"state": state, "lastRowSecondsAgo": None if state == "idle" else 0.4,
            "stallSeconds": 60.0, "reason": None, "ts": _NOW}


def _systemCardText(payload: Any, **kwargs: Any) -> list[str]:
    """The whole System Status card's rendered text, in reading order."""
    surface = _surface(payload, **kwargs)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            return _textOf(path[-1])
    return []


def _drillRows(payload: Any) -> list[str]:
    """The detail behind the verdict, as printed, with the overlay OPEN.

    MOVED PIN (US-894-f): the overlay's head and body text (the Pi detail);
    an overlay that did not open fails here rather than reading empty.
    """
    surface = _surface(payload, steps=_OPEN_DRILL, parked=True)
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None
    assert _textOf(surface.pathById("sys-detail-head")[-1]) == ["PI"]
    return _textOf(surface.pathById("sys-detail-body")[-1])


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS FIRST. A large share of the assertions in this file are
# absence-shaped ("never green", "no fabricated id", "no digit"), and every one
# of them passes vacuously if the harness reads nothing at all. A renamed class
# or a probe crash would turn the whole file green while pinning nothing.
# ---------------------------------------------------------------------------


def test_theStylesheetPaintsGreenOnlyForTheOkLevel():
    """
    Given: this file repeatedly claims the IDLE tile is "not green"
    When: the shipped stylesheet is resolved for each tile level in turn
    Then: `ok` is the ONLY level that resolves to the green token.

          Without this, "not green" only means "the token is not the string ok",
          and a sheet that painted `neutral` green would leave this file passing
          while a parked Pi claimed an active recording.
    """
    # MOVED PIN (US-894-b): no DRIVE tile is painted; any rendered `.tile`
    # carries the same `.tile[data-level] .tile-value` cascade.
    surface = _surface(_systemStatus())
    tiles = surface.pathsByClass("tile")
    assert tiles, "no rendered .tile"
    path = tiles[0]
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


def test_theDriveStateDoesNotDecideTheDataWord_captureHealthDoes():
    """
    Given: Atlas's punch-list 3.4 reading -- `drive.state: "idle"` -- and the
           opposite, a recording drive
    When: the DATA row is built beside a capture-health payload
    Then: the word follows CAPTURE-HEALTH both ways (spec s4.3, Iris I3), and a
          parked Pi's row is never green.

          MOVED PIN (US-894-c): this pinned the DRIVE tile's IDLE / REC. The
          tile is retired; the honest-instrument half that survives is that the
          page never paints recording from a drive-state string.
    """
    parked = _dataRow(_systemStatus(), _captureHealth("idle"))
    assert (parked["word"], parked["look"]) == ("idle", "secondary"), parked

    # A drive "recording" while capture-health says idle: the capture fact wins.
    driving = _dataRow(_systemStatus(driveState="recording", driveId=52),
                       _captureHealth("idle"))
    assert driving["word"] == "idle", driving

    # And the reverse: rows landing on a parked drive state still read recording.
    landing = _dataRow(_systemStatus(), _captureHealth("ok"))
    assert (landing["word"], landing["look"]) == ("recording", "ok"), landing


def test_idleIsNominalNotAFault_theVerdictIsNotMovedByIt():
    """
    Given: a parked Pi with every other source healthy
    When: the System page renders
    Then: the verdict reads the provider's ALL OK.

          MOVED PIN (US-894-b): this pinned `SYSTEM · OK` from the retired
          summary's SYS_LEVEL_RANK. The page counts nothing now; DRIVE=IDLE is
          not a verdict member, so the line stays ALL OK.
    """
    printed = _systemCardText(_systemStatus())

    assert printed[0] == "ALL OK", printed


def test_idleIsNeverListedAsAnIssueInTheDrillDown():
    """
    Given: the verdict opens the detail behind it (US-894-f: the Pi detail;
           the US-509 issue list is deleted)
    When: the overlay is opened on a parked but otherwise healthy Pi
    Then: no DRIVE row appears.

          The other half of the ranking: a green source in a fault list is a
          FABRICATED fault. Asserted on the OPENED overlay rather than on the
          view object, because the row could equally be dropped by the renderer.
    """
    rows = _drillRows(_systemStatus())

    assert [row for row in rows if "DRIVE" in row] == [], rows


def test_unreadableDriveBlock_movesNothingAndListsNoRow():
    """
    Given: a state file with NO drive block at all (an old or truncated file),
           every other source healthy
    When: the page and the drill-down are built
    Then: the DATA row is exactly what it is with the block present, the
          verdict is the provider's, and no DRIVE row is listed.

          MOVED PIN (US-894-c): the DRIVE tile that painted the typed absence
          (and listed it in the drill) is retired with the drive fact's place
          on the page. A row that silently changed with a block it no longer
          reads would be a second, hidden reader.
    """
    capture = _captureHealth("ok")
    assert _dataRow(_withoutDriveBlock(), capture) == _dataRow(_systemStatus(), capture)
    view = _view(_withoutDriveBlock(), capture)
    assert view["verdict"]["text"] == "ALL OK"
    # MOVED PIN (US-894-f): the drill and its tiles are deleted (US-759), so
    # no DRIVE tile or drill row can exist at all.
    assert "tiles" not in view
    assert "drill" not in view


# ---------------------------------------------------------------------------
# SURFACE B -- the LAST DRIVE tile (`drive.lastDrive`).
#
# US-505 covers `idleLastDriveFact` thoroughly as a FUNCTION. None of it renders,
# and its DOM guard is a string grep over carousel.js. Everything below is on the
# painted tile.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# THE INDEPENDENCE OF THE TWO FACTS. One block, two renderers -- so the
# tempting simplification is to gate one on the other, and it would look right in
# every healthy payload. Only a payload whose two halves DISAGREE can tell.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# NO LINGERING. A tile that keeps its last good reading after the producer dies
# is indistinguishable from a healthy one, so the failure is invisible on the
# panel by construction -- a test has to catch it because an operator cannot.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# THE CHAIN, END TO END. Everything above starts at `buildSystemStatusState`.
# The last-drive fact is decided one layer UP by a SQL read, and the state fact
# by the drive detector, so this is where a producer rename or a re-shape at any
# link actually fails. US-505's own chain test stops at the pure probe.
# ---------------------------------------------------------------------------


def test_realOrchestratorWhileDriving_theDataRowReadsCaptureNotTheDrive(tmp_path):
    """
    Given: the REAL orchestrator with a detector reporting a drive in progress
           and no id minted in this process
    When: the page is built from what it emitted, with no capture-health file
    Then: the emitted drive block is the producer's (recording, driveId null)
          and the DATA row reads `--` / `capture not read yet` -- a recording
          drive never stands in for a capture reading (spec s4.3).
    """
    emitted = _emitToStateFile(
        tmp_path,
        database=_driveSummaryDb([(_ATLAS_DRIVE_ID, _ATLAS_DRIVE_STARTED, "real")]),
        driveDetector=SimpleNamespace(isDriving=lambda: True),
    )

    assert emitted["drive"]["state"] == "recording", emitted["drive"]
    assert emitted["drive"]["driveId"] is None, emitted["drive"]

    row = _dataRow(emitted)
    assert row["word"] == "--", row
    assert row["sentence"].startswith("capture not read yet"), row


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


# MOVED PIN (US-896-b): test_liveMotionFeedRemovesTheLastDriveTileFromThePanel_
# characterisation is DELETED on purpose (PM, CIO-approved 2026-10-19). I-us638
# is fixed: LAST DRIVE now lives on the NAV card's trip row (CIO Q1, US-704
# closes on US-896-b), pinned in tests/ui/test_nav_page.py.


def test_theSystemPageNeverPrintsADriveId_characterisation():
    """
    Given: a parked Pi with drive 51 on record
    When: the System page's rows are built
    Then: no row names a drive or prints its id.

          The second half of I-us638, re-recorded (US-894-c): the DRIVE tile is
          retired and the DATA row carries capture and sync, never the
          completed-drive identity -- which lives on the NAV trip row
          (US-896-b).
    """
    view = _view(_systemStatus(), _captureHealth("idle"))
    printed = json.dumps([[r.get("value"), r["sentence"]] for r in view["rows"]])

    assert str(_ATLAS_DRIVE_ID) not in printed, printed
    assert "drive" not in printed.lower(), printed
