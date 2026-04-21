#!/usr/bin/env python3
"""
pm_status.py -- PM session-start snapshot.

Prints a compact one-screen status summary:
  - current sprint: name, story count, per-story (id/size/priority/status/deps)
  - backlog: B- features grouped by status
  - story counter: nextId + last reservation note

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

REPO_ROOT = Path(__file__).resolve().parents[3]
SPRINT_PATH = REPO_ROOT / "offices" / "ralph" / "sprint.json"
BACKLOG_PATH = REPO_ROOT / "offices" / "pm" / "backlog.json"
COUNTER_PATH = REPO_ROOT / "offices" / "pm" / "story_counter.json"


def printSprintSummary() -> None:
    if not SPRINT_PATH.exists():
        print(f"[sprint] {SPRINT_PATH} does not exist")
        return
    d = json.loads(SPRINT_PATH.read_text(encoding="utf-8"))
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


def printBacklogSummary() -> None:
    if not BACKLOG_PATH.exists():
        print(f"[backlog] {BACKLOG_PATH} does not exist")
        return
    d = json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))
    print("=== BACKLOG ===")
    print(f"  lastUpdated: {d.get('lastUpdated', '?')}  updatedBy: {d.get('updatedBy', '?')}")
    buckets: dict[str, list[tuple[str, str]]] = {}
    for epic in d.get("epics", []):
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sprint", action="store_true", help="Show sprint only")
    parser.add_argument("--backlog", action="store_true", help="Show backlog only")
    parser.add_argument("--counter", action="store_true", help="Show counter only")
    args = parser.parse_args(argv)

    anyFlag = args.sprint or args.backlog or args.counter
    if not anyFlag or args.sprint:
        printSprintSummary()
        print()
    if not anyFlag or args.backlog:
        printBacklogSummary()
        print()
    if not anyFlag or args.counter:
        printCounterSummary()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
