"""
File: offices/pm/scripts/graduate_story.py
Purpose: Move a completed Story/Feature/Epic out of the active backlog
         into offices/pm/archive/completed-work-products/. Removes from
         backlog.json. Refuses if status != 'complete'.

Note (2026-06-19): A "ghost" Story (present in backlog.json but with no
companion Story.md -- e.g. filed directly into JSON during grooming) used to
make graduation raise + abort, which left such stories stranded in the active
backlog forever. Graduation now SYNTHESIZES an archive record .md from the JSON
entry when no source .md exists, so the completed-work record is preserved and
active/archive separation stays tight.
"""
import json
from pathlib import Path


def _synthesizeArchiveMd(story: dict) -> str:
    """Render a backlog Story JSON entry as an archive record .md.

    Used when a Story has no companion Story.md (a "ghost") so graduation still
    preserves a human-readable completed-work record instead of dropping it.
    """
    lines = [
        "---",
        f"id: {story.get('id', '')}",
        f"parent: {story.get('parent', '')}",
        f"type: {story.get('type', '')}",
        f"size: {story.get('size', '')}",
        f"status: {story.get('status', '')}",
        "archivedFrom: backlog.json (no source Story.md -- synthesized at graduation)",
        "---",
        "",
        f"# {story.get('id', '')} — {story.get('title', '')}",
        "",
        "## Goal",
        story.get("goal", "(none recorded)"),
        "",
        "## Definition of Done",
    ]
    for d in story.get("definitionOfDone", []) or ["(none recorded)"]:
        lines.append(f"- {d}")
    lines.append("")
    lines.append("## Validation Criteria")
    for vc in story.get("validationCriteria", []):
        lines.append(f"- ({vc.get('action', '')}) -> ({vc.get('outcome', '')})")
    lines.append("")
    lines.append(
        "_Synthesized from backlog.json at graduation (2026-06-19); the original "
        "Story was filed directly into JSON without a Story.md._"
    )
    lines.append("")
    return "\n".join(lines)


def graduateStory(storyId: str, repoRoot: Path, dryRun: bool = False) -> None:
    """
    Graduate a completed Story from the active backlog to the archive.

    Args:
        storyId: ID like 'US-359'.
        repoRoot: Path containing offices/pm/backlog.json and offices/pm/backlog/.
        dryRun: If True, print intended actions without executing.

    Raises:
        ValueError: If the story is not found or its status is not 'complete'.
                    A missing Story.md is NOT fatal -- an archive record is
                    synthesized from the JSON entry.
    """
    backlogPath = repoRoot / "offices/pm/backlog.json"
    data = json.loads(backlogPath.read_text(encoding="utf-8"))
    story = next((s for s in data["stories"] if s["id"] == storyId), None)
    if not story:
        raise ValueError(f"Story {storyId} not found in backlog.json")
    if story["status"] != "complete":
        raise ValueError(
            f"Story {storyId} status is '{story['status']}', not complete"
        )

    # Match both naming forms: "US-377.md" (bare) and "US-377-some-slug.md".
    backlogDir = repoRoot / "offices/pm/backlog"
    mdPath = next(
        (
            p
            for p in sorted(backlogDir.glob(f"{storyId}*.md"))
            if p.stem == storyId or p.stem.startswith(f"{storyId}-")
        ),
        None,
    )
    archiveDir = repoRoot / "offices/pm/archive/completed-work-products"

    if dryRun:
        if mdPath:
            print(f"[dry-run] would move {mdPath} -> {archiveDir / mdPath.name}")
        else:
            print(f"[dry-run] would SYNTHESIZE {archiveDir / (storyId + '-archived.md')} (no source .md)")
        print(f"[dry-run] would remove {storyId} from backlog.json")
        return

    archiveDir.mkdir(parents=True, exist_ok=True)
    if mdPath:
        mdPath.rename(archiveDir / mdPath.name)
    else:
        # Ghost story: preserve the record by synthesizing an archive .md.
        (archiveDir / f"{storyId}-archived.md").write_text(
            _synthesizeArchiveMd(story), encoding="utf-8"
        )
        print(f"  note: {storyId} had no Story.md -- synthesized an archive record")

    data["stories"] = [s for s in data["stories"] if s["id"] != storyId]
    backlogPath.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: graduate_story.py <US-id> [--dry-run]", file=sys.stderr)
        sys.exit(1)
    dryRun = "--dry-run" in sys.argv
    repoRoot = Path(__file__).resolve().parents[3]
    graduateStory(sys.argv[1], repoRoot=repoRoot, dryRun=dryRun)
    print("Graduation complete.")
