#!/usr/bin/env python3
"""
backlog_set.py -- CLI for common backlog.json mutations.

Encapsulates the mutation patterns Marcus (PM) uses at sprint boundaries:
  - flip feature status (pending | groomed | in_sprint | in_progress | blocked | complete | declined)
  - add a phase record under a feature (used for B-037 crawl/walk/run/sprint/harden)
  - record completion metadata on a feature
  - bump lastUpdated + updatedBy
  - CREATE A STORY (``--add-story``) with every schema-required field stamped

Stdlib-only. Idempotent: re-running with the same args is safe.

--add-story (US-669 / F-118)
----------------------------
Until this subcommand there was NO story-creation path in the toolchain: filing
a story meant hand-editing a ~900 KB JSON file and remembering twelve required
fields. That lost to convenience twice -- 47 stories across Sprints 50-55
(repaired by US-465) and 41 more across US-628..US-667. ``backfill_story_metadata``
is the repair; this is the prevention. They are not alternatives.

The required-field list is READ from ``backlog_schema.REQUIRED_STORY_FIELDS``
at call time and never restated here. Add a field there and this tool starts
requiring it with no edit -- see :func:`buildStory`.

Usage examples:

  # File a story under an existing Feature:
  python -m tools.pm.backlog_set --add-story \
      --story-parent F-118 \
      --story-title "The backlog lint reports every violation" \
      --story-goal "As the PM, I want ..." \
      --story-dod "SSOT: tools/pm/sprint_lint.py" \
      --story-dod "END STATE: every violation is listed" \
      --story-vc "run the lint over a backlog with 3 violations" "all 3 are reported" \
      --story-type tech-debt --story-size S --story-status sprint-ready

  # At session start, bump the lastUpdated field:
  python -m tools.pm.backlog_set --updated-by "Marcus (PM, Session 24)"

  # Flip a feature status:
  python -m tools.pm.backlog_set --feature B-044 --status in_sprint \
      --field inSprint="Sprint 14 (US-201)"

  # Record completion:
  python -m tools.pm.backlog_set --feature B-042 --status complete \
      --completed-date 2026-04-18 \
      --completed-by "Ralph (US-187, Sprint 12)"

  # Add a phase record to B-037 (or any feature with phases[]):
  python -m tools.pm.backlog_set --feature B-037 --add-phase harden \
      --phase-status in_progress \
      --phase-sprint "Sprint 14" \
      --phase-branch sprint/pi-harden \
      --phase-date 2026-04-19 \
      --phase-stories US-192,US-193,US-194,US-195,US-196,US-197,US-198,US-199,US-200,US-201 \
      --phase-note "Sprint 14 loaded -- TD fixes + data-collection v2 + carryforward"
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Roots come from the _paths SSOT -- depth-independent by construction.
#
# Imported as a MODULE, and resolved at CALL time (see resolveBacklogPath).
# `from tools.pm._paths import SHARE_ROOT` resolved eagerly at import, so merely
# importing this file was a configuration error when $FLEET_SHARE was unset --
# and it froze the path, so a test (or a caller) that repointed the share after
# import was silently ignored. graduate_story.py already resolves at call time;
# this now matches it.
from tools.pm import _paths, backlog_schema

# Proposed-change lines echo user-supplied notes/field values that may carry
# Unicode (e.g. the '->' rendered as U+2192, em-dashes), so harden stdout+stderr
# to UTF-8 before any print (Windows cp1252 crash guard, US-466). Inlined to keep
# this script self-contained ("Stdlib-only"); canonical recipe: _encoding.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VALID_STATUSES = {
    "pending", "groomed", "in_sprint", "in_progress",
    "blocked", "complete", "declined",
}

# The required story fields that carry SEMANTIC content -- the PM's judgement,
# which no tool may invent (AC #5). Everything else in
# ``backlog_schema.REQUIRED_STORY_FIELDS`` is metadata: an id we allocate,
# timestamps we stamp, enumerations with a conservative default, and empty-list
# defaults. This is a SELECTION from that frozenset, not a copy of it -- a test
# pins ``SEMANTIC_STORY_FIELDS <= REQUIRED_STORY_FIELDS``, and any field added
# to the schema that is not named here is caught by buildStory's missing-field
# check and REFUSED. The tool degrades to refusing, never to inventing.
SEMANTIC_STORY_FIELDS = ("parent", "title", "goal", "definitionOfDone",
                         "validationCriteria")

# Conservative defaults for the three enumerated required fields. `pending` is
# the honest state for a story nobody has groomed yet; `normal`/`M` are the base
# case. All three are validated against the schema's own frozensets, so an
# invalid default cannot ship.
STORY_TYPE_DEFAULT = "normal"
STORY_SIZE_DEFAULT = "M"
STORY_STATUS_DEFAULT = "pending"

_STORY_ID_RE = re.compile(r"^US-(\d+)$")


class StoryCreationError(ValueError):
    """Raised when a story cannot be created. Carries EVERY reason, not the first."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def resolveBacklogPath(override: str | None = None) -> Path:
    """Resolve backlog.json, honouring an explicit override."""
    return Path(override) if override else _paths.resolveShareRoot() / "pm" / "backlog.json"


def resolveCounterPath(override: str | None = None) -> Path:
    """Resolve story_counter.json, honouring an explicit override."""
    if override:
        return Path(override)
    return _paths.resolveShareRoot() / "pm" / "story_counter.json"


def loadBacklog(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or resolveBacklogPath()).read_text(encoding="utf-8"))


def writeJsonAtomic(path: Path, data: dict[str, Any]) -> None:
    """Land ``data`` at ``path`` via a sibling temp file + :func:`os.replace`.

    backlog.json is ~900 KB on a share with no git and no revert. A truncating
    ``open(path, "w")`` that then raises destroys it -- that is not theoretical,
    it cost a 22,588-byte file on this share on 2026-08-31. ``os.replace`` is
    atomic on POSIX and Windows alike, so a reader sees either the whole old
    file or the whole new one.

    On ANY failure the temp is removed and the previous file is left untouched.

    Args:
        path: Destination file.
        data: JSON-serialisable payload.

    Raises:
        OSError: Re-raised after cleanup, so the caller refuses loudly rather
            than reporting a write that did not happen.
    """
    tempPath = path.with_name(path.name + ".tmp")
    try:
        with open(tempPath, "w", encoding="utf-8") as fh:
            # ensure_ascii=False: the PM's prose is full of arrows and emoji and
            # must stay readable on disk (US-466).
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tempPath, path)
    except OSError:
        try:
            tempPath.unlink()
        except OSError:
            pass
        raise


def saveBacklog(data: dict[str, Any], path: Path | None = None) -> None:
    writeJsonAtomic(path or resolveBacklogPath(), data)


def findFeature(data: dict[str, Any], featureId: str) -> dict[str, Any] | None:
    """Find a Feature by id in either backlog shape.

    v2.0.0 (schemaVersion 2.0.0, current) keeps features in a TOP-LEVEL
    ``features`` list. This function previously walked ``epics[].features[]``
    only -- the v1 shape -- so on the live backlog it returned None for every
    feature id and the entire ``--feature`` branch of this tool exited 2. The
    legacy nested walk is kept so archived v1 documents still resolve.

    Args:
        data: Parsed backlog (either shape).
        featureId: e.g. ``F-118`` (v2) or ``B-037`` (v1).

    Returns:
        The feature dict, or None if no feature carries that id.
    """
    for feature in data.get("features", []):
        if feature.get("id") == featureId:
            return feature
    for epic in data.get("epics", []):
        for feature in epic.get("features", []):
            if feature.get("id") == featureId:
                return feature
    return None


def allocateStoryId(data: dict[str, Any], counter: dict[str, Any]) -> tuple[str, list[str]]:
    """Allocate the next free ``US-N`` id, above BOTH counters and every record.

    Three sources can disagree: ``story_counter.json``'s ``nextId``,
    ``backlog.json``'s ``counters.story``, and the highest id actually present.
    On 2026-09-04 the live files read US-681 / 678 / US-680 -- so trusting
    ``counters.story`` alone would have minted US-679, a duplicate.

    The floor is therefore the MAXIMUM of all three. That can never collide, and
    the cost of a disagreement is a gap in the sequence, which is harmless. The
    disagreement is REPORTED rather than silently absorbed: a counter that has
    fallen behind is a symptom of something else writing the file.

    Args:
        data: Parsed backlog.
        counter: Parsed story_counter.json.

    Returns:
        ``(storyId, warnings)``.
    """
    warnings: list[str] = []

    def numberOf(value: Any) -> int:
        match = _STORY_ID_RE.match(str(value or ""))
        return int(match.group(1)) if match else 0

    fromCounterFile = numberOf(counter.get("nextId"))
    fromBacklogCounter = int(data.get("counters", {}).get("story") or 0) + 1
    highestPresent = max(
        (numberOf(s.get("id")) for s in data.get("stories", [])), default=0
    ) + 1

    chosen = max(fromCounterFile, fromBacklogCounter, highestPresent)
    if len({fromCounterFile, fromBacklogCounter, highestPresent}) > 1:
        warnings.append(
            f"id sources disagree -- story_counter.json nextId={counter.get('nextId')!r}, "
            f"backlog counters.story implies US-{fromBacklogCounter}, highest story "
            f"present implies US-{highestPresent}. Allocating US-{chosen} (above all "
            f"three); the gap is deliberate and harmless, a collision would not be."
        )
    return f"US-{chosen}", warnings


def buildStory(
    *,
    storyId: str,
    parent: str,
    title: str,
    goal: str,
    definitionOfDone: list[str],
    validationCriteria: list[dict[str, str]],
    storyType: str = STORY_TYPE_DEFAULT,
    size: str = STORY_SIZE_DEFAULT,
    status: str = STORY_STATUS_DEFAULT,
    conditionalOutcomes: list[str] | None = None,
    createdBy: str | None = None,
    sourceRefs: list[str] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Assemble a schema-complete story record.

    Metadata is stamped (id, createdAt/updatedAt, empty-list defaults);
    semantic content is never invented -- callers must supply it, and
    :func:`validateStoryRequest` refuses when they have not.

    The required-field check reads ``backlog_schema.REQUIRED_STORY_FIELDS`` as a
    MODULE ATTRIBUTE, deliberately: ``from backlog_schema import ...`` would bind
    a copy at import time and this tool would stop noticing schema growth --
    which is the exact drift class US-669 closes. Add a field to the schema and
    this function starts refusing until the field is supplied.

    Args:
        storyId: Allocated id, e.g. ``US-681``.
        parent: Feature id (validated by the caller against the backlog).
        title: Story title.
        goal: The "As the PM, I want ... because ..." statement.
        definitionOfDone: Non-empty list of DoD clauses.
        validationCriteria: Non-empty list of ``{action, outcome}`` dicts.
        storyType: One of ``backlog_schema.VALID_STORY_TYPES``.
        size: One of ``backlog_schema.VALID_STORY_SIZES``.
        status: One of ``backlog_schema.VALID_STORY_STATUSES``.
        conditionalOutcomes: Optional; defaults to ``[]``.
        createdBy: Optional provenance credit.
        sourceRefs: Optional provenance references.
        today: Run date (YYYY-MM-DD); defaults to the system date.

    Returns:
        The story dict.

    Raises:
        StoryCreationError: If the schema requires a field this function does
            not know how to supply. Refusing is the safe degradation -- the one
            thing it must never do is default a field it cannot reason about.
    """
    today = today or _dt.date.today().isoformat()
    story: dict[str, Any] = {
        "id": storyId,
        "parent": parent,
        "type": storyType,
        "size": size,
        "status": status,
        "createdAt": today,
        "updatedAt": today,
        "title": title,
        "goal": goal,
        "definitionOfDone": list(definitionOfDone),
        "conditionalOutcomes": list(conditionalOutcomes or []),
        "validationCriteria": [dict(vc) for vc in validationCriteria],
        "tasks": [],
    }
    if createdBy:
        story["createdBy"] = createdBy
    if sourceRefs:
        story["sourceRefs"] = list(sourceRefs)

    missing = sorted(backlog_schema.REQUIRED_STORY_FIELDS - set(story))
    if missing:
        raise StoryCreationError([
            f"backlog_schema.REQUIRED_STORY_FIELDS demands {missing}, which this "
            f"tool does not know how to supply. Refusing rather than defaulting a "
            f"field whose meaning it cannot reason about -- teach buildStory about "
            f"it (metadata) or add a --story-* flag for it (content)."
        ])
    return story


def validateStoryRequest(
    data: dict[str, Any], supplied: dict[str, Any], storyId: str
) -> list[str]:
    """Collect EVERY reason the requested story cannot be created.

    Every reason, not the first: a one-at-a-time refusal makes the drift look
    small and costs the PM a round trip per field, which is how the correct path
    lost to hand-editing in the first place (F-118).

    Args:
        data: Parsed backlog.
        supplied: The semantic content the caller provided, keyed by field name.
        storyId: The id about to be used.

    Returns:
        A list of human-readable reasons; empty when the request is creatable.
    """
    reasons: list[str] = []

    for field in SEMANTIC_STORY_FIELDS:
        value = supplied.get(field)
        # Present-but-empty is REFUSED, not accepted. A story that is
        # schema-valid and semantically empty is worse than a missing one,
        # because the lint then certifies it (PM Rule 7).
        if isinstance(value, str):
            empty = not value.strip()
        else:
            empty = not value
        if empty:
            reasons.append(
                f"{field}: required semantic content was not supplied. This tool "
                f"will not invent a placeholder to satisfy the schema."
            )

    if supplied.get("parent") and findFeature(data, supplied["parent"]) is None:
        reasons.append(
            f"parent: {supplied['parent']!r} is not an existing Feature id. Every "
            f"Story has a Feature parent (Rule 11 -- no orphans); an Epic or Story "
            f"id will not do."
        )

    if any(s.get("id") == storyId for s in data.get("stories", [])):
        reasons.append(
            f"id: {storyId} already exists in the backlog. Refusing rather than "
            f"appending a duplicate."
        )

    return reasons


def addStory(
    data: dict[str, Any],
    counter: dict[str, Any],
    *,
    storyId: str | None = None,
    today: str | None = None,
    **supplied: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Validate, build and append a story; bump both counters in ``data``.

    Mutates ``data`` and ``counter`` in memory only. The caller lands them.

    Args:
        data: Parsed backlog (mutated).
        counter: Parsed story_counter.json (mutated).
        storyId: Explicit id, or None to allocate.
        today: Run date; defaults to the system date.
        **supplied: Semantic + optional fields for :func:`buildStory`.

    Returns:
        ``(story, warnings)``.

    Raises:
        StoryCreationError: With EVERY reason the request was refused. Nothing
            is mutated when this raises.
    """
    warnings: list[str] = []
    if storyId is None:
        storyId, warnings = allocateStoryId(data, counter)

    reasons = validateStoryRequest(data, supplied, storyId)
    if reasons:
        raise StoryCreationError(reasons)

    story = buildStory(storyId=storyId, today=today, **supplied)

    # Prove the new record against the REAL validator before writing -- but in a
    # SYNTHETIC one-epic/one-feature wrapper, not against the whole backlog.
    #
    # Validating the whole file would make story creation impossible whenever
    # any unrelated pre-existing story has drifted -- and pre-existing drift is
    # the normal state this story was written from (41 records on 2026-09-01).
    # The prevention tool must not be disabled by the condition the repair tool
    # exists to fix.
    feature = findFeature(data, story["parent"])
    epic = next((e for e in data.get("epics", [])
                 if e.get("id") == (feature or {}).get("parent")), None)
    backlog_schema.validateBacklog({
        "schemaVersion": "2.0.0",
        "epics": [epic] if epic else [],
        "features": [dict(feature or {}, parent=(epic or {}).get("id"))],
        "stories": [story],
    })

    data.setdefault("stories", []).append(story)
    number = int(_STORY_ID_RE.match(storyId).group(1))
    data.setdefault("counters", {})["story"] = number
    counter["nextId"] = f"US-{number + 1}"
    counter["lastUpdated"] = today or _dt.date.today().isoformat()
    return story, warnings


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

    # Story creation (US-669). All --story-* flags are inert without --add-story.
    parser.add_argument("--add-story", action="store_true",
                        help="Create a Story with every schema-required field stamped")
    parser.add_argument("--story-id", help="Explicit id (default: allocate the next free US-N)")
    parser.add_argument("--story-parent", help="Feature id (e.g. F-118) -- must already exist")
    parser.add_argument("--story-title", help="Story title")
    parser.add_argument("--story-goal", help="'As the <role>, I want ... because ...'")
    parser.add_argument("--story-dod", action="append", default=[],
                        help="A definitionOfDone clause (repeat for each)")
    parser.add_argument("--story-vc", action="append", nargs=2, default=[],
                        metavar=("ACTION", "OUTCOME"),
                        help="A validationCriteria pair (repeat for each)")
    parser.add_argument("--story-co", action="append", default=[],
                        help="A conditionalOutcome (repeat; defaults to none)")
    parser.add_argument("--story-source-ref", action="append", default=[],
                        help="A sourceRefs entry (repeat)")
    parser.add_argument("--story-created-by", help="Provenance credit")
    parser.add_argument("--story-type", choices=sorted(backlog_schema.VALID_STORY_TYPES),
                        default=STORY_TYPE_DEFAULT)
    parser.add_argument("--story-size", choices=sorted(backlog_schema.VALID_STORY_SIZES),
                        default=STORY_SIZE_DEFAULT)
    parser.add_argument("--story-status", choices=sorted(backlog_schema.VALID_STORY_STATUSES),
                        default=STORY_STATUS_DEFAULT)
    parser.add_argument("--backlog", help="backlog.json path override")
    parser.add_argument("--counter", help="story_counter.json path override")

    parser.add_argument("--dry-run", action="store_true", help="Print the proposed JSON without writing")

    args = parser.parse_args(argv)

    backlogPath = resolveBacklogPath(args.backlog)

    if args.add_story:
        return _runAddStory(args, backlogPath)

    data = loadBacklog(backlogPath)
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

    saveBacklog(data, backlogPath)
    print(f"\nWrote {backlogPath}")
    return 0


def _runAddStory(args: argparse.Namespace, backlogPath: Path) -> int:
    """Drive ``--add-story``: validate, build, then land both files.

    Args:
        args: Parsed CLI namespace.
        backlogPath: Resolved backlog.json path.

    Returns:
        Process exit code -- 0 on success, 2 on refusal or write failure.
    """
    counterPath = resolveCounterPath(args.counter)
    data = loadBacklog(backlogPath)
    counter = (json.loads(counterPath.read_text(encoding="utf-8"))
               if counterPath.exists() else {})

    try:
        story, warnings = addStory(
            data, counter,
            storyId=args.story_id,
            parent=args.story_parent or "",
            title=args.story_title or "",
            goal=args.story_goal or "",
            definitionOfDone=args.story_dod,
            validationCriteria=[{"action": a, "outcome": o} for a, o in args.story_vc],
            conditionalOutcomes=args.story_co,
            sourceRefs=args.story_source_ref,
            createdBy=args.story_created_by,
            storyType=args.story_type,
            size=args.story_size,
            status=args.story_status,
        )
    except (StoryCreationError, backlog_schema.BacklogValidationError) as exc:
        reasons = getattr(exc, "reasons", [str(exc)])
        print("REFUSED -- nothing was written:", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Proposed story {story['id']} ({story['type']}/{story['size']}) "
          f"under {story['parent']}:")
    print(f"  title: {story['title']}")
    print(f"  createdAt/updatedAt: {story['createdAt']}")
    print(f"  definitionOfDone: {len(story['definitionOfDone'])} clause(s), "
          f"validationCriteria: {len(story['validationCriteria'])} pair(s)")

    if args.dry_run:
        print("\n[DRY RUN -- no write performed]")
        return 0

    # ORDERING IS DELIBERATE: the counter lands FIRST.
    #
    # If the backlog write then fails, the id is burned and the sequence has a
    # gap -- harmless. The other order fails the other way: a landed story whose
    # counter bump was lost hands the SAME id to the next caller, which is the
    # collision AC #7 exists to prevent. Prefer a gap to a duplicate.
    try:
        if counter:
            writeJsonAtomic(counterPath, counter)
        writeJsonAtomic(backlogPath, data)
    except OSError as exc:
        print(f"REFUSED -- write failed, previous files left intact: {exc}",
              file=sys.stderr)
        return 2

    print(f"\nWrote {story['id']} to {backlogPath}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
