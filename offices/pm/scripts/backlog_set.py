#!/usr/bin/env python3
"""
backlog_set.py -- CLI for common backlog.json mutations.

Encapsulates the mutation patterns Marcus (PM) uses at sprint boundaries:
  - flip feature status (pending | groomed | in_sprint | in_progress | blocked | complete | declined)
  - add a phase record under a feature (used for B-037 crawl/walk/run/sprint/harden)
  - record completion metadata on a feature
  - bump lastUpdated + updatedBy

Never touches sprint.json or story_counter.json -- those have their own tools.
Stdlib-only. Idempotent: re-running with the same args is safe.

Usage examples:
  # At session start, bump the lastUpdated field:
  python offices/pm/scripts/backlog_set.py --updated-by "Marcus (PM, Session 24)"

  # Flip a feature status:
  python offices/pm/scripts/backlog_set.py --feature B-044 --status in_sprint \
      --field inSprint="Sprint 14 (US-201)"

  # Record completion:
  python offices/pm/scripts/backlog_set.py --feature B-042 --status complete \
      --completed-date 2026-04-18 \
      --completed-by "Ralph (US-187, Sprint 12)"

  # Add a phase record to B-037 (or any feature with phases[]):
  python offices/pm/scripts/backlog_set.py --feature B-037 --add-phase harden \
      --phase-status in_progress \
      --phase-sprint "Sprint 14" \
      --phase-branch sprint/pi-harden \
      --phase-date 2026-04-19 \
      --phase-stories US-192,US-193,US-194,US-195,US-196,US-197,US-198,US-199,US-200,US-201 \
      --phase-note "Sprint 14 loaded -- TD fixes + data-collection v2 + carryforward"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKLOG_PATH = REPO_ROOT / "offices" / "pm" / "backlog.json"

VALID_STATUSES = {
    "pending", "groomed", "in_sprint", "in_progress",
    "blocked", "complete", "declined",
}


def loadBacklog() -> dict[str, Any]:
    return json.loads(BACKLOG_PATH.read_text(encoding="utf-8"))


def saveBacklog(data: dict[str, Any]) -> None:
    # Preserve trailing newline convention
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    BACKLOG_PATH.write_text(text, encoding="utf-8")


def findFeature(data: dict[str, Any], featureId: str) -> dict[str, Any] | None:
    for epic in data.get("epics", []):
        for feature in epic.get("features", []):
            if feature.get("id") == featureId:
                return feature
    return None


def parseFieldPairs(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            raise ValueError(f"--field expects key=value form; got {raw!r}")
        k, _, v = raw.partition("=")
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage examples:\n")[1] if "Usage examples:" in __doc__ else "",
    )
    parser.add_argument("--feature", help="Feature ID (e.g. B-037)")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), help="New status")
    parser.add_argument(
        "--field", action="append", default=[],
        help="Extra field to set, key=value (can repeat; top-level feature field)",
    )
    parser.add_argument("--completed-date", help="YYYY-MM-DD")
    parser.add_argument("--completed-by", help="Credit line")
    parser.add_argument("--progress-note", help="Set a progressNote string")

    # Phase sub-commands (all optional; presence of --add-phase triggers)
    parser.add_argument("--add-phase", help="Phase name to add (e.g. harden)")
    parser.add_argument(
        "--phase-status",
        choices=sorted({"in_progress", "complete", "blocked", "milestone-closed", "pending"}),
        help="Status for the new phase record",
    )
    parser.add_argument("--phase-sprint", help="Sprint label (e.g. 'Sprint 14')")
    parser.add_argument("--phase-branch", help="Sprint branch name")
    parser.add_argument("--phase-date", help="Phase createdDate or completedDate")
    parser.add_argument("--phase-stories", help="Comma-separated story IDs")
    parser.add_argument("--phase-note", help="Free-text note for the phase record")

    # Top-level metadata
    parser.add_argument("--updated-by", help="Bumps lastUpdated to today and sets updatedBy")
    parser.add_argument("--last-updated", help="Override date (default: today in backlog's style)")

    parser.add_argument("--dry-run", action="store_true", help="Print the proposed JSON without writing")

    args = parser.parse_args(argv)

    data = loadBacklog()
    changes: list[str] = []

    # Top-level metadata updates
    if args.updated_by:
        from datetime import date
        today = args.last_updated or date.today().isoformat()
        data["lastUpdated"] = today
        data["updatedBy"] = args.updated_by
        changes.append(f"lastUpdated -> {today}, updatedBy -> {args.updated_by}")

    # Feature-level updates
    if args.feature:
        feature = findFeature(data, args.feature)
        if feature is None:
            print(f"ERROR: feature {args.feature} not found in backlog.json", file=sys.stderr)
            return 2

        if args.status:
            before = feature.get("status")
            feature["status"] = args.status
            changes.append(f"{args.feature}.status: {before} -> {args.status}")

        for k, v in parseFieldPairs(args.field).items():
            feature[k] = v
            changes.append(f"{args.feature}.{k} -> {v!r}")

        if args.completed_date:
            feature["completedDate"] = args.completed_date
            changes.append(f"{args.feature}.completedDate -> {args.completed_date}")
        if args.completed_by:
            feature["completedBy"] = args.completed_by
            changes.append(f"{args.feature}.completedBy -> {args.completed_by}")
        if args.progress_note:
            feature["progressNote"] = args.progress_note
            changes.append(f"{args.feature}.progressNote -> {args.progress_note[:60]}...")

        if args.add_phase:
            feature.setdefault("phases", {})
            phaseRecord: dict[str, Any] = {}
            if args.phase_status:
                phaseRecord["status"] = args.phase_status
            if args.phase_sprint:
                phaseRecord["sprint"] = args.phase_sprint
            if args.phase_branch:
                phaseRecord["branch"] = args.phase_branch
            if args.phase_date:
                phaseRecord["createdDate" if args.phase_status == "in_progress" else "completedDate"] = args.phase_date
            if args.phase_stories:
                phaseRecord["stories"] = [s.strip() for s in args.phase_stories.split(",") if s.strip()]
            if args.phase_note:
                phaseRecord["note"] = args.phase_note
            feature["phases"][args.add_phase] = phaseRecord
            changes.append(f"{args.feature}.phases.{args.add_phase} = {json.dumps(phaseRecord)}")
    elif any([args.status, args.completed_date, args.completed_by, args.progress_note, args.add_phase]):
        print("ERROR: --feature required when using feature-level flags", file=sys.stderr)
        return 2

    if not changes:
        print("No changes requested. Use --help for usage.")
        return 0

    print("Proposed changes:")
    for c in changes:
        print(f"  - {c}")

    if args.dry_run:
        print("\n[DRY RUN -- no write performed]")
        return 0

    saveBacklog(data)
    print(f"\nWrote {BACKLOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
