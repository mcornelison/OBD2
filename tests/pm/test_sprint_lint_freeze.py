"""Tests for sprint_lint freeze-drift + per-story empty-list checks (spec 2026-05-28)."""
import hashlib

from offices.pm.scripts.sprint_lint import lintSprintValidation


def _hash(lines):
    canonical = "\n".join(sorted(line.strip() for line in lines))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _minimalSprintDict(bigDoD, hash_=None, withStory=True):
    """Build a minimal sprint.json dict with valid required validation fields."""
    sprintDict = {
        "schemaVersion": "2.0.0",
        "sprint": "Sprint 99 -- test",
        "stories": [],
        "validation": {
            "bigDefinitionOfDone": bigDoD,
            "validationMethod": "test drill",
            "validatesFeatures": ["F-005"],
            "currentVersion": "V0.28.0",
            "validatedAt": None,
            "validatedBy": None,
            "frozenAt": "2026-05-28T12:00:00Z",
            "bigDoDHash": hash_ if hash_ is not None else _hash(bigDoD),
        },
    }
    if withStory:
        sprintDict["stories"].append({
            "id": "US-359",
            "title": "T",
            "parent": "F-005",
            "type": "normal",
            "size": "S",
            "status": "sprint-ready",
            "passes": False,
            "acceptance": ["DoD-1"],
            "validationCriteria": [{"action": "a", "outcome": "o"}],
        })
    return sprintDict


def test_lintSprintValidation_noDrift_passes(tmp_path):
    """Given freeze fields match bigDoD content, no error."""
    bigDoD = ["clause A", "clause B"]
    d = _minimalSprintDict(bigDoD)
    errs = lintSprintValidation(d, tmp_path)
    # No drift errors. (Other errors may exist due to missing manifest,
    # but no error mentioning 'modified after freeze'.)
    assert not any("modified after freeze" in e for e in errs)


def test_lintSprintValidation_driftDetected_errors(tmp_path):
    """Given bigDoD edited after freeze hash was computed, ERROR."""
    bigDoD = ["clause A", "clause B"]
    d = _minimalSprintDict(bigDoD)
    # Modify bigDoD after the hash was set
    d["validation"]["bigDefinitionOfDone"].append("late addition clause")
    errs = lintSprintValidation(d, tmp_path)
    assert any("modified after freeze" in e for e in errs)


def test_lintSprintValidation_storyValidationCriteriaEmpty_errors(tmp_path):
    """Given a sprint story with empty validationCriteria, ERROR."""
    d = _minimalSprintDict(["clause A"])
    d["stories"][0]["validationCriteria"] = []
    errs = lintSprintValidation(d, tmp_path)
    assert any("validationCriteria empty" in e for e in errs)


def test_lintSprintValidation_storyAcceptanceEmpty_errors(tmp_path):
    """Given a sprint story with empty acceptance/DoD, ERROR."""
    d = _minimalSprintDict(["clause A"])
    d["stories"][0]["acceptance"] = []
    errs = lintSprintValidation(d, tmp_path)
    assert any("definitionOfDone empty" in e for e in errs)


def test_lintSprintValidation_storyAcceptanceEmptyWithDoDFallback_errors(tmp_path):
    """
    Regression: even if a story has definitionOfDone populated, an empty
    acceptance field (the sprint.json contract) must ERROR. The fallback
    behavior of the prior implementation masked broken stories.
    """
    d = _minimalSprintDict(["clause A"])
    d["stories"][0]["acceptance"] = []
    d["stories"][0]["definitionOfDone"] = ["this would have masked the bug"]
    errs = lintSprintValidation(d, tmp_path)
    assert any("definitionOfDone empty" in e for e in errs)
