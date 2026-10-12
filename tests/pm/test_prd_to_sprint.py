################################################################################
# File Name: test_prd_to_sprint.py
# Purpose/Description: Tests for prd_to_sprint -- PRD MD -> sprint.json conversion.
# Author: Marcus (PM)
# Creation Date: 2026-05-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-27    | Marcus (PM)  | Initial implementation -- Task 5 TDD
# 2026-08-29    | Rex (Dev)    | US-609: retire the two freeze-field tests (the
#               |              | mechanic was retired 2026-07-13); replace with a
#               |              | negative guard that the retirement holds.
# ================================================================================
################################################################################

"""Tests for prd_to_sprint -- PRD MD -> sprint.json conversion."""
import json
import shutil
from pathlib import Path

import pytest

from tools.pm.prd_to_sprint import convertPrdToSprint

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def _fleetShare(tmp_path, monkeypatch):
    """Point $FLEET_SHARE at this test's tmp tree.

    The tools resolve their share root through
    :func:`tools.pm._paths.resolveShareRoot`, so setting the env var exercises
    the REAL resolution path rather than injecting a root that production
    callers never inject.
    """
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    return tmp_path



def _setupFakeRepo(tmpRoot: Path):
    """Build a minimal repo layout that convertPrdToSprint can read."""
    (tmpRoot / "pm/backlog").mkdir(parents=True)
    (tmpRoot / "pm/prds").mkdir(parents=True)
    (tmpRoot / "ralph").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json",
                tmpRoot / "pm/backlog.json")
    shutil.copy(FIXTURES / "prd_sample.md",
                tmpRoot / "pm/prds/prd-V0.28.0-sprint-43.md")
    # also need a Story.md for US-359 with full content
    storyMd = """---
id: US-359
parent: F-103
type: normal
size: M
status: sprint-ready
createdAt: 2026-05-27
deps: []
sourceRefs: []
---

# US-359 — Boot splash

## Goal
As CIO, I want a boot splash so I know when the Pi is ready.

## Definition of Done
- splash visible within 3s

## Conditional outcomes
- if collector fails → degraded amber

## Validation criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | Boot Pi cold | Splash within 3s |
"""
    (tmpRoot / "pm/backlog/US-359-boot-splash.md").write_text(storyMd, encoding="utf-8")


def test_convertPrdToSprint_basicConversion(tmp_path):
    _setupFakeRepo(tmp_path)
    prdPath = tmp_path / "pm/prds/prd-V0.28.0-sprint-43.md"
    outPath = tmp_path / "ralph/sprint.json"
    convertPrdToSprint(prdPath, outPath)
    assert outPath.exists()
    sprint = json.loads(outPath.read_text())
    assert sprint["version"] == "V0.28.0"
    assert sprint["sprint"] == 43
    assert len(sprint["stories"]) == 1
    s = sprint["stories"][0]
    # sprint-level frozen-contract assertions
    assert sprint["schemaVersion"] == "2.0.0"
    assert sprint["createdFromPRD"].endswith("prd-V0.28.0-sprint-43.md")
    assert "/" in sprint["createdFromPRD"] and "\\" not in sprint["createdFromPRD"]
    # story-level
    assert s["id"] == "US-359"
    assert s["parent"] == "F-103"
    assert s["epicId"] == "E-001"
    assert s["type"] == "normal"
    assert s["size"] == "M"
    assert s["status"] == "sprint-ready"
    assert s["passes"] is False
    assert s["acceptance"] == ["fixture parses", "validator passes"]
    assert s["validationCriteria"] == [{"action": "load fixture", "outcome": "validator returns OK"}]
    # sprint-level bigDoD aggregation
    assert len(sprint["validation"]["bigDefinitionOfDone"]) == 1
    bigDoD = sprint["validation"]["bigDefinitionOfDone"][0]
    assert "→" in bigDoD
    assert "[from US-359]" in bigDoD


def test_convertPrdToSprint_doesNotStampRetiredFreezeFields(tmp_path):
    """
    Given: the sample PRD fixture is converted
    When: convertPrdToSprint runs
    Then: the validation block carries NEITHER frozenAt NOR bigDoDHash

    The freeze mechanic was retired by CIO directive 2026-07-13.  Two tests
    here previously asserted the OPPOSITE (``writesFreezeFields`` and
    ``freezeHash_deterministic``) and failed with ``KeyError`` on a pristine
    tree.  They are RETIRED rather than "fixed": the tool is correct, and
    re-adding the stamping to make them pass would resurrect a mechanic the
    CIO retired (US-609).

    This replacement is deliberately a NEGATIVE assertion.  Deleting the two
    stale tests alone would leave nothing pinning the retirement, so a silent
    re-add of freeze stamping would pass the suite.

    Scope fence: ``sprint_lint`` still drift-checks ARCHIVED sprints that
    carry the fields -- 14 of them on the share, V0.28.1 through V0.29.9,
    the newest 2026-07-05.  That path is deliberately untouched and is
    covered by ``test_sprint_lint_freeze.py``.
    """
    _setupFakeRepo(tmp_path)
    prdPath = tmp_path / "pm/prds/prd-V0.28.0-sprint-43.md"
    outPath = tmp_path / "ralph/sprint.json"
    convertPrdToSprint(prdPath, outPath)
    v = json.loads(outPath.read_text(encoding="utf-8"))["validation"]
    # Premise check FIRST: a negative assertion passes vacuously if the block
    # it inspects vanishes, so pin that there is still a contract to freeze.
    assert v["bigDefinitionOfDone"], "premise gone: no bigDefinitionOfDone to freeze"
    assert "frozenAt" not in v, "freeze stamping resurrected -- retired 2026-07-13"
    assert "bigDoDHash" not in v, "freeze stamping resurrected -- retired 2026-07-13"
