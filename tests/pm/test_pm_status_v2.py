# tests/pm/test_pm_status_v2.py
# Tests for pm_status v2 -- 4-tier tree rendering + status rollup.
"""Tests for pm_status v2 -- 4-tier tree rendering + status rollup."""
import json
from pathlib import Path
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
