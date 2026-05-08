#!/usr/bin/env python3
"""
archive_sprint_artifacts.py -- Sprint-close Phase 2.

Snapshots offices/ralph/sprint.json + progress.txt into
offices/ralph/archive/ with a UTC timestamp filename.

Filename convention (filesystem-safe; underscore between date + time;
trailing Z for UTC marker):
  sprint.archive.YYYY-MM-DD_HHMMSSZ.json
  progress.archive.YYYY-MM-DD_HHMMSSZ.txt

Usage:
  python offices/pm/scripts/archive_sprint_artifacts.py
  python offices/pm/scripts/archive_sprint_artifacts.py --dry-run

Exit code: 0 on success; 1 on missing source files; 2 on archive
collision (re-run within 1 sec; abort + investigate).

Saves PM ~80 tokens per sprint close (vs inline bash `cp` + `python -c`
timestamp generation).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SPRINT_PATH = REPO_ROOT / "offices" / "ralph" / "sprint.json"
PROGRESS_PATH = REPO_ROOT / "offices" / "ralph" / "progress.txt"
ARCHIVE_DIR = REPO_ROOT / "offices" / "ralph" / "archive"


def archiveArtifacts(timestamp: str | None = None, dryRun: bool = False) -> tuple[Path, Path]:
    """Archive sprint.json + progress.txt with UTC timestamp filenames.

    Args:
        timestamp: Override timestamp (for testing); default = now in UTC.
        dryRun: If True, print intended actions without copying.

    Returns:
        Tuple of (sprintArchivePath, progressArchivePath).
    """
    if not SPRINT_PATH.exists():
        print(f"ERROR: {SPRINT_PATH} not found", file=sys.stderr)
        sys.exit(1)
    if not PROGRESS_PATH.exists():
        print(f"ERROR: {PROGRESS_PATH} not found", file=sys.stderr)
        sys.exit(1)

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")

    sprintArchive = ARCHIVE_DIR / f"sprint.archive.{timestamp}.json"
    progressArchive = ARCHIVE_DIR / f"progress.archive.{timestamp}.txt"

    if sprintArchive.exists() or progressArchive.exists():
        print(f"ERROR: archive timestamp collision -- {timestamp} already exists", file=sys.stderr)
        print("       (re-run within 1 sec or genuine duplicate; investigate before retry)", file=sys.stderr)
        sys.exit(2)

    if dryRun:
        print(f"DRY-RUN: would copy {SPRINT_PATH} -> {sprintArchive}")
        print(f"DRY-RUN: would copy {PROGRESS_PATH} -> {progressArchive}")
        return sprintArchive, progressArchive

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPRINT_PATH, sprintArchive)
    shutil.copy(PROGRESS_PATH, progressArchive)

    print(f"Archived sprint.json   -> {sprintArchive.relative_to(REPO_ROOT)}")
    print(f"Archived progress.txt  -> {progressArchive.relative_to(REPO_ROOT)}")
    return sprintArchive, progressArchive


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--timestamp", help="Override UTC timestamp (YYYY-MM-DD_HHMMSSZ)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying")
    args = parser.parse_args(argv)

    archiveArtifacts(timestamp=args.timestamp, dryRun=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
