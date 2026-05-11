#!/usr/bin/env python3
"""
chain_validate_aggregate.py -- /chain-validated Phase 1+2 support.

Enumerates sprint.json files belonging to a V0.X minor-version chain
(e.g. V0.27 = V0.27.2 + V0.27.3 + V0.27.4 + V0.27.5 stacked sprint
branches awaiting chain-end merge to main), aggregates each sprint's
validation block, and reports whether the chain is READY (all sprints
validated) or INCOMPLETE (one+ sprint's validatedAt still null).

Per CIO 2026-05-10 chain-end-merge rule: main = "fully functional working
system"; sprint branches stay deployed-but-pre-merge until the whole
chain validates IRL.  This script powers the chain-wide pre-flight
gate the /chain-validated slash command runs before touching git history.

Usage:
  # Auto-discover: glob offices/ralph/archive/sprint.archive.*.json plus
  # the current offices/ralph/sprint.json; filter by --chain prefix.
  python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27

  # Explicit paths (test harness + ad-hoc inspection):
  python offices/pm/scripts/chain_validate_aggregate.py \\
      --chain V0.27 \\
      --paths offices/ralph/archive/sprint.archive.X.json \\
              offices/ralph/sprint.json

  # Machine-readable for downstream tooling (e.g. the slash command's
  # phase 2 summary table):
  python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --json

  # CI gate: exit 1 if chainStatus != READY.
  python offices/pm/scripts/chain_validate_aggregate.py --chain V0.27 --strict

Exit codes:
  0  chain READY OR --strict not set (report mode)
  1  --strict + chainStatus = INCOMPLETE (gate failed)
  2  file/parse error

Stdlib-only (matches offices/pm/scripts/ convention).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARCHIVE_GLOB = REPO_ROOT / "offices" / "ralph" / "archive" / "sprint.archive.*.json"
DEFAULT_CURRENT_SPRINT = REPO_ROOT / "offices" / "ralph" / "sprint.json"


def discoverChainPaths(chainPrefix: str) -> list[Path]:
    """Glob the archive dir + include the current sprint.json.

    Filters happen inside aggregateChain (by reading each file's
    validation.currentVersion).  This function just enumerates candidates.
    """
    archives = [Path(p) for p in glob.glob(str(DEFAULT_ARCHIVE_GLOB))]
    if DEFAULT_CURRENT_SPRINT.exists():
        archives.append(DEFAULT_CURRENT_SPRINT)
    return archives


def _loadSprintValidation(path: Path) -> dict | None:
    """Return the validation block from a sprint.json file, or None on parse error.

    A missing validation block returns None too -- the file is skipped (pre-Sprint-28
    archives have no validation block, which is by design).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: skipping {path}: {exc}", file=sys.stderr)
        return None

    validation = data.get("validation")
    if not isinstance(validation, dict):
        return None
    if not validation.get("currentVersion"):
        return None

    return {
        "path": str(path),
        "sprintTitle": data.get("sprint", ""),
        "currentVersion": validation.get("currentVersion"),
        "validatedAt": validation.get("validatedAt"),
        "validatedBy": validation.get("validatedBy"),
        "validatesFeatures": list(validation.get("validatesFeatures") or []),
        "bigDefinitionOfDone": list(validation.get("bigDefinitionOfDone") or []),
    }


def aggregateChain(paths: list[Path], chainPrefix: str) -> dict:
    """Aggregate validation blocks across all sprints whose currentVersion starts
    with chainPrefix.

    Args:
        paths: sprint.json paths to consider (current + archives).
        chainPrefix: e.g. ``V0.27`` -- matches V0.27.2, V0.27.3, V0.27.4 etc.

    Returns dict with keys:
        chainPrefix: str (echoed input)
        sprintsInChain: list of per-sprint dicts (ordered by currentVersion)
        aggregateValidatesFeatures: sorted unique union of validatesFeatures
        aggregateBigDoD: list of {currentVersion, clause} dicts (order preserved
            within each sprint; sprints ordered by currentVersion)
        unvalidatedSprints: list of currentVersion strings whose validatedAt is None
        chainStatus: 'READY' (>=1 sprint + all validated) or 'INCOMPLETE'
    """
    inChain: list[dict] = []
    for p in paths:
        record = _loadSprintValidation(Path(p))
        if record is None:
            continue
        if not record["currentVersion"].startswith(chainPrefix):
            continue
        inChain.append(record)

    # Stable ordering: by currentVersion (lexicographic works because chain
    # versions are zero-padded-equivalent within a single minor epoch:
    # V0.27.2 < V0.27.3 < V0.27.4 etc.).
    inChain.sort(key=lambda r: r["currentVersion"])

    aggregateFeatures: set[str] = set()
    aggregateBigDoD: list[dict] = []
    unvalidated: list[str] = []
    for record in inChain:
        for feat in record["validatesFeatures"]:
            aggregateFeatures.add(feat)
        for clause in record["bigDefinitionOfDone"]:
            aggregateBigDoD.append({
                "currentVersion": record["currentVersion"],
                "clause": clause,
            })
        if not record["validatedAt"]:
            unvalidated.append(record["currentVersion"])

    chainStatus = "READY" if inChain and not unvalidated else "INCOMPLETE"

    return {
        "chainPrefix": chainPrefix,
        "sprintsInChain": inChain,
        "aggregateValidatesFeatures": sorted(aggregateFeatures),
        "aggregateBigDoD": aggregateBigDoD,
        "unvalidatedSprints": unvalidated,
        "chainStatus": chainStatus,
    }


def renderHumanReport(result: dict) -> str:
    """Build a human-readable summary of the aggregate result."""
    lines: list[str] = []
    lines.append(f"Chain {result['chainPrefix']} aggregate")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Sprints in chain: {len(result['sprintsInChain'])}")
    for s in result["sprintsInChain"]:
        marker = "OK" if s["validatedAt"] else "PENDING"
        vAt = s["validatedAt"] or "(not yet validated)"
        lines.append(f"  [{marker:<7}] {s['currentVersion']:<10} {vAt:<22} {s['sprintTitle']}")
    lines.append("")
    lines.append(f"Aggregate validatesFeatures ({len(result['aggregateValidatesFeatures'])}):")
    for f in result["aggregateValidatesFeatures"]:
        lines.append(f"  {f}")
    lines.append("")
    lines.append(f"Aggregate bigDefinitionOfDone clauses ({len(result['aggregateBigDoD'])}):")
    for entry in result["aggregateBigDoD"]:
        lines.append(f"  [{entry['currentVersion']}] {entry['clause']}")
    lines.append("")
    lines.append(f"chainStatus: {result['chainStatus']}")
    if result["unvalidatedSprints"]:
        lines.append(f"unvalidatedSprints: {', '.join(result['unvalidatedSprints'])}")
        lines.append("    (each sprint needs its own /sprint-validated before chain merge)")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--chain",
        required=True,
        help="Chain version prefix to filter on, e.g. 'V0.27' matches V0.27.2/.3/.4/...",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=None,
        help="Explicit sprint.json paths to consider; default = auto-discover (archive + current)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default = human report)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if chainStatus != READY (CI gate for slash command pre-flight)",
    )
    args = parser.parse_args(argv)

    if args.paths is not None:
        candidatePaths = [Path(p) for p in args.paths]
    else:
        candidatePaths = discoverChainPaths(args.chain)

    result = aggregateChain(candidatePaths, args.chain)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(renderHumanReport(result))

    if args.strict and result["chainStatus"] != "READY":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
