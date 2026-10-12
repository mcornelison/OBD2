#!/usr/bin/env python3
"""
chain_validate_aggregate.py -- /chain-validated Phase 1+2 support.

Enumerates sprint.json files belonging to a V0.X minor-version chain
(e.g. V0.27 = V0.27.2 + V0.27.3 + V0.27.4 + V0.27.5 stacked sprint
branches awaiting chain-end merge to main), aggregates each sprint's
validation block, and reports READY / INCOMPLETE. THE GATE IS THE CHAIN
TIP ALONE (:238); an earlier patch's null stamp is EXPECTED (US-618).

Per CIO 2026-05-10 chain-end-merge rule: main = "fully functional working
system"; sprint branches stay deployed-but-pre-merge until the whole
chain validates IRL.  This script powers the chain-wide pre-flight
gate the /chain-validated slash command runs before touching git history.

Usage:
  # Auto-discover: glob offices/ralph/archive/sprint.archive.*.json plus
  # the current offices/ralph/sprint.json; filter by --chain prefix.
  python -m tools.pm.chain_validate_aggregate --chain V0.27

  # Explicit paths (test harness + ad-hoc inspection):
  python -m tools.pm.chain_validate_aggregate \\
      --chain V0.27 \\
      --paths offices/ralph/archive/sprint.archive.X.json \\
              offices/ralph/sprint.json

  # Machine-readable for downstream tooling (e.g. the slash command's
  # phase 2 summary table):
  python -m tools.pm.chain_validate_aggregate --chain V0.27 --json

  # CI gate: exit 1 if chainStatus != READY.
  python -m tools.pm.chain_validate_aggregate --chain V0.27 --strict

Exit codes:
  0  chain READY OR --strict not set (report mode)
  1  --strict + chainStatus = INCOMPLETE (gate failed)
  2  file/parse error

Stdlib-only (matches tools/pm/ convention).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

# Roots come from the _paths SSOT -- depth-independent by construction.
from tools.pm._paths import SHARE_ROOT

# Aggregated bigDefinitionOfDone clauses carry Unicode (e.g. the '->' rendered
# as U+2192); the human report prints them, so harden stdout+stderr to UTF-8
# before any print (Windows cp1252 crash guard, US-466). Inlined to keep this
# script self-contained ("Stdlib-only"); canonical recipe: _encoding.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_ARCHIVE_GLOB = SHARE_ROOT / "ralph" / "archive" / "sprint.archive.*.json"
DEFAULT_CURRENT_SPRINT = SHARE_ROOT / "ralph" / "sprint.json"


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


# ------------------------------------------------------------------------------
# bigDoD clause retirement (US-619)
# ------------------------------------------------------------------------------
# A chain bigDefinitionOfDone clause can be invalidated by a finding that lands
# AFTER the sprint that wrote it -- the V0.29.29/US-552 "output is the panel-
# native 480x320" clause is the founding case: BL-034 measured the panel's EDID
# and it advertises no such mode, so the clause cannot be discharged truthfully,
# ever.  Any sweep reaching it has exactly two outs -- fail the chain, or write
# evidence for something that did not happen.  That is the fabricated-fixture
# defect at chain scale, so the retire route has to be a MECHANISM.
#
# The route is ADDITIVE.  Archive snapshots are testimony and are never edited:
# a clause is retired by adding a record to tools/pm/bigdod_retirements.json,
# which this module reads and overlays.  Nothing rewrites the sprint that made
# the claim, so the original record survives alongside the retirement.
#
# NOTE ON PLACEMENT: this layer deliberately sits OUTSIDE aggregateChain rather
# than inside it.  The docs (and this sprint's own bigDoD) cite the chain-tip
# gate at chain_validate_aggregate.py:238 BY LINE NUMBER, and US-618's lint pins
# it (_CITED_GATE_LINE).  Inserting anything above that line silently rots every
# one of those citations -- including two .claude/commands/ docs that are still
# write-blocked pending us618_apply_command_doc_fix.py.  Retirement is also a
# strictly separate concern from the gate: it annotates the clause LIST and does
# not touch chainStatus, which remains chain-tip-only (CIO 2026-05-23).
DEFAULT_RETIREMENTS_PATH = Path(__file__).resolve().parent / "bigdod_retirements.json"

# Fields a retirement record carries onto the clause it retires.
_RETIREMENT_FIELDS = ("retiredAt", "retiredBy", "authority", "reason", "supersededStory")


def loadRetirements(path: Path | None = None) -> list[dict]:
    """Load the bigDoD retirement ledger.

    Args:
        path: ledger to read; default = ``tools/pm/bigdod_retirements.json``.

    Returns:
        The ``retirements`` list, or ``[]`` when the DEFAULT ledger is absent
        (a repo that has retired nothing yet is a valid state).

    Raises:
        FileNotFoundError: an EXPLICITLY supplied path does not exist.  A typo'd
            ``--retirements`` must not degrade into "no retirements", which
            would silently un-retire every clause in the ledger.
        ValueError: the ledger exists but is malformed.
    """
    explicit = path is not None
    ledgerPath = Path(path) if explicit else DEFAULT_RETIREMENTS_PATH

    if not ledgerPath.exists():
        if explicit:
            raise FileNotFoundError(f"retirement ledger not found: {ledgerPath}")
        return []

    try:
        data = json.loads(ledgerPath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"retirement ledger is not valid JSON: {ledgerPath}: {exc}") from exc

    retirements = data.get("retirements")
    if not isinstance(retirements, list):
        raise ValueError(f"retirement ledger has no 'retirements' list: {ledgerPath}")

    for i, record in enumerate(retirements):
        missing = [k for k in ("currentVersion", "clause", "retiredBy", "authority")
                   if not (isinstance(record, dict) and record.get(k))]
        if missing:
            raise ValueError(
                f"{ledgerPath}: retirements[{i}] is missing required field(s): "
                f"{', '.join(missing)}. A retirement with no cited authority is "
                "exactly the unsourced claim this mechanism exists to prevent."
            )

    return retirements


def annotateRetirements(result: dict, retirements: list[dict] | None = None) -> dict:
    """Overlay the retirement ledger onto an :func:`aggregateChain` result.

    Marks each retired clause in ``aggregateBigDoD`` in place -- the clause is
    never dropped.  Removing it would delete the record of a claim the project
    once made; the point is that a reader sees the clause AND sees that it was
    retired and by whose authority.

    MATCHING IS EXACT on the ``(currentVersion, clause)`` pair, never substring.
    That is load-bearing rather than fastidious: the V0.29.29/US-552 clause being
    retired and the V0.29.15/US-482 clause that must NOT be retired both contain
    the string "480x320", and the US-482 one describes the shipping arrangement
    exactly.  A substring rule would retire a correct clause by association.

    A record whose ``currentVersion`` is not in the aggregated chain is simply
    not applicable (wrong chain, or filtered out) and is silent.  A record whose
    version IS in the chain but matches no clause is STALE -- an inert
    retirement, reported via ``staleRetirements`` so it cannot rot unnoticed.

    Args:
        result: an :func:`aggregateChain` return value (mutated and returned).
        retirements: ledger records; default = load the shipped ledger.

    Returns:
        ``result``, with these keys added:
            retiredBigDoD: list of the retired ``aggregateBigDoD`` entries
            staleRetirements: list of records that matched nothing in-chain
    """
    if retirements is None:
        retirements = loadRetirements()

    index = {(r["currentVersion"], r["clause"]): r for r in retirements}
    chainVersions = {s["currentVersion"] for s in result["sprintsInChain"]}
    matched: set[tuple] = set()
    retiredEntries: list[dict] = []

    for entry in result["aggregateBigDoD"]:
        key = (entry["currentVersion"], entry["clause"])
        record = index.get(key)
        if record is None:
            entry["retired"] = False
            continue
        entry["retired"] = True
        for field in _RETIREMENT_FIELDS:
            if record.get(field):
                entry[field] = record[field]
        matched.add(key)
        retiredEntries.append(entry)

    stale = [
        {
            "currentVersion": r["currentVersion"],
            "clause": r["clause"],
            "why": (
                f"{r['currentVersion']} IS in this chain but carries no clause with "
                "this exact text -- the ledger entry matches nothing and retires "
                "nothing. Re-copy the clause verbatim from the aggregate, or drop "
                "the record."
            ),
        }
        for r in retirements
        if r["currentVersion"] in chainVersions
        and (r["currentVersion"], r["clause"]) not in matched
    ]

    result["retiredBigDoD"] = retiredEntries
    result["staleRetirements"] = stale
    return result


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
    retired = result.get("retiredBigDoD") or []
    live = len(result["aggregateBigDoD"]) - len(retired)
    header = f"Aggregate bigDefinitionOfDone clauses ({len(result['aggregateBigDoD'])}"
    if retired:
        header += f"; {live} live, {len(retired)} RETIRED"
    lines.append(header + "):")
    for entry in result["aggregateBigDoD"]:
        if not entry.get("retired"):
            lines.append(f"  [{entry['currentVersion']}] {entry['clause']}")
            continue
        # A retired clause is shown, not hidden -- the reader needs to see both
        # the claim and the authority that withdrew it. The marker leads so the
        # line cannot be skim-read as still-owed work.
        lines.append(f"  [{entry['currentVersion']}] [RETIRED] {entry['clause']}")
        lines.append(f"      retired {entry.get('retiredAt', '(no date)')} "
                     f"by {entry.get('retiredBy', '(no authority)')}")
        lines.append(f"      authority: {entry.get('authority', '(none cited)')}")
        if entry.get("reason"):
            lines.append(f"      reason: {entry['reason']}")
        lines.append("      -> do NOT attempt to discharge this clause; do NOT write "
                     "evidence for it.")
    lines.append("")

    stale = result.get("staleRetirements") or []
    if stale:
        lines.append(f"STALE RETIREMENTS ({len(stale)}) -- ledger entries that retire nothing:")
        for s in stale:
            lines.append(f"  [{s['currentVersion']}] {s['clause']}")
            lines.append(f"      {s['why']}")
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
    parser.add_argument(
        "--retirements",
        default=None,
        help="bigDoD retirement ledger (US-619); default = tools/pm/bigdod_retirements.json",
    )
    args = parser.parse_args(argv)

    if args.paths is not None:
        candidatePaths = [Path(p) for p in args.paths]
    else:
        candidatePaths = discoverChainPaths(args.chain)

    result = aggregateChain(candidatePaths, args.chain)

    try:
        retirements = loadRetirements(Path(args.retirements) if args.retirements else None)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    result = annotateRetirements(result, retirements)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(renderHumanReport(result))

    if args.strict and result["chainStatus"] != "READY":
        return 1
    # A stale ledger entry retires nothing while reporting that it does, so the
    # sweep it was written to protect walks straight back into the clause. Under
    # --strict -- the pre-flight for an operation that rewrites git history --
    # that is a stop. chainStatus is NOT touched: it stays chain-tip-only, and
    # the message says which of the two failures this is.
    if args.strict and result["staleRetirements"]:
        print(
            f"ERROR: {len(result['staleRetirements'])} stale retirement(s) -- chainStatus "
            f"is {result['chainStatus']}, but the retirement ledger no longer matches the "
            "chain. See STALE RETIREMENTS above.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
