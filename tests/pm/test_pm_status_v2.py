# tests/pm/test_pm_status_v2.py
# Tests for pm_status v2 -- 4-tier tree rendering + status rollup.
"""Tests for pm_status v2 -- 4-tier tree rendering + status rollup."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from offices.pm.scripts.pm_status import renderTree, computeRollups

FIXTURES = Path(__file__).parent / "fixtures"


def test_computeRollups_emptyEpicWithNoFeatures_status_pending():
    """
    Given: an epic with no features or stories
    When: computeRollups is called
    Then: epic status stays pending
    """
    # Arrange
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "pending", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [],
        "stories": [],
    }
    # Act
    rolled = computeRollups(data)
    # Assert
    assert rolled["epics"][0]["status"] == "pending"


def test_computeRollups_epicWithActiveFeature_status_active():
    """
    Given: backlog fixture with F-103 (groomed) under E-001
    When: computeRollups is called
    Then: E-001 status is active (has non-pending non-complete feature)
    """
    # Arrange
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    # the fixture has F-103 status=groomed under E-001
    # Act
    rolled = computeRollups(data)
    epicStatus = next(e["status"] for e in rolled["epics"] if e["id"] == "E-001")
    # Assert — at least one feature groomed → epic is active
    assert epicStatus == "active"


def test_computeRollups_featureWithAllStoriesComplete_status_complete():
    """
    Given: a feature with one complete story under it
    When: computeRollups is called
    Then: both feature and epic statuses roll up to complete
    """
    # Arrange
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                      "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "stories": [
            {"id": "US-1", "parent": "F-1", "title": "T", "type": "normal", "size": "S",
             "status": "complete", "goal": "g", "definitionOfDone": ["d"],
             "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
             "deps": [], "sourceRefs": [], "tasks": [],
             "createdAt": "2026-05-27", "updatedAt": "2026-05-27"},
        ],
    }
    # Act
    rolled = computeRollups(data)
    # Assert
    assert rolled["features"][0]["status"] == "complete"
    assert rolled["epics"][0]["status"] == "complete"


def test_renderTree_outputContainsEpicFeatureStory():
    """
    Given: the v2 fixture backlog (E-001 → F-103 → US-359)
    When: renderTree is called
    Then: output contains all three IDs
    """
    # Arrange
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    # Act
    out = renderTree(data)
    # Assert
    assert "E-001" in out
    assert "F-103" in out
    assert "US-359" in out


def test_computeRollups_featureWithBlockedStory_status_active():
    """A blocked story is in-flight; feature should roll up to active."""
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                      "status": "groomed", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "stories": [
            {"id": "US-1", "parent": "F-1", "title": "T", "type": "normal", "size": "S",
             "status": "blocked", "goal": "g", "definitionOfDone": ["d"],
             "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
             "deps": [], "sourceRefs": [], "tasks": [],
             "createdAt": "2026-05-27", "updatedAt": "2026-05-27"},
        ],
    }
    rolled = computeRollups(data)
    assert rolled["features"][0]["status"] == "active"


# ---------------------------------------------------------------------------
# dev/main branching workflow -- formatBranchTips pure formatter (spec 2026-05-28)
# ---------------------------------------------------------------------------

def test_formatBranchTips_bothBranches_returnsTwoLineBlock():
    """
    Given: main and dev both exist with distinct hashes
    When: formatBranchTips is called with their hashes + versions
    Then: output is a "=== BRANCHES ===" block listing both
    """
    # Arrange + Act
    from offices.pm.scripts.pm_status import formatBranchTips
    result = formatBranchTips(
        mainHash="abc1234",
        mainVersion="V0.27.19",
        devHash="def5678",
        devVersion="V0.28.0",
    )
    # Assert
    assert "=== BRANCHES ===" in result
    assert "main: V0.27.19 / abc1234" in result
    assert "dev:  V0.28.0 / def5678" in result


def test_formatBranchTips_devMissing_returnsNotBootstrappedMarker():
    """
    Given: dev does not exist (pre-bootstrap state)
    When: formatBranchTips is called with devHash=None, devVersion=None
    Then: output shows main details + "dev: not yet bootstrapped"
    """
    # Arrange + Act
    from offices.pm.scripts.pm_status import formatBranchTips
    result = formatBranchTips(
        mainHash="abc1234",
        mainVersion="V0.27.19",
        devHash=None,
        devVersion=None,
    )
    # Assert
    assert "main: V0.27.19 / abc1234" in result
    assert "dev:  not yet bootstrapped" in result


def test_formatBranchTips_devAtMain_marksConverged():
    """
    Given: dev hash matches main hash (post-chain-merge ff state)
    When: formatBranchTips is called
    Then: dev line is annotated "(= main; ready for next chain)"
    """
    # Arrange + Act
    from offices.pm.scripts.pm_status import formatBranchTips
    result = formatBranchTips(
        mainHash="abc1234",
        mainVersion="V0.27.19",
        devHash="abc1234",
        devVersion="V0.27.19",
    )
    # Assert
    assert "dev:  V0.27.19 / abc1234 (= main; ready for next chain)" in result


# ---------------------------------------------------------------------------
# Existing v2 tests continue below
# ---------------------------------------------------------------------------


def test_computeRollups_featureWithMixedCompleteAndPending_status_active():
    """Partial completion (some done, some pending) is active, not pending."""
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                      "status": "groomed", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "stories": [
            {"id": "US-1", "parent": "F-1", "title": "T1", "type": "normal", "size": "S",
             "status": "complete", "goal": "g", "definitionOfDone": ["d"],
             "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
             "deps": [], "sourceRefs": [], "tasks": [],
             "createdAt": "2026-05-27", "updatedAt": "2026-05-27"},
            {"id": "US-2", "parent": "F-1", "title": "T2", "type": "normal", "size": "S",
             "status": "pending", "goal": "g", "definitionOfDone": ["d"],
             "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
             "deps": [], "sourceRefs": [], "tasks": [],
             "createdAt": "2026-05-27", "updatedAt": "2026-05-27"},
        ],
    }
    rolled = computeRollups(data)
    assert rolled["features"][0]["status"] == "active"
