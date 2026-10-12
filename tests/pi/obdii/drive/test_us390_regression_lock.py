################################################################################
# File Name: test_us390_regression_lock.py
# Purpose/Description: US-390 (F-107) AC#1 -- permanent regression lock for the
#                      US-386 drives-28/29 close-signal reproducer.  US-388
#                      fixed the DriveDetector and REMOVED the two xfail markers
#                      that shipped the stale-open scenarios RED; this guard
#                      fails loudly if the reproducer is ever silently neutered
#                      again (an xfail/skip marker reintroduced, a scenario test
#                      deleted, or the file pushed out of the fast suite via a
#                      `slow` marker).  Belt-and-suspenders so a future Pi
#                      regression cannot quietly disable the Root-2 net.
# Author: Rex (Ralph agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-390) | Initial -- locks the US-386 reproducer into the
#                               fast suite permanently (no xfail/skip/slow, all
#                               four scenarios present).  Static AST scan -- no
#                               import side effects; self-tests its own marker
#                               detector so the lock is never vacuous.
# ================================================================================
################################################################################

"""US-390 AC#1 -- regression lock guarding the US-386 reproducer.

The US-386 reproducer (``test_drive2829_close_signal_reproducer.py``) is the
in-process Root-2 net for the drives-28/29 close-signal defect.  At US-386 the
two stale-open scenarios shipped ``@pytest.mark.xfail`` (the defect was real);
US-388 fixed the DriveDetector and removed those markers, making the file a
permanent GREEN regression net.

This guard makes "permanent" enforceable.  It statically parses the reproducer
source (``ast`` -- no import, no detector wiring, no DB) and asserts:

* all four scenario tests are still present (no silent deletion),
* NO test function/class carries an ``xfail`` / ``skip`` / ``skipif`` marker
  (no silent re-neutering of the stale-open scenarios), and
* the module is NOT marked ``slow`` (it stays in the ``-m "not slow"`` fast
  suite that VC#1 runs).

The marker detector self-tests against a synthetic ``@pytest.mark.xfail`` snippet
(``test_markerDetector_flagsXfail_selfTest``) so the lock is never vacuously
green: if the detector stopped recognising xfail, the self-test fails first.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The reproducer this lock guards.  Resolved relative to THIS file so the guard
# does not depend on the package-import path or on executing the reproducer's
# detector/DB imports.
_REPRODUCER_PATH = (
    Path(__file__).with_name("test_drive2829_close_signal_reproducer.py")
)

# The four scenarios that must remain present (US-386 contract; the two
# stale-open scenarios are the ones US-388 flipped GREEN).
_EXPECTED_TESTS = frozenset({
    "test_shortDrive_opensAndClosesExactlyOneDriveId",
    "test_backToBackMissedClose_eachPhysicalDriveOwnDriveId",
    "test_keyOnAfterMissedClose_mintsNewDriveId_noAbsorption",
    "test_reproIsDeterministic_acrossTwoRuns",
})

# Markers that would neuter or evict the reproducer from the fast suite.
_FORBIDDEN_MARKERS = frozenset({"xfail", "skip", "skipif"})
_FAST_SUITE_EVICTING_MARKER = "slow"

# The three def-node kinds that carry a ``decorator_list`` + ``name``.
_DefNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _markerNamesOnDecorators(node: _DefNode) -> set[str]:
    """Return the ``pytest.mark.<NAME>`` names decorating a def node.

    Handles both the bare-attribute form (``@pytest.mark.skip``) and the call
    form (``@pytest.mark.xfail(reason=...)``).  Only decorators whose attribute
    chain passes through ``.mark.`` are counted, so an unrelated
    ``@something.xfail`` would not be mistaken for a pytest marker.
    """
    names: set[str] = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Attribute)
            and target.value.attr == "mark"
        ):
            names.add(target.attr)
    return names


def _parseReproducer() -> ast.Module:
    """Parse the reproducer source into an AST (no execution)."""
    source = _REPRODUCER_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(_REPRODUCER_PATH))


def _allDefNodes(tree: ast.Module) -> list[_DefNode]:
    """Every function/class def in the module (recursively)."""
    defs: list[_DefNode] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs.append(node)
    return defs


def _moduleLevelMarkerNames(tree: ast.Module) -> set[str]:
    """``pytest.mark.<NAME>`` names referenced by a module-level ``pytestmark``.

    A module-level ``pytestmark = pytest.mark.slow`` (or a list of them) applies
    its markers to every test in the file; this surfaces those so the guard can
    reject a module-wide ``slow`` / ``skip`` re-introduction too.
    """
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "pytestmark" not in targets:
            continue
        for sub in ast.walk(node.value):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Attribute)
                and sub.value.attr == "mark"
            ):
                names.add(sub.attr)
    return names


class TestReproducerRegressionLock:
    """The US-386 reproducer stays a permanent, un-neuterable fast-suite test."""

    def test_reproducerFileExists(self) -> None:
        """The reproducer this sprint locks must still be on disk."""
        assert _REPRODUCER_PATH.is_file(), (
            f"US-386 reproducer missing at {_REPRODUCER_PATH} -- the Root-2 "
            "regression net was deleted."
        )

    def test_allFourScenariosPresent(self) -> None:
        """No scenario test was silently dropped from the reproducer."""
        tree = _parseReproducer()
        present = {
            node.name
            for node in _allDefNodes(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }
        missing = _EXPECTED_TESTS - present
        assert not missing, (
            f"US-386 reproducer is missing scenario test(s): {sorted(missing)}. "
            "Each is part of the locked Root-2 net (US-390 AC#1)."
        )

    def test_noXfailOrSkipMarkers_onAnyTest(self) -> None:
        """No test re-acquired an xfail/skip marker (the neutering US-388 undid)."""
        tree = _parseReproducer()
        offenders: dict[str, set[str]] = {}
        for node in _allDefNodes(tree):
            bad = _markerNamesOnDecorators(node) & _FORBIDDEN_MARKERS
            if bad:
                offenders[node.name] = bad
        moduleBad = _moduleLevelMarkerNames(tree) & _FORBIDDEN_MARKERS
        if moduleBad:
            offenders["<module pytestmark>"] = moduleBad
        assert not offenders, (
            "US-386 reproducer has forbidden xfail/skip markers reintroduced "
            f"{offenders}. The stale-open scenarios must stay GREEN-asserting "
            "(US-388 removed these markers; US-390 locks them out)."
        )

    def test_notMarkedSlow_staysInFastSuite(self) -> None:
        """The reproducer must remain in the `-m "not slow"` fast suite (VC#1)."""
        tree = _parseReproducer()
        slowOnDef = any(
            _FAST_SUITE_EVICTING_MARKER in _markerNamesOnDecorators(node)
            for node in _allDefNodes(tree)
        )
        slowOnModule = _FAST_SUITE_EVICTING_MARKER in _moduleLevelMarkerNames(tree)
        assert not (slowOnDef or slowOnModule), (
            "US-386 reproducer is marked `slow` -- VC#1 runs the fast suite "
            '(`-m "not slow"`) and would no longer include the Root-2 net.'
        )

    def test_markerDetector_flagsXfail_selfTest(self) -> None:
        """Self-test: the detector recognises a real `@pytest.mark.xfail`.

        Guards against a vacuous lock -- if the AST detector stopped seeing
        xfail, every assertion above would pass for the wrong reason.  Proving
        it flags a synthetic xfail is this guard's "watch it go RED" evidence.
        """
        snippet = (
            "import pytest\n"
            "@pytest.mark.xfail(reason='self-test')\n"
            "@pytest.mark.skip\n"
            "def f():\n"
            "    pass\n"
        )
        fnNode = ast.parse(snippet).body[1]
        assert isinstance(fnNode, ast.FunctionDef)
        detected = _markerNamesOnDecorators(fnNode)
        assert "xfail" in detected
        assert "skip" in detected
        # And a non-pytest decorator of the same leaf name is NOT a false match.
        nonPytest = ast.parse("@thing.xfail\ndef g():\n    pass\n").body[0]
        assert isinstance(nonPytest, ast.FunctionDef)
        assert _markerNamesOnDecorators(nonPytest) == set()
