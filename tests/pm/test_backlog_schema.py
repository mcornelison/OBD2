################################################################################
# File Name: test_backlog_schema.py
# Purpose/Description: Tests for backlog_schema validator (v2.0.0).
# Author: Marcus (PM)
# Creation Date: 2026-05-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-27    | Marcus (PM)  | Initial implementation -- Task 1 TDD
# ================================================================================
################################################################################

"""Tests for backlog_schema validator (v2.0.0)."""
from pathlib import Path
import json
import pytest
from offices.pm.scripts.backlog_schema import validateBacklog, BacklogValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def test_validateBacklog_validFixture_returnsBacklog():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    result = validateBacklog(data)
    assert result["schemaVersion"] == "2.0.0"
    assert len(result["epics"]) == 1
    assert len(result["stories"]) == 1


def test_validateBacklog_missingSchemaVersion_raises():
    data = {"epics": [], "features": [], "stories": []}
    with pytest.raises(BacklogValidationError, match="schemaVersion"):
        validateBacklog(data)


def test_validateBacklog_storyMissingValidationCriteria_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    del data["stories"][0]["validationCriteria"]
    with pytest.raises(BacklogValidationError, match="validationCriteria"):
        validateBacklog(data)


def test_validateBacklog_invalidStoryType_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["stories"][0]["type"] = "bogus-type"
    with pytest.raises(BacklogValidationError, match="type"):
        validateBacklog(data)


def test_validateBacklog_orphanFeature_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["features"][0]["parent"] = "E-999"
    with pytest.raises(BacklogValidationError, match="orphan"):
        validateBacklog(data)


def test_validateBacklog_validationCriteriaShape_actionOutcomePairs():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["stories"][0]["validationCriteria"] = [{"foo": "bar"}]
    with pytest.raises(BacklogValidationError, match="validationCriteria"):
        validateBacklog(data)
