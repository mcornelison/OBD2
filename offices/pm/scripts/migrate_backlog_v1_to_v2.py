"""
File: offices/pm/scripts/migrate_backlog_v1_to_v2.py
Author: Marcus (PM)
Created: 2026-05-27
Purpose: One-time helper to convert v1 backlog.json (deeply-nested
         epics[].features[].stories[]) into a draft v2.0.0 backlog.json
         (4-tier hierarchy with proposed Epic taxonomy from the design
         spec §9.2). PM hand-reviews + corrects the suggested Epic
         parents per item.
"""
import json
import sys
from datetime import date
from pathlib import Path


# Initial Epic taxonomy per spec §9.2
EPICS_INITIAL = [
    {
        "id": "E-001",
        "title": "UI/UX Polish",
        "description": "Pi-side display: boot/shutdown splash, status surfaces, touch UI.",
        "keywords": ["splash", "display", "touch", "ui", "ux"],
    },
    {
        "id": "E-002",
        "title": "Data Pipeline & Analytics",
        "description": "Server analytics, schema normalization, drive detection.",
        "keywords": ["drive", "analytics", "schema", "server", "sync", "data"],
    },
    {
        "id": "E-003",
        "title": "Tuning Intelligence",
        "description": "Thresholds, GEMs, Spool layer, ECMLink integration.",
        "keywords": ["threshold", "gem", "knock", "ecmlink", "fuel", "tuning"],
    },
    {
        "id": "E-004",
        "title": "Infrastructure & Deploy",
        "description": "Pi pipeline, sync, deploy, hostnames, alerts.",
        "keywords": ["deploy", "sync", "pi", "hostname", "infrastructure"],
    },
    {
        "id": "E-005",
        "title": "Reports & CLI",
        "description": "Export, Ollama, CLI tooling.",
        "keywords": ["export", "report", "cli", "ollama"],
    },
    {
        "id": "E-OPS",
        "title": "Operational Hygiene",
        "description": "Bugs / tech debt / housekeeping without a domain Feature home.",
        "keywords": [],
    },
]


def _suggestEpicParent(itemTitle: str, itemSlug: str) -> str:
    """Return best-guess E-XXX id by keyword match against Epic taxonomy.

    Args:
        itemTitle: Human-readable title of the backlog item.
        itemSlug: ID string (e.g. "b-103") used as supplemental text.

    Returns:
        Epic id string (e.g. "E-001"). Defaults to "E-OPS" when no keyword hits.
    """
    text = (itemTitle + " " + itemSlug).lower()
    best, bestHits = "E-OPS", 0
    for epic in EPICS_INITIAL:
        hits = sum(1 for kw in epic["keywords"] if kw in text)
        if hits > bestHits:
            best, bestHits = epic["id"], hits
    return best


def _flattenV1Items(v1: dict) -> list[dict]:
    """Flatten all B-XXX feature items from v1's nested epic/feature structure.

    In v1, the "features" list inside each epic contains B-XXX items directly
    (the features ARE the backlog items, not containers of items).

    Args:
        v1: Parsed v1 backlog dict.

    Returns:
        Flat list of all backlog item dicts that carry a B- prefixed id.
    """
    out: list[dict] = []

    # Top-level items list (alternate v1 shapes)
    if "items" in v1 and isinstance(v1["items"], list):
        out.extend(v1["items"])

    for epic in v1.get("epics", []):
        if not isinstance(epic, dict):
            continue
        # Some v1 shapes nest items directly on the epic
        out.extend(epic.get("items", []))
        for feature in epic.get("features", []):
            if not isinstance(feature, dict):
                continue
            # Sub-items if present (forward-compat with any intermediate shape)
            out.extend(feature.get("items", []))
            # In standard v1, the feature itself IS the B-XXX item
            if feature.get("id", "").startswith("B-"):
                out.append(feature)

    return out


def _mapStatusToV2Feature(v1Status: str) -> str:
    """Map v1 status string to v2 Feature status enum value.

    Args:
        v1Status: Status string from v1 backlog item.

    Returns:
        Corresponding v2 Feature status string.
    """
    mapping: dict[str, str] = {
        "pending": "pending",
        "groomed": "groomed",
        "in_progress": "active",
        "in-progress": "active",
        "in_sprint": "in-sprint",
        "blocked": "groomed",
        "complete": "complete",
    }
    return mapping.get(v1Status, "pending")


def migrate(v1Path: Path, v2Path: Path) -> None:
    """Generate a draft v2 backlog.json from a v1 backlog.json.

    Reads every B-XXX feature item from the v1 nested structure, renames each
    to F-XXX with a renamedFrom audit field, suggests an Epic parent via
    keyword matching, and writes a draft v2.0.0 backlog.json. The input file
    is never modified.

    Args:
        v1Path: Path to existing v1 backlog.json (read-only).
        v2Path: Path where draft v2 backlog.json should be written.
    """
    v1 = json.loads(v1Path.read_text(encoding="utf-8"))
    today = date.today().isoformat()

    epics = [
        {
            "id": e["id"],
            "title": e["title"],
            "description": e["description"],
            "status": "active",
            "createdAt": today,
            "updatedAt": today,
        }
        for e in EPICS_INITIAL
    ]

    features: list[dict] = []
    stories: list[dict] = []

    for item in _flattenV1Items(v1):
        bId = item.get("id") or item.get("backlogId") or ""
        if not bId.startswith("B-"):
            continue
        suffix = bId.split("-", 1)[1]
        fId = "F-" + suffix
        parentEpic = _suggestEpicParent(item.get("title", ""), bId.lower())
        features.append(
            {
                "id": fId,
                "parent": parentEpic,
                "title": item.get("title", "(unknown)"),
                "description": (
                    item.get("description", "") or item.get("summary", "") or ""
                )[:280],
                "status": _mapStatusToV2Feature(item.get("status", "pending")),
                "renamedFrom": bId,
                "createdAt": today,
                "updatedAt": today,
            }
        )

    # Compute counters: next available id beyond any already-present value
    numericEpicIds = [
        int(e["id"].split("-")[1])
        for e in epics
        if e["id"].split("-")[1].isdigit()
    ]
    numericFeatureIds = [
        int(f["id"].split("-")[1])
        for f in features
        if f["id"].split("-")[1].isdigit()
    ]
    counters = {
        "epic": (max(numericEpicIds, default=5) + 1),
        "feature": (max(numericFeatureIds, default=109) + 1),
        "story": 359,
    }

    v2 = {
        "schemaVersion": "2.0.0",
        "lastUpdated": today,
        "updatedBy": "migrate_backlog_v1_to_v2.py (DRAFT -- PM hand-review owed)",
        "counters": counters,
        "epics": epics,
        "features": features,
        "stories": stories,
    }
    v2Path.write_text(json.dumps(v2, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: migrate_backlog_v1_to_v2.py <v1.json> <v2-out.json>",
            file=sys.stderr,
        )
        sys.exit(1)
    migrate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Drafted v2 backlog at {sys.argv[2]} -- PM hand-review owed.")
