#!/usr/bin/env python3
"""
pm_status.py -- PM session-start snapshot.

Prints a compact one-screen status summary:
  - current sprint: name, story count, per-story (id/size/priority/status/deps)
  - backlog: B- features grouped by status (v1) or Epic/Feature/Story tree (v2)
  - story counter: nextId + last reservation note

Detects backlog schemaVersion:
  - "2.0.0" → v2 path: computeRollups() + renderTree() + active PRDs + sprint
  - anything else → v1 legacy path (existing behaviour unchanged)

Used at session start by Marcus (PM) to orient before any planning work.
Stdlib-only; runs on Windows git-bash or Linux.

Usage:
  python offices/pm/scripts/pm_status.py              # full snapshot
  python offices/pm/scripts/pm_status.py --sprint     # sprint only
  python offices/pm/scripts/pm_status.py --backlog    # backlog only
  python offices/pm/scripts/pm_status.py --counter    # counter only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Migrated v1 backlog titles may contain Unicode (e.g. '→'). Reconfigure stdout
# to UTF-8 so the tree view doesn't crash on Windows cp1252 consoles.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[3]
SPRINT_PATH = REPO_ROOT / "offices" / "ralph" / "sprint.json"
BACKLOG_PATH = REPO_ROOT / "offices" / "pm" / "backlog.json"
COUNTER_PATH = REPO_ROOT / "offices" / "pm" / "story_counter.json"


def printSprintSummary() -> None:
    """Print sprint.json summary (v1 legacy entry point)."""
    if not SPRINT_PATH.exists():
        print(f"[sprint] {SPRINT_PATH} does not exist")
        return
    _renderSprintFromJson(SPRINT_PATH)



def printCounterSummary() -> None:
    if not COUNTER_PATH.exists():
        print(f"[counter] {COUNTER_PATH} does not exist")
        return
    d = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
    print("=== STORY COUNTER ===")
    print(f"  nextId:       US-{d.get('nextId', '?')}")
    print(f"  lastUpdated:  {d.get('lastUpdated', '?')}")
    notes = d.get("notes", "")
    if notes:
        noteLines = notes.split(". ")
        print("  last note:")
        for line in noteLines:
            if line.strip():
                print(f"    {line.strip()}")


# ---------------------------------------------------------------------------
# v2.0.0 helpers — Epic/Feature/Story tree view + status rollup
# ---------------------------------------------------------------------------

def computeRollups(data: dict) -> dict:
    """Recompute Epic + Feature statuses from their children.

    Writes the cached value into the data dict in-place and returns it.
    Caller is responsible for persisting if desired.

    Args:
        data: Parsed backlog.json dict (schemaVersion 2.0.0).

    Returns:
        The same dict with updated status fields on all epics and features.
    """
    storiesByFeature: dict[str, list[dict]] = {}
    for s in data.get("stories", []):
        storiesByFeature.setdefault(s["parent"], []).append(s)

    featuresByEpic: dict[str, list[dict]] = {}
    for f in data.get("features", []):
        children = storiesByFeature.get(f["id"], [])
        newStatus = _rollupFeatureStatus(children)
        # Preserve manually-set status when Feature has no Stories (migration
        # case + brand-new Feature case). Only overwrite when children dictate.
        if newStatus is not None:
            f["status"] = newStatus
        featuresByEpic.setdefault(f["parent"], []).append(f)

    for e in data.get("epics", []):
        children = featuresByEpic.get(e["id"], [])
        newStatus = _rollupEpicStatus(children)
        if newStatus is not None:
            e["status"] = newStatus

    return data


def _rollupFeatureStatus(stories: list[dict]) -> str | None:
    """
    Roll up Feature status from its stories per spec §5.

    Rules (in priority order):
    - no stories               -> None (preserve manually-set status)
    - all stories complete     -> complete
    - any in-flight story
      (in-progress, sprint-ready, in-prd, blocked) -> active
    - some-but-not-all complete (partial progress)  -> active
    - any groomed or passed    -> groomed
    - else                     -> pending
    """
    if not stories:
        return None
    statuses = {s["status"] for s in stories}
    if statuses == {"complete"}:
        return "complete"
    if any(st in statuses for st in ("in-progress", "sprint-ready", "in-prd", "blocked")):
        return "active"
    if "complete" in statuses:
        # partial completion -- some done, some not yet
        return "active"
    if "groomed" in statuses or "passed" in statuses:
        return "groomed"
    return "pending"


def _rollupEpicStatus(features: list[dict]) -> str | None:
    """Compute Epic status from its child features (spec §5).

    Args:
        features: List of feature dicts (after their statuses have been rolled up).

    Returns:
        Rolled-up status string, or None to preserve manually-set status when no features.
    """
    if not features:
        return None
    statuses = {f["status"] for f in features}
    if statuses == {"complete"}:
        return "complete"
    if statuses == {"pending"}:
        return "pending"
    return "active"


def renderTree(data: dict) -> str:
    """Render Epic → Feature → Story tree as plain text.

    Pure function — no I/O side effects.

    Args:
        data: Parsed backlog.json dict (schemaVersion 2.0.0).

    Returns:
        Multi-line string with indented hierarchy.
    """
    storiesByFeature: dict[str, list[dict]] = {}
    for s in data.get("stories", []):
        storiesByFeature.setdefault(s["parent"], []).append(s)

    featuresByEpic: dict[str, list[dict]] = {}
    for f in data.get("features", []):
        featuresByEpic.setdefault(f["parent"], []).append(f)

    lines = []
    for e in data.get("epics", []):
        lines.append(f"{e['id']:<8} [{e['status']:<8}] {e['title']}")
        for f in featuresByEpic.get(e["id"], []):
            lines.append(f"  {f['id']:<8} [{f['status']:<8}] {f['title']}")
            for s in storiesByFeature.get(f["id"], []):
                lines.append(
                    f"    {s['id']:<8} [{s['status']:<12}] "
                    f"({s['type']}, {s['size']}) {s['title']}"
                )
    return "\n".join(lines)


def _renderSprintFromJson(sprintPath: Path) -> None:
    """Print sprint.json summary (shared by v1 and v2 paths).

    Args:
        sprintPath: Path to sprint.json.
    """
    d = json.loads(sprintPath.read_text(encoding="utf-8"))
    print(f"=== SPRINT: {d.get('sprint', '?')} ===")
    print("  branch hint:   sprint-branch per Rule 8 (see PM projectManager.md)")
    print(f"  createdBy:     {d.get('createdBy', '?')}")
    print(f"  createdAt:     {d.get('createdAt', '?')}")
    baseline = d.get("testBaseline", {})
    print(
        f"  testBaseline:  fastSuite={baseline.get('fastSuite', '?')} "
        f"ruffErrors={baseline.get('ruffErrors', '?')}"
    )
    stories = d.get("stories", [])
    print(f"  stories:       {len(stories)}")
    sizeCounts: dict[str, int] = {}
    statusCounts: dict[str, int] = {}
    for s in stories:
        sizeCounts[s.get("size", "?")] = sizeCounts.get(s.get("size", "?"), 0) + 1
        statusCounts[s.get("status", "?")] = statusCounts.get(s.get("status", "?"), 0) + 1
    print(f"  sizes:         {dict(sorted(sizeCounts.items()))}")
    print(f"  statuses:      {dict(sorted(statusCounts.items()))}")
    print()
    print(f"  {'ID':<8} {'Size':<4} {'Pri':<6} {'Status':<12} {'Deps':<20} Title")
    print(f"  {'-' * 8} {'-' * 4} {'-' * 6} {'-' * 12} {'-' * 20} {'-' * 60}")
    for s in stories:
        deps = ",".join(s.get("dependencies") or []) or "-"
        title = s.get("title", "")
        if len(title) > 60:
            title = title[:57] + "..."
        print(
            f"  {s.get('id', '?'):<8} {s.get('size', '?'):<4} "
            f"{s.get('priority', '?'):<6} {s.get('status', '?'):<12} "
            f"{deps:<20} {title}"
        )


def _renderPrdsAndSprint() -> None:
    """Render active PRDs + current sprint.json (v2 view). Minimal MVP."""
    prdsDir = REPO_ROOT / "offices" / "pm" / "prds"
    activePrds = [p for p in prdsDir.glob("prd-V*.md")] if prdsDir.exists() else []
    if activePrds:
        print("=== ACTIVE PRDs ===")
        for p in sorted(activePrds):
            print(f"  {p.name}")
    else:
        print("=== No active PRDs ===")
    print()
    if SPRINT_PATH.exists():
        _renderSprintFromJson(SPRINT_PATH)


def _renderV1Legacy(data: dict) -> None:
    """Print legacy v1 backlog summary (schemaVersion != 2.0.0).

    Args:
        data: Parsed backlog.json dict (v1 shape).
    """
    print("=== BACKLOG ===")
    print(f"  lastUpdated: {data.get('lastUpdated', '?')}  updatedBy: {data.get('updatedBy', '?')}")
    buckets: dict[str, list[tuple[str, str]]] = {}
    for epic in data.get("epics", []):
        for feature in epic.get("features", []):
            fid = feature.get("id", "")
            if not fid.startswith("B-"):
                continue
            status = feature.get("status", "?")
            buckets.setdefault(status, []).append((fid, feature.get("title", "")[:70]))
    statusOrder = ["in_progress", "in_sprint", "blocked", "groomed", "pending", "complete", "declined"]
    seen: set[str] = set()
    for status in statusOrder:
        if status not in buckets:
            continue
        items = buckets[status]
        print(f"\n  -- {status} ({len(items)}) --")
        for fid, title in sorted(items):
            print(f"    {fid:<6}  {title}")
        seen.add(status)
    for status, items in buckets.items():
        if status in seen:
            continue
        print(f"\n  -- {status} ({len(items)}) --")
        for fid, title in sorted(items):
            print(f"    {fid:<6}  {title}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sprint", action="store_true", help="Show sprint only")
    parser.add_argument("--backlog", action="store_true", help="Show backlog only")
    parser.add_argument("--counter", action="store_true", help="Show counter only")
    args = parser.parse_args(argv)

    anyFlag = args.sprint or args.backlog or args.counter

    # Determine whether backlog is needed for this invocation.
    # v2 path always requires backlog.json (rollup is its job).
    # v1 path: backlog.json is only required when --backlog is explicitly requested
    # or no flags are given (full snapshot).  --sprint-only can proceed without it.
    backlogNeeded = not anyFlag or args.backlog

    if not BACKLOG_PATH.exists():
        if backlogNeeded:
            print(f"[backlog] {BACKLOG_PATH} does not exist", file=sys.stderr)
            if args.sprint:
                # --backlog was also implied by no-flag default but --sprint was given:
                # fall through to v1 sprint-only rendering below.
                pass
            else:
                return 1
        else:
            # --sprint (or --counter) only; backlog not needed -- print warning and continue
            print(f"[backlog] {BACKLOG_PATH} does not exist -- skipping backlog section", file=sys.stderr)

        # v1 sprint/counter only (backlog missing)
        if not anyFlag or args.sprint:
            printSprintSummary()
            print()
        if not anyFlag or args.counter:
            printCounterSummary()
        return 0

    data = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))

    if data.get("schemaVersion") == "2.0.0":
        # v2 path: compute + cache rollups, then render tree
        if not anyFlag or args.backlog:
            data = computeRollups(data)
            # persist rolled-up statuses back to disk (cache writeback)
            BACKLOG_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print("=== BACKLOG v2.0.0 ===")
            print(renderTree(data))
            print()
        if not anyFlag or args.sprint:
            _renderPrdsAndSprint()
            print()
        if not anyFlag or args.counter:
            printCounterSummary()
    else:
        # v1 legacy path: unchanged behaviour
        if not anyFlag or args.sprint:
            printSprintSummary()
            print()
        if not anyFlag or args.backlog:
            _renderV1Legacy(data)
            print()
        if not anyFlag or args.counter:
            printCounterSummary()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
