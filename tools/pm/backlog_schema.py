################################################################################
# File Name: backlog_schema.py
# Purpose/Description: Schema types + validator for backlog.json v2.0.0.
#                      Enforces 4-tier hierarchy invariants: no orphans,
#                      valid types, required fields per tier, and
#                      validationCriteria shape.
# Author: Marcus (PM)
# Creation Date: 2026-05-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-27    | Marcus (PM)  | Initial implementation -- Task 1 TDD
# 2026-07-13    | Rex (Ralph)  | US-465: accept 'superseded' as a story status
# 2026-09-04    | Rex (Ralph)  | US-670: collect-all path beside validateBacklog
# ================================================================================
################################################################################

"""
File: tools/pm/backlog_schema.py
Purpose: Schema types + validator for backlog.json v2.0.0.
         Enforces 4-tier hierarchy invariants: no orphans, valid types,
         required fields per tier, validationCriteria shape.

US-670 -- TWO ENTRY POINTS, ONE AUTHORITY.

``validateBacklog`` raises on the FIRST violation; callers depend on that and
it is unchanged. ``collectBacklogViolations`` returns them ALL, so one lint run
can tell a 41-story drift from a 1-story typo (measured 2026-09-01: the lint
printed one line while 41 stories were affected).

Both are thin wrappers over ``_iterViolations`` -- the ONLY place an invariant
is stated. A second hand-written copy of the rules is the drift US-669 and
US-675 closed, and it is banned here by a test that asserts the raised message
is character-identical to the first collected violation's.
"""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

VALID_STORY_TYPES = frozenset({"normal", "issue", "blocker", "tech-debt",
                              "research", "housekeeping", "security"})
VALID_STORY_SIZES = frozenset({"XS", "S", "M", "L"})
VALID_EPIC_STATUSES = frozenset({"pending", "active", "complete"})
VALID_FEATURE_STATUSES = frozenset({"pending", "groomed", "in-sprint", "active", "blocked", "complete", "declined",
                                    "awaiting-validation", "superseded"})
VALID_STORY_STATUSES = frozenset({"pending", "groomed", "in-prd", "sprint-ready",
                                  "in-progress", "blocked", "passed", "complete",
                                  "superseded"})
VALID_TASK_STATUSES = frozenset({"open", "done"})

REQUIRED_STORY_FIELDS = frozenset({
    "id", "parent", "title", "type", "size", "status",
    "goal", "definitionOfDone", "conditionalOutcomes", "validationCriteria",
    "createdAt", "updatedAt",
})


# Violation-class codes (US-670). One per invariant. The lint groups its count
# summary by these, which is what lets a reader tell 41 from 1 without counting
# lines by hand. Codes are part of the tool's output contract -- renaming one is
# a visible change.
CODE_SCHEMA_VERSION = "schemaVersion"
CODE_EPIC_STATUS = "epicStatus"
CODE_FEATURE_ORPHAN = "featureOrphan"
CODE_FEATURE_STATUS = "featureStatus"
CODE_STORY_MISSING_FIELDS = "storyMissingFields"
CODE_STORY_ORPHAN = "storyOrphan"
CODE_STORY_TYPE = "storyType"
CODE_STORY_SIZE = "storySize"
CODE_STORY_STATUS = "storyStatus"
CODE_STORY_VALIDATION_CRITERIA = "storyValidationCriteria"
CODE_STORY_DEFINITION_OF_DONE = "storyDefinitionOfDone"
CODE_STORY_TASKS = "storyTasks"

VIOLATION_CODES = frozenset({
    CODE_SCHEMA_VERSION,
    CODE_EPIC_STATUS,
    CODE_FEATURE_ORPHAN,
    CODE_FEATURE_STATUS,
    CODE_STORY_MISSING_FIELDS,
    CODE_STORY_ORPHAN,
    CODE_STORY_TYPE,
    CODE_STORY_SIZE,
    CODE_STORY_STATUS,
    CODE_STORY_VALIDATION_CRITERIA,
    CODE_STORY_DEFINITION_OF_DONE,
    CODE_STORY_TASKS,
})


class BacklogValidationError(ValueError):
    """Raised when backlog.json fails v2.0.0 schema validation."""


@dataclass(frozen=True)
class BacklogViolation:
    """
    One schema-invariant violation, attributable to one entity.

    Attributes:
        code: Violation class, one of VIOLATION_CODES. Groups the count summary.
        entityId: Id of the Epic / Feature / Story the violation is about.
        message: Human-readable reason -- byte-identical to what
            validateBacklog raises for this violation.
    """
    code: str
    entityId: str
    message: str


def validateBacklog(data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a parsed backlog.json against schema v2.0.0.

    Returns the input dict if valid. Raises BacklogValidationError otherwise.

    Fails on the FIRST violation. Callers that need every violation in one
    pass want collectBacklogViolations instead; this signature is unchanged
    because other tools depend on the raise (US-670 clause 6).

    Args:
        data: Parsed backlog.json as a Python dict.

    Returns:
        The input dict unchanged if all invariants pass.

    Raises:
        BacklogValidationError: If any schema invariant is violated.
    """
    for violation in _iterViolations(data):
        raise BacklogValidationError(violation.message)
    return data


def collectBacklogViolations(data: dict[str, Any]) -> list[BacklogViolation]:
    """
    Return EVERY schema violation in a parsed backlog.json, not just the first.

    US-670: the raising validator under-reported a 41-story drift by 40x,
    which read as a triviality and was deferred. Firing is not the same as
    informing.

    Enforces exactly the invariants validateBacklog enforces -- both walk the
    same generator, so no rule can be relaxed here without relaxing it there.

    Args:
        data: Parsed backlog.json as a Python dict.

    Returns:
        List of BacklogViolation in document order; empty if the backlog is
        schema-clean.
    """
    return list(_iterViolations(data))


def _iterViolations(data: dict[str, Any]) -> Iterator[BacklogViolation]:
    """
    Yield every schema violation in a parsed backlog, in document order.

    THE SINGLE AUTHORITY on backlog invariants. validateBacklog raises on the
    first thing this yields; collectBacklogViolations lists them all.

    Args:
        data: Parsed backlog.json as a Python dict.

    Yields:
        BacklogViolation, one per violated invariant.
    """
    if data.get("schemaVersion") != "2.0.0":
        yield BacklogViolation(
            CODE_SCHEMA_VERSION,
            "backlog",
            f"schemaVersion must be '2.0.0', got {data.get('schemaVersion')!r}",
        )
        # Hard stop, not a cascade: a non-v2 file has a different SHAPE, so
        # walking it would emit a violation for every record it contains
        # (conditionalOutcome 2 -- a hundred derived errors from one cause is
        # the same under-informing failure inverted).
        return

    epicIds = {e["id"] for e in data.get("epics", [])}
    featureIds = {f["id"] for f in data.get("features", [])}

    for epic in data.get("epics", []):
        if epic.get("status") not in VALID_EPIC_STATUSES:
            yield BacklogViolation(
                CODE_EPIC_STATUS,
                str(epic.get("id")),
                f"Epic {epic.get('id')}: invalid status {epic.get('status')!r}",
            )

    for feature in data.get("features", []):
        if feature.get("parent") not in epicIds:
            yield BacklogViolation(
                CODE_FEATURE_ORPHAN,
                str(feature.get("id")),
                f"Feature {feature.get('id')}: orphan -- parent {feature.get('parent')!r} not in epics",
            )
        if feature.get("status") not in VALID_FEATURE_STATUSES:
            yield BacklogViolation(
                CODE_FEATURE_STATUS,
                str(feature.get("id")),
                f"Feature {feature.get('id')}: invalid status {feature.get('status')!r}",
            )

    for story in data.get("stories", []):
        yield from _iterStoryViolations(story, featureIds)


def _iterStoryViolations(
    story: dict[str, Any], featureIds: set[str]
) -> Iterator[BacklogViolation]:
    """
    Yield every schema violation for one Story.

    Dependent checks are suppressed PER FIELD, not per story: a story missing
    `parent` gets no orphan check (it would be meaningless, and would raise
    KeyError), but a story missing only `createdAt` still has its type, size
    and status checked. Aborting the whole story after its first violation
    would reproduce US-670's own defect one level down -- the 41 measured
    stories were missing exactly createdAt/updatedAt, so every other fault in
    them would have stayed invisible.

    Args:
        story: Story dict to validate.
        featureIds: Ids of every Feature in the backlog (for the orphan check).

    Yields:
        BacklogViolation, one per violated invariant.
    """
    storyId = str(story.get("id"))
    missing = REQUIRED_STORY_FIELDS - set(story.keys())
    if missing:
        yield BacklogViolation(
            CODE_STORY_MISSING_FIELDS,
            storyId,
            f"Story {story.get('id')}: missing required fields {sorted(missing)}",
        )

    if "parent" not in missing and story["parent"] not in featureIds:
        yield BacklogViolation(
            CODE_STORY_ORPHAN,
            storyId,
            f"Story {story.get('id')}: orphan -- parent {story['parent']!r} not in features",
        )
    if "type" not in missing and story["type"] not in VALID_STORY_TYPES:
        yield BacklogViolation(
            CODE_STORY_TYPE,
            storyId,
            f"Story {story.get('id')}: invalid type {story['type']!r}",
        )
    if "size" not in missing and story["size"] not in VALID_STORY_SIZES:
        yield BacklogViolation(
            CODE_STORY_SIZE,
            storyId,
            f"Story {story.get('id')}: invalid size {story['size']!r}",
        )
    if "status" not in missing and story["status"] not in VALID_STORY_STATUSES:
        yield BacklogViolation(
            CODE_STORY_STATUS,
            storyId,
            f"Story {story.get('id')}: invalid status {story['status']!r}",
        )
    if "validationCriteria" not in missing:
        yield from _iterValidationCriteriaViolations(story)
    if "definitionOfDone" not in missing:
        yield from _iterDefinitionOfDoneViolations(story)
    yield from _iterTaskViolations(story)


def _iterValidationCriteriaViolations(story: dict[str, Any]) -> Iterator[BacklogViolation]:
    """
    Yield violations of the validationCriteria shape rule.

    Per spec 2026-05-28 (CIO directive #2): every Story must have at least one
    testable (action, outcome) pair so Ralph has a completion signal and Atlas
    has reviewable criteria.

    Args:
        story: Story dict to validate.

    Yields:
        BacklogViolation if validationCriteria is not a list, is empty, or
        contains items without exactly {action, outcome} non-empty strings.
    """
    storyId = str(story.get("id"))
    vc = story.get("validationCriteria")
    if not isinstance(vc, list):
        yield BacklogViolation(
            CODE_STORY_VALIDATION_CRITERIA,
            storyId,
            f"Story {story.get('id')}: validationCriteria must be a list",
        )
        return
    if len(vc) == 0:
        yield BacklogViolation(
            CODE_STORY_VALIDATION_CRITERIA,
            storyId,
            f"Story {story.get('id')}: validationCriteria must be non-empty "
            f"(at least 1 (action, outcome) pair) per directive 2026-05-23 #2",
        )
        return
    for i, item in enumerate(vc):
        if not isinstance(item, dict) or set(item.keys()) != {"action", "outcome"}:
            yield BacklogViolation(
                CODE_STORY_VALIDATION_CRITERIA,
                storyId,
                f"Story {story.get('id')}: validationCriteria[{i}] must have keys "
                f"{{action, outcome}}, got {item!r}",
            )
            continue
        for key in ("action", "outcome"):
            value = item[key]
            if not isinstance(value, str) or not value.strip():
                yield BacklogViolation(
                    CODE_STORY_VALIDATION_CRITERIA,
                    storyId,
                    f"Story {story.get('id')}: validationCriteria[{i}] {key} "
                    f"must be a non-empty string, got {value!r}",
                )


def _iterDefinitionOfDoneViolations(story: dict[str, Any]) -> Iterator[BacklogViolation]:
    """
    Yield violations of the definitionOfDone shape rule.

    Per spec 2026-05-28 (CIO directive #2): every Story must have at least one
    DoD criterion so Ralph knows when complete.

    Args:
        story: Story dict to validate.

    Yields:
        BacklogViolation if definitionOfDone is not a list, is empty, or
        contains non-string / empty-string items.
    """
    storyId = str(story.get("id"))
    dod = story.get("definitionOfDone")
    if not isinstance(dod, list):
        yield BacklogViolation(
            CODE_STORY_DEFINITION_OF_DONE,
            storyId,
            f"Story {story.get('id')}: definitionOfDone must be a list",
        )
        return
    if len(dod) == 0:
        yield BacklogViolation(
            CODE_STORY_DEFINITION_OF_DONE,
            storyId,
            f"Story {story.get('id')}: definitionOfDone must be non-empty "
            f"(at least 1 criterion) per directive 2026-05-23 #2",
        )
        return
    for i, item in enumerate(dod):
        if not isinstance(item, str) or not item.strip():
            yield BacklogViolation(
                CODE_STORY_DEFINITION_OF_DONE,
                storyId,
                f"Story {story.get('id')}: definitionOfDone[{i}] must be a non-empty "
                f"string, got {item!r}",
            )


def _iterTaskViolations(story: dict[str, Any]) -> Iterator[BacklogViolation]:
    """
    Yield violations of the tasks shape rule.

    Args:
        story: Story dict to validate.

    Yields:
        BacklogViolation if tasks is not a list or a task has an invalid status.
    """
    storyId = str(story.get("id"))
    tasks = story.get("tasks", [])
    if not isinstance(tasks, list):
        yield BacklogViolation(
            CODE_STORY_TASKS,
            storyId,
            f"Story {story.get('id')}: tasks must be a list",
        )
        return
    for task in tasks:
        if task.get("status") not in VALID_TASK_STATUSES:
            yield BacklogViolation(
                CODE_STORY_TASKS,
                storyId,
                f"Story {story.get('id')} task {task.get('id')!r}: "
                f"invalid status {task.get('status')!r}",
            )
