################################################################################
# File Name: test_sprint_lint_v2.py
# Purpose/Description: Tests for sprint_lint v2 backlog rules --
#                      lintBacklog(), LintError, LintWarning.
# Author: Marcus (PM)
# Creation Date: 2026-05-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-27    | Marcus (PM)  | Initial implementation -- Task 3 TDD
# ================================================================================
################################################################################

"""Tests for sprint_lint v2 backlog rules."""
import json
import tempfile
from pathlib import Path
from offices.pm.scripts.sprint_lint import lintBacklog, LintError, LintWarning


def _withTempBacklog(data: dict):
    """Return a Path with the JSON written; caller cleans up."""
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, fp)
    fp.close()
    return Path(fp.name)


VALID_FIXTURE = {
    "schemaVersion": "2.0.0",
    "lastUpdated": "2026-05-27",
    "updatedBy": "test",
    "counters": {"epic": 2, "feature": 110, "story": 360},
    "epics": [{"id": "E-001", "title": "T", "description": "d",
               "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
    "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                  "status": "groomed", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
    "stories": [{
        "id": "US-1", "parent": "F-1", "title": "T", "type": "normal", "size": "S",
        "status": "groomed", "goal": "g", "definitionOfDone": ["d"],
        "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
        "deps": [], "sourceRefs": [], "tasks": [],
        "createdAt": "2026-05-27", "updatedAt": "2026-05-27"
    }],
}


def test_lintBacklog_valid_returnsNoErrors():
    path = _withTempBacklog(VALID_FIXTURE)
    errors, warnings = lintBacklog(path)
    assert errors == []


def test_lintBacklog_invalidStoryType_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["stories"][0]["type"] = "bogus"
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("type" in e.message for e in errors)


def test_lintBacklog_storyMissingValidationCriteria_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    del bad["stories"][0]["validationCriteria"]
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("validationCriteria" in e.message for e in errors)


def test_lintBacklog_orphanStory_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["stories"][0]["parent"] = "F-999"
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("orphan" in e.message.lower() for e in errors)


def test_lintBacklog_unknownEpicStatusHandEdit_returnsWarning():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["epics"][0]["status"] = "complete"  # cache mismatch -- only 1 groomed feature
    path = _withTempBacklog(bad)
    _, warnings = lintBacklog(path)
    assert any("rollup" in w.message.lower() or "cache" in w.message.lower() for w in warnings)
