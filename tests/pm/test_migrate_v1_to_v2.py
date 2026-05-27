"""Tests for v1 -> v2 backlog migration helper."""
import json
import shutil
from pathlib import Path
from offices.pm.scripts.migrate_backlog_v1_to_v2 import migrate

FIXTURES = Path(__file__).parent / "fixtures"


def test_migrate_v1_produces_v2_shape(tmp_path):
    shutil.copy(FIXTURES / "v1_backlog_sample.json", tmp_path / "v1.json")
    outPath = tmp_path / "v2.json"
    migrate(tmp_path / "v1.json", outPath)
    v2 = json.loads(outPath.read_text())
    assert v2["schemaVersion"] == "2.0.0"
    assert "counters" in v2
    assert "epics" in v2 and "features" in v2 and "stories" in v2


def test_migrate_assignsEpicParentsForKnownBitems(tmp_path):
    """Migration should suggest an epic parent for B-XXX based on slug match."""
    shutil.copy(FIXTURES / "v1_backlog_sample.json", tmp_path / "v1.json")
    outPath = tmp_path / "v2.json"
    migrate(tmp_path / "v1.json", outPath)
    v2 = json.loads(outPath.read_text())
    # every Feature has a parent that exists in epics
    epicIds = {e["id"] for e in v2["epics"]}
    for f in v2["features"]:
        assert f["parent"] in epicIds, f"Feature {f['id']} has unknown parent {f['parent']}"


def test_migrate_renamesBitemsToFitems(tmp_path):
    """B-XXX becomes F-XXX with renamedFrom audit field set."""
    shutil.copy(FIXTURES / "v1_backlog_sample.json", tmp_path / "v1.json")
    outPath = tmp_path / "v2.json"
    migrate(tmp_path / "v1.json", outPath)
    v2 = json.loads(outPath.read_text())
    fIds = {f["id"] for f in v2["features"]}
    assert "F-103" in fIds
    assert "F-076" in fIds
    # renamedFrom audit
    f103 = next(f for f in v2["features"] if f["id"] == "F-103")
    assert f103["renamedFrom"] == "B-103"


def test_migrate_keywordMatchAssignsUiToE001(tmp_path):
    """A 'splash' item should match E-001 UI/UX keywords."""
    shutil.copy(FIXTURES / "v1_backlog_sample.json", tmp_path / "v1.json")
    outPath = tmp_path / "v2.json"
    migrate(tmp_path / "v1.json", outPath)
    v2 = json.loads(outPath.read_text())
    f103 = next(f for f in v2["features"] if f["id"] == "F-103")
    assert f103["parent"] == "E-001"  # 'splash' keyword matches UI/UX epic


def test_migrate_keywordMatchAssignsSchemaToE002(tmp_path):
    """A 'schema' item should match E-002 Data Pipeline & Analytics."""
    shutil.copy(FIXTURES / "v1_backlog_sample.json", tmp_path / "v1.json")
    outPath = tmp_path / "v2.json"
    migrate(tmp_path / "v1.json", outPath)
    v2 = json.loads(outPath.read_text())
    f076 = next(f for f in v2["features"] if f["id"] == "F-076")
    assert f076["parent"] == "E-002"  # 'schema' keyword matches Data Pipeline epic


def test_migrate_preservesDeclinedStatus(tmp_path):
    """A v1 'declined' item must NOT become 'pending' -- silent re-grooming."""
    v1 = {
        "$schema": "Eclipse OBD-II PMO Backlog v1.0",
        "lastUpdated": "2026-05-27",
        "epics": [{
            "id": "E-99", "name": "T", "phase": 1, "status": "complete", "description": "t",
            "features": [{
                "id": "B-006",
                "title": "Migrate from camelCase to snake_case",
                "priority": "low",
                "status": "declined",
                "size": "L",
                "category": "refactor",
                "dependencies": [],
                "stories": []
            }]
        }]
    }
    v1Path = tmp_path / "v1.json"
    v1Path.write_text(json.dumps(v1), encoding="utf-8")
    outPath = tmp_path / "v2.json"
    migrate(v1Path, outPath)
    v2 = json.loads(outPath.read_text())
    f006 = next(f for f in v2["features"] if f["id"] == "F-006")
    assert f006["status"] == "declined", "declined status must round-trip to v2"


def test_suggestEpicParent_doesNotFalseMatchUiInRequirements():
    """'ui' as substring of 'requirements' must NOT pull item to E-001 UI/UX."""
    from offices.pm.scripts.migrate_backlog_v1_to_v2 import _suggestEpicParent
    # title with only non-Epic-matching words but containing the substring 'ui'
    result = _suggestEpicParent("OBD2 Patterns and Requirements Reference", "b-011")
    assert result == "E-OPS", "word-boundary match must not catch 'ui' inside 'requirements'"
