#!/usr/bin/env python3
"""
sprint_lint.py -- Audit offices/ralph/sprint.json against the Sprint Contract
v1.0 spec at docs/superpowers/specs/2026-04-14-sprint-contract-design.md.

Also validates offices/pm/backlog.json v2.0.0 via --backlog mode.

Catches things I (Marcus) routinely get wrong when grooming:
  - Missing or wrong-typed required fields (feedback scaffold, passes: false-not-null)
  - Sizing-cap violations (S/M/L caps on filesToTouch + acceptance count)
  - Title length > 70 chars
  - Banned phrases in acceptance/invariants/stopConditions
  - Missing pre-flight audit as first acceptance criterion
  - Stories missing pmSignOff field when sized L
  - Phantom paths in scope.filesToTouch (US-274 / AI-001 -- always on)
  - Commit-vs-claim drift in feedback.filesActuallyTouched (US-282 / AI-002 --
    OPT-IN via --check-feedback; catches the 2026-Sprints-22-23-24 rescue
    pattern where Ralph's per-story commits log work that never staged)

Backlog (--backlog mode):
  - Schema validation via backlog_schema.validateBacklog (errors)
  - Rollup-cache staleness check: compares stored Epic/Feature status against
    what computeRollups would compute fresh (warnings)

Exit code: 0 = clean, non-zero = violations found.

Usage:
  python offices/pm/scripts/sprint_lint.py             # default sprint.json path
  python offices/pm/scripts/sprint_lint.py --strict    # fail on warnings too
  python offices/pm/scripts/sprint_lint.py --story US-195   # audit one story
  python offices/pm/scripts/sprint_lint.py --check-feedback # commit-vs-claim verifier
  python offices/pm/scripts/sprint_lint.py --backlog   # lint backlog.json v2.0.0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Ensure repo root is on sys.path so `offices.*` imports work when this
# module is run directly as a script (python offices/pm/scripts/sprint_lint.py).
# When imported via pytest or package import, REPO_ROOT is already on sys.path.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SPRINT_PATH = REPO_ROOT / "offices" / "ralph" / "sprint.json"

# Per Sprint Contract v1.0
SIZE_CAPS = {
    "S": {"filesToTouch": 2, "acceptance": 3, "diffLines": 200},
    "M": {"filesToTouch": 5, "acceptance": 5, "diffLines": 500},
    "L": {"filesToTouch": 10, "acceptance": 8, "diffLines": 1000},
}

REQUIRED_FIELDS = [
    "id", "title", "size", "intent", "priority", "dependencies",
    "scope", "groundingRefs", "acceptance", "verification",
    "invariants", "feedback", "passes",
]

REQUIRED_SCOPE_KEYS = ["filesToTouch", "filesToRead"]

BANNED_PHRASES = [
    (r"\bhandle edge cases\b", "handle edge cases"),
    (r"\bworks correctly\b", "works correctly"),
    (r"\bgood UX\b", "good UX"),
    (r"\bas appropriate\b", "as appropriate"),
    (r"\bif needed\b", "if needed"),
    (r"\betc\.", "etc."),
    (r"\band so on\b", "and so on"),
    (r"\bmake sure that\b", "make sure that"),
]

TITLE_CAP = 70
ID_PATTERN = re.compile(r"^US-\d+(-[a-z])?$")


def _canonicalizeBigDoD(lines: list[str]) -> str:
    """Canonicalize a bigDefinitionOfDone list for stable SHA-256 hashing.

    Recipe (per spec 2026-05-28 CIO directive #2): strip each line, sort,
    join with ``\\n``.  Stable across line reordering and trailing-
    whitespace edits so a re-serialization of identical content always
    produces the same hash.  Single source of truth shared by
    :func:`prd_to_sprint.convertPrdToSprint` (freeze write) and
    :func:`lintSprintValidation` (freeze-drift read).
    """
    return "\n".join(sorted(line.strip() for line in lines))


def parseFilesToTouchEntry(entry: str) -> tuple[str, str | None]:
    """Split a ``scope.filesToTouch`` entry into (path, annotation).

    The entry shape is ``"<path> (<annotation>)"`` with the annotation
    optional.  Splits on the *first* ``" ("`` so nested parens inside the
    annotation (``"(UPDATE -- adds (helper))"``) never confuse the path
    boundary.  If no ``" ("`` separator is present the whole string is the
    path and annotation is ``None``.

    The trailing ``)`` of the outer parenthetical is stripped from the
    annotation when present so callers see plain text like
    ``"UPDATE -- adds (helper)"`` rather than ``"UPDATE -- adds (helper))"``.
    """
    idx = entry.find(" (")
    if idx == -1:
        return entry.strip(), None
    path = entry[:idx].strip()
    annotation = entry[idx + 2 :]
    if annotation.endswith(")"):
        annotation = annotation[:-1]
    return path, annotation


def lintFilesToTouchPaths(story: dict, repoRoot: Path) -> list[str]:
    """Verify every UPDATE / unannotated ``filesToTouch`` path exists on disk.

    Closes the AI-001 phantom-path drift pattern (9 sessions running across
    Sprints 14-22).  ``(NEW ...)`` annotations exempt the path from the
    existence check because such files are explicitly being created by the
    story.  Any other annotation (or none at all) requires the path to
    already exist in the repo.
    """
    errs: list[str] = []
    files = story.get("scope", {}).get("filesToTouch", []) or []
    for entry in files:
        if not isinstance(entry, str):
            continue
        path, annotation = parseFilesToTouchEntry(entry)
        if annotation is not None and annotation.lstrip().upper().startswith("NEW"):
            continue
        if not (repoRoot / path).exists():
            errs.append(f"filesToTouch path does not exist on disk: {path!r}")
    return errs


def _collectChangedFilesSinceRef(repoRoot: Path, sinceRef: str) -> set[str] | None:
    """Return the union of paths changed in commits in ``sinceRef..HEAD``.

    Walks ``git log <sinceRef>..HEAD --pretty=format: --name-only`` in
    ``repoRoot``.  Returns ``None`` if the subprocess fails (not in a
    git repo, ref does not resolve, etc.) so callers can degrade
    gracefully without crashing the whole lint run.

    Each line of git's ``--name-only`` output is either a relative path
    or a blank separator between commits; both are folded into a single
    set.  Path separators are normalized to forward slashes so the
    resulting set is portable across Windows / POSIX (US-282 stop-
    condition #1: cross-platform reliability).
    """
    try:
        result = subprocess.run(  # noqa: S603 -- explicit argv, repoRoot constrained by caller
            ["git", "log", f"{sinceRef}..HEAD", "--pretty=format:", "--name-only"],
            cwd=str(repoRoot),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        path = line.strip().replace("\\", "/")
        if path:
            changed.add(path)
    return changed


def _resolveSprintBaseRef(repoRoot: Path, baseBranch: str = "main") -> str | None:
    """Resolve the sprint branch's divergence point from ``baseBranch``.

    Defaults to ``git merge-base HEAD main`` per US-282 spec.  Returns
    ``None`` if merge-base cannot be resolved (no main branch, detached
    HEAD with no merge ancestry, etc.) so callers can fall through to a
    warning rather than crash.
    """
    try:
        result = subprocess.run(  # noqa: S603 -- explicit argv
            ["git", "merge-base", "HEAD", baseBranch],
            cwd=str(repoRoot),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip() or None


def lintFeedbackVsTreeDiff(
    story: dict,
    repoRoot: Path,
    sprintBaseRef: str,
) -> list[str]:
    """Verify every ``feedback.filesActuallyTouched`` claim appears in commits.

    Closes AI-002 -- the commit-but-not-stage pattern that surfaced in
    Sprint 22 (rescue commit ``096dade``) and Sprint 23 (rescue commit
    ``6d8af99``).  Walks ``git log <sprintBaseRef>..HEAD`` to collect
    the union of changed paths, then asserts every entry in
    ``story.feedback.filesActuallyTouched`` (after parenthetical
    stripping via :func:`parseFilesToTouchEntry`) appears in that union.

    Returns one error string per missing claim, shaped::

        feedback claim missing from commits: '<path>'

    Empty / missing / non-dict ``feedback`` is a graceful no-op so
    pre-ship lint runs (where ``filesActuallyTouched`` is the default
    empty list) never spurious-fail.  The OPT-IN ``--check-feedback``
    flag in :func:`main` is the gate that activates this verifier.
    """
    fb = story.get("feedback")
    if not isinstance(fb, dict):
        return []
    claimed = fb.get("filesActuallyTouched") or []
    if not claimed:
        return []
    changed = _collectChangedFilesSinceRef(repoRoot, sprintBaseRef)
    if changed is None:
        return []
    errs: list[str] = []
    for entry in claimed:
        if not isinstance(entry, str):
            continue
        path, _annotation = parseFilesToTouchEntry(entry)
        if path and path not in changed:
            errs.append(f"feedback claim missing from commits: {path!r}")
    return errs


def lintStory(
    story: dict,
    strict: bool = False,
    repoRoot: Path | None = None,
    checkFeedback: bool = False,
    sprintBaseRef: str | None = None,
) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one story."""
    errs: list[str] = []
    warns: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in story:
            errs.append(f"missing required field: {field}")

    if "id" in story and not ID_PATTERN.match(story["id"]):
        errs.append(f"id {story['id']!r} does not match US-\\d+(-[a-z])?")

    if "title" in story and len(story["title"]) > TITLE_CAP:
        warns.append(f"title is {len(story['title'])} chars (cap {TITLE_CAP})")

    if "size" in story and story["size"] not in SIZE_CAPS:
        errs.append(f"size {story['size']!r} not one of S/M/L")

    if "scope" in story:
        for k in REQUIRED_SCOPE_KEYS:
            if k not in story["scope"]:
                errs.append(f"scope missing required key: {k}")

    if story.get("passes") is None:
        errs.append("passes is None; spec says false-until-complete")
    elif story.get("passes") not in (True, False):
        errs.append(f"passes is {story.get('passes')!r}; must be bool")

    fb = story.get("feedback")
    if fb is None:
        errs.append("feedback field is missing or None")
    elif not isinstance(fb, dict) or set(fb.keys()) != {"filesActuallyTouched", "grounding"}:
        warns.append(f"feedback should be {{filesActuallyTouched, grounding}}; got {sorted(fb.keys()) if isinstance(fb, dict) else type(fb).__name__}")

    # Sizing cap check
    sz = story.get("size")
    if sz in SIZE_CAPS:
        cap = SIZE_CAPS[sz]
        ftt = len(story.get("scope", {}).get("filesToTouch", []))
        # acceptance excludes pre-flight (so we count len-1 if first item looks like pre-flight)
        acc = story.get("acceptance", []) or []
        accNonPreflight = len(acc)
        if acc and ("pre-flight" in acc[0].lower() or ("audit" in acc[0].lower() and "before" in acc[0].lower())):
            accNonPreflight = len(acc) - 1
        if ftt > cap["filesToTouch"]:
            warns.append(f"sized {sz} but filesToTouch={ftt} (cap {cap['filesToTouch']}); consider {('M' if sz=='S' else 'L')}")
        if accNonPreflight > cap["acceptance"]:
            warns.append(f"sized {sz} but acceptance={accNonPreflight} (cap {cap['acceptance']}, excl pre-flight)")

    # L stories require pmSignOff
    if sz == "L" and "pmSignOff" not in story:
        errs.append("size L requires pmSignOff field")

    # Pre-flight audit as first acceptance
    acc = story.get("acceptance", []) or []
    if acc:
        first = acc[0].lower()
        if not ("pre-flight" in first or ("audit" in first and "before" in first)):
            warns.append("first acceptance is not pre-flight audit per spec example")

    # filesToTouch path-existence check (US-274 / AI-001) -- catches phantom
    # paths surfaced by Marcus's template generator before they hit Ralph.
    errs.extend(lintFilesToTouchPaths(story, repoRoot or REPO_ROOT))

    # feedback.filesActuallyTouched commit-vs-claim check (US-282 / AI-002) --
    # OPT-IN via the --check-feedback flag so pre-ship lint runs (empty
    # feedback by design) do NOT spurious-fail.  Default off mirrors the
    # behavior pre-fix where this check did not exist at all.
    if checkFeedback:
        effectiveRoot = repoRoot or REPO_ROOT
        baseRef = sprintBaseRef or _resolveSprintBaseRef(effectiveRoot)
        if baseRef is None:
            warns.append(
                "checkFeedback enabled but sprint base ref could not be resolved "
                "(merge-base HEAD main failed); skipping commit-vs-claim check",
            )
        else:
            errs.extend(lintFeedbackVsTreeDiff(story, effectiveRoot, baseRef))

    # Banned phrases (search across acceptance + invariants + stopConditions + intent)
    sources = []
    if isinstance(story.get("intent"), str):
        sources.append(("intent", story["intent"]))
    for field in ("acceptance", "invariants", "stopConditions"):
        for i, item in enumerate(story.get(field) or []):
            if isinstance(item, str):
                sources.append((f"{field}[{i}]", item))
    for loc, text in sources:
        for pattern, label in BANNED_PHRASES:
            if re.search(pattern, text, re.IGNORECASE):
                warns.append(f"banned phrase {label!r} in {loc}: ...{text[max(0, text.lower().find(label.lower())-15):text.lower().find(label.lower())+len(label)+25].strip()}...")

    return errs, warns


def lintSprintValidation(sprintData: dict, repoRoot: Path) -> list[str]:
    """Validate the sprint-level ``validation`` block per Mike 2026-05-08 workflow.

    Required fields (per `/sprint-deploy-pm` + `/sprint-validated` contract):
      - ``validation.bigDefinitionOfDone``  -- non-empty list of clauses
      - ``validation.validationMethod``     -- string
      - ``validation.validatesFeatures``    -- list of F-NNN ids
      - ``validation.currentVersion``       -- string matching SemVer ``V<major>.<minor>.<patch>``
      - ``validation.validatedAt``          -- null or ISO datetime
      - ``validation.validatedBy``          -- null or string

    Cross-check (warning): ``validatesFeatures`` ids should exist in
    ``offices/pm/regression_manifest.json``.

    Returns list of error strings.  Empty list means clean.
    """
    errs: list[str] = []
    v = sprintData.get("validation")
    if v is None:
        errs.append("missing required sprint-level 'validation' block (Sprint 28+ requirement per Mike 2026-05-08 workflow)")
        return errs
    if not isinstance(v, dict):
        errs.append(f"'validation' must be a dict, got {type(v).__name__}")
        return errs

    bdod = v.get("bigDefinitionOfDone")
    if not isinstance(bdod, list) or len(bdod) == 0:
        errs.append("validation.bigDefinitionOfDone must be a non-empty list of clause strings")
    elif not all(isinstance(c, str) and c.strip() for c in bdod):
        errs.append("validation.bigDefinitionOfDone clauses must be non-empty strings")

    if not isinstance(v.get("validationMethod"), str):
        errs.append("validation.validationMethod must be a non-empty string")

    vf = v.get("validatesFeatures")
    if not isinstance(vf, list):
        errs.append("validation.validatesFeatures must be a list of F-NNN ids")
    else:
        for fid in vf:
            if not isinstance(fid, str) or not re.match(r"^F-\d+$", fid):
                errs.append(f"validation.validatesFeatures entry {fid!r} does not match F-NNN pattern")

    cv = v.get("currentVersion")
    if not isinstance(cv, str) or not re.match(r"^V\d+\.\d+\.\d+$", cv):
        errs.append(f"validation.currentVersion {cv!r} does not match SemVer pattern V<major>.<minor>.<patch>")

    if "validatedAt" not in v:
        errs.append("validation.validatedAt missing (null until validated)")
    if "validatedBy" not in v:
        errs.append("validation.validatedBy missing (null until validated)")

    # Cross-check: validatesFeatures ids exist in manifest
    manifestPath = repoRoot / "offices" / "pm" / "regression_manifest.json"
    if isinstance(vf, list) and manifestPath.exists():
        try:
            manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
            knownIds = {f.get("id") for f in manifest.get("features", [])}
            for fid in vf:
                if isinstance(fid, str) and fid not in knownIds:
                    errs.append(f"validation.validatesFeatures references unknown feature {fid!r} (not in regression_manifest.json)")
        except (json.JSONDecodeError, OSError):
            pass  # cross-check is best-effort

    # Freeze-drift check per spec 2026-05-28 (CIO directive #2).  Legacy
    # sprints (V0.27 chain + earlier) lack ``frozenAt`` -- skip silently so
    # archived contracts continue to lint cleanly.
    frozenAt = v.get("frozenAt")
    if frozenAt:
        stored = v.get("bigDoDHash")
        if not stored:
            errs.append(
                "validation.frozenAt set but validation.bigDoDHash missing -- "
                "contract corrupt"
            )
        elif isinstance(bdod, list):
            canonical = _canonicalizeBigDoD(bdod)
            computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if computed != stored:
                errs.append(
                    f"validation.bigDefinitionOfDone modified after freeze at "
                    f"{frozenAt}; computed={computed[:8]}, stored={stored[:8]}. "
                    f"Late additions are forbidden per directive 2026-05-23 #2 -- "
                    f"create a patch sprint instead."
                )

    # Per-story empty-list checks per spec 2026-05-28.  Every sprint story
    # MUST carry at least one (action, outcome) validationCriteria pair and
    # a non-empty DoD so Ralph has a complete-signal contract.
    for story in sprintData.get("stories", []):
        vc = story.get("validationCriteria", [])
        if not vc:
            errs.append(
                f"Story {story.get('id', '?')}: validationCriteria empty in sprint.json "
                f"-- every story must have at least 1 (action, outcome) pair "
                f"per directive 2026-05-23 #2"
            )
        dod = story.get("acceptance", []) or story.get("definitionOfDone", [])
        if not dod:
            errs.append(
                f"Story {story.get('id', '?')}: definitionOfDone empty in sprint.json "
                f"-- every story must have a non-empty DoD so Ralph knows when complete"
            )

    return errs


# ---------------------------------------------------------------------------
# Backlog v2.0.0 lint types + function
# ---------------------------------------------------------------------------

@dataclass
class LintError:
    """A schema-validation failure from lintBacklog."""
    message: str


@dataclass
class LintWarning:
    """A rollup-cache staleness warning from lintBacklog."""
    message: str


def lintBacklog(path: Path) -> tuple[list[LintError], list[LintWarning]]:
    """
    Lint a backlog.json v2.0.0 file. Returns (errors, warnings).

    Errors are schema-validation failures (from validateBacklog).
    Warnings are rollup-cache mismatches (Epic/Feature status stored differs
    from what computeRollups would compute fresh).

    Args:
        path: Path to backlog.json (any Path-like object with .read_text()).

    Returns:
        Tuple of (errors, warnings) lists of LintError / LintWarning.
    """
    from offices.pm.scripts.backlog_schema import validateBacklog, BacklogValidationError
    from offices.pm.scripts.pm_status import computeRollups

    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[LintError] = []
    warnings: list[LintWarning] = []

    try:
        validateBacklog(data)
    except BacklogValidationError as e:
        errors.append(LintError(message=str(e)))
        return errors, warnings  # short-circuit on validation failure

    # Rollup-cache check: deep-copy data, recompute, diff with stored.
    storedEpic = {e["id"]: e["status"] for e in data["epics"]}
    storedFeature = {f["id"]: f["status"] for f in data["features"]}

    fresh = json.loads(json.dumps(data))  # deep copy -- computeRollups mutates in-place
    computeRollups(fresh)
    for e in fresh["epics"]:
        if e["status"] != storedEpic[e["id"]]:
            warnings.append(LintWarning(
                message=f"Epic {e['id']} rollup cache stale: "
                        f"stored={storedEpic[e['id']]!r} computed={e['status']!r}"
            ))
    for f in fresh["features"]:
        if f["status"] != storedFeature[f["id"]]:
            warnings.append(LintWarning(
                message=f"Feature {f['id']} rollup cache stale: "
                        f"stored={storedFeature[f['id']]!r} computed={f['status']!r}"
            ))

    return errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--story", help="Lint only one story by ID")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too")
    parser.add_argument("--path", default=str(SPRINT_PATH), help="sprint.json path override")
    parser.add_argument(
        "--check-feedback",
        action="store_true",
        help=(
            "Walk git log <merge-base HEAD main>..HEAD and verify every "
            "story.feedback.filesActuallyTouched entry appears in at least "
            "one commit's tree-diff (US-282 / AI-002 commit-vs-claim "
            "verifier).  OPT-IN: leave off for pre-ship lint runs where "
            "feedback is still empty."
        ),
    )
    parser.add_argument(
        "--sprint-base-ref",
        default=None,
        help=(
            "Override the sprint base ref for --check-feedback (default: "
            "merge-base HEAD main).  Useful for testing or for sprints "
            "branched from a non-main base."
        ),
    )
    parser.add_argument(
        "--backlog",
        action="store_true",
        help=(
            "Lint offices/pm/backlog.json v2.0.0: schema validation (errors) "
            "and rollup-cache staleness check (warnings).  Exits 1 if errors."
        ),
    )
    args = parser.parse_args(argv)

    # --backlog mode: delegates entirely to lintBacklog(), then exits.
    if args.backlog:
        backlogPath = REPO_ROOT / "offices" / "pm" / "backlog.json"
        if not backlogPath.exists():
            print(f"ERROR: {backlogPath} not found", file=sys.stderr)
            return 2
        errors, warnings = lintBacklog(backlogPath)
        for e in errors:
            print(f"ERROR: {e.message}", file=sys.stderr)
        for w in warnings:
            print(f"WARNING: {w.message}")
        return 1 if errors or (args.strict and warnings) else 0

    p = Path(args.path)
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        return 2

    d = json.loads(p.read_text(encoding="utf-8"))
    stories = d.get("stories", [])
    if args.story:
        stories = [s for s in stories if s.get("id") == args.story]
        if not stories:
            print(f"ERROR: story {args.story} not found", file=sys.stderr)
            return 2

    totalErrs = 0
    totalWarns = 0
    print(f"Linting {p}\n")

    # Sprint-level validation block (Mike 2026-05-08 workflow); skipped when --story selects a single story
    if not args.story:
        validationErrs = lintSprintValidation(d, REPO_ROOT)
        if validationErrs:
            print("  SPRINT-LEVEL")
            for e in validationErrs:
                print(f"    ERROR   {e}")
                totalErrs += 1

    for s in stories:
        errs, warns = lintStory(
            s,
            args.strict,
            checkFeedback=args.check_feedback,
            sprintBaseRef=args.sprint_base_ref,
        )
        if not errs and not warns:
            print(f"  {s.get('id', '?'):<8} OK")
            continue
        print(f"  {s.get('id', '?'):<8}")
        for e in errs:
            print(f"    ERROR   {e}")
            totalErrs += 1
        for w in warns:
            print(f"    warn    {w}")
            totalWarns += 1

    print(f"\nSummary: {totalErrs} error(s), {totalWarns} warning(s) across {len(stories)} stor{'y' if len(stories)==1 else 'ies'}")

    if totalErrs > 0:
        return 1
    if args.strict and totalWarns > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
