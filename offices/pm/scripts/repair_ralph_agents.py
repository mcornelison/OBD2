#!/usr/bin/env python3
"""
repair_ralph_agents.py -- Repair offices/ralph/ralph_agents.json corruption.

Recurring bug: Rex (Ralph agent 1) writes long multi-session notes via
the Edit tool, which doesn't auto-escape quotes. An unescaped `"` inside
the `note` string breaks the JSON parser and agent.py loadAgents()
crashes with "Expecting value: line N column M". Symptom: ralph.sh fails
on getNext invocation.

Observed Sprint 21 close, Sprint 24 close (2 occurrences across 4 sprints).

Repair strategy:
  Truncate Rex's bloated note to a short pointer ("see progress.txt for
  detail"). Detail log lives in progress.txt anyway -- the JSON-state
  file should stay minimal. Preserves agents 2/3/4 untouched.

Usage:
  python offices/pm/scripts/repair_ralph_agents.py             # repair if corrupt; no-op if clean
  python offices/pm/scripts/repair_ralph_agents.py --dry-run   # detect + describe; don't write
  python offices/pm/scripts/repair_ralph_agents.py --check     # just exit 0/1 based on JSON validity

Exit code: 0 on clean OR successful repair; 1 on irreparable corruption
(agents 2-4 not parseable); 2 on missing file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENTS_PATH = REPO_ROOT / "offices" / "ralph" / "ralph_agents.json"

DEFAULT_REX_NOTE = (
    "Note repaired by repair_ralph_agents.py (unescaped quote in long note "
    "broke json.load + agent.py loadAgents). Detail log canonical in "
    "offices/ralph/progress.txt; sprint outcomes in offices/ralph/sprint.json."
)


def isValidJson(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except json.JSONDecodeError:
        return False


def repairAgents(path: Path, dryRun: bool) -> int:
    """Repair ralph_agents.json if corrupt. Returns 0 on success, 1 on failure."""
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 2

    if isValidJson(path):
        print("ralph_agents.json is valid JSON; no repair needed")
        return 0

    print("ralph_agents.json has invalid JSON; attempting Rex-bloated-note repair pattern")

    raw = path.read_text(encoding="utf-8")
    # Find agent 2 boundary (well-formed); agents 2/3/4 are typically untouched
    m = re.search(r'    \{\s*\n\s*"id":\s*2,', raw)
    if not m:
        print("ERROR: cannot locate agent 2 boundary; corruption is wider than Rex-note pattern", file=sys.stderr)
        print("       manual repair required", file=sys.stderr)
        return 1

    # Reconstruct: clean agent 1 + verbatim agents 2-4 (well-formed JSON tail)
    agents234 = raw[m.start():]
    cleanAgent1 = {
        "id": 1,
        "name": "Rex",
        "type": "windows-dev",
        "status": "unassigned",
        "taskid": "",
        "lastCheck": "",
        "note": DEFAULT_REX_NOTE,
    }
    agent1Str = json.dumps(cleanAgent1, indent=4)
    agent1Indented = "\n".join("    " + line if i > 0 else line for i, line in enumerate(agent1Str.split("\n")))

    repaired = '{\n  "max_agent": 4,\n  "agents": [\n    ' + agent1Indented + ",\n    " + agents234

    # Verify repaired structure parses
    try:
        parsed = json.loads(repaired)
        if len(parsed.get("agents", [])) != 4:
            raise ValueError(f"expected 4 agents post-repair, got {len(parsed.get('agents', []))}")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: repair attempt produced invalid JSON ({exc}); manual repair required", file=sys.stderr)
        return 1

    if dryRun:
        print(f"DRY-RUN: would repair {path}")
        print(f"  Rex note shortened to: {DEFAULT_REX_NOTE[:80]}...")
        print(f"  Agents 2-4 preserved verbatim")
        print(f"  Repaired size: {len(repaired)} bytes (was {len(raw)})")
        return 0

    path.write_text(repaired, encoding="utf-8", newline="\n")
    print(f"Repaired {path}")
    print(f"  Rex note shortened (Detail in progress.txt)")
    print(f"  Agents 2-4 preserved")
    print(f"  Size: {len(raw)} -> {len(repaired)} bytes")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--path", default=str(DEFAULT_AGENTS_PATH), help="ralph_agents.json path override")
    parser.add_argument("--dry-run", action="store_true", help="Detect + describe; don't write")
    parser.add_argument("--check", action="store_true", help="Exit 0/1 based on JSON validity (no repair)")
    args = parser.parse_args(argv)

    path = Path(args.path)

    if args.check:
        if isValidJson(path):
            print("VALID")
            return 0
        print("INVALID")
        return 1

    return repairAgents(path, args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
