#!/usr/bin/env python3
"""
sprint_lint.py -- Audit offices/ralph/sprint.json against the Sprint Contract
v1.0 spec at docs/superpowers/specs/2026-04-14-sprint-contract-design.md.

Catches things I (Marcus) routinely get wrong when grooming:
  - Missing or wrong-typed required fields (feedback scaffold, passes: false-not-null)
  - Sizing-cap violations (S/M/L caps on filesToTouch + acceptance count)
  - Title length > 70 chars
  - Banned phrases in acceptance/invariants/stopConditions
  - Missing pre-flight audit as first acceptance criterion
  - Stories missing pmSignOff field when sized L

Exit code: 0 = clean, non-zero = violations found.

Usage:
  python offices/pm/scripts/sprint_lint.py             # default sprint.json path
  python offices/pm/scripts/sprint_lint.py --strict    # fail on warnings too
  python offices/pm/scripts/sprint_lint.py --story US-195   # audit one story
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
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


def lintStory(
    story: dict,
    strict: bool = False,
    repoRoot: Path | None = None,
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--story", help="Lint only one story by ID")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings too")
    parser.add_argument("--path", default=str(SPRINT_PATH), help="sprint.json path override")
    args = parser.parse_args(argv)

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
    for s in stories:
        errs, warns = lintStory(s, args.strict)
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
