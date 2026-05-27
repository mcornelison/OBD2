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
# ================================================================================
################################################################################

"""
File: offices/pm/scripts/backlog_schema.py
Purpose: Schema types + validator for backlog.json v2.0.0.
         Enforces 4-tier hierarchy invariants: no orphans, valid types,
         required fields per tier, validationCriteria shape.
"""
from typing import Any

VALID_STORY_TYPES = frozenset({"normal", "issue", "blocker", "tech-debt",
                              "research", "housekeeping", "security"})
VALID_STORY_SIZES = frozenset({"XS", "S", "M", "L"})
VALID_EPIC_STATUSES = frozenset({"pending", "active", "complete"})
VALID_FEATURE_STATUSES = frozenset({"pending", "groomed", "in-sprint", "active", "complete"})
VALID_STORY_STATUSES = frozenset({"pending", "groomed", "in-prd", "sprint-ready",
                                  "in-progress", "blocked", "passed", "complete"})
VALID_TASK_STATUSES = frozenset({"open", "done"})

REQUIRED_STORY_FIELDS = frozenset({
    "id", "parent", "title", "type", "size", "status",
    "goal", "definitionOfDone", "conditionalOutcomes", "validationCriteria",
    "createdAt", "updatedAt",
})


class BacklogValidationError(ValueError):
    """Raised when backlog.json fails v2.0.0 schema validation."""


def validateBacklog(data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a parsed backlog.json against schema v2.0.0.

    Returns the input dict if valid. Raises BacklogValidationError otherwise.

    Args:
        data: Parsed backlog.json as a Python dict.

    Returns:
        The input dict unchanged if all invariants pass.

    Raises:
        BacklogValidationError: If any schema invariant is violated.
    """
    if data.get("schemaVersion") != "2.0.0":
        raise BacklogValidationError(
            f"schemaVersion must be '2.0.0', got {data.get('schemaVersion')!r}"
        )

    epicIds = {e["id"] for e in data.get("epics", [])}
    featureIds = {f["id"] for f in data.get("features", [])}

    for epic in data.get("epics", []):
        if epic.get("status") not in VALID_EPIC_STATUSES:
            raise BacklogValidationError(
                f"Epic {epic.get('id')}: invalid status {epic.get('status')!r}"
            )

    for feature in data.get("features", []):
        if feature.get("parent") not in epicIds:
            raise BacklogValidationError(
                f"Feature {feature.get('id')}: orphan -- parent {feature.get('parent')!r} not in epics"
            )
        if feature.get("status") not in VALID_FEATURE_STATUSES:
            raise BacklogValidationError(
                f"Feature {feature.get('id')}: invalid status {feature.get('status')!r}"
            )

    for story in data.get("stories", []):
        missing = REQUIRED_STORY_FIELDS - set(story.keys())
        if missing:
            raise BacklogValidationError(
                f"Story {story.get('id')}: missing required fields {sorted(missing)}"
            )
        if story["parent"] not in featureIds:
            raise BacklogValidationError(
                f"Story {story['id']}: orphan -- parent {story['parent']!r} not in features"
            )
        if story["type"] not in VALID_STORY_TYPES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid type {story['type']!r}"
            )
        if story["size"] not in VALID_STORY_SIZES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid size {story['size']!r}"
            )
        if story["status"] not in VALID_STORY_STATUSES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid status {story['status']!r}"
            )
        _validateValidationCriteria(story)
        _validateTasks(story)

    return data


def _validateValidationCriteria(story: dict[str, Any]) -> None:
    """
    Validate that validationCriteria is a list of {action, outcome} dicts.

    Args:
        story: Story dict to validate.

    Raises:
        BacklogValidationError: If validationCriteria is missing, not a list,
            or contains items without exactly {action, outcome} keys.
    """
    vc = story.get("validationCriteria")
    if not isinstance(vc, list):
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be a list"
        )
    for i, item in enumerate(vc):
        if not isinstance(item, dict) or set(item.keys()) != {"action", "outcome"}:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] must have keys {{action, outcome}}, "
                f"got {item!r}"
            )


def _validateTasks(story: dict[str, Any]) -> None:
    """
    Validate that tasks is a list and each task has a valid status.

    Args:
        story: Story dict to validate.

    Raises:
        BacklogValidationError: If tasks is not a list or a task has
            an invalid status value.
    """
    tasks = story.get("tasks", [])
    if not isinstance(tasks, list):
        raise BacklogValidationError(
            f"Story {story['id']}: tasks must be a list"
        )
    for task in tasks:
        if task.get("status") not in VALID_TASK_STATUSES:
            raise BacklogValidationError(
                f"Story {story['id']} task {task.get('id')!r}: invalid status {task.get('status')!r}"
            )
