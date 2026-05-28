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
File: offices/pm/scripts/prd_to_sprint.py
Purpose: Convert a PRD MD file (YAML frontmatter + markdown body) into
         a Ralph-readable sprint.json contract. Snapshots Story.md content
         at conversion time (sprint.json is frozen; later Story.md edits
         do not propagate).
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

from offices.pm.scripts.sprint_lint import _canonicalizeBigDoD


def convertPrdToSprint(prdPath: Path, outPath: Path, repoRoot: Path) -> None:
    """Read PRD MD at prdPath, write generated sprint.json to outPath.

    Args:
        prdPath: Path to a PRD markdown file with YAML frontmatter containing
                 sprint / version / selectedStories.
        outPath: Path where the generated sprint.json should be written.
        repoRoot: Path containing offices/pm/backlog.json and
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

    backlogPath = repoRoot / "offices" / "pm" / "backlog.json"
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

    # Freeze the contract per spec 2026-05-28 (CIO directive #2).
    # Canonicalization recipe lives in sprint_lint._canonicalizeBigDoD so
    # the freeze write (here) and the freeze-drift read (sprint_lint) share
    # a single source of truth.
    canonicalBigDoD = _canonicalizeBigDoD(bigDoD)
    bigDoDHash = hashlib.sha256(canonicalBigDoD.encode("utf-8")).hexdigest()
    frozenAt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sprintJson: dict[str, Any] = {
        "schemaVersion": "2.0.0",
        "sprint": meta["sprint"],
        "version": meta["version"],
        "createdFromPRD": str(prdPath.relative_to(repoRoot)).replace("\\", "/"),
        "stories": sprintStories,
        "validation": {
            "bigDefinitionOfDone": bigDoD,
            "frozenAt": frozenAt,
            "bigDoDHash": bigDoDHash,
        },
    }

    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.write_text(json.dumps(sprintJson, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: prd_to_sprint.py <prd-md> <sprint-json>", file=sys.stderr)
        sys.exit(1)
    repoRoot = Path(__file__).resolve().parents[3]
    convertPrdToSprint(Path(sys.argv[1]), Path(sys.argv[2]), repoRoot)
    print(f"Wrote {sys.argv[2]}")
