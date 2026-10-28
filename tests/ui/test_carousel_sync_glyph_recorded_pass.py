################################################################################
# File Name: test_carousel_sync_glyph_recorded_pass.py
# Purpose/Description: US-633 (F-138, punch-list H2) -- RECORD THE PASS on the
#   top-bar SYNC glyph, on the RENDERED SURFACE, and record the defect the
#   recording exposed.
#
#   WHY THIS FILE EXISTS AT ALL. `syncGlyphState` was referenced by ZERO tests
#   in the repository: the only places `glyph-sync` appeared in the suite
#   checked that the ELEMENT is present and laid out, never its `data-state`.
#   This file turns the glyph's behaviour into evidence.
#
#   THE RULE TODAY (US-917-d, spec s4.3.1; was US-894-c's neutral/amber).
#   Four states, first match wins: `error` (amber) EXACTLY while the
#   provider's verdict has a `sync` member -- amber still means counted
#   (s4.0); `busy` (--blue-busy) while sync.inProgress; `ok` (green) once
#   sync.lastOkTs is on record; else `unknown` (--text-tertiary).
#   `sync.stale` never paints anything. The member-driven cases here add a
#   synthetic `sync` member to the real builder's verdict; the provider's own
#   S1-S3 members are pinned on the generated sync-* fixtures
#   (tests/ui/test_sync_glyph_four_states.py).
#
#   THE I-us633 FINDING (green by default) IS CLOSED by that rule: the old
#   `s.stale === true ? "amber" : "ok"` made GREEN the default for every input
#   that was not literally the boolean true -- a never-synced parked Pi read
#   `OK` above `never` under a green glyph. The characterisations recorded that
#   behaviour and said to RE-RECORD them when it changed; they are re-recorded
#   below against the neutral glyph.
#
#   THE PAYLOAD IS BUILT BY THE REAL PRODUCER. `buildSystemStatusState` and
#   `isSyncStaleWhileDriving` are imported and called, so what is pinned is the
#   producer->consumer contract, not this file's idea of the schema.
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
# 2026-08-31    | Ralph (Rex)  | Initial -- US-633 punch-list H2 recorded pass +
#               |              | the green-by-default finding (I-us633).
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-b): the 2x2 grid and the
#               |              | `SYSTEM · …` summary are retired; the card-text
#               |              | cases read the view's tile; the summary's
#               |              | `SYSTEM · OK` is the verdict's ALL OK.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-c, spec s4.3 I4, Atlas P9):
#               |              | the glyph is NEUTRAL without a `sync` verdict
#               |              | member and amber only with one; the I-us633
#               |              | characterisations are re-recorded; the SYNC
#               |              | tile is retired, so card text is the DATA row.
# 2026-10-27    | Rex (US-917-d)| MOVED PINS (spec s4.3.1): FOUR states, first
#               |              | match wins -- error (a sync member, amber),
#               |              | busy (inProgress, blue), ok (lastOkTs on record,
#               |              | green), unknown (grey). neutral/amber are gone;
#               |              | the reset paints syncGlyphState(null) = unknown.
# ================================================================================
################################################################################

"""US-633 / US-894-c / US-917-d tests: the SYNC glyph's four states."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
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

from pi.splash.system_status_emitter import (  # noqa: E402
    buildSystemStatusState,
    isSyncStaleWhileDriving,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

# The design tokens the shipped stylesheet resolves each glyph state to. Read
# through the real cascade rather than asserted as a colour name.
GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
NEUTRAL = "var(--text-secondary)"
# US-917-d: the busy and unknown looks.
BLUE = "var(--blue-busy)"
GREY = "var(--text-tertiary)"

# Spool S-3 owns the real number; any positive threshold exercises the policy.
_STALE_THRESHOLD_S = 300.0

_NOW = "2026-08-31T10:50:00Z"
_FRESH_SYNC = "2026-08-31T10:49:22Z"
_STALE_SYNC = "2026-08-31T09:00:00Z"

# A `sync` member in US-917-c's shape, added to the REAL builder's verdict
# here (no threshold is handed in, so the builder counts none itself) -- the
# only hand-set field in this file.
_SYNC_MEMBER = {"key": "sync", "reason": "Sync failing at home."}


# ---------------------------------------------------------------------------
# Fixtures -- assembled by the REAL producer, never hand-written JSON.
# ---------------------------------------------------------------------------


def _systemStatus(**overrides: Any) -> dict:
    """A system-status payload from the shipped emitter's own builder.

    Defaults: OBD linked, parked, on wall power, sync healthy. `obdAvailable`
    stays True so `idle` is false and the System card is on screen.
    """
    args: dict[str, Any] = {
        "syncLastOkTs": _FRESH_SYNC,
        "syncStale": False,
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": _NOW,
        "obdAvailable": True,
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


def _emitted(driveState: str, syncLastOkTs: str | None, **overrides: Any) -> dict:
    """A payload whose `stale` bit is DECIDED by the shipped policy function."""
    return _systemStatus(
        driveState=driveState,
        syncLastOkTs=syncLastOkTs,
        syncStale=isSyncStaleWhileDriving(
            driveState, syncLastOkTs, _NOW, thresholdS=_STALE_THRESHOLD_S
        ),
        **overrides,
    )


def _withSyncMember(payload: dict) -> dict:
    """The payload with a `sync` member counted, as US-917 will publish it."""
    out = copy.deepcopy(payload)
    out["verdict"]["members"].append(dict(_SYNC_MEMBER))
    out["verdict"]["issueCount"] = len(out["verdict"]["members"])
    return out


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(routes: dict[str, Any], steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _glyph(payload: Any, steps: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """The sync glyph as the operator sees it -> (data-state, resolved colour)."""
    routes = {} if payload is None else {"/system-status": payload}
    surface = _surface(routes, steps)
    path = surface.pathById("glyph-sync")
    assert path is not None, "no #glyph-sync in the rendered DOM"
    assert surface.rendered(path), "#glyph-sync is in the DOM but not displayed"
    state = path[-1].get("attrs", {}).get("data-state")
    declaration = surface.winningDeclaration(path, "color")
    colour = declaration[0] if declaration else ""
    return (state, colour)


def _syncView(payload: Any) -> dict:
    """systemStatusView through the shipped carousel.js (node probe)."""
    probe = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
    proc = subprocess.run(
        ["node", probe, "systemStatusView", json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _dataRow(payload: Any) -> dict:
    """The DATA row the view builds (US-894-c: it replaced the SYNC tile)."""
    rows = [r for r in _syncView(payload)["rows"] if r["key"] == "data"]
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------------------
# Negative controls FIRST: "must not be amber / green" passes vacuously if the
# harness reads nothing at all.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsTheSyncGlyph_negativeControl():
    """
    Given: every "must not be amber" assertion in this file fails open if the
           harness cannot resolve the glyph
    When: a payload carrying a `sync` member is rendered
    Then: the glyph resolves to a real state AND a real colour (amber).
    """
    # MOVED PIN (US-917-d): the member's state is `error` (was `amber`).
    state, colour = _glyph(_withSyncMember(_systemStatus()))
    assert state == "error", f"harness read no glyph state: {state!r}"
    assert colour == AMBER, f"harness read no glyph colour: {colour!r}"


def test_theHarnessActuallyReadsTheDataRow_negativeControl():
    """The DATA row the card-text cases read exists and carries the stamp."""
    row = _dataRow(_systemStatus())
    assert row["label"] == "DATA"
    assert "synced" in row["value"], row


def test_theStylesheetPaintsGreenOnlyForTheOkState():
    """
    Given: the claims below are colour claims
    When: the shipped stylesheet is resolved for each glyph state in turn
    Then: `ok` is the ONLY state that resolves to green, `amber` resolves to
          amber, and `neutral` to neither.
    """
    tree = rh.runDashboard(routes={"/system-status": _systemStatus()}, viewport=PANEL)[
        "tree"
    ]
    surface = rh.dashboardSurface(tree, viewport=PANEL)
    path = surface.pathById("glyph-sync")
    assert path is not None

    resolved = {}
    for state in ("ok", "amber", "down", "neutral"):
        path[-1]["attrs"]["data-state"] = state
        declaration = surface.winningDeclaration(path, "color")
        resolved[state] = declaration[0] if declaration else NEUTRAL

    assert resolved["ok"] == GREEN, resolved
    assert resolved["amber"] == AMBER, resolved
    assert resolved["neutral"] not in (GREEN, AMBER), resolved
    greens = [s for s, c in resolved.items() if c == GREEN]
    assert greens == ["ok"], f"green is reachable from more than `ok`: {resolved}"


# ---------------------------------------------------------------------------
# THE RULE (US-917-d, s4.3.1): error (member) > busy > ok (lastOkTs) > unknown.
# MOVED PINS: each case below read `neutral` under US-894-c.
# ---------------------------------------------------------------------------


def test_syncGlyph_healthySync_rendersOk():
    """
    Given: a sync that succeeded 38 s ago
    When: the shipped dashboard renders it
    Then: ok, green -- a delivery is on record and no member is counted.
    """
    state, colour = _glyph(_systemStatus())
    assert state == "ok"
    assert colour == GREEN


def test_syncGlyph_atlasDrainingBacklog_isOkNeverAmber_punchListH2():
    """
    Given: Atlas's punch-list H2 shape -- sync working through a backlog
    When: rendered
    Then: ok, never amber: a draining backlog is health, not a fault, and the
          backlog itself is the DATA row's `rows waiting`.
    """
    payload = _systemStatus(syncRowsWaiting=3000)
    assert _glyph(payload)[0] == "ok"
    assert "3,000 rows waiting" in _dataRow(payload)["sentence"]


def test_syncGlyph_aPushRunning_rendersBusyBlue():
    """
    Given: sync.inProgress true (US-917-a) and no member
    When: rendered
    Then: busy, blue -- over the green of the delivery on record.
    """
    state, colour = _glyph(_systemStatus(syncInProgress=True))
    assert state == "busy"
    assert colour == BLUE


def test_syncGlyph_staleWhileRecording_isOk_noMemberNoAmber():
    """
    Given: a drive recording with the last sync well past the threshold, so the
           shipped policy sets `sync.stale`
    When: the glyph renders it
    Then: ok, not amber. `stale` is not a verdict member (Atlas P9) and driving
          is never a sync case (s4.3.1); an amber nobody counted is the s4.0
          false instrument.
    """
    payload = _emitted("recording", _STALE_SYNC, driveId=51)
    assert payload["sync"]["stale"] is True
    assert payload["verdict"]["issueCount"] == 0
    state, colour = _glyph(payload)
    assert state == "ok"
    assert colour != AMBER


@pytest.mark.parametrize("lastOk, want", [(None, "unknown"), ("corrupt-value", "ok")])
def test_syncGlyph_recordingWithNoUsableSync_isNeverAmber(lastOk, want):
    """
    Given: a drive recording with no sync on record, or a corrupt stamp -- the
           policy flags both stale
    When: rendered
    Then: never amber. Null is `unknown`; a non-null stamp is `ok` by the
          s4.3.1 rule (lastOkTs non-null; the glyph does not parse it), and the
          DATA row carries the fact in words, never a raw string.
    """
    payload = _emitted("recording", lastOk, driveId=51)
    assert payload["sync"]["stale"] is True
    assert _glyph(payload)[0] == want
    row = _dataRow(payload)
    assert "corrupt-value" not in row["value"]
    assert row["value"].endswith("no sync on record" if lastOk is None else "synced --")


def test_syncGlyph_withASyncMember_rendersError():
    """
    Given: a verdict that COUNTS sync, with a push running too
    When: rendered
    Then: error, amber -- the member wins over busy (amber over blue).
    """
    payload = _withSyncMember(
        _emitted("recording", _STALE_SYNC, driveId=51, syncInProgress=True)
    )
    state, colour = _glyph(payload)
    assert state == "error"
    assert colour == AMBER


def test_syncGlyph_goesErrorWhenTheMemberArrives_andOkWhenItLeaves():
    """
    Given: a panel that painted a member-less payload
    When: the next poll carries a `sync` member, then the one after drops it
    Then: ok -> error -> ok (amber straight to green on the delivery that
          clears the member). A glyph written once and never updated fails.
    """
    plain = _systemStatus()
    counted = _withSyncMember(plain)
    state, _ = _glyph(
        copy.deepcopy(plain),
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": counted}}, {"flush": 4}],
    )
    assert state == "error"
    state, _ = _glyph(
        copy.deepcopy(counted),
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": plain}}, {"flush": 4}],
    )
    assert state == "ok"


# ---------------------------------------------------------------------------
# THE TYPED ABSENCE: absent stays absent.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("shape", ["absent", "null"])
def test_syncGlyph_syncBlockMissing_rendersUnknown(shape):
    # MOVED PIN (US-917-d): unknown, grey (was neutral).
    payload = _systemStatus()
    if shape == "absent":
        del payload["sync"]
    else:
        payload["sync"] = None
    state, colour = _glyph(payload)
    assert state == "unknown"
    assert colour == GREY


def test_dataRow_syncBlockAbsent_showsNoDateAndNoInventedCount():
    """
    Given: no `sync` block
    When: the DATA row is built
    Then: `no sync on record` and `rows not read` -- NO fabricated stamp and NO
          invented `0 rows waiting` (US-564's defect class).
    """
    payload = _systemStatus()
    del payload["sync"]
    row = _dataRow(payload)
    assert row["value"].endswith("no sync on record"), row
    assert "rows not read" in row["sentence"], row
    assert "0 rows waiting" not in row["sentence"]


def test_syncGlyph_stateFileMissingEntirely_rendersUnknown():
    """No /system-status file at all -> unknown, the markup's starting value
    (MOVED PIN, US-917-d: was neutral)."""
    assert _glyph(None)[0] == "unknown"


def test_syncGlyph_stateFileVanishesAfterACountedRead_doesNotLingerAmber():
    """
    Given: a panel that painted an error (member) glyph
    When: the state file then disappears (the emitter died, tmpfs cleared)
    Then: the glyph returns to UNKNOWN -- `resetSystemGlyphs` paints
          syncGlyphState(null); a lingering paint from a dead emitter is a
          reading nobody is taking any more. (MOVED PIN, US-917-d.)
    """
    state, colour = _glyph(
        _withSyncMember(_systemStatus()),
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}],
    )
    assert state == "unknown", "a dead emitter left the sync glyph painted"
    assert colour != AMBER


def test_syncGlyph_stateFileKeptAfterACountedRead_staysError_control():
    """The control: the same two-step render with the file kept stays error."""
    state, _ = _glyph(
        _withSyncMember(_systemStatus()), steps=[{"flush": 4}, {"flush": 4}]
    )
    assert state == "error"


# ---------------------------------------------------------------------------
# I-us633, RE-RECORDED (US-894-c, then US-917-d). Green now has ONE source, a
# delivery on record (lastOkTs non-null); never-synced is unknown, never green.
# ---------------------------------------------------------------------------


def test_recorded_neverSyncedWhileParked_isUnknownNotGreen():
    """
    Given: a parked Pi that has NEVER completed a sync, 4820 rows waiting
    When: the shipped policy runs and the panel renders it
    Then: the glyph is unknown (it was GREEN under I-us633) and the DATA row
          says `no sync on record` -- no `OK` above `never` anywhere.
    """
    payload = _emitted("idle", None, syncRowsWaiting=4820)
    assert payload["sync"]["stale"] is False, "the producer does not flag a parked Pi"
    state, colour = _glyph(payload)
    assert state == "unknown"
    assert colour != GREEN
    row = _dataRow(payload)
    assert row["value"].endswith("no sync on record"), row
    assert "4,820 rows waiting" in row["sentence"], row


def test_recorded_syncThirtySevenDaysBehindWhileParked_isOk_andDated():
    """
    Given: a parked Pi whose last data stored 2026-07-25 -- 37 days ago, built
           with no S3 threshold (so the provider counts no member)
    When: rendered
    Then: ok, the colour of the last result (s4.3.1; only the provider's sync
          member makes it error), and the row dates it `Jul 25`.
    """
    payload = _emitted("idle", "2026-07-25T10:00:00Z", syncRowsWaiting=48200)
    assert payload["sync"]["stale"] is False
    assert _glyph(payload)[0] == "ok"
    assert _dataRow(payload)["value"].endswith("synced Jul 25")


@pytest.mark.parametrize("stale", ["missing", "true"])
def test_recorded_malformedStale_isIgnored(stale):
    """A `stale` key missing, or the STRING "true": `stale` is never read, so
    the delivery on record decides -- ok (MOVED PIN, US-917-d: was neutral)."""
    payload = _systemStatus()
    if stale == "missing":
        del payload["sync"]["stale"]
    else:
        payload["sync"]["stale"] = "true"
    assert _glyph(payload)[0] == "ok"


def test_theGlyphHasExactlyOneAcquisition_offTheVerdict():
    """
    Given: ssot-design-pattern rule B -- one acquisition, many consumers
    When: carousel.js is read
    Then: `syncGlyphState` is defined once and called from `systemStatusView`
          over the whole payload, plus by the reset with null (MOVED PIN,
          US-917-d) -- it reads the verdict's members and the sync block,
          never `sync.stale` or a second freshness source.
    """
    jsPath = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
    with open(jsPath, encoding="utf-8") as fh:
        body = fh.read()
    assert body.count("syncGlyphState(") == 3, (
        "expected one definition, the view's call and the reset's null call"
    )
    assert "sync: syncGlyphState(data)," in body
    assert "paintSyncGlyph(glyphEls.sync, syncGlyphState(null));" in body
    start = body.index("function syncGlyphState(")
    fn = body[start:body.index("\n  }", start)]
    assert "verdictMemberKeys(data)" in fn
    assert "stale" not in fn
