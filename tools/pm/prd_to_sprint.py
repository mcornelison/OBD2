################################################################################
# File Name: prd_to_sprint.py
# Purpose/Description: Convert a PRD MD file (YAML frontmatter + markdown body)
#   into a Ralph-readable sprint.json contract. Snapshots Story content at
#   conversion time (sprint.json is frozen; later Story.md edits do not propagate).
# Author: Marcus (PM)
# Creation Date: 2026-05-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-27    | Marcus (PM)  | Initial implementation -- Task 5 backlog-hierarchy-v2
# ================================================================================
################################################################################

"""
File: tools/pm/prd_to_sprint.py
Purpose: Convert a PRD MD file (YAML frontmatter + markdown body) into
         a Ralph-readable sprint.json contract. Snapshots Story.md content
         at conversion time (sprint.json is frozen; later Story.md edits
         do not propagate).
"""
import json
import sys
from pathlib import Path
from typing import Any

import frontmatter

# Roots come from the _paths SSOT -- depth-independent by construction.
from tools.pm._paths import SHARE_ROOT, resolveShareRoot


def convertPrdToSprint(
    prdPath: Path, outPath: Path, shareRoot: Path | None = None
) -> None:
    """Read PRD MD at prdPath, write generated sprint.json to outPath.

    Args:
        prdPath: Path to a PRD markdown file with YAML frontmatter containing
                 sprint / version / selectedStories.
        outPath: Path where the generated sprint.json should be written.
        shareRoot: Fleet-share root containing pm/backlog.json and
                  offices/pm/backlog/US-*.md files.

    Raises:
        ValueError: If a selectedStory referenced in the PRD is not in backlog.json,
                    or if required frontmatter fields (sprint, version, selectedStories)
                    are missing from the PRD, or if a story's parent feature or epic
                    cannot be resolved in backlog.json.
    """
    prd = frontmatter.load(prdPath)
    meta = prd.metadata

    if "selectedStories" not in meta:
        raise ValueError(
            f"PRD {prdPath.name}: missing required frontmatter field 'selectedStories'"
        )
    if "sprint" not in meta:
        raise ValueError(
            f"PRD {prdPath.name}: missing required frontmatter field 'sprint'"
        )
    if "version" not in meta:
        raise ValueError(
            f"PRD {prdPath.name}: missing required frontmatter field 'version'"
        )

    if shareRoot is None:
        shareRoot = resolveShareRoot()
    backlogPath = shareRoot / "pm" / "backlog.json"
    backlog = json.loads(backlogPath.read_text(encoding="utf-8"))

    epicsById: dict[str, Any] = {e["id"]: e for e in backlog["epics"]}
    featuresById: dict[str, Any] = {f["id"]: f for f in backlog["features"]}
    storiesById: dict[str, Any] = {s["id"]: s for s in backlog["stories"]}

    sprintStories: list[dict[str, Any]] = []
    bigDoD: list[str] = []

    for storyId in meta["selectedStories"]:
        story = storiesById.get(storyId)
        if not story:
            raise ValueError(
                f"PRD {prdPath.name}: selectedStory {storyId} not in backlog.json"
            )
        feature = featuresById.get(story["parent"])
        if not feature:
            raise ValueError(
                f"PRD {prdPath.name}: story {storyId} parent {story['parent']!r} not in backlog.json features"
            )
        epic = epicsById.get(feature["parent"])
        if not epic:
            raise ValueError(
                f"PRD {prdPath.name}: feature {feature['id']} parent {feature['parent']!r} not in backlog.json epics"
            )

        sprintStories.append({
            "id": story["id"],
            "title": story["title"],
            "parent": feature["id"],
            "epicId": epic["id"],
            "type": story["type"],
            "size": story["size"],
            "status": "sprint-ready",
            "passes": False,
            "acceptance": story.get("definitionOfDone", []),
            "validationCriteria": story.get("validationCriteria", []),
            "conditionalOutcomes": story.get("conditionalOutcomes", []),
            "goal": story.get("goal", ""),
            "tasks": story.get("tasks", []),
        })

        for vc in story.get("validationCriteria", []):
            bigDoD.append(
                f"({vc.get('action', '')}) → ({vc.get('outcome', '')})  [from {storyId}]"
            )

    # Sprint contract = the aggregated bigDefinitionOfDone + per-story
    # validationCriteria.  The freeze-hash mechanic (frozenAt / bigDoDHash) was
    # retired per CIO directive 2026-07-13 -- it added a drift-lock we don't
    # need on a two-author contract flow.  sprint_lint skips the drift check
    # when frozenAt is absent, so no consumer change is required.
    sprintJson: dict[str, Any] = {
        "schemaVersion": "2.0.0",
        "sprint": meta["sprint"],
        "version": meta["version"],
        "createdFromPRD": str(prdPath.relative_to(shareRoot)).replace("\\", "/"),
        "stories": sprintStories,
        "validation": {
            "bigDefinitionOfDone": bigDoD,
        },
    }

    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.write_text(json.dumps(sprintJson, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: prd_to_sprint.py <prd-md> <sprint-json>", file=sys.stderr)
        sys.exit(1)
    convertPrdToSprint(Path(sys.argv[1]), Path(sys.argv[2]), SHARE_ROOT)
    print(f"Wrote {sys.argv[2]}")
