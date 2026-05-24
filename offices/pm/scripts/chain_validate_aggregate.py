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


def _versionSortKey(currentVersion: str) -> tuple:
    """Parse a sprint ``currentVersion`` into a tuple suitable for ordering.

    ``'V0.27.18'`` -> ``(0, 27, 18)`` so that ``V0.27.18 > V0.27.9`` as expected.
    Lexicographic sort on the raw string puts ``V0.27.18`` BEFORE ``V0.27.2``
    (the seventh char is ``'1'`` vs ``'2'``), which silently misidentifies the
    chain tip once a chain grows past 9 patches.  The V0.27 chain hit that
    threshold at V0.27.10; this helper is what makes the chain-tip-validation-
    authoritative rule (CIO 2026-05-23) actually pick the right tip.

    Non-numeric components fall back to ``(0, str)`` ordering so future tags
    like ``V0.27.18-rc1`` still sort sensibly without raising.
    """
    cleaned = currentVersion.lstrip("Vv")
    parts: list[tuple] = []
    for part in cleaned.split("."):
        try:
            parts.append((0, int(part), ""))
        except ValueError:
            parts.append((1, 0, part))
    return tuple(parts)


def _snapshotAuthorityKey(record: dict) -> tuple:
    """Return a sort key ranking how authoritative a sprint.json snapshot is.

    Used as the tie-breaker when multiple snapshots share a ``currentVersion``
    (e.g. ``sprint.archive.2026-05-22_015122Z.json`` + a re-archived snapshot
    from a patch deploy + the live ``offices/ralph/sprint.json``).  Tuple
    components, in priority order, all sorted ascending so ``max(key=)`` picks
    the winner:

    1. ``validatedAt is not None`` -- a snapshot with a populated
       ``validatedAt`` always beats one whose validation block has not yet
       been stamped, regardless of file ordering.  This is the load-bearing
       case: ``/sprint-deploy-pm`` archives BEFORE ``/sprint-validated`` runs,
       so the archive's ``validatedAt`` is ``null`` and the live snapshot
       (or a later re-archive) carries the truth.
    2. ``validatedAt`` value -- among snapshots that all have a non-null
       ``validatedAt``, prefer the lexicographically-latest one (ISO-8601
       strings compare correctly, so this is "most recent validation stamp").
    3. ``path.name`` lexicographic -- fallback when neither has a stamp.
       For the default discovery glob, ``sprint.json`` sorts after
       ``sprint.archive.*.json`` (``.j`` > ``.a``), so the live file wins
       over an old archive when neither has been validated yet.
    """
    return (
        record["validatedAt"] is not None,
        record["validatedAt"] or "",
        Path(record["path"]).name,
    )


def aggregateChain(paths: list[Path], chainPrefix: str) -> dict:
    """Aggregate validation blocks across all sprints whose currentVersion starts
    with chainPrefix.

    Each distinct ``currentVersion`` appears in the output at most once;
    duplicate snapshots (e.g. the live ``sprint.json`` plus one or more
    ``sprint.archive.*.json`` files from successive patch deploys -- see
    Argus's 2026-05-11 TI-002 gap) are collapsed via
    :func:`_snapshotAuthorityKey` (validated stamp wins; latest stamp wins;
    then path-name ordering).

    ``chainStatus`` follows the CIO chain-end-merge rule (2026-05-23): only
    the **chain-tip** sprint's ``validatedAt`` gates ``READY``.  Earlier
    patches in the chain (V0.27.2..V0.27.17 in the V0.27 example) are each
    superseded by the next patch and never independently re-validated -- their
    ``validatedAt = null`` is expected under chain-end-merge workflow and
    must not block ``--strict``.  ``unvalidatedSprints`` still lists every
    null entry as informational context for the human report.

    Args:
        paths: sprint.json paths to consider (current + archives).
        chainPrefix: e.g. ``V0.27`` -- matches V0.27.2, V0.27.3, V0.27.4 etc.

    Returns dict with keys:
        chainPrefix: str (echoed input)
        sprintsInChain: list of per-sprint dicts (ordered by currentVersion, deduplicated)
        aggregateValidatesFeatures: sorted unique union of validatesFeatures
        aggregateBigDoD: list of {currentVersion, clause} dicts (order preserved
            within each sprint; sprints ordered by currentVersion)
        unvalidatedSprints: list of currentVersion strings whose validatedAt is None
            (informational; does NOT gate chainStatus under chain-end-merge rule)
        chainTipVersion: str | None -- the currentVersion of the chain-tip sprint
            (highest-versioned in chain); None if chain is empty
        chainStatus: 'READY' (chain-tip validated) or 'INCOMPLETE' (chain-tip
            unvalidated OR chain empty)
    """
    # Step 1: load + filter (existing behavior).
    candidates: list[dict] = []
    for p in paths:
        record = _loadSprintValidation(Path(p))
        if record is None:
            continue
        if not record["currentVersion"].startswith(chainPrefix):
            continue
        candidates.append(record)

    # Step 2: dedupe by currentVersion (TI-002 fix -- Argus 2026-05-11 gap).
    # Multiple snapshots of the same sprint (live sprint.json + archive snapshots
    # from successive patch deploys) all share currentVersion; collapse to the
    # most-authoritative one via _snapshotAuthorityKey.
    byVersion: dict[str, dict] = {}
    for record in candidates:
        version = record["currentVersion"]
        if version not in byVersion or (
            _snapshotAuthorityKey(record) > _snapshotAuthorityKey(byVersion[version])
        ):
            byVersion[version] = record

    inChain = sorted(byVersion.values(), key=lambda r: _versionSortKey(r["currentVersion"]))

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

    # Step 3: chain-tip-validation-authoritative (CIO chain-end-merge rule 2026-05-23).
    # The chain validates as a whole at the tip; earlier patches are superseded
    # by successive ones and not re-validated individually.
    chainTip = inChain[-1] if inChain else None
    chainTipVersion = chainTip["currentVersion"] if chainTip else None
    chainStatus = "READY" if chainTip and chainTip["validatedAt"] else "INCOMPLETE"

    return {
        "chainPrefix": chainPrefix,
        "sprintsInChain": inChain,
        "aggregateValidatesFeatures": sorted(aggregateFeatures),
        "aggregateBigDoD": aggregateBigDoD,
        "unvalidatedSprints": unvalidated,
        "chainTipVersion": chainTipVersion,
        "chainStatus": chainStatus,
    }


def renderHumanReport(result: dict) -> str:
    """Build a human-readable summary of the aggregate result."""
    lines: list[str] = []
    lines.append(f"Chain {result['chainPrefix']} aggregate")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Sprints in chain: {len(result['sprintsInChain'])}")
    chainTipVersion = result.get("chainTipVersion")
    for s in result["sprintsInChain"]:
        marker = "OK" if s["validatedAt"] else "PENDING"
        vAt = s["validatedAt"] or "(not yet validated)"
        tipTag = " <-- chain tip" if s["currentVersion"] == chainTipVersion else ""
        lines.append(
            f"  [{marker:<7}] {s['currentVersion']:<10} {vAt:<22} {s['sprintTitle']}{tipTag}"
        )
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
    if chainTipVersion:
        lines.append(f"chainTipVersion: {chainTipVersion} (gate -- chain-end-merge rule)")
    if result["unvalidatedSprints"]:
        lines.append(f"unvalidatedSprints: {', '.join(result['unvalidatedSprints'])}")
        if result["chainStatus"] == "READY":
            lines.append(
                "    (informational only -- earlier patches superseded by chain-tip; "
                "earlier-NULL is expected under chain-end-merge rule)"
            )
        else:
            lines.append(
                "    (chain-tip validation pending -- chain not yet ready for merge)"
            )
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
