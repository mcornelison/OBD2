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
#   MOVED PIN (US-898-b1): the ALERTS card now renders states/alerts entries
#   (#alerts-card) instead of the dtc-driven hero + list, so the once-invariant
#   is read off `.warn-row` elements built from provider fixtures. The featured
#   / directive / empty-state / na cases retired with the hero they pinned:
#   there is no featured row (the provider orders, the page features nothing),
#   the empty list is US-898-b2's NONE / NOT CHECKED, and an na code is never
#   an entry (the provider drops it).
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
# 2026-10-20    | Ralph (Rex)  | US-898-b1 -- MOVED PIN: the card renders states/alerts;
#                               the once-invariant re-pointed, hero cases retired.
# ================================================================================
################################################################################

"""US-757 tests: the Alerts card never reads one stored code as two."""

from __future__ import annotations

import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "alerts")


def _alerts(name: str) -> dict:
    """A states/alerts payload written by the real provider (US-898-b1 fixtures)."""
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _textOf(node: dict) -> list[str]:
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _card(alerts: dict) -> dict:
    """Render `alerts`; return the ALERTS card's text + its row count."""
    surface = rh.dashboardSurface(rh.runDashboard(routes={"/alerts": alerts})["tree"])
    path = surface.pathById("alerts-card")
    text = " ".join(_textOf(path[-1])) if path else ""
    return {"text": text, "rows": len(surface.pathsByClass("warn-row"))}


def test_harnessReadsTheAlertsCard_negativeControl():
    """
    Given: every count below is vacuous if the harness finds no card
    When: two codes render
    Then: both identifiers are present in the card text.
    """
    got = _card(_alerts("two-stored-codes-real"))
    assert "P0400" in got["text"] and "P0443" in got["text"], got


def test_twoStoredCodes_eachIdentifierAppearsExactlyOnce():
    """
    Given: P0400 (worst) + P0443 stored -- the in-car state
    When: the card renders
    Then: each code identifier appears once; neither reads as two codes.
    """
    got = _card(_alerts("two-stored-codes-real"))
    assert got["text"].count("P0400") == 1, got
    assert got["text"].count("P0443") == 1, got
    assert got["rows"] == 2, got


def test_oneStoredCode_appearsOnce_andKeepsItsChip():
    """
    Given: exactly one stored code
    When: the card renders
    Then: it appears once and does NOT lose its tier chip.
    """
    alerts = _alerts("two-stored-codes-real")
    alerts["entries"] = alerts["entries"][1:]
    got = _card(alerts)
    assert got["text"].count("P0443") == 1, got
    assert got["rows"] == 1, got
    assert "MINOR" in got["text"], got


def test_countHeader_stillMatchesTheState():
    """
    Given: a live battery WATCH and two stored codes
    When: the card renders
    Then: the header counts three active entries, each code still once.
    """
    got = _card(_alerts("mixed-live-and-stored"))
    assert "3 ACTIVE" in got["text"], got
    assert got["text"].count("P0400") == 1 and got["text"].count("P0443") == 1, got
