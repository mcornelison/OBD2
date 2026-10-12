################################################################################
# File Name: test_carousel_settings_kind_coverage.py
# Purpose/Description: US-421 -- every settings `kind` the renderer BRANCHES on
#     must be a kind SETTINGS_SPECS declares. carousel.js carried a three-choice
#     CAR/WALL/UNKNOWN control for kind "mode", which US-668 removed from the
#     spec table: dead code that read as a live control. The guard is a SET
#     RELATION computed at run time from the module's own settingsSpecs() export
#     plus a source scan -- never a hand-written list of kinds, which would have
#     to be edited by the same person who forgot the branch.
# Author: Rex (US-421)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-22    | Rex (US-421)   | Initial -- kind coverage, scanner self-test,
#               |                | Off/On for every declared spec.
# ================================================================================
################################################################################
"""US-421: the renderer branches only on settings kinds that actually exist."""

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

# Any `<anything>kind === "literal"` comparison, whichever object it hangs off
# (`spec.kind`, `view.kind`, a local `kind`). Both === and == are matched so a
# loosened comparison cannot slip past the guard.
_KIND_COMPARISON = re.compile(r"\bkind\s*={2,3}\s*\"([^\"]+)\"")


def _view(fn: str, *args: object) -> object:
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _source() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


def comparedKinds(source: str) -> set[str]:
    """Every settings kind the source compares against a literal."""
    return set(_KIND_COMPARISON.findall(source))


@_NODE_TESTS
def test_everyComparedKind_isDeclaredInSettingsSpecs():
    """
    Given: the kinds SETTINGS_SPECS declares, read from the module's own export
    When: compared with every `kind === "..."` branch in the source
    Then: the branches are a SUBSET of the declarations -- a control the spec
        table cannot produce is dead code that reads as live
    """
    declared = {spec["kind"] for spec in _view("settingsSpecs")}
    compared = comparedKinds(_source())

    assert compared <= declared, sorted(compared - declared)


def test_theScannerSeesEveryComparisonShape():
    """
    Given: the comparison shapes a renderer would plausibly use
    When: scanned
    Then: each is found -- the subset assertion above is only evidence because
        this scanner demonstrably matches (design-patterns.md 6)
    """
    assert comparedKinds('if (spec.kind === "mode") {') == {"mode"}
    assert comparedKinds('if (view.kind === "mode")') == {"mode"}
    assert comparedKinds('} else if (kind === "bool") {') == {"bool"}
    assert comparedKinds('if (kind == "seconds")') == {"seconds"}
    assert comparedKinds('spec.kindOf === "mode"') == set()


@_NODE_TESTS
def test_everyDeclaredSpec_rendersTheTwoChoiceControl():
    """
    Given: every spec the band declares
    When: its choices are built
    Then: the same two-choice Off/On control. `seconds` shares it correctly --
        auto-rotate is DERIVED from autoRotateS > 0 -- so this is not residue
    """
    for spec in _view("settingsSpecs"):
        assert _view("settingsChoices", spec) == [
            {"value": False, "label": "Off"},
            {"value": True, "label": "On"},
        ], spec["key"]


@_NODE_TESTS
def test_anUnknownKind_getsTheTwoChoiceControl_notAThirdState():
    """A spec whose kind the table never declared still yields Off/On -- the
    renderer has no second control shape to fall into."""
    assert _view("settingsChoices", {"key": "x", "kind": "mode"}) == [
        {"value": False, "label": "Off"},
        {"value": True, "label": "On"},
    ]


def test_theCarWallControlIsGone():
    """AC2: the CAR/WALL labels are not in the renderer. (The deprecation is
    still DOCUMENTED in comments -- a zero-match rule on `power.mode` would
    forbid recording that it happened, which is explicitly not the gate.)"""
    source = _source()
    assert '"CAR"' not in source
    assert '"WALL"' not in source


def test_settingsChoiceActive_readsNoModeField():
    """AC3: the active-choice test has no branch reading a `mode` field."""
    source = _source()
    start = source.index("function settingsChoiceActive(")
    body = source[start:source.index("\n  }", start)]
    assert ".mode" not in body, body
