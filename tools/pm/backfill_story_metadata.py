#!/usr/bin/env python3
################################################################################
# File Name: backfill_story_metadata.py
# Purpose/Description: Idempotent repair tool for backlog.json v2.0.0 metadata
#                      drift (US-465 / F-118). Backfills the required story
#                      fields (status, createdAt, updatedAt, conditionalOutcomes,
#                      tasks) that were dropped for stories shipped in
#                      Sprints 50-55, so pm_status.py and `sprint_lint --backlog`
#                      run clean. Metadata-only: never touches semantic content
#                      (title/goal/DoD/type/size/parent).
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (Ralph)  | Initial implementation -- US-465 TDD
# ================================================================================
################################################################################

"""
Backfill drifted required metadata onto backlog.json v2.0.0 stories.

The 47-story metadata drift (Sprints 50-55) left many shipped stories missing
required fields, which crashes pm_status.py (KeyError on ``s["status"]`` /
``s["parent"]``) and fails ``sprint_lint --backlog``. This tool repairs it.

Authoritative signal for real end-state: the archived sprint.json files under
``offices/ralph/archive/``. A story that appears with ``passes: true`` in an
archived sprint SHIPPED -> its real status is ``complete``. Terminal states
(complete/superseded/declined) are preserved as-is; a genuinely-open story with
no shipped signal is NEVER guessed complete (conservative ``pending``).

Dates are proxy-derived from the earliest archived sprint the story appears in
(the archive filename carries the sprint-close date, e.g.
``sprint.archive.2026-07-01_...`` -> ``2026-07-01``) and marked proxy-derived
in a ``metaBackfill`` provenance object. Git first-appearance is used as an
optional secondary proxy for stories with no archive appearance; a story with
no archive or git signal degrades to the run date, still marked proxy. (A 94-story
git pickaxe over a 218 KB file on the slow SMB share is not in-loop-feasible,
and the v1->v2 backlog migration muddies true first-appearance -- so the
sprint-close proxy is the deterministic, reusable primary source.)

Idempotent: a story that already carries every required field (and a list
``tasks``) is skipped, so a re-run is a no-op.

Usage:
  python -m tools.pm.backfill_story_metadata            # apply + write
  python -m tools.pm.backfill_story_metadata --dry-run  # report only
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

# Reconfigure stdout to UTF-8 so provenance / summary printing does not crash on
# a Windows cp1252 console (mirrors pm_status.py). See US-466.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Roots come from the _paths SSOT -- depth-independent by construction.
from tools.pm._paths import REPO_ROOT, SHARE_ROOT

BACKLOG_PATH = SHARE_ROOT / "pm" / "backlog.json"
ARCHIVE_DIR = SHARE_ROOT / "ralph" / "archive"

# The required story fields come from the schema, which is their SSOT.
#
# This was a restated copy until US-669, guarded only by a comment saying the
# two "MUST stay in sync". That is the same defect class US-669 closes on the
# creation side: a duplicated list goes stale the moment the schema grows, and
# nothing goes red -- the backfill would simply stop repairing the new field
# while still reporting every story compliant. backlog_schema imports nothing
# from tools.pm, so there is no circular-import cost to reading it directly.
# tests/pm/test_backlog_add_story.py bans a second assignment across tools/pm.
from tools.pm.backlog_schema import REQUIRED_STORY_FIELDS  # noqa: E402

# Deliberate terminal end-states -- never overwritten by a shipped signal.
TERMINAL_STATUSES = frozenset({"complete", "superseded", "declined"})

_ARCHIVE_DATE_RE = re.compile(r"sprint\.archive\.(\d{4}-\d{2}-\d{2})_")


# ---------------------------------------------------------------------------
# archive indexing
# ---------------------------------------------------------------------------

def buildSprintDateIndex(archiveDir: Path) -> dict[int, str]:
    """Map each sprint number to its earliest close date (YYYY-MM-DD).

    Reads the ``sprint`` field inside each ``sprint.archive.*.json`` and pairs
    it with the date embedded in the filename. When a sprint was re-archived
    more than once, the earliest date wins (first close).

    Args:
        archiveDir: Directory containing ``sprint.archive.*.json`` files.

    Returns:
        Dict of ``{sprintNumber: "YYYY-MM-DD"}``.
    """
    index: dict[int, str] = {}
    for path in sorted(archiveDir.glob("sprint.archive.*.json")):
        match = _ARCHIVE_DATE_RE.search(path.name)
        if not match:
            continue
        fileDate = match.group(1)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        sprint = data.get("sprint")
        if not isinstance(sprint, int):
            continue
        existing = index.get(sprint)
        if existing is None or fileDate < existing:
            index[sprint] = fileDate
    return index


def buildStoryShipIndex(archiveDir: Path) -> dict[str, dict[str, set[int]]]:
    """Map each story id to the sprints it was ``seen`` in and ``passed`` in.

    A story with ``passes: true`` in an archived sprint SHIPPED -- this is the
    authoritative real-end-state signal that the live ``status`` field lost.

    Args:
        archiveDir: Directory containing ``sprint.archive.*.json`` files.

    Returns:
        Dict of ``{storyId: {"passed": set[int], "seen": set[int]}}``.
    """
    index: dict[str, dict[str, set[int]]] = {}
    for path in sorted(archiveDir.glob("sprint.archive.*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        sprint = data.get("sprint")
        if not isinstance(sprint, int):
            continue
        for story in data.get("stories", []):
            storyId = story.get("id")
            if not storyId:
                continue
            entry = index.setdefault(storyId, {"passed": set(), "seen": set()})
            entry["seen"].add(sprint)
            if story.get("passes") is True:
                entry["passed"].add(sprint)
    return index


# ---------------------------------------------------------------------------
# per-story resolution
# ---------------------------------------------------------------------------

def isCompliant(story: dict) -> bool:
    """True when a story carries every required field and a list ``tasks``.

    This is the idempotency gate: compliant stories are skipped so a re-run is
    a no-op.

    Args:
        story: A backlog story dict.

    Returns:
        True if no backfill is needed.
    """
    if not REQUIRED_STORY_FIELDS <= set(story.keys()):
        return False
    return isinstance(story.get("tasks"), list)


def resolveStatus(story: dict, shipIndex: dict[str, dict[str, set[int]]]) -> tuple[str, str]:
    """Resolve a story's real end-state status + a provenance source label.

    Priority:
      1. Terminal status present (complete/superseded/declined) -> preserved.
      2. Shipped (passes:true in any archive)                   -> ``complete``.
      3. Present non-terminal status, not shipped               -> preserved.
      4. Absent + not shipped                                   -> ``pending``
         (conservative; a genuinely-open story is never guessed complete).

    Args:
        story: A backlog story dict.
        shipIndex: Output of :func:`buildStoryShipIndex`.

    Returns:
        ``(status, sourceLabel)``.
    """
    current = story.get("status")
    if current in TERMINAL_STATUSES:
        return current, "preserved-terminal"

    entry = shipIndex.get(story.get("id", ""), {})
    if entry.get("passed"):
        return "complete", "archived-sprint-passes"

    if current:
        return current, "preserved-existing"

    return "pending", "conservative-default"


def resolveDates(
    story: dict,
    shipIndex: dict[str, dict[str, set[int]]],
    sprintDates: dict[int, str],
    gitResolver: Callable[[str], str | None] | None,
    today: str,
) -> tuple[str, str, str]:
    """Resolve proxy createdAt/updatedAt for a story + a provenance source.

    Primary: the earliest archived sprint the story appears in (passed or
    seen) -> that sprint's close date. Secondary: an optional git
    first-appearance resolver. Fallback: the run date (still marked proxy).

    Args:
        story: A backlog story dict.
        shipIndex: Output of :func:`buildStoryShipIndex`.
        sprintDates: Output of :func:`buildSprintDateIndex`.
        gitResolver: Optional callable ``(storyId) -> "YYYY-MM-DD" | None``.
        today: The run date (YYYY-MM-DD), used only as last-resort proxy.

    Returns:
        ``(createdAt, updatedAt, sourceLabel)``. Both dates use the same proxy.
    """
    entry = shipIndex.get(story.get("id", ""), {})
    sprints = entry.get("passed", set()) | entry.get("seen", set())
    candidate = [s for s in sprints if s in sprintDates]
    if candidate:
        earliest = min(candidate)
        date = sprintDates[earliest]
        return date, date, f"proxy:sprint-{earliest}-close"

    if gitResolver is not None:
        gitDate = gitResolver(story.get("id", ""))
        if gitDate:
            return gitDate, gitDate, "proxy:git-first-appearance"

    return today, today, "proxy:unknown-conservative"


def backfillStory(
    story: dict,
    shipIndex: dict[str, dict[str, set[int]]],
    sprintDates: dict[int, str],
    gitResolver: Callable[[str], str | None] | None = None,
    today: str | None = None,
) -> tuple[dict, bool]:
    """Return ``(story, changed)`` after backfilling any missing metadata.

    Metadata-only: never mutates title/goal/DoD/type/size/parent. Existing
    createdAt/updatedAt values are preserved; only absent ones are filled.
    A ``metaBackfill`` provenance object records the derivation.

    Args:
        story: A backlog story dict (mutated in place and also returned).
        shipIndex: Output of :func:`buildStoryShipIndex`.
        sprintDates: Output of :func:`buildSprintDateIndex`.
        gitResolver: Optional git first-appearance resolver.
        today: Run date (YYYY-MM-DD); defaults to the system date.

    Returns:
        ``(story, changed)`` -- ``changed`` is False for an already-compliant
        story (idempotency).
    """
    if isCompliant(story):
        return story, False

    today = today or _dt.date.today().isoformat()

    if "conditionalOutcomes" not in story:
        story["conditionalOutcomes"] = []
    if not isinstance(story.get("tasks"), list):
        story["tasks"] = []

    status, statusSource = resolveStatus(story, shipIndex)
    story["status"] = status

    createdAt, updatedAt, dateSource = resolveDates(
        story, shipIndex, sprintDates, gitResolver, today
    )
    if "createdAt" not in story:
        story["createdAt"] = createdAt
    if "updatedAt" not in story:
        story["updatedAt"] = updatedAt

    story["metaBackfill"] = {
        "backfilledAt": today,
        "statusSource": statusSource,
        "dateSource": dateSource,
        "note": "US-465 metadata-drift repair; dates proxy-derived, not exact.",
    }
    return story, True


# ---------------------------------------------------------------------------
# whole-backlog driver
# ---------------------------------------------------------------------------

def _gitFirstAppearanceResolver(repoRoot: Path) -> Callable[[str], str | None]:
    """Build a best-effort git first-appearance date resolver.

    Uses a single ``git log -S`` pickaxe per story id against backlog.json and
    reads the oldest matching commit's author date. Degrades to ``None`` on any
    git failure so the caller falls back to the run date. Used only for the rare
    story with no archived-sprint appearance (one pickaxe, not 94).
    """
    # THE EVICTION BOUNDARY.
    #
    # backlog.json was tracked at offices/pm/backlog.json until 2026-08-24, when
    # offices/ was evicted from the repo and moved to the fleet share. This
    # pickaxe therefore still works -- but ONLY for stories that first appeared
    # on or before that date. Every commit touching the backlog after it is on
    # the share, which is not version controlled at all, so git has nothing to
    # search.
    #
    # That distinction has to be VISIBLE. Before this constant existed the
    # resolver returned None for a post-boundary story exactly as it does for a
    # git failure, and the caller silently substituted the run date -- a
    # confident, wrong first-appearance date with no indication it was invented.
    # A post-boundary miss is now reported as a KNOWN, EXPLAINED gap.
    backlogRel = "offices/pm/backlog.json"
    evictionBoundary = "2026-08-24"

    def resolver(storyId: str) -> str | None:
        try:
            result = subprocess.run(  # noqa: S603 -- explicit argv
                ["git", "log", "--reverse", "--format=%ad", "--date=short",
                 "-S", f'"{storyId}"', "--", backlogRel],
                cwd=str(repoRoot), capture_output=True, text=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if lines:
            return lines[0]
        # No pre-boundary commit touches this story. Say why rather than let the
        # caller fall back to today's date as if it had measured something.
        print(
            f"  {storyId}: no first-appearance date available -- backlog.json "
            f"left version control on {evictionBoundary} (offices/ eviction), so "
            f"git history cannot date a story introduced after it. Falling back "
            f"to the run date; treat that value as UNKNOWN, not measured.",
            file=sys.stderr,
        )
        return None

    return resolver


def backfillBacklog(
    data: dict,
    archiveDir: Path,
    gitResolver: Callable[[str], str | None] | None = None,
    today: str | None = None,
) -> tuple[dict, list[str]]:
    """Backfill every drifted story in a parsed backlog dict.

    Args:
        data: Parsed backlog.json (mutated in place and returned).
        archiveDir: Directory of archived sprint.json files (the ship signal).
        gitResolver: Optional git first-appearance resolver.
        today: Run date (YYYY-MM-DD); defaults to the system date.

    Returns:
        ``(data, changes)`` -- ``changes`` is a list of "US-XXX -> ..." strings
        (empty when nothing needed backfilling; a re-run yields an empty list).
    """
    sprintDates = buildSprintDateIndex(archiveDir)
    shipIndex = buildStoryShipIndex(archiveDir)
    changes: list[str] = []
    for story in data.get("stories", []):
        _story, changed = backfillStory(story, shipIndex, sprintDates, gitResolver, today)
        if changed:
            changes.append(
                f"{story['id']} -> status={story['status']} "
                f"createdAt={story['createdAt']} ({story['metaBackfill']['dateSource']})"
            )
    return data, changes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing.")
    parser.add_argument("--backlog", default=str(BACKLOG_PATH),
                        help="backlog.json path override.")
    args = parser.parse_args(argv)

    backlogPath = Path(args.backlog)
    if not backlogPath.exists():
        print(f"ERROR: {backlogPath} not found", file=sys.stderr)
        return 2

    data = json.loads(backlogPath.read_text(encoding="utf-8"))
    gitResolver = _gitFirstAppearanceResolver(REPO_ROOT)
    data, changes = backfillBacklog(data, ARCHIVE_DIR, gitResolver=gitResolver)

    if not changes:
        print("backfill: no drift -- all stories already compliant (no-op).")
        return 0

    print(f"backfill: {len(changes)} stor{'y' if len(changes) == 1 else 'ies'} "
          f"{'would be' if args.dry_run else ''} backfilled:")
    for line in changes:
        print(f"  {line}")

    if args.dry_run:
        print("\n--dry-run: no file written.")
        return 0

    backlogPath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {backlogPath}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
