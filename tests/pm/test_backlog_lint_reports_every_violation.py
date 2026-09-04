################################################################################
# File Name: test_backlog_lint_reports_every_violation.py
# Purpose/Description: US-670 -- the backlog lint must report EVERY schema
#                      violation in one run, with a count per violation class,
#                      so a 41-story drift is distinguishable from a 1-story
#                      typo. Pins all THREE layers separately (collector,
#                      lintBacklog, CLI) because an end-to-end test cannot say
#                      which layer produced the pass.
# Author: Rex (Ralph)
# Creation Date: 2026-09-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-04    | Rex (Ralph)  | US-670: collect-all backlog violations
# ================================================================================
################################################################################

"""
US-670 -- one lint run reports every backlog schema violation.

THE DEFECT HAD TWO LAYERS OF SHORT-CIRCUIT, not one:

  1. ``backlog_schema.validateBacklog`` raises on the FIRST failing story.
  2. ``sprint_lint.lintBacklog`` caught that ONE exception, appended ONE
     LintError and returned.

Fixing either alone leaves the other truncating, and a CLI-only test cannot
tell which layer produced a pass -- so each layer is pinned directly here
(US-669's "when two layers enforce the same rule, an end-to-end test pins
neither").

NO RULE IS RELAXED, ADDED OR REWORDED by US-670. ``validateBacklog`` still
raises, with the same message, on the same first violation. That equivalence
is asserted mechanically (see ``TestTheRuleSetIsUnchanged``) rather than
promised in prose, because the collect-all path would otherwise be a second
copy of the invariants -- exactly the drift US-669 and US-675 closed.
"""
import json

import pytest

from tools.pm import backlog_schema, sprint_lint
from tools.pm.backlog_schema import (
    BacklogValidationError,
    collectBacklogViolations,
    validateBacklog,
)
from tools.pm.sprint_lint import lintBacklog, main


def _cleanBacklog():
    """
    Build a minimal SCHEMA-CLEAN backlog v2.0.0: 1 epic + 1 feature + 1 story.

    Returns a fresh dict each call so a test can mutate one field without
    contaminating another.

    Returns:
        A dict that ``validateBacklog`` accepts unmodified.
    """
    return {
        "schemaVersion": "2.0.0",
        "lastUpdated": "2026-09-04",
        "updatedBy": "test",
        "counters": {"epic": 1, "feature": 1, "story": 1},
        "epics": [{
            "id": "E-001", "title": "T", "description": "d",
            "status": "active",
            "createdAt": "2026-09-04", "updatedAt": "2026-09-04",
        }],
        "features": [{
            "id": "F-1", "parent": "E-001", "title": "T", "description": "d",
            "status": "in-sprint",
            "createdAt": "2026-09-04", "updatedAt": "2026-09-04",
        }],
        "stories": [_story("US-1")],
    }


def _story(storyId, **overrides):
    """
    Build one schema-clean story dict.

    Args:
        storyId: Value for the story's ``id`` field.
        **overrides: Field values to replace on the returned story.

    Returns:
        A story dict carrying every field in REQUIRED_STORY_FIELDS.
    """
    story = {
        "id": storyId, "parent": "F-1", "title": "T",
        "type": "normal", "size": "S", "status": "sprint-ready",
        "goal": "g",
        "definitionOfDone": ["DoD-1"],
        "conditionalOutcomes": ["if x then y"],
        "validationCriteria": [{"action": "a", "outcome": "o"}],
        "deps": [], "sourceRefs": [], "tasks": [],
        "createdAt": "2026-09-04", "updatedAt": "2026-09-04",
    }
    story.update(overrides)
    return story


def _codes(violations):
    """
    Extract the violation-class code from each violation.

    Args:
        violations: Iterable of BacklogViolation.

    Returns:
        List of code strings, in report order.
    """
    return [v.code for v in violations]


@pytest.fixture
def withTempBacklog(tmp_path):
    """Factory fixture: writes a backlog dict to tmp_path and returns its Path."""
    def _make(data):
        p = tmp_path / "backlog.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p
    return _make


@pytest.fixture
def runCli(tmp_path, monkeypatch, capsys):
    """
    Factory fixture: runs ``sprint_lint --backlog`` against a temp backlog.

    Points the CLI's SHARE_ROOT at tmp_path so ``--backlog`` reads the
    fixture rather than the live share.

    Returns:
        Callable(data) -> (exitCode, stdout, stderr).
    """
    def _run(data, argv=("--backlog",)):
        pmDir = tmp_path / "pm"
        pmDir.mkdir(exist_ok=True)
        (pmDir / "backlog.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(sprint_lint, "SHARE_ROOT", tmp_path)
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err
    return _run


# ---------------------------------------------------------------------------
# LAYER 1 -- the collector itself, called directly with nothing downstream.
# ---------------------------------------------------------------------------

class TestTheCollectorReportsEveryViolation:
    """collectBacklogViolations walks the WHOLE backlog, not just to the first fault."""

    def test_threeDistinctClassesAcrossDifferentStories_allThreeReported(self):
        """
        Given: three stories, each violating a DIFFERENT invariant
        When: collectBacklogViolations walks the backlog
        Then: all three are returned, each naming its own story id

        This is validationCriterion 1 at the collector level. Today
        validateBacklog raises on US-A and US-B / US-C are never reached.
        """
        data = _cleanBacklog()
        data["stories"] = [
            _story("US-A", size="XXL"),          # invalid size
            _story("US-B", parent="F-999"),      # orphan parent
            _story("US-C"),                      # missing required field
        ]
        del data["stories"][2]["goal"]

        violations = collectBacklogViolations(data)

        assert len(violations) == 3, _codes(violations)
        assert {v.entityId for v in violations} == {"US-A", "US-B", "US-C"}
        assert len(set(_codes(violations))) == 3

    def test_sameViolationOnFortyStories_returnsFortyNotOne(self):
        """
        Given: forty stories all missing createdAt/updatedAt (the MEASURED drift)
        When: collectBacklogViolations walks the backlog
        Then: forty violations come back, one per story, each named

        This is validationCriterion 2 at the collector level, and it encodes
        the actual defect: against the live backlog the lint printed ONE line
        while 41 stories were affected.
        """
        data = _cleanBacklog()
        data["stories"] = []
        for i in range(40):
            story = _story(f"US-{600 + i}")
            del story["createdAt"]
            del story["updatedAt"]
            data["stories"].append(story)

        violations = collectBacklogViolations(data)

        assert len(violations) == 40
        assert len({v.entityId for v in violations}) == 40

    def test_cleanBacklog_returnsEmptyList(self):
        """
        Given: a schema-clean backlog
        When: collectBacklogViolations walks it
        Then: an empty list -- the collector invents nothing
        """
        assert collectBacklogViolations(_cleanBacklog()) == []

    def test_everyViolationCarriesAClassCodeAndAnEntityId(self):
        """
        Given: a backlog with a feature-level AND a story-level violation
        When: the violations are collected
        Then: each carries a non-empty class code drawn from VIOLATION_CODES
              and the id of the entity it is about

        The class code is what makes "a count per violation class" possible;
        a bare message string cannot be grouped.
        """
        data = _cleanBacklog()
        data["features"].append({
            "id": "F-2", "parent": "E-999", "title": "T", "description": "d",
            "status": "in-sprint",
            "createdAt": "2026-09-04", "updatedAt": "2026-09-04",
        })
        data["stories"].append(_story("US-2", type="bogus"))

        violations = collectBacklogViolations(data)

        assert len(violations) == 2
        for v in violations:
            assert v.code in backlog_schema.VIOLATION_CODES
            assert v.entityId
            assert v.message
        assert {v.entityId for v in violations} == {"F-2", "US-2"}


class TestDependentChecksAreSkippedNotCascaded:
    """
    conditionalOutcome 2: report the first-order violation, SKIP the dependent
    one. A hundred derived errors from one cause is the same under-informing
    failure inverted.
    """

    def test_storyMissingParent_doesNotAlsoReportAnOrphanParent(self):
        """
        Given: a story with no `parent` key at all
        When: the violations are collected
        Then: exactly ONE violation -- the missing field. The orphan check is
              meaningless without a parent to check and is skipped.

        It would also raise KeyError on story["parent"], so this is a crash
        guard as well as a cascade guard.
        """
        data = _cleanBacklog()
        del data["stories"][0]["parent"]

        violations = collectBacklogViolations(data)

        assert len(violations) == 1
        assert violations[0].code == backlog_schema.CODE_STORY_MISSING_FIELDS

    def test_missingMetadataField_stillReportsIndependentViolationsOnPresentFields(self):
        """
        Given: a story missing createdAt (metadata) AND carrying an invalid size
        When: the violations are collected
        Then: BOTH are reported

        LOAD-BEARING. The cheap way to satisfy the cascade rule is to abort the
        whole story after its first violation -- which would REPRODUCE US-670's
        own defect one level down, because the 41 measured stories were missing
        exactly createdAt/updatedAt and every other fault in them would go
        unseen. Skipping is per-FIELD, not per-story.
        """
        data = _cleanBacklog()
        del data["stories"][0]["createdAt"]
        data["stories"][0]["size"] = "XXL"

        violations = collectBacklogViolations(data)

        assert set(_codes(violations)) == {
            backlog_schema.CODE_STORY_MISSING_FIELDS,
            backlog_schema.CODE_STORY_SIZE,
        }

    def test_wrongSchemaVersion_reportsOnlyThatAndStops(self):
        """
        Given: a file that is not backlog v2.0.0 at all
        When: the violations are collected
        Then: exactly one violation -- the schemaVersion

        A v1 file has a different SHAPE; walking it would emit a violation for
        every record in it. That is the cascade this rule exists to prevent,
        and it also preserves validateBacklog's existing behaviour exactly.
        """
        data = _cleanBacklog()
        data["schemaVersion"] = "1.0.0"
        data["stories"] = [_story("US-A", size="XXL"), _story("US-B", type="bogus")]

        violations = collectBacklogViolations(data)

        assert len(violations) == 1
        assert violations[0].code == backlog_schema.CODE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# THE ANTI-DRIFT PIN -- one authority, two entry points.
# ---------------------------------------------------------------------------

# Every invariant backlog_schema enforces, with the mutation that trips it.
# If a rule is added to the schema and not added here, the completeness test
# below goes red.
_RULE_TABLE = [
    ("schemaVersion", lambda d: d.update(schemaVersion="1.0.0")),
    ("epicStatus", lambda d: d["epics"][0].update(status="bogus")),
    ("featureOrphan", lambda d: d["features"][0].update(parent="E-999")),
    ("featureStatus", lambda d: d["features"][0].update(status="bogus")),
    ("storyMissingFields", lambda d: d["stories"][0].pop("goal")),
    ("storyOrphan", lambda d: d["stories"][0].update(parent="F-999")),
    ("storyType", lambda d: d["stories"][0].update(type="bogus")),
    ("storySize", lambda d: d["stories"][0].update(size="XXL")),
    ("storyStatus", lambda d: d["stories"][0].update(status="bogus")),
    ("storyValidationCriteria", lambda d: d["stories"][0].update(validationCriteria=[])),
    ("storyDefinitionOfDone", lambda d: d["stories"][0].update(definitionOfDone=[])),
    ("storyTasks", lambda d: d["stories"][0].update(tasks=[{"id": "T-1", "status": "bogus"}])),
]


class TestTheRuleSetIsUnchanged:
    """
    US-670 clause 1: the invariants are NOT changing -- only how many of their
    violations one run can report. No rule relaxed, added or reworded.
    """

    @pytest.mark.parametrize("name,mutate", _RULE_TABLE, ids=[r[0] for r in _RULE_TABLE])
    def test_everyRuleStillFiresOnBothPaths(self, name, mutate):
        """
        Given: a clean backlog with exactly ONE invariant broken
        When: it is run through BOTH collectBacklogViolations and validateBacklog
        Then: the collector reports it AND validateBacklog still raises

        This is the "no rule was relaxed" guard. A collect-all path that
        quietly dropped an invariant would look like a pass everywhere else.
        """
        data = _cleanBacklog()
        mutate(data)

        violations = collectBacklogViolations(data)
        assert len(violations) == 1, f"{name}: {_codes(violations)}"

        with pytest.raises(BacklogValidationError):
            validateBacklog(data)

    @pytest.mark.parametrize("name,mutate", _RULE_TABLE, ids=[r[0] for r in _RULE_TABLE])
    def test_validateBacklogRaisesTheExactMessageOfTheFirstCollectedViolation(self, name, mutate):
        """
        Given: a clean backlog with one invariant broken
        When: both entry points are exercised
        Then: the raised message is CHARACTER-IDENTICAL to the first collected
              violation's message

        THIS IS THE ANTI-DRIFT PIN. It fails the moment anyone implements the
        collect-all path as a SECOND copy of the invariants, because two hand-
        written copies do not produce identical strings for long. One authority
        or this test is red.
        """
        data = _cleanBacklog()
        mutate(data)

        violations = collectBacklogViolations(data)
        with pytest.raises(BacklogValidationError) as exc:
            validateBacklog(data)

        assert str(exc.value) == violations[0].message

    def test_theRuleTableCoversEveryCodeTheSchemaCanEmit(self):
        """
        Given: the VIOLATION_CODES the schema declares
        When: compared against the codes _RULE_TABLE actually trips
        Then: they are the same set

        Without this, adding a rule to the schema and forgetting to cover it
        here would leave the two tests above silently narrower than they read.
        """
        tripped = set()
        for _name, mutate in _RULE_TABLE:
            data = _cleanBacklog()
            mutate(data)
            tripped.update(_codes(collectBacklogViolations(data)))

        assert tripped == set(backlog_schema.VIOLATION_CODES)

    def test_validateBacklog_cleanBacklog_stillReturnsTheInputUnchanged(self):
        """
        Given: a clean backlog
        When: validateBacklog is called
        Then: it returns the SAME object -- the existing contract is intact
        """
        data = _cleanBacklog()
        assert validateBacklog(data) is data

    def test_validateBacklog_stopsAtTheFirstViolation_notTheLast(self):
        """
        Given: two stories violating different invariants, in order
        When: validateBacklog is called
        Then: it raises about the FIRST one

        Callers that catch BacklogValidationError read its message; reporting
        the last violation instead would be a silent contract change.
        """
        data = _cleanBacklog()
        data["stories"] = [_story("US-A", size="XXL"), _story("US-B", type="bogus")]

        with pytest.raises(BacklogValidationError) as exc:
            validateBacklog(data)

        assert "US-A" in str(exc.value)
        assert "US-B" not in str(exc.value)


# ---------------------------------------------------------------------------
# LAYER 2 -- lintBacklog, which had its OWN short-circuit.
# ---------------------------------------------------------------------------

class TestLintBacklogDoesNotTruncate:
    """
    sprint_lint.lintBacklog appended ONE LintError and returned. Pinned
    directly, because a collect-all schema behind a truncating consumer is
    still a lint that reports one violation.
    """

    def test_fortyViolations_returnsFortyLintErrors(self, withTempBacklog):
        """
        Given: forty stories each missing required metadata
        When: lintBacklog reads the file
        Then: forty LintErrors come back, not one

        Dies if anyone restores `return errors, warnings` after the first append.
        """
        data = _cleanBacklog()
        data["stories"] = []
        for i in range(40):
            story = _story(f"US-{600 + i}")
            del story["createdAt"]
            data["stories"].append(story)

        errors, _warnings = lintBacklog(withTempBacklog(data))

        assert len(errors) == 40

    def test_lintErrorsCarryTheViolationClassCode(self, withTempBacklog):
        """
        Given: two DIFFERENT violation classes
        When: lintBacklog reads the file
        Then: the LintErrors carry distinct class codes

        The CLI groups by this; if lintBacklog flattened it to a message the
        count-per-class summary could not be produced.
        """
        data = _cleanBacklog()
        data["stories"] = [_story("US-A", size="XXL"), _story("US-B", type="bogus")]

        errors, _ = lintBacklog(withTempBacklog(data))

        assert {e.code for e in errors} == {
            backlog_schema.CODE_STORY_SIZE,
            backlog_schema.CODE_STORY_TYPE,
        }

    def test_schemaViolations_stillSkipTheRollupCacheCheck(self, withTempBacklog):
        """
        Given: a backlog with a schema violation AND a stale rollup cache
        When: lintBacklog reads it
        Then: errors are reported and warnings are EMPTY

        The rollup short-circuit is legitimate and stays: computeRollups over a
        file that failed schema validation produces meaningless warnings (and
        can crash). US-670 removes the ERROR truncation only.
        """
        data = _cleanBacklog()
        data["stories"][0]["size"] = "XXL"
        data["epics"][0]["status"] = "complete"  # cache mismatch

        errors, warnings = lintBacklog(withTempBacklog(data))

        assert errors
        assert warnings == []

    def test_cleanBacklog_returnsNoErrors(self, withTempBacklog):
        """
        Given: a schema-clean backlog
        When: lintBacklog reads it
        Then: no errors
        """
        errors, _ = lintBacklog(withTempBacklog(_cleanBacklog()))
        assert errors == []


# ---------------------------------------------------------------------------
# LAYER 3 -- the CLI a human actually runs.
# ---------------------------------------------------------------------------

class TestTheCliReportsEveryViolationWithACount:
    """validationCriteria 1-3, through `python -m tools.pm.sprint_lint --backlog`."""

    def test_threeViolationClasses_allReportedInOneRun_exitNonZero(self, runCli):
        """
        Given: a backlog with a missing field, an orphan parent and an invalid
               size, on three different stories
        When: sprint_lint --backlog runs ONCE
        Then: all three appear, each naming its story id, and exit is non-zero

        validationCriterion 1, verbatim.
        """
        data = _cleanBacklog()
        data["stories"] = [
            _story("US-A", size="XXL"),
            _story("US-B", parent="F-999"),
            _story("US-C"),
        ]
        del data["stories"][2]["goal"]

        code, _out, err = runCli(data)

        assert code != 0
        for storyId in ("US-A", "US-B", "US-C"):
            assert storyId in err

    def test_fortyViolations_theOutputStatesTheCount(self, runCli):
        """
        Given: the same violation on forty stories
        When: sprint_lint --backlog runs
        Then: the output STATES 40, so it is readable without counting lines

        validationCriterion 2 -- "the criterion that encodes the actual defect".
        """
        data = _cleanBacklog()
        data["stories"] = []
        for i in range(40):
            story = _story(f"US-{600 + i}")
            del story["createdAt"]
            data["stories"].append(story)

        code, _out, err = runCli(data)

        assert code != 0
        summary = [ln for ln in err.splitlines() if "VIOLATIONS:" in ln]
        assert summary, err
        assert "40" in summary[0]

    def test_theStatedCountTracksTheData_oneIsNotReportedAsForty(self, runCli):
        """
        Given: a backlog with exactly ONE violation
        When: sprint_lint --backlog runs
        Then: the summary states 1, not 40

        CONTROL for the test above. "The output states the count" is also
        satisfied by printing a constant; only a second, different data set
        proves the number is derived. This pair is the whole of VC2 -- a
        reader must be able to tell 1 from 41.
        """
        data = _cleanBacklog()
        story = _story("US-600")
        del story["createdAt"]
        data["stories"] = [story]

        code, _out, err = runCli(data)

        assert code != 0
        summary = [ln for ln in err.splitlines() if "VIOLATIONS:" in ln][0]
        assert "1" in summary
        assert "40" not in summary

    def test_theSummaryBreaksTheCountDownByViolationClass(self, runCli):
        """
        Given: three stories missing a field and one with an invalid size
        When: sprint_lint --backlog runs
        Then: the summary names each class with its own count

        END STATE: "plus a count per violation class".
        """
        data = _cleanBacklog()
        data["stories"] = []
        for i in range(3):
            story = _story(f"US-{700 + i}")
            del story["createdAt"]
            data["stories"].append(story)
        data["stories"].append(_story("US-800", size="XXL"))

        code, _out, err = runCli(data)

        assert code != 0
        assert f"{backlog_schema.CODE_STORY_MISSING_FIELDS} 3" in " ".join(err.split())
        assert f"{backlog_schema.CODE_STORY_SIZE} 1" in " ".join(err.split())

    def test_cleanBacklog_exitsZeroAndPrintsNoViolationOutput(self, runCli):
        """
        Given: a schema-clean backlog
        When: sprint_lint --backlog runs
        Then: exit 0, no ERROR lines, and NO summary block

        validationCriterion 3 and the negative case: a lint that prints on
        success trains people to stop reading it, which is the same failure
        one layer up.
        """
        code, out, err = runCli(_cleanBacklog())

        assert code == 0
        assert "ERROR" not in err
        assert "VIOLATIONS:" not in err
        assert "VIOLATIONS:" not in out

    def test_theGateIsNotWeakened_anySingleViolationStillExitsNonZero(self, runCli):
        """
        Given: a backlog with exactly one violation
        When: sprint_lint --backlog runs
        Then: exit is non-zero

        US-670 makes the lint MORE informative, never more permissive.
        "Report" must not become "warn and pass".
        """
        data = _cleanBacklog()
        data["stories"][0]["size"] = "XXL"

        code, _out, _err = runCli(data)

        assert code == 1
