################################################################################
# File Name: test_carousel_gear_reason_distinctness.py
# Purpose/Description: US-739 -- the gear tile's reason strings must be PAIRWISE
#     DISTINCT. The existing underscore sweep cannot establish that: gearReasonText
#     falls back to reason.replace(/_/g," "), so an unknown token already renders
#     underscore-free and the sweep passes on an unchanged file -- an inert guard
#     for exactly the two tokens this story adds. These tests compare the rendered
#     strings against each other, and pin that every token the producer exports
#     has an EXPLICIT entry rather than riding the fallback.
# Author: Rex (US-739)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-739)   | Initial -- distinctness, explicit entries, the
#               |                | ruled wording and the width envelope.
# ================================================================================
################################################################################
"""US-739: every gear reason renders as its own words, not a shared string."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

import pi.obdii.gear_derivation as gd

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js"
)

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# The longest string the shipped table already establishes: "too slow to tell".
_WIDTH_ENVELOPE = 16


def _producerTokens() -> list[str]:
    return [getattr(gd, name) for name in gd.__all__ if name.startswith("REASON_")]


def _view(fn: str, *args: object) -> object:
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _explicitEntries() -> dict[str, str]:
    """The GEAR_REASON_TEXT table as literally written in the source."""
    source = open(_JS, encoding="utf-8").read()
    block = source[source.index("var GEAR_REASON_TEXT = {"):]
    block = block[: block.index("};")]
    return dict(re.findall(r"(\w+):\s*\"([^\"]*)\"", block))


@_NODE_TESTS
def test_everyProducerReasonRendersADistinctString():
    """
    Given: every REASON_* token the deriver exports
    When:  each is rendered
    Then:  no two share a string. Two facts wearing one word is the defect the
        whole typed-absence family exists to remove
    """
    rendered = {token: _view("gearReasonText", token) for token in _producerTokens()}

    duplicates = [s for s in rendered.values() if list(rendered.values()).count(s) > 1]
    assert not duplicates, rendered


@_NODE_TESTS
@pytest.mark.parametrize(
    ("token", "text"),
    [("link_down", "no link"), ("settling_park", "confirming park")],
)
def test_theNewTokensCarryThePmRuledWording(token: str, text: str):
    """The operator wording is the PM's and the CIO's, not the developer's."""
    assert _view("gearReasonText", token) == text


def test_everyProducerReasonHasAnExplicitEntry():
    """
    Given: the source table
    When:  compared with the producer's exported tokens
    Then:  each has its own entry. The replace(/_/g," ") fallback is for tokens
        that do not exist YET -- a shipped token riding it reaches the driver as
        de-underscored machine vocabulary nobody chose
    """
    entries = _explicitEntries()
    missing = [t for t in _producerTokens() if t not in entries]
    assert missing == [], missing


def test_theNewStringsFitTheWidthEnvelope():
    """AC4: both sit inside the envelope the shipped strings establish. If one
    did not fit, the story says STOP AND REPORT rather than abbreviate."""
    entries = _explicitEntries()
    for token in ("link_down", "settling_park"):
        assert len(entries[token]) <= _WIDTH_ENVELOPE, entries[token]


@_NODE_TESTS
def test_theUnderscoreSweepAloneCouldNotCatchThis():
    """
    Given: a token with NO entry in the table
    When:  rendered
    Then:  it still comes back underscore-free -- which is why the existing
        sweep passes on a file missing these entries, and why distinctness has
        to be asserted separately (design-patterns.md 6)
    """
    assert "_" not in str(_view("gearReasonText", "some_new_token"))
