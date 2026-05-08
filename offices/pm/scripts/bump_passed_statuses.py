#!/usr/bin/env python3
"""
bump_passed_statuses.py -- Sprint-close Phase 1 hygiene.

Walks offices/ralph/sprint.json and bumps status fields to 'passed' for any
story where passes:true but status is still pending/complete/completed
(Ralph's standing hygiene gap; same pattern observed every sprint close
since Sprint 14).

Usage:
  python offices/pm/scripts/bump_passed_statuses.py             # default sprint.json path
  python offices/pm/scripts/bump_passed_statuses.py --dry-run   # preview without writing
  python offices/pm/scripts/bump_passed_statuses.py --path <override>

Exit code: 0 on success (regardless of count bumped), 1 on parse error.

Saves PM ~50 tokens per sprint close (vs inline `python -c` block) and
makes the intent reviewable in version control.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPRINT_PATH = REPO_ROOT / "offices" / "ralph" / "sprint.json"

TERMINAL_NON_PASSED = ("pending", "complete", "completed")


def bumpStatuses(path: Path, dryRun: bool) -> int:
    """Bump pending/complete/completed -> passed for stories with passes:true.

    Returns the number of stories bumped.
    """
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    bumped: list[tuple[str, str]] = []

    for story in data.get("stories", []):
        if story.get("passes") is not True:
            continue
        currentStatus = story.get("status")
        if currentStatus in TERMINAL_NON_PASSED:
            bumped.append((story.get("id", "?"), currentStatus))
            story["status"] = "passed"

    if not bumped:
        print("No status fields to bump (all passes:true stories already 'passed')")
        return 0

    if dryRun:
        print(f"DRY-RUN: would bump {len(bumped)} status field(s):")
        for storyId, oldStatus in bumped:
            print(f"  {storyId:<8} {oldStatus} -> passed")
        return len(bumped)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Bumped {len(bumped)} status field(s):")
    for storyId, oldStatus in bumped:
        print(f"  {storyId:<8} {oldStatus} -> passed")
    return len(bumped)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--path", default=str(DEFAULT_SPRINT_PATH), help="sprint.json path override")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args(argv)

    bumpStatuses(Path(args.path), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
