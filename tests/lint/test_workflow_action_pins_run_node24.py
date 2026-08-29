################################################################################
# File Name: test_workflow_action_pins_run_node24.py
# Purpose/Description: Standing-rule lint (US-472 / F-119) -- every first-party
#     GitHub Action this repo pins must resolve to a major whose `runs.using` is
#     `node24`. GitHub is retiring the Node20 action runtime; a Node20-era pin
#     emits a deprecation warning today and breaks when the runtime is
#     auto-forced.
#
#     THE TRAP THIS LINT EXISTS FOR: `actions/upload-artifact@v5` LOOKS like the
#     fix and is NOT. Its v5.0.0 release notes announce "this update supports
#     Node v24.x", but its action.yml still declares `using: 'node20'`, and
#     v6.0.0's own notes say it outright: "v5 had preliminary support for
#     Node.js 24, however this action was by default still running on Node.js
#     20." US-472 was groomed naming @v5 as the target. Bumping to it would have
#     closed the story, changed the version string, and left the deprecation
#     warning exactly where it was.
#
#     So the rule is pinned to a MEASURED `runs.using` value, never to a version
#     number that sounds recent. Every entry below was read from that action's
#     own action.yml at that tag on 2026-08-28 (see MEASURED_* tables).
#
#     GROUNDING -- GitHub's own annotation on the last green migration-drift run
#     (run 32647699967, 2026-08-23, head 68c1b907) named the three offenders
#     verbatim:
#       "Node.js 20 is deprecated. The following actions target Node.js 20 but
#        are being forced to run on Node.js 24: actions/checkout@v4,
#        actions/setup-python@v5, actions/upload-artifact@v4."
#     Note "are being FORCED" -- the auto-migration this repo was trying to get
#     ahead of has already happened. The exposure left is the warning itself plus
#     running action code on a runtime its major was never tested against.
# Author: Claude (Ralph / Rex)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Claude       | Initial -- US-472, Node24 action-pin lint.
# ================================================================================
################################################################################

"""Lint: pinned first-party GitHub Actions must run on the node24 runtime."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# The FIRST major of each first-party action whose action.yml declares
# `runs.using: node24`. Measured 2026-08-28 by reading
# https://raw.githubusercontent.com/<repo>/<tag>/action.yml directly.
#
#   actions/checkout        v4 -> node20 | v5 -> node24   (v5.0.0, 2025-08-11)
#   actions/setup-python    v5 -> node20 | v6 -> node24   (v6.0.0, 2025-09-04)
#   actions/upload-artifact v4 -> node20 | v5 -> node20 ! | v6 -> node24
#                                                         (v6.0.0, 2025-12-12)
#
# All three node24 majors require Actions Runner >= v2.327.1. Every job in this
# repo is `runs-on: ubuntu-latest` (GitHub-hosted, always current), so that
# requirement is met; it would matter on a self-hosted runner.
FIRST_NODE24_MAJOR: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
}

# Majors measured as node20 on 2026-08-28. Named individually so the failure
# message can say WHY rather than just "too old" -- @v5 of upload-artifact in
# particular reads as a Node24 release and is not one.
MEASURED_NODE20_MAJORS: dict[tuple[str, int], str] = {
    ("actions/checkout", 4): "action.yml declares `using: node20`",
    ("actions/setup-python", 5): "action.yml declares `using: 'node20'`",
    ("actions/upload-artifact", 4): "action.yml declares `using: 'node20'`",
    ("actions/upload-artifact", 5): (
        "action.yml declares `using: 'node20'` DESPITE the v5.0.0 notes saying "
        "'supports Node v24.x'. v6.0.0's notes: 'v5 had preliminary support for "
        "Node.js 24, however this action was by default still running on Node.js "
        "20.' Use @v6 or newer -- @v5 does NOT clear the deprecation."
    ),
}

_USES_MAJOR = re.compile(r"^v(\d+)")


def _iterSteps() -> list[tuple[Path, str, str]]:
    """Yield (workflow path, step label, `uses:` value) for every step in every workflow.

    Returns:
        list[tuple[Path, str, str]]: one entry per step that declares `uses:`.
    """
    out: list[tuple[Path, str, str]] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for jobName, job in (doc.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                uses = step.get("uses")
                if uses:
                    out.append((path, f"{jobName}[{index}] {step.get('name', '?')}", uses))
    return out


def _pinnedActions() -> list[tuple[Path, str, str, str]]:
    """Yield (path, step label, repo, ref) for every non-local `uses:` pin.

    Returns:
        list[tuple[Path, str, str, str]]: pins referencing a published action.
    """
    out: list[tuple[Path, str, str, str]] = []
    for path, label, uses in _iterSteps():
        if uses.startswith("./") or uses.startswith("docker://"):
            continue  # local composite / container action -- no marketplace major
        repo, _, ref = uses.partition("@")
        out.append((path, label, repo, ref))
    return out


def _label(entry: tuple[Path, str, str, str]) -> str:
    path, stepLabel, repo, ref = entry
    return f"{path.name}::{stepLabel}::{repo}@{ref}"


def test_thereAreWorkflowActionPinsToCheck() -> None:
    """Guard the guard: an empty glob would make every case below vacuously pass."""
    pins = _pinnedActions()
    assert pins, f"no `uses:` action pins found under {WORKFLOW_DIR} -- the lint is inert"


@pytest.mark.parametrize("entry", _pinnedActions(), ids=_label)
def test_actionPin_isNotAMeasuredNode20Major(entry: tuple[Path, str, str, str]) -> None:
    """
    Given: a workflow step pinning a published GitHub Action
    When: the pinned major is checked against the majors measured as node20
    Then: it is not one of them
    """
    _, _, repo, ref = entry
    match = _USES_MAJOR.match(ref)
    if match is None:
        pytest.skip(f"{repo}@{ref} is not pinned by major -- covered by the coverage test")
    major = int(match.group(1))
    reason = MEASURED_NODE20_MAJORS.get((repo, major))
    assert reason is None, (
        f"{repo}@{ref} runs on the deprecated Node20 action runtime: {reason}"
    )


@pytest.mark.parametrize("entry", _pinnedActions(), ids=_label)
def test_actionPin_isAtOrAboveItsFirstNode24Major(
    entry: tuple[Path, str, str, str],
) -> None:
    """
    Given: a workflow step pinning a first-party `actions/*` action
    When: its major is compared against the first major measured as node24
    Then: it is at or above that major
    """
    _, _, repo, ref = entry
    floor = FIRST_NODE24_MAJOR.get(repo)
    assert floor is not None, (
        f"{repo} is pinned but has no measured node24 floor. Read its action.yml at "
        f"the tag you intend to pin, confirm `runs.using: node24`, and add it to "
        f"FIRST_NODE24_MAJOR -- do NOT trust the release notes alone "
        f"(actions/upload-artifact@v5 is the counterexample)."
    )
    match = _USES_MAJOR.match(ref)
    assert match is not None, (
        f"{repo}@{ref} is not pinned by major, so its runtime cannot be checked "
        f"statically. Pin `@v<major>` or record the measured runtime here."
    )
    assert int(match.group(1)) >= floor, (
        f"{repo}@{ref} predates the first node24 major (@v{floor}) and will emit a "
        f"Node20 deprecation warning."
    )


def test_uploadArtifactIsNotPinnedToV5_thePreliminaryNode24Major() -> None:
    """
    Given: US-472 named actions/upload-artifact@v5 as the Node24 target
    When: the shipped pins are read
    Then: @v5 is not among them -- it is still a node20 action
    """
    offenders = [
        _label(e) for e in _pinnedActions() if e[2] == "actions/upload-artifact" and e[3] == "v5"
    ]
    assert not offenders, (
        "actions/upload-artifact@v5 declares `using: 'node20'` in its own action.yml. "
        "It reads as the Node24 release and is not one. Offending pins: "
        f"{offenders}"
    )


def test_migrationDriftWorkflow_keepsTheInputsItsStepsDependOn() -> None:
    """
    Given: the action majors were bumped across a major-version boundary
    When: the migration-drift job's `with:` blocks are read
    Then: the inputs the job depends on survived the bump
    """
    doc = yaml.safe_load((WORKFLOW_DIR / "migration-drift.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["real-mariadb-migration-chain"]["steps"]
    byAction = {s["uses"].partition("@")[0]: s for s in steps if s.get("uses")}

    setupPython = byAction["actions/setup-python"]
    assert setupPython["with"]["python-version"] == "3.11", (
        "setup-python@v6 keeps the v5 `python-version` input; the pin must keep using it"
    )

    upload = byAction["actions/upload-artifact"]
    assert upload["with"]["name"] == "migration-drift-report"
    assert upload["with"]["path"] == "migration-drift-report.xml"
    # v7 adds an opt-in `archive:` input that uploads a single file UNZIPPED and
    # ignores `name:`. Leaving it unset preserves the v4 zip-with-name behaviour
    # the report-download step expects.
    assert "archive" not in upload["with"], (
        "`archive:` changes the artifact's shape and makes `name:` inert -- if this "
        "is deliberate, update the guard and the README together"
    )
