################################################################################
# File Name: test_carousel_prior_shutdown_tile.py
# Purpose/Description: US-744 -- the previous shutdown's verdict is RENDERED.
#     US-728 computed it on every boot and published it; nothing under
#     src/pi/ui/ read it (grep for priorShutdown returned zero on 2026-09-21).
#     These tests pin the tile: it reads the published block and never recomputes
#     a verdict, every absence is typed and carries its reason, the verdict
#     carries the age of the boot that recorded it, and NO branch renders a
#     default "clean".
# Author: Rex (US-744)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-744)   | Initial -- verdict, typed absences, age, and
#               |                | the read-only rule.
# ================================================================================
################################################################################
"""US-744: the prior-shutdown tile renders the published verdict, honestly."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js"
)

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

_NOW = "2026-09-22T16:51:36Z"


def _view(fn: str, *args: object) -> object:
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _block(**over: object) -> dict:
    """A priorShutdown block exactly as PriorShutdownSummary.toStatePayload()
    emits it -- the shape measured on the car."""
    block: dict = {
        "verdict": "clean",
        "reason": "graceful",
        "lastStage": None,
        "label": "CLEAN",
        "endedAtTs": None,
        "endedAtAbsence": "end time not recorded",
        "notAfterTs": "2026-09-21T23:20:44Z",
        "notAfterLabel": "next boot recorded (upper bound)",
        "caveat": None,
        "dataQuality": "clock_unsynced",
    }
    block.update(over)
    return block


def _sysState(**over: object) -> dict:
    state: dict = {
        "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": "2026-09-22T16:51:32Z", "rows": 1, "pending": 0, "stale": False},
        "power": {"source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "priorShutdown": _block(),
        "ts": _NOW,
    }
    state.update(over)
    return state


# --------------------------------------------------------------- the verdict


@_NODE_TESTS
def test_cleanVerdict_rendersTheVerdictAndTheBootItDescribes():
    """
    Given: a CLEAN prior-shutdown block
    When: the tile is built
    Then: the verdict is the value, and the detail carries the age of the boot
        that recorded it (AC3 -- a verdict without a boot reference is
        unfalsifiable)
    """
    tile = _view("priorShutdownTile", _block(), _NOW)

    assert tile["value"] == "CLEAN"
    assert "17 h ago" in tile["detail"], tile["detail"]


@_NODE_TESTS
def test_ungracefulVerdict_rendersUngraceful_notClean():
    """An ungraceful shutdown reads UNGRACEFUL."""
    tile = _view(
        "priorShutdownTile",
        _block(verdict="ungraceful", reason="crashed_during_operation",
               label="UNGRACEFUL: ended without a recorded shutdown",
               caveat="a graceful poweroff whose CLEAN_COMPLETE write did not land also reads as ungraceful"),
        _NOW,
    )

    assert tile["value"] == "UNGRACEFUL"
    assert "17 h ago" in tile["detail"]


@_NODE_TESTS
def test_noRecordVerdict_isItsOwnValue_notAnAbsence():
    """
    Given: the NO RECORD verdict -- a row that recorded no prior boot
    When: rendered
    Then: it says NO RECORD. This is a DIFFERENT fact from "not read", and the
        two must not collapse into one string
    """
    tile = _view(
        "priorShutdownTile",
        _block(verdict="no_record", reason="indeterminate_no_record",
               label="NO RECORD: first boot, or no shutdown trail"),
        _NOW,
    )

    assert tile["value"] == "NO RECORD"


# ------------------------------------------------------------- typed absences


@_NODE_TESTS
@pytest.mark.parametrize(
    ("block", "reason"),
    [
        (None, "not read"),
        ({}, "no verdict"),
        (_block(verdict=None), "no verdict"),
        (_block(verdict="something_new"), "unrecognised"),
        ("clean", "not read"),
    ],
    ids=["absent", "empty", "verdictNull", "unknownVerdict", "notAnObject"],
)
def test_everyAbsence_isTypedAndCarriesItsReason_neverClean(block, reason):
    """
    Given: a block that is absent, empty, verdict-less, unrecognised, or not an
        object at all
    When: rendered
    Then: a dash with a reason -- and never the word CLEAN. Showing "clean"
        because there is nothing to show is the failure this subsystem exists
        to prevent
    """
    tile = _view("priorShutdownTile", block, _NOW)

    assert tile["value"] == "—"
    assert reason in tile["detail"], tile["detail"]
    assert "CLEAN" not in tile["value"]
    assert tile["level"] == "neutral"


@_NODE_TESTS
def test_unknownAge_saysSo_ratherThanFabricatingOne():
    """A block with no boot reference renders the verdict with an honest
    'age unknown' -- the dashboard's own idiom -- not a blank or a zero."""
    tile = _view("priorShutdownTile", _block(notAfterTs=None), _NOW)

    assert tile["value"] == "CLEAN"
    assert "age unknown" in tile["detail"]


@_NODE_TESTS
def test_clockUnsyncedVerdict_marksTheAgeAsUnreliable():
    """
    Given: data_quality 'clock_unsynced' -- true on 198 of 296 startup_log rows
        on the car, so this is the common case, not the rare one
    When: rendered
    Then: the age is marked, because it was computed from a pre-NTP stamp
    """
    tile = _view("priorShutdownTile", _block(dataQuality="clock_unsynced"), _NOW)
    clean = _view("priorShutdownTile", _block(dataQuality="full"), _NOW)

    assert "clock" in tile["detail"], tile["detail"]
    assert "clock" not in clean["detail"]


# ------------------------------------------------------------- read-only rule


def _diag(view: dict, key: str) -> dict:
    rows = [d for d in view["drill"]["diagnostics"] if d["key"] == key]
    assert len(rows) == 1, view["drill"]["diagnostics"]
    return rows[0]


@_NODE_TESTS
def test_theVerdictIsInTheDrillDown_readFromThePublishedKey():
    """
    Given: a system-status payload carrying the verdict
    When: the card view is built
    Then: the drill-down lists it as a reference fact. It is NOT a sixth grid
        tile: the card is held to a 4-fact ceiling (US-557), and this story
        forbids re-budgeting the band to make room
    """
    view = _view("systemStatusView", _sysState())

    row = _diag(view, "priorShutdown")
    assert row["label"] == "LAST STOP"
    assert row["text"].startswith("CLEAN · ")
    assert "priorShutdown" not in view["tiles"]


@_NODE_TESTS
def test_theVerdictIsAlwaysListed_evenWhenTheProducerIsDark():
    """
    Given: no priorShutdown block at all -- the state the car was in before
        US-744 wired the producer
    When: the card view is built
    Then: the row is STILL listed, saying it was not read. A row that vanishes
        when the producer goes dark is exactly how this verdict stayed
        invisible from US-728 until now
    """
    view = _view("systemStatusView", _sysState(priorShutdown=None))

    assert _diag(view, "priorShutdown")["text"].startswith("— · not read")
    assert view["drill"]["tappable"] is True


@_NODE_TESTS
def test_aVerdictIsNeverAnIssue_theSummaryStaysOk():
    """
    Given: an UNGRACEFUL verdict from a previous boot
    When: the card summarises
    Then: SYSTEM still reads OK and the issue list stays empty. The verdict is
        HISTORY, not a live fault; an amber tile would make the card cry wolf
        for the whole session about a shutdown that already happened
    """
    view = _view(
        "systemStatusView",
        _sysState(priorShutdown=_block(verdict="ungraceful", label="UNGRACEFUL: x")),
    )

    assert view["summary"]["text"] == "SYSTEM · OK"
    assert view["drill"]["rows"] == []
    assert "UNGRACEFUL" in _diag(view, "priorShutdown")["text"]


def test_theRendererComputesNoVerdictOfItsOwn():
    """
    Given: carousel.js
    When: searched for the producer's classification inputs
    Then: it never reads prior_boot_clean / startup_log / the reason codes --
        it renders the published verdict and nothing else (AC4)
    """
    source = open(_JS, encoding="utf-8").read()
    # The producer's INPUT columns and reason codes. Classifying a verdict here
    # would need one of these; rendering the published one needs none.
    # ("startup_log" is deliberately not on this list: the tile names it in the
    # operator-facing absence reason, which is words, not a second read.)
    for forbidden in (
        "prior_boot_clean",
        "prior_boot_reason",
        "prior_last_entry_ts",
        "poweroff_accepted_unfinalized",
        "crashed_during_operation",
        "wedged_before_poweroff",
    ):
        assert forbidden not in source, forbidden
    # It reads the published key, which is the whole point of the story.
    assert re.search(r"\bpriorShutdown\b", source)
