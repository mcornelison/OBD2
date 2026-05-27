"""
File: offices/pm/scripts/graduate_story.py
Purpose: Move a completed Story/Feature/Epic out of the active backlog
         into offices/pm/archive/completed-work-products/. Removes from
         backlog.json. Refuses if status != 'complete'.
"""
import json
from pathlib import Path


def graduateStory(storyId: str, repoRoot: Path, dryRun: bool = False) -> None:
    """
    Graduate a completed Story from the active backlog to the archive.

    Args:
        storyId: ID like 'US-359'.
        repoRoot: Path containing offices/pm/backlog.json and offices/pm/backlog/.
        dryRun: If True, print intended actions without executing.

    Raises:
        ValueError: If the story is not found, its status is not 'complete',
                    or its MD file is missing.
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

    mdPath = next(
        (p for p in (repoRoot / "offices/pm/backlog").glob(f"{storyId}-*.md")), None
    )
    if not mdPath:
        raise ValueError(
            f"Story {storyId}: no MD file found at offices/pm/backlog/{storyId}-*.md"
        )

    archiveDir = repoRoot / "offices/pm/archive/completed-work-products"
    archiveDir.mkdir(parents=True, exist_ok=True)
    targetPath = archiveDir / mdPath.name

    if dryRun:
        print(f"[dry-run] would move {mdPath} -> {targetPath}")
        print(f"[dry-run] would remove {storyId} from backlog.json")
        return

    mdPath.rename(targetPath)
    data["stories"] = [s for s in data["stories"] if s["id"] != storyId]
    backlogPath.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: graduate_story.py <US-id> [--dry-run]", file=sys.stderr)
        sys.exit(1)
    dryRun = "--dry-run" in sys.argv
    repoRoot = Path(__file__).resolve().parents[3]
    graduateStory(sys.argv[1], repoRoot=repoRoot, dryRun=dryRun)
    print("Graduation complete.")
