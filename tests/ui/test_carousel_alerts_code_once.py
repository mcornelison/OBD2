################################################################################
# File Name: test_carousel_alerts_code_once.py
# Purpose/Description: US-757 (F-123) -- the Alerts card renders every stored
#   code EXACTLY ONCE.
#
#   THE DEFECT, ESTABLISHED. The "featured" block was NOT a selection. Its code
#   is `alertableCodes(codes)[0]` -- the head of the same worst-first ordering
#   the list uses -- so the worst code was simply drawn twice: once as the hero
#   block, once as the first row. With P0400 + P0443 stored, P0400 read as two
#   codes and P0443 as one. No user choice ever picks it, so there is no
#   "selected item" to cue; it is a straightforward bug.
#
#   THE FIX, AND WHY THIS SHAPE. Space is scarce at 3.5 inches, so the
#   duplication is REMOVED rather than decorated: the worst code's ROW is now
#   the featured entry (it carries the tier border + the directive line), and
#   there is no separate hero element. Every code keeps its tappable row, and
#   the single-code case keeps its directive.
#
#   Read off the RENDERED surface (render_harness boots the shipped carousel.js
#   over the shipped markup) -- a correct `alertsCardView` proves nothing about
#   what the operator reads. Severities below are fixture labels chosen to
#   exercise the tiers, not claims about any code's real classification.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-757 each code renders once.
# ================================================================================
################################################################################

"""US-757 tests: the Alerts card never reads one stored code as two."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# Shorts deliberately never contain a code identifier, so counting a code's
# occurrences in the card text counts code ENTRIES, not description words.
_WORST = {"code": "P0400", "severity": "watch", "short": "EGR flow", "status": "stored"}
_OTHER = {"code": "P0443", "severity": "minor", "short": "EVAP purge", "status": "stored"}
_NA = {"code": "P1750", "severity": "na", "short": "Auto-trans solenoid", "status": "stored"}


def _dtcState(codes: list[dict[str, Any]]) -> dict:
    """A completed-read `dtc` payload in the emitter's shape."""
    return {
        "codes": codes,
        "mil": bool(codes),
        "newSinceTs": None,
        "source": {"dtc": {"available": True, "reason": None}},
        "ts": "2026-09-14T15:54:00Z",
    }


def _textOf(node: dict) -> list[str]:
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _card(codes: list[dict[str, Any]]) -> dict:
    """Render `codes`; return the Alerts card's text + its entry-element counts."""
    surface = rh.dashboardSurface(
        rh.runDashboard(routes={"/dtc": _dtcState(codes)})["tree"]
    )
    text = ""
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "dtc":
            text = " ".join(_textOf(path[-1]))
            break
    return {
        "text": text,
        "rows": len(surface.pathsByClass("dtc-row")),
        "featured": len(surface.pathsByClass("dtc-hero")),
    }


def test_harnessReadsTheAlertsCard_negativeControl():
    """
    Given: every count below is vacuous if the harness finds no card
    When: two codes render
    Then: both identifiers are present in the card text.
    """
    got = _card([_WORST, _OTHER])
    assert "P0400" in got["text"] and "P0443" in got["text"], got


def test_twoStoredCodes_eachIdentifierAppearsExactlyOnce():
    """
    Given: P0400 (worst) + P0443 stored -- the in-car state
    When: the card renders
    Then: each code identifier appears once; neither reads as two codes.
    """
    got = _card([_OTHER, _WORST])
    assert got["text"].count("P0400") == 1, got
    assert got["text"].count("P0443") == 1, got
    assert got["rows"] == 2, got


def test_twoStoredCodes_onlyTheWorstIsFeatured_andItIsItsOwnRow():
    """
    Given: the same two codes
    When: the card renders
    Then: exactly one entry is featured, it is a row (not an extra block), and
          it carries the worst code's directive.
    """
    got = _card([_OTHER, _WORST])
    assert got["featured"] == 1, got
    assert got["rows"] == 2, got
    assert "DRIVE GENTLY · GET DIAGNOSED" in got["text"], got


def test_oneStoredCode_appearsOnce_andKeepsItsDirective():
    """
    Given: exactly one stored code
    When: the card renders
    Then: it appears once and does NOT lose its tier chip or directive.
    """
    got = _card([_OTHER])
    assert got["text"].count("P0443") == 1, got
    assert got["rows"] == 1, got
    assert got["featured"] == 1, got
    assert "MINOR" in got["text"], got
    assert "SAFE TO CLEAR ONCE LOGGED" in got["text"], got


def test_zeroStoredCodes_emptyStateUnchanged():
    """
    Given: a completed read with no codes
    When: the card renders
    Then: the honest all-clear, no rows, no featured entry.
    """
    got = _card([])
    assert "No stored codes" in got["text"], got
    assert got["rows"] == 0 and got["featured"] == 0, got
    assert "0 stored · 0 pending" in got["text"], got


def test_countHeader_stillMatchesTheState():
    """
    Given: two stored codes and one pending
    When: the card renders
    Then: the header reads 2 stored · 1 pending (the count was never the bug).
    """
    pending = {**_NA, "code": "P0301", "severity": "stop", "status": "pending"}
    got = _card([_WORST, _OTHER, pending])
    assert "2 stored · 1 pending" in got["text"], got
    assert got["text"].count("P0301") == 1, got


def test_naOnly_isListedButNeverFeatured():
    """
    Given: only an `na` code (never a hero, S-12)
    When: the card renders
    Then: it is listed once, nothing is featured, no false all-clear.
    """
    got = _card([_NA])
    assert got["text"].count("P1750") == 1, got
    assert got["rows"] == 1 and got["featured"] == 0, got
    assert "No stored codes" not in got["text"], got
