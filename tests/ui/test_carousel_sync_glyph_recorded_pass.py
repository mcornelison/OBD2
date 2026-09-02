################################################################################
# File Name: test_carousel_sync_glyph_recorded_pass.py
# Purpose/Description: US-633 (F-138, punch-list H2) -- RECORD THE PASS on the
#   top-bar SYNC glyph, on the RENDERED SURFACE, and record the defect the
#   recording exposed.
#
#   WHY THIS FILE EXISTS AT ALL. `syncGlyphState` is referenced by ZERO tests in
#   the repository. The only two places `glyph-sync` appears in the suite
#   (test_topbar_three_column_grid.py, tests/deploy/test_dashboard_kit.py) loop
#   over three glyph IDs checking that the ELEMENT is present and laid out --
#   neither reads its `data-state`. So the story's premise is literally true
#   here: Atlas observed the glyph green while sync drained 500 rows/5 s and
#   believed it correct, and that belief was the only thing holding the
#   behaviour up. This file turns it into evidence.
#
#   THE PASS IS REAL AND IS RECORDED BELOW. Healthy -> `ok`; stale -> `amber`;
#   an absent `sync` block -> `neutral` with the word `unavailable`; and a state
#   file that VANISHES after a good read returns the glyph to `neutral` rather
#   than leaving a green one lingering. Atlas's own draining scenario is pinned
#   verbatim. Every one of those is correct today.
#
#   FINDING RECORDED, NOT FIXED (sprint contract: a VERIFY story that finds a
#   defect RECORDS it and FILES a fix story -- it must NEVER quietly become the
#   fix, because that hides the defect rate the sweep exists to measure).
#   `syncGlyphState` reads `s.stale === true ? "amber" : "ok"`. The ELSE branch
#   is an affirmative claim, so GREEN is the default for every input that is not
#   literally the boolean true. Three surfaces of that one root, all confirmed
#   on the rendered panel and all pinned below as CHARACTERISATION:
#     1. A Pi that has NEVER synced, parked, 4820 rows pending, renders
#        `SYNC / OK / never` under a GREEN glyph and a `SYSTEM . OK` summary.
#        "OK" is printed directly above the word "never".
#     2. A last-sync 37 days old with 48200 rows pending, parked -- same.
#     3. A malformed `stale` (key missing, or the STRING "true") -- green.
#   Filed as offices/pm/issues/I-us633-sync-glyph-defaults-to-green.md.
#
#   NEITHER HALF IS WRONG ALONE, which is why no existing test catches it.
#   `isSyncStaleWhileDriving` deliberately declines to flag a PARKED Pi (its
#   docstring: a parked Pi catches up on the next WiFi return) and `syncTile`
#   correctly renders `lastOkTs: null` as the honest word `never`. The lie is in
#   the composition -- the same two-correct-halves shape as US-494/495/498, and
#   the reason every assertion here goes through the SHIPPED renderer over the
#   SHIPPED markup rather than calling `syncGlyphState` directly.
#
#   THE PAYLOAD IS BUILT BY THE REAL PRODUCER. `buildSystemStatusState` and
#   `isSyncStaleWhileDriving` are imported and called, so what is pinned is the
#   producer->consumer contract, not this file's idea of the schema. A test that
#   hand-writes the JSON stays green through a producer rename (the US-628
#   lesson).
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
# ================================================================================
################################################################################

"""US-633 tests: the SYNC glyph reports drain state honestly -- the recorded pass."""

from __future__ import annotations

import copy
import os
import shutil
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

# The shipped panel, not the harness default. A glyph is a 3.5" one-bit signal;
# measuring it at 1920x1080 would resolve a media query the operator never sees.
PANEL = (480, 320)

# Spelled as escapes, never literals -- this file is written and re-read on a
# Windows SMB share where a raw em-dash / middle dot has been mangled before
# (the same precaution test_carousel_sync_stamp.py takes, for the same reason).
EM_DASH = "—"

# The design tokens the shipped stylesheet resolves each glyph state to. Read
# through the real cascade rather than asserted as a colour name, so a sheet
# that repainted `amber` green would fail here instead of passing on a string.
GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
NEUTRAL = "var(--text-secondary)"

# Spool S-3 owns the real number; any positive threshold exercises the policy.
_STALE_THRESHOLD_S = 300.0

_NOW = "2026-08-31T10:50:00Z"
_FRESH_SYNC = "2026-08-31T10:49:22Z"


# ---------------------------------------------------------------------------
# Fixtures -- assembled by the REAL producer, never hand-written JSON.
# ---------------------------------------------------------------------------


def _systemStatus(**overrides: Any) -> dict:
    """A system-status payload from the shipped emitter's own builder.

    Defaults describe the state Atlas photographed: OBD linked, parked, on wall
    power, sync healthy. `obdAvailable` stays True on purpose -- the emitter's
    `idle` flag is (not obdAvailable) and not recording, and a True `idle`
    sends the dashboard to the idle face where there is no System card to read.
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
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


def _emitted(driveState: str, syncLastOkTs: str | None, **overrides: Any) -> dict:
    """A payload whose `stale` bit is DECIDED by the shipped policy function.

    The point of routing through `isSyncStaleWhileDriving` rather than passing a
    literal is that the glyph is then pinned against the producer's real verdict.
    A policy change that stopped flagging a stale drive would fail these tests,
    which is the failure the operator would actually feel.
    """
    return _systemStatus(
        driveState=driveState,
        syncLastOkTs=syncLastOkTs,
        syncStale=isSyncStaleWhileDriving(
            driveState, syncLastOkTs, _NOW, thresholdS=_STALE_THRESHOLD_S
        ),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Reading the rendered panel.
# ---------------------------------------------------------------------------


def _surface(routes: dict[str, Any], steps: list[dict[str, Any]] | None = None):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _glyph(payload: Any, steps: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """The sync glyph as the operator sees it -> (data-state, resolved colour).

    Returns the COLOUR as well as the state because "non-green" is the claim the
    story makes, and a state token only means non-green while the stylesheet
    agrees. Resolving through `winningDeclaration` makes the two travel together.
    """
    routes = {} if payload is None else {"/system-status": payload}
    surface = _surface(routes, steps)
    path = surface.pathById("glyph-sync")
    assert path is not None, "no #glyph-sync in the rendered DOM"
    assert surface.rendered(path), "#glyph-sync is in the DOM but not displayed"
    state = path[-1].get("attrs", {}).get("data-state")
    declaration = surface.winningDeclaration(path, "color")
    colour = declaration[0] if declaration else ""
    return (state, colour)


def _cardText(payload: Any, steps: list[dict[str, Any]] | None = None) -> list[str]:
    """The System Status card's rendered text, in reading order."""
    routes = {} if payload is None else {"/system-status": payload}
    surface = _surface(routes, steps)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "system-status":
            return _textOf(path[-1])
    return []


def _textOf(node: dict) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


# ---------------------------------------------------------------------------
# Negative controls FIRST. Several assertions below are "must not be green",
# which passes vacuously if the harness reads nothing at all -- a renamed ID or
# a probe crash would turn this whole file green while pinning nothing.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsTheSyncGlyph_negativeControl():
    """
    Given: every "must not be green" assertion in this file fails open if the
           harness cannot resolve the glyph
    When: an unmistakably healthy payload is rendered
    Then: the glyph resolves to a real state AND a real colour.
    """
    state, colour = _glyph(_systemStatus())
    assert state == "ok", f"harness read no glyph state: {state!r}"
    assert colour == GREEN, f"harness read no glyph colour: {colour!r}"


def test_theHarnessActuallyReadsTheSystemCard_negativeControl():
    """
    Given: the card-text assertions below are also absence-shaped
    When: a healthy payload is rendered
    Then: the SYNC tile's label is in the card text.
    """
    text = _cardText(_systemStatus())
    assert "SYNC" in text, f"harness read nothing from the System card: {text!r}"


def test_theStylesheetPaintsGreenOnlyForTheOkState():
    """
    Given: this file's central claim is "non-green when stale or failing"
    When: the shipped stylesheet is resolved for each glyph state in turn
    Then: `ok` is the ONLY state that resolves to the green token.

          Without this, every "non-green" assertion is really just "the token is
          not the string ok", and a stylesheet that painted `amber` green would
          leave the file passing while the panel lied.
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
    greens = [s for s, c in resolved.items() if c == GREEN]
    assert greens == ["ok"], f"green is reachable from more than `ok`: {resolved}"


# ---------------------------------------------------------------------------
# THE RECORDED PASS (validationCriteria 1). Atlas observed the glyph green while
# sync drained 500 rows/5 s and believed it correct. It is correct, and this is
# now evidence rather than a memory.
# ---------------------------------------------------------------------------


def test_syncGlyph_healthySync_rendersGreen():
    """
    Given: a sync that succeeded 38 s ago with nothing pending
    When: the shipped dashboard renders it
    Then: the glyph is `ok` and the stylesheet paints it green.
    """
    assert _glyph(_systemStatus()) == ("ok", GREEN)


def test_syncGlyph_atlasDrainingBacklog_staysGreen_punchListH2():
    """
    Given: THE OBSERVATION THIS STORY RECORDS -- Atlas watched sync drain a
           backlog at 500 rows / 5 s (punch list H2) and the glyph stayed green
    When: that shape is rendered: a large recent batch and a backlog still going
    Then: green, because sync is WORKING.

          A draining backlog is health, not a fault. Pinned explicitly so that a
          future "pending > 0 must be amber" change has to argue with the
          measurement rather than quietly invert it.
    """
    assert _glyph(_systemStatus(syncRows=500, syncPending=3000)) == ("ok", GREEN)


def test_syncCard_healthySync_showsOkAndTheStamp():
    """
    Given: a healthy sync
    When: the System card renders
    Then: the SYNC tile reads OK and carries the last-success stamp, and the
          summary line is not claiming a fault.
    """
    text = _cardText(_systemStatus())
    assert "SYNC" in text
    assert "OK" in text
    assert any(t.startswith("Aug 31, 2026") for t in text), text


def test_syncGlyph_recordingWithAFreshSync_isStillGreen():
    """
    Given: a drive RECORDING with a sync that succeeded 38 s ago
    When: the shipped policy decides staleness and the glyph renders it
    Then: green -- the amber has to be EARNED.

          This is the control for the negative case below. Without it, a
          renderer that ambered on every recording drive would satisfy the
          "turns non-green when stale" test while being useless.
    """
    payload = _emitted("recording", _FRESH_SYNC, driveId=51)
    assert payload["sync"]["stale"] is False
    assert _glyph(payload) == ("ok", GREEN)


# ---------------------------------------------------------------------------
# THE NEGATIVE CASE the story requires: non-green when sync is stale or failing.
# ---------------------------------------------------------------------------


def test_syncGlyph_staleWhileRecording_rendersAmberNotGreen():
    """
    Given: a drive recording with the last sync well past the threshold
    When: the shipped policy flags it and the glyph renders that verdict
    Then: amber, and specifically NOT green -- un-backed-up drive data (I-4).
    """
    payload = _emitted("recording", "2026-08-31T09:00:00Z", driveId=51)
    assert payload["sync"]["stale"] is True
    state, colour = _glyph(payload)
    assert state == "amber"
    assert colour != GREEN
    assert colour == AMBER


def test_syncGlyph_recordingWithNoSyncEverRecorded_rendersAmber():
    """
    Given: a drive recording on a Pi that has never synced at all
    When: the policy runs
    Then: amber. We never claim a freshness we cannot prove.
    """
    payload = _emitted("recording", None, driveId=51)
    assert payload["sync"]["stale"] is True
    assert _glyph(payload)[0] == "amber"


def test_syncGlyph_recordingWithAnUnparseableStamp_rendersAmber():
    """
    Given: a corrupt `lastOkTs` while recording
    When: the policy fails to parse it
    Then: amber, never a confident green from an unreadable field.
    """
    payload = _emitted("recording", "corrupt-value", driveId=51)
    assert payload["sync"]["stale"] is True
    assert _glyph(payload)[0] == "amber"


def test_syncCard_stale_namesSyncInTheSummaryLine():
    """
    Given: a stale sync while recording
    When: the System card renders
    Then: the tile reads STALE and the one-glance summary NAMES sync as the
          unhappy source -- the glyph says "something", the card says "what".
    """
    text = _cardText(_emitted("recording", "2026-08-31T09:00:00Z", driveId=51))
    assert "STALE" in text
    assert any("SYNC" in t and "STALE" in t for t in text), text


def test_syncGlyph_goesGreenToAmberWhenSyncGoesStale():
    """
    Given: a panel that has already read a HEALTHY sync and painted it green
    When: the next poll returns a stale sync
    Then: the glyph moves to amber.

          The single-render tests above cannot catch a glyph that is written
          once and never updated; this one can.
    """
    healthy = _systemStatus()
    stale = _emitted("recording", "2026-08-31T09:00:00Z", driveId=51)
    state, colour = _glyph(
        copy.deepcopy(healthy),
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": stale}}, {"flush": 4}],
    )
    assert state == "amber"
    assert colour != GREEN


# ---------------------------------------------------------------------------
# THE TYPED ABSENCE (validationCriteria 3): the absent case renders as absence,
# never as a plausible-looking value.
# ---------------------------------------------------------------------------


def test_syncGlyph_syncBlockAbsent_rendersNeutralNotGreen():
    """
    Given: a system-status payload with no `sync` block at all
    When: the glyph renders
    Then: neutral grey -- not green, not amber.

          Amber would be a claim about a measurement nobody took (the ARCH-007
          WiFi-glyph rule); green would be the punch-list 2.1 defect, an unread
          value painted as a settled result.
    """
    payload = _systemStatus()
    del payload["sync"]
    state, colour = _glyph(payload)
    assert state == "neutral"
    assert colour not in (GREEN, AMBER)


def test_syncGlyph_syncBlockNull_rendersNeutralNotGreen():
    """
    Given: `sync` present but null
    When: the glyph renders
    Then: neutral. A key that exists with no content is still nothing measured.
    """
    payload = _systemStatus()
    payload["sync"] = None
    assert _glyph(payload)[0] == "neutral"


def test_syncCard_syncBlockAbsent_showsUnavailableNeverAZeroOrADate():
    """
    Given: no `sync` block
    When: the System card renders
    Then: the tile shows the em-dash and the word `unavailable`, and carries NO
          fabricated stamp and NO invented `0 pending` (US-564's defect class).
    """
    payload = _systemStatus()
    del payload["sync"]
    text = _cardText(payload)
    assert EM_DASH in text, text
    assert "unavailable" in text, text
    assert not any(t.startswith("Aug ") or t.startswith("Jul ") for t in text), text
    assert "0 pending" not in " ".join(text)


def test_syncGlyph_stateFileMissingEntirely_rendersNeutral():
    """
    Given: no /system-status file at all (the pre-first-write boot window)
    When: the dashboard polls and 404s
    Then: neutral -- the markup's own starting value, never a guess.
    """
    assert _glyph(None)[0] == "neutral"


def test_syncGlyph_stateFileVanishesAfterAGoodRead_doesNotLingerGreen():
    """
    Given: a panel that has already read a healthy sync and painted it green
    When: the state file then disappears (the emitter died, tmpfs cleared)
    Then: the glyph returns to NEUTRAL.

          THE HIGHEST-VALUE PIN IN THIS FILE. A lingering green is
          indistinguishable from a healthy one, so this failure mode is
          invisible on the panel by construction -- exactly the class of defect
          a test has to catch because an operator cannot. carousel.js has an
          explicit `resetSystemGlyphs` guard for it and, until now, nothing
          held that guard in place.
    """
    state, colour = _glyph(
        copy.deepcopy(_systemStatus()),
        steps=[{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}],
    )
    assert state == "neutral", "a dead emitter left the sync glyph green"
    assert colour != GREEN


def test_syncGlyph_stateFileKeptAfterAGoodRead_staysGreen_control():
    """
    Given: the same two-step render, but the file does NOT vanish
    When: the second poll returns the same healthy payload
    Then: still green.

          The control for the test above: without it, a harness whose second
          step reset everything unconditionally would pass the no-stale-green
          test while proving nothing.
    """
    state, _ = _glyph(
        copy.deepcopy(_systemStatus()), steps=[{"flush": 4}, {"flush": 4}]
    )
    assert state == "ok"


# ---------------------------------------------------------------------------
# THE FINDING -- RECORDED, NOT FIXED. See I-us633.
#
# `syncGlyphState` is `s.stale === true ? "amber" : "ok"`, so GREEN is the
# DEFAULT for every input that is not literally the boolean true. The producer's
# `stale` flag means "stale WHILE DRIVING" and is False for a parked Pi by
# design; the glyph promotes that "not flagged" into an affirmative "healthy".
#
# These tests assert what the panel does TODAY. They are expected to FAIL when
# the defect is fixed, and that is deliberate -- whoever fixes it is told, at
# the point of the change, that this file has an opinion and that the measured
# behaviour was recorded rather than assumed. Do not "repair" them by relaxing
# the assertion; re-record them against the new behaviour.
# ---------------------------------------------------------------------------


def test_characterisation_neverSyncedWhileParked_currentlyRendersGreen():
    """
    Given: a parked Pi that has NEVER completed a sync, 4820 rows pending
    When: the shipped policy runs and the panel renders it
    Then: TODAY the glyph is GREEN and the tile reads `OK` above the word
          `never`.

          This is the defect, at its clearest: the affirmative verdict `OK`
          printed directly above `never`, under a green glyph, with the
          one-glance summary reading `SYSTEM . OK`. Filed as I-us633.
    """
    payload = _emitted("idle", None, syncRows=0, syncPending=4820)
    assert payload["sync"]["stale"] is False, "the producer does not flag a parked Pi"

    state, colour = _glyph(payload)
    assert state == "ok", "I-us633 behaviour changed -- re-record this measurement"
    assert colour == GREEN

    text = _cardText(payload)
    assert "OK" in text and "never" in text, text
    assert any("SYSTEM" in t and "OK" in t for t in text), text


def test_characterisation_syncThirtySevenDaysBehindWhileParked_currentlyRendersGreen():
    """
    Given: a parked Pi whose last successful sync was 2026-07-25 -- 37 days ago
           -- with 48200 rows pending
    When: the panel renders it
    Then: TODAY, green.

          The sibling of the case above and, unlike it, one where the stamp on
          the tile does carry the age. Recorded separately because the fix for
          the two may differ: `never` has no defensible green at all, while
          "37 days behind while parked" is at least arguably the documented
          parked-catches-up policy. Both are green today.
    """
    payload = _emitted("idle", "2026-07-25T10:00:00Z", syncRows=12, syncPending=48200)
    assert payload["sync"]["stale"] is False
    assert _glyph(payload) == ("ok", GREEN)


def test_characterisation_staleKeyMissing_currentlyRendersGreen():
    """
    Given: a malformed `sync` block with no `stale` key at all
    When: the glyph renders
    Then: TODAY, green.

          A field that was never written is not a measurement, and the same file
          already knows this: `wifiGlyphState` returns neutral for a source that
          is "available but ungradeable -- still not a claim". The sync glyph is
          the outlier. Part of I-us633, same root: the unconditional else.
    """
    payload = _systemStatus()
    del payload["sync"]["stale"]
    assert _glyph(payload) == ("ok", GREEN)


def test_characterisation_staleIsTheStringTrue_currentlyRendersGreen():
    """
    Given: `stale` arriving as the STRING "true" rather than the boolean
    When: the strict `=== true` comparison fails
    Then: TODAY, green -- the failure mode of a strict check whose else branch
          is an affirmative claim rather than a neutral one. Part of I-us633.
    """
    payload = _systemStatus()
    payload["sync"]["stale"] = "true"
    assert _glyph(payload) == ("ok", GREEN)


def test_theGlyphHasExactlyOneAcquisitionOfSyncState():
    """
    Given: ssot-design-pattern rule B -- one acquisition, many consumers
    When: carousel.js is read
    Then: `syncGlyphState` is called exactly once, from `systemStatusView`,
          off the same `data.sync` the SYNC TILE reads.

          Pinned because the obvious "fix" for I-us633 is to reach for a second
          source (a row count, a separate freshness probe) to decide the colour.
          That is how this project got a latched magnetometer. The honest fix
          reads more of the block it already has.
    """
    jsPath = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
    with open(jsPath, encoding="utf-8") as fh:
        body = fh.read()
    assert body.count("syncGlyphState(") == 2, (
        "expected exactly one definition and one call site of syncGlyphState"
    )
    assert "sync: syncGlyphState(data.sync)" in body
