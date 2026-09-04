#!/usr/bin/env python3
"""
repair_ralph_agents.py -- Repair offices/ralph/ralph_agents.json corruption.

Recurring bug: Rex (Ralph agent 1) writes long multi-session notes via
the Edit tool, which doesn't auto-escape quotes. An unescaped `"` inside
the `note` string breaks the JSON parser and agent.py loadAgents()
crashes with "Expecting value: line N column M". Symptom: ralph.sh fails
on getNext invocation.

Observed Sprint 21 close, Sprint 24 close, and 2026-08-31 -- three
occurrences to date.

Repair strategy:
  Truncate Rex's bloated note to a short pointer ("see progress.txt for
  detail"). Detail log lives in progress.txt anyway -- the JSON-state
  file should stay minimal. Every other agent is preserved verbatim.

THE ROSTER SIZE IS READ, NEVER ASSUMED (US-664)
-----------------------------------------------
This tool used to assert ``len(agents) != 4`` after rebuilding, and hardcode
``"max_agent": 4`` into what it wrote. The fleet now runs two agents, so on
2026-08-31 -- the third occurrence of the corruption it exists to repair, and
the first anyone had actually reached for it -- it refused a correct file with
"expected 4 agents post-repair, got 2", and the PM repaired the file by hand.

Both halves of that are fixed here, and the second one matters more than the
one that was reported:

  * The post-repair count is compared against the PRE-repair count (see
    :func:`countAgentBlocks` and :func:`rosterSizeRefusal`). The safety check
    is worth keeping -- losing an agent must still refuse -- it was the
    CONSTANT that was wrong, not the check.

  * ``max_agent`` is recovered from the file being repaired. Fixing only the
    count check would have turned a useless tool into a destructive one: the
    refusal was the only thing stopping a 2-agent roster from being rewritten
    to claim 4.

Usage:
  python -m tools.pm.repair_ralph_agents             # repair if corrupt; no-op if clean
  python -m tools.pm.repair_ralph_agents --dry-run   # detect + describe; don't write
  python -m tools.pm.repair_ralph_agents --check     # just exit 0/1 based on JSON validity

Exit code: 0 on clean OR successful repair; 1 on irreparable corruption
(the surviving roster is not parseable, or the rebuild would change the roster
size); 2 on missing file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Roots come from the _paths SSOT -- depth-independent by construction.
#
# Imported as a MODULE and resolved at CALL time (see resolveAgentsPath).
# `from tools.pm._paths import SHARE_ROOT` resolved eagerly at import, so merely
# importing this file was a configuration error when $FLEET_SHARE was unset --
# even for `--check --path <explicit>`, which needs no share at all. That is
# this story's own defect class in the import statement: a recovery tool that
# declines for a reason unrelated to the job, at exactly the moment something
# is already broken. graduate_story.py and backlog_set.py resolve at call time;
# this now matches them.
from tools.pm import _paths

DEFAULT_REX_NOTE = (
    "Note repaired by repair_ralph_agents.py (unescaped quote in long note "
    "broke json.load + agent.py loadAgents). Detail log canonical in "
    "offices/ralph/progress.txt; sprint outcomes in offices/ralph/sprint.json."
)

# One agent object's opening, used to COUNT the roster in a file too corrupt to
# parse. The literal line break between `{` and `"id"` is load-bearing: a JSON
# string cannot contain a real newline, so this cannot match a note that quotes
# an agent object at someone (Rex's notes do exactly that). Indentation is
# deliberately NOT pinned -- a repair splices text together and whitespace
# drifts, and this corruption has recurred three times, so "previously
# repaired" is an expected input rather than an edge case.
_AGENT_BLOCK_RE = re.compile(r"\{[ \t]*\r?\n\s*\"id\"\s*:\s*\d+")

# The seam the rebuild splices at: the start of the second agent's object.
_TAIL_BOUNDARY_RE = re.compile(r"\{[ \t]*\r?\n\s*\"id\"\s*:\s*2\s*,")

_MAX_AGENT_RE = re.compile(r"\"max_agent\"\s*:\s*(\d+)")


def resolveAgentsPath(override: str | None = None) -> Path:
    """Resolve ralph_agents.json, honouring an explicit override.

    Args:
        override: Explicit path from ``--path``, or None to use the share.

    Returns:
        The path to operate on.
    """
    if override:
        return Path(override)
    return _paths.resolveShareRoot() / "ralph" / "ralph_agents.json"


def isValidJson(path: Path) -> bool:
    """Report whether a file parses as JSON."""
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except json.JSONDecodeError:
        return False


def countAgentBlocks(raw: str) -> int:
    """Count the agent objects in raw file text, parseable or not.

    This is the PRE-repair roster size, and it is deliberately derived from the
    raw document rather than from the tail the rebuild splices in. Deriving
    both sides of the safety check from the same text would make the comparison
    agree with itself no matter what the rebuild did.

    Over-counting is the safe direction: a document mangled badly enough to
    confuse this refuses the repair rather than writing a roster nobody
    verified.

    Args:
        raw: The file's text.

    Returns:
        Number of agent objects found.
    """
    return len(_AGENT_BLOCK_RE.findall(raw))


def recoverMaxAgent(raw: str) -> int | None:
    """Recover the declared ``max_agent`` from raw file text.

    Only the document head -- everything before the ``"agents"`` key -- is
    searched, so a note mentioning ``max_agent`` in prose cannot be mistaken
    for the declaration.

    Args:
        raw: The file's text.

    Returns:
        The declared value, or None if the key is absent.
    """
    head = raw.split('"agents"', 1)[0]
    match = _MAX_AGENT_RE.search(head)
    return int(match.group(1)) if match else None


def rosterSizeRefusal(preCount: int, postCount: int) -> str | None:
    """Report why a rebuilt roster must be refused, or None if it is sound.

    The invariant that actually matters is that the repair changed nothing
    about WHO is on the roster -- in either direction. Losing an agent destroys
    state; gaining one fabricates it.

    Args:
        preCount: Agents present before the repair.
        postCount: Agents present in the rebuilt document.

    Returns:
        A refusal reason naming both counts, or None.
    """
    if postCount == preCount:
        return None
    verb = "dropped" if postCount < preCount else "invented"
    return (
        f"the rebuild {verb} an agent: {preCount} agent(s) before, "
        f"{postCount} after"
    )


def writeAtomically(path: Path, text: str) -> None:
    """Replace a file's contents without ever truncating the original.

    The fleet share has no git, no snapshots and no undo, and an in-place
    ``open(path, "w")`` truncates BEFORE it can fail -- which already destroyed
    a 22,588-byte file on this share on 2026-08-31. The stakes are highest
    here: the only copy of the file this tool exists to recover is the one it
    is writing over.

    Args:
        path: Destination file.
        text: Full replacement contents.

    Raises:
        OSError: If the temp write or the replace fails. The original is
            untouched in both cases.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


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
    preCount = countAgentBlocks(raw)

    # Splice at the second agent: everything from there on is well-formed under
    # this corruption pattern, because the bug lives in Rex's note.
    boundary = _TAIL_BOUNDARY_RE.search(raw)
    if not boundary:
        print(
            "ERROR: cannot locate the second agent's boundary; corruption is wider "
            "than the Rex-note pattern",
            file=sys.stderr,
        )
        print("       manual repair required", file=sys.stderr)
        return 1

    tail = raw[boundary.start():]
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
    agent1Indented = "\n".join(
        "    " + line if i > 0 else line for i, line in enumerate(agent1Str.split("\n"))
    )

    def compose(maxAgentValue: int) -> str:
        return (
            "{\n"
            f'  "max_agent": {maxAgentValue},\n'
            '  "agents": [\n    ' + agent1Indented + ",\n    " + tail
        )

    declaredMaxAgent = recoverMaxAgent(raw)

    # Compose once with a provisional value purely to learn the post-repair
    # roster size, then compose again with the value that size may imply. The
    # agent objects are spliced as TEXT either way, so nothing downstream of
    # agent 1 is reserialised.
    try:
        parsed = json.loads(compose(declaredMaxAgent if declaredMaxAgent is not None else 0))
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: repair attempt produced invalid JSON ({exc}); manual repair required",
            file=sys.stderr,
        )
        return 1

    postCount = len(parsed.get("agents", []))
    refusal = rosterSizeRefusal(preCount, postCount)
    if refusal is not None:
        print(f"ERROR: {refusal}; manual repair required", file=sys.stderr)
        return 1

    if declaredMaxAgent is None:
        # The story names two authorities for the roster: max_agent and the
        # agents[] array. With the first absent the second answers. Defaulting
        # to a literal here would be the original defect wearing a fallback's
        # clothes.
        maxAgent = postCount
        print(f"  max_agent absent; derived {maxAgent} from the surviving roster")
    else:
        maxAgent = declaredMaxAgent
        if maxAgent != postCount:
            # Preserved, not "corrected". This disagreement predates the
            # corruption and is not this tool's to resolve -- and refusing over
            # it would be US-664's own defect restored, declining a file for a
            # condition unrelated to the repair.
            print(
                f"  WARNING: max_agent says {maxAgent} but {postCount} agent(s) are "
                f"present; preserving the declared value -- resolve by hand if wrong"
            )

    repaired = compose(maxAgent)

    if dryRun:
        print(f"DRY-RUN: would repair {path}")
        print(f"  Rex note shortened to: {DEFAULT_REX_NOTE[:80]}...")
        print(f"  Roster preserved: {postCount} agent(s), max_agent {maxAgent}")
        print(f"  Repaired size: {len(repaired)} bytes (was {len(raw)})")
        return 0

    try:
        writeAtomically(path, repaired)
    except OSError as exc:
        print(
            f"ERROR: could not write {path} ({exc}); the original is unchanged",
            file=sys.stderr,
        )
        return 1

    print(f"Repaired {path}")
    print("  Rex note shortened (Detail in progress.txt)")
    print(f"  Roster preserved: {postCount} agent(s), max_agent {maxAgent}")
    print(f"  Size: {len(raw)} -> {len(repaired)} bytes")
    return 0


def main(argv: list[str]) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--path", default=None, help="ralph_agents.json path override")
    parser.add_argument("--dry-run", action="store_true", help="Detect + describe; don't write")
    parser.add_argument("--check", action="store_true", help="Exit 0/1 based on JSON validity (no repair)")
    args = parser.parse_args(argv)

    path = resolveAgentsPath(args.path)

    if args.check:
        if isValidJson(path):
            print("VALID")
            return 0
        print("INVALID")
        return 1

    return repairAgents(path, args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
