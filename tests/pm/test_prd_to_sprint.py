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
# ================================================================================
################################################################################

"""Tests for prd_to_sprint -- PRD MD -> sprint.json conversion."""
import json
import shutil
from pathlib import Path

from offices.pm.scripts.prd_to_sprint import convertPrdToSprint

FIXTURES = Path(__file__).parent / "fixtures"


def _setupFakeRepo(tmpRoot: Path):
    """Build a minimal repo layout that convertPrdToSprint can read."""
    (tmpRoot / "offices/pm/backlog").mkdir(parents=True)
    (tmpRoot / "offices/pm/prds").mkdir(parents=True)
    (tmpRoot / "offices/ralph").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json",
                tmpRoot / "offices/pm/backlog.json")
    shutil.copy(FIXTURES / "prd_sample.md",
                tmpRoot / "offices/pm/prds/prd-V0.28.0-sprint-43.md")
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
    (tmpRoot / "offices/pm/backlog/US-359-boot-splash.md").write_text(storyMd, encoding="utf-8")


def test_convertPrdToSprint_basicConversion(tmp_path):
    _setupFakeRepo(tmp_path)
    prdPath = tmp_path / "offices/pm/prds/prd-V0.28.0-sprint-43.md"
    outPath = tmp_path / "offices/ralph/sprint.json"
    convertPrdToSprint(prdPath, outPath, repoRoot=tmp_path)
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
