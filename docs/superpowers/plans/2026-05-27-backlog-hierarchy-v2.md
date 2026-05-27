# Backlog Hierarchy v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `offices/pm/backlog.json` + per-tier MD files + PM tooling to the 4-tier hierarchy (Epic → Feature → Story → Task) defined in `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md`. Re-tier ~10 active B-XXX items + ~30 V0.28+ candidates; fold I/BL/TD intake; leave 35 completed B-XXX legacy archive untouched.

**Architecture:** Hybrid JSON-index + per-tier MD files. `backlog.json` (schemaVersion 2.0.0) holds structural tree + status cache. Per-tier MD files (`E-XXX.md` / `F-XXX.md` / `US-XXX.md`) hold prose contract with YAML frontmatter mirroring JSON structural fields. PRD is single-file MD (`prd-V<X>.<Y>.<Z>-sprint-<N>.md`) with YAML frontmatter for tooling-needed fields. Sprint.json schema gets minor additions (parent/epicId/type/validationCriteria); Ralph contract is otherwise unchanged.

**Tech Stack:** Python 3.11+ (existing PM tooling), `pytest` for tests, `python-frontmatter` library for YAML+MD parsing, standard `json`/`pathlib`/`shutil` for file ops. Spec at `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` is the contract of record.

---

## Scope

In scope:
- New `backlog_schema.py` module (Python types + validator for v2.0.0 JSON)
- Update `pm_status.py` to read v2.0.0 + render tree view + auto-rollup
- Update `sprint_lint.py` with new contract rules (typed Stories, required fields, JSON↔MD sync)
- Update `bump_passed_statuses.py` for new status enum
- NEW `prd_to_sprint.py` (mechanical PRD-MD → sprint.json conversion)
- NEW `graduate_story.py` (move completed items to archive)
- NEW `migrate_backlog_v1_to_v2.py` (one-time helper)
- New templates: `_template-epic.md`, `_template-feature.md`, `_template-story.md`, `_template-prd.md`
- 6 Epic MD files (E-001..E-005 + E-OPS)
- Migration execution (re-tier ~10 active + ~30 V0.28+ candidates; fold open I/BL/TD)
- PM Rules amendments (Rule 5 rewrite + new Rules 11+12) in `offices/pm/projectManager.md`

Out of scope (separate efforts):
- dev/main branching workflow (CIO directive #1; needs its own spec)
- Sprint contract template update for validation-criteria-upfront (CIO directive #2; needs its own spec change)
- Migration of 35 completed B-XXX items (legacy archive unchanged)

---

## File Structure

### New files

| Path | Purpose |
|---|---|
| `offices/pm/scripts/backlog_schema.py` | Schema types + validator for backlog.json v2.0.0 |
| `offices/pm/scripts/prd_to_sprint.py` | Convert PRD MD → sprint.json |
| `offices/pm/scripts/graduate_story.py` | Move completed items to archive/completed-work-products |
| `offices/pm/scripts/migrate_backlog_v1_to_v2.py` | One-time migration helper |
| `offices/pm/backlog/_template-epic.md` | Epic MD template |
| `offices/pm/backlog/_template-feature.md` | Feature MD template |
| `offices/pm/backlog/_template-story.md` | Story MD template |
| `offices/pm/prds/_template-prd.md` | PRD MD template |
| `offices/pm/backlog/E-001-uiux-polish.md` | Epic file |
| `offices/pm/backlog/E-002-data-pipeline-analytics.md` | Epic file |
| `offices/pm/backlog/E-003-tuning-intelligence.md` | Epic file |
| `offices/pm/backlog/E-004-infrastructure-deploy.md` | Epic file |
| `offices/pm/backlog/E-005-reports-cli.md` | Epic file |
| `offices/pm/backlog/E-OPS-operational-hygiene.md` | Epic file |
| `offices/pm/archive/completed-work-products/.gitkeep` | Archive dir marker |
| `offices/pm/archive/intake-records/.gitkeep` | Folded intake archive marker |
| `tests/pm/test_backlog_schema.py` | Schema validator tests |
| `tests/pm/test_pm_status_v2.py` | pm_status v2 tests |
| `tests/pm/test_sprint_lint_v2.py` | sprint_lint v2 rules tests |
| `tests/pm/test_prd_to_sprint.py` | PRD conversion tests |
| `tests/pm/test_graduate_story.py` | Graduation tests |
| `tests/pm/test_migrate_v1_to_v2.py` | Migration helper tests |
| `tests/pm/fixtures/v2_backlog_sample.json` | Reference fixture for v2 schema |
| `tests/pm/fixtures/v1_backlog_sample.json` | Reference fixture for v1 (pre-migration) |

### Modified files

| Path | What changes |
|---|---|
| `offices/pm/scripts/pm_status.py` | Read schema v2.0.0; render Epic→Feature→Story tree; auto-rollup statuses; report multi-PRD + sprint state |
| `offices/pm/scripts/sprint_lint.py` | Add backlog-v2 rules: typed Story enum, required fields per tier, JSON↔MD frontmatter sync check, no-orphan check, PRD shape validation |
| `offices/pm/scripts/bump_passed_statuses.py` | Recognize new status enum (`sprint-ready`, `in-progress`, `passed`, `complete`) |
| `offices/pm/projectManager.md` | Rule 5 rewrite + new Rules 11 + 12 |
| `offices/pm/backlog.json` | Migrate to schemaVersion 2.0.0 (during Task 12) |
| (each active B-XXX file in `offices/pm/backlog/`) | Renamed to F-XXX with new frontmatter + body restructured per Feature.md template |

### Files explicitly not touched

- `offices/ralph/sprint.json` (Ralph's contract; sprint.json schema additions land when first V0.28.0 sprint spins, not in this migration)
- `offices/ralph/prompt.md` (Ralph instructions; unchanged)
- 35 completed B-XXX files in `offices/pm/archive/` (legacy shape preserved)

---

## Execution order

Tasks 1–9 build TOOLING (TDD, reversible). Tasks 10–14 execute DATA MIGRATION (one-time, more imperative). Task 15 amends PM Rules. Task 16 final validation.

Run Tasks 1–9 strictly in order (later tasks depend on earlier types/modules). Tasks 10–13 also strict-order. Task 14 (PM Rules) can run any time after Task 1.

---

### Task 1: Backlog schema module + validator

**Files:**
- Create: `offices/pm/scripts/backlog_schema.py`
- Create: `tests/pm/test_backlog_schema.py`
- Create: `tests/pm/fixtures/v2_backlog_sample.json`

- [ ] **Step 1.1: Write the fixture file `tests/pm/fixtures/v2_backlog_sample.json`**

```json
{
  "schemaVersion": "2.0.0",
  "lastUpdated": "2026-05-27",
  "updatedBy": "test fixture",
  "counters": {"epic": 2, "feature": 110, "story": 360},
  "epics": [
    {
      "id": "E-001",
      "title": "Test Epic",
      "description": "Fixture epic for tests.",
      "status": "active",
      "createdAt": "2026-05-27",
      "updatedAt": "2026-05-27"
    }
  ],
  "features": [
    {
      "id": "F-103",
      "parent": "E-001",
      "title": "Test Feature",
      "description": "Fixture feature.",
      "status": "groomed",
      "renamedFrom": "B-103",
      "createdAt": "2026-05-26",
      "updatedAt": "2026-05-27"
    }
  ],
  "stories": [
    {
      "id": "US-359",
      "parent": "F-103",
      "title": "Test Story",
      "type": "normal",
      "size": "M",
      "status": "groomed",
      "goal": "As tester, I want a fixture so tests can run.",
      "definitionOfDone": ["fixture parses", "validator passes"],
      "conditionalOutcomes": ["if validator fails → test fails"],
      "validationCriteria": [{"action": "load fixture", "outcome": "validator returns OK"}],
      "deps": [],
      "sourceRefs": [],
      "tasks": [],
      "createdAt": "2026-05-27",
      "updatedAt": "2026-05-27"
    }
  ]
}
```

- [ ] **Step 1.2: Write the failing tests `tests/pm/test_backlog_schema.py`**

```python
"""Tests for backlog_schema validator (v2.0.0)."""
from pathlib import Path
import json
import pytest
from offices.pm.scripts.backlog_schema import validateBacklog, BacklogValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def test_validateBacklog_validFixture_returnsBacklog():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    result = validateBacklog(data)
    assert result["schemaVersion"] == "2.0.0"
    assert len(result["epics"]) == 1
    assert len(result["stories"]) == 1


def test_validateBacklog_missingSchemaVersion_raises():
    data = {"epics": [], "features": [], "stories": []}
    with pytest.raises(BacklogValidationError, match="schemaVersion"):
        validateBacklog(data)


def test_validateBacklog_storyMissingValidationCriteria_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    del data["stories"][0]["validationCriteria"]
    with pytest.raises(BacklogValidationError, match="validationCriteria"):
        validateBacklog(data)


def test_validateBacklog_invalidStoryType_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["stories"][0]["type"] = "bogus-type"
    with pytest.raises(BacklogValidationError, match="type"):
        validateBacklog(data)


def test_validateBacklog_orphanFeature_raises():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["features"][0]["parent"] = "E-999"
    with pytest.raises(BacklogValidationError, match="orphan"):
        validateBacklog(data)


def test_validateBacklog_validationCriteriaShape_actionOutcomePairs():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    data["stories"][0]["validationCriteria"] = [{"foo": "bar"}]
    with pytest.raises(BacklogValidationError, match="validationCriteria"):
        validateBacklog(data)
```

- [ ] **Step 1.3: Run tests to verify they fail**

Run: `pytest tests/pm/test_backlog_schema.py -v`
Expected: 6 tests FAIL with `ImportError: cannot import name 'validateBacklog'`

- [ ] **Step 1.4: Implement `offices/pm/scripts/backlog_schema.py`**

```python
"""
File: offices/pm/scripts/backlog_schema.py
Purpose: Schema types + validator for backlog.json v2.0.0.
         Enforces 4-tier hierarchy invariants: no orphans, valid types,
         required fields per tier, validationCriteria shape.
"""
from typing import Any

VALID_STORY_TYPES = {"normal", "issue", "blocker", "tech-debt",
                     "research", "housekeeping", "security"}
VALID_STORY_SIZES = {"XS", "S", "M", "L"}
VALID_EPIC_STATUSES = {"pending", "active", "complete"}
VALID_FEATURE_STATUSES = {"pending", "groomed", "in-sprint", "active", "complete"}
VALID_STORY_STATUSES = {"pending", "groomed", "in-prd", "sprint-ready",
                        "in-progress", "blocked", "passed", "complete"}
VALID_TASK_STATUSES = {"open", "done"}

REQUIRED_STORY_FIELDS = {
    "id", "parent", "title", "type", "size", "status",
    "goal", "definitionOfDone", "conditionalOutcomes", "validationCriteria",
    "createdAt", "updatedAt",
}


class BacklogValidationError(ValueError):
    """Raised when backlog.json fails v2.0.0 schema validation."""


def validateBacklog(data: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a parsed backlog.json against schema v2.0.0.

    Returns the input dict if valid. Raises BacklogValidationError otherwise.
    """
    if data.get("schemaVersion") != "2.0.0":
        raise BacklogValidationError(
            f"schemaVersion must be '2.0.0', got {data.get('schemaVersion')!r}"
        )

    epicIds = {e["id"] for e in data.get("epics", [])}
    featureIds = {f["id"] for f in data.get("features", [])}

    for epic in data.get("epics", []):
        if epic.get("status") not in VALID_EPIC_STATUSES:
            raise BacklogValidationError(
                f"Epic {epic.get('id')}: invalid status {epic.get('status')!r}"
            )

    for feature in data.get("features", []):
        if feature.get("parent") not in epicIds:
            raise BacklogValidationError(
                f"Feature {feature.get('id')}: orphan -- parent {feature.get('parent')!r} not in epics"
            )
        if feature.get("status") not in VALID_FEATURE_STATUSES:
            raise BacklogValidationError(
                f"Feature {feature.get('id')}: invalid status {feature.get('status')!r}"
            )

    for story in data.get("stories", []):
        missing = REQUIRED_STORY_FIELDS - set(story.keys())
        if missing:
            raise BacklogValidationError(
                f"Story {story.get('id')}: missing required fields {missing}"
            )
        if story["parent"] not in featureIds:
            raise BacklogValidationError(
                f"Story {story['id']}: orphan -- parent {story['parent']!r} not in features"
            )
        if story["type"] not in VALID_STORY_TYPES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid type {story['type']!r}"
            )
        if story["size"] not in VALID_STORY_SIZES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid size {story['size']!r}"
            )
        if story["status"] not in VALID_STORY_STATUSES:
            raise BacklogValidationError(
                f"Story {story['id']}: invalid status {story['status']!r}"
            )
        _validateValidationCriteria(story)
        _validateTasks(story)

    return data


def _validateValidationCriteria(story: dict[str, Any]) -> None:
    vc = story.get("validationCriteria")
    if not isinstance(vc, list):
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be a list"
        )
    for i, item in enumerate(vc):
        if not isinstance(item, dict) or set(item.keys()) != {"action", "outcome"}:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] must have keys {{action, outcome}}, "
                f"got {item!r}"
            )


def _validateTasks(story: dict[str, Any]) -> None:
    tasks = story.get("tasks", [])
    if not isinstance(tasks, list):
        raise BacklogValidationError(
            f"Story {story['id']}: tasks must be a list"
        )
    for task in tasks:
        if task.get("status") not in VALID_TASK_STATUSES:
            raise BacklogValidationError(
                f"Story {story['id']} task {task.get('id')!r}: invalid status {task.get('status')!r}"
            )
```

- [ ] **Step 1.5: Run tests to verify pass**

Run: `pytest tests/pm/test_backlog_schema.py -v`
Expected: 6 tests PASS.

- [ ] **Step 1.6: Commit**

```bash
git add offices/pm/scripts/backlog_schema.py tests/pm/test_backlog_schema.py tests/pm/fixtures/v2_backlog_sample.json
git commit -m "feat(pm-tooling): add backlog_schema v2.0.0 validator -- 4-tier hierarchy invariants"
```

---

### Task 2: Update `pm_status.py` for v2.0.0

**Files:**
- Modify: `offices/pm/scripts/pm_status.py`
- Create: `tests/pm/test_pm_status_v2.py`

- [ ] **Step 2.1: Read current `pm_status.py` to understand existing structure**

Run: `cat offices/pm/scripts/pm_status.py | head -60`
Expected: see the existing main() + print logic.

- [ ] **Step 2.2: Write failing tests `tests/pm/test_pm_status_v2.py`**

```python
"""Tests for pm_status v2 -- 4-tier tree rendering + status rollup."""
import json
from pathlib import Path
from offices.pm.scripts.pm_status import renderTree, computeRollups

FIXTURES = Path(__file__).parent / "fixtures"


def test_computeRollups_emptyEpicWithNoFeatures_status_pending():
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "pending", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [],
        "stories": [],
    }
    rolled = computeRollups(data)
    assert rolled["epics"][0]["status"] == "pending"


def test_computeRollups_epicWithActiveFeature_status_active():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    # the fixture has F-103 status=groomed under E-001
    rolled = computeRollups(data)
    epicStatus = next(e["status"] for e in rolled["epics"] if e["id"] == "E-001")
    # at least one feature groomed → epic is active
    assert epicStatus == "active"


def test_computeRollups_featureWithAllStoriesComplete_status_complete():
    data = {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-001", "title": "T", "description": "d",
                   "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                      "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
        "stories": [
            {"id": "US-1", "parent": "F-1", "title": "T", "type": "normal", "size": "S",
             "status": "complete", "goal": "g", "definitionOfDone": ["d"],
             "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
             "deps": [], "sourceRefs": [], "tasks": [],
             "createdAt": "2026-05-27", "updatedAt": "2026-05-27"},
        ],
    }
    rolled = computeRollups(data)
    assert rolled["features"][0]["status"] == "complete"
    assert rolled["epics"][0]["status"] == "complete"


def test_renderTree_outputContainsEpicFeatureStory():
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text())
    out = renderTree(data)
    assert "E-001" in out
    assert "F-103" in out
    assert "US-359" in out
```

- [ ] **Step 2.3: Run tests to verify they fail**

Run: `pytest tests/pm/test_pm_status_v2.py -v`
Expected: 4 tests FAIL with ImportError.

- [ ] **Step 2.4: Add `computeRollups` and `renderTree` to `pm_status.py`**

Add these functions to `offices/pm/scripts/pm_status.py` (preserve existing `main()` for backward compat; update `main()` to detect schemaVersion and route):

```python
def computeRollups(data: dict) -> dict:
    """
    Recompute Epic + Feature statuses from their children.
    Writes the cached value into the data dict and returns it.
    Caller is responsible for persisting if desired.
    """
    storiesByFeature: dict[str, list[dict]] = {}
    for s in data.get("stories", []):
        storiesByFeature.setdefault(s["parent"], []).append(s)

    featuresByEpic: dict[str, list[dict]] = {}
    for f in data.get("features", []):
        children = storiesByFeature.get(f["id"], [])
        f["status"] = _rollupFeatureStatus(children)
        featuresByEpic.setdefault(f["parent"], []).append(f)

    for e in data.get("epics", []):
        children = featuresByEpic.get(e["id"], [])
        e["status"] = _rollupEpicStatus(children)

    return data


def _rollupFeatureStatus(stories: list[dict]) -> str:
    if not stories:
        return "pending"
    statuses = {s["status"] for s in stories}
    if statuses == {"complete"}:
        return "complete"
    if "in-progress" in statuses or "sprint-ready" in statuses or "in-prd" in statuses:
        return "active"
    if "groomed" in statuses or "passed" in statuses:
        return "groomed"
    return "pending"


def _rollupEpicStatus(features: list[dict]) -> str:
    if not features:
        return "pending"
    statuses = {f["status"] for f in features}
    if statuses == {"complete"}:
        return "complete"
    if statuses == {"pending"}:
        return "pending"
    return "active"


def renderTree(data: dict) -> str:
    """Render Epic → Feature → Story tree as plain text."""
    storiesByFeature: dict[str, list[dict]] = {}
    for s in data.get("stories", []):
        storiesByFeature.setdefault(s["parent"], []).append(s)

    featuresByEpic: dict[str, list[dict]] = {}
    for f in data.get("features", []):
        featuresByEpic.setdefault(f["parent"], []).append(f)

    lines = []
    for e in data.get("epics", []):
        lines.append(f"{e['id']:<8} [{e['status']:<8}] {e['title']}")
        for f in featuresByEpic.get(e["id"], []):
            lines.append(f"  {f['id']:<8} [{f['status']:<8}] {f['title']}")
            for s in storiesByFeature.get(f["id"], []):
                lines.append(f"    {s['id']:<8} [{s['status']:<12}] ({s['type']}, {s['size']}) {s['title']}")
    return "\n".join(lines)
```

Then update the existing `main()` to read schemaVersion and either run v1 (legacy) or v2 (new) display path:

```python
def main():
    backlogPath = REPO_ROOT / "offices" / "pm" / "backlog.json"
    data = json.loads(backlogPath.read_text())
    if data.get("schemaVersion") == "2.0.0":
        data = computeRollups(data)
        # persist rolled-up statuses back to disk (cache writeback)
        backlogPath.write_text(json.dumps(data, indent=2) + "\n")
        print("=== BACKLOG v2.0.0 ===")
        print(renderTree(data))
        print()
        _renderPrdsAndSprint()
    else:
        _renderV1Legacy(data)  # existing code, extracted into helper
```

(Extract the previous `main()` body into `_renderV1Legacy(data)`.)

- [ ] **Step 2.5: Run tests to verify pass**

Run: `pytest tests/pm/test_pm_status_v2.py -v`
Expected: 4 tests PASS.

- [ ] **Step 2.6: Smoke-test against current v1 backlog (no regression)**

Run: `python offices/pm/scripts/pm_status.py`
Expected: legacy v1 output renders unchanged (since current backlog.json is still v1).

- [ ] **Step 2.7: Commit**

```bash
git add offices/pm/scripts/pm_status.py tests/pm/test_pm_status_v2.py
git commit -m "feat(pm-tooling): pm_status v2 -- tree view + status rollup + v1/v2 dispatch"
```

---

### Task 3: Update `sprint_lint.py` with v2 rules

**Files:**
- Modify: `offices/pm/scripts/sprint_lint.py`
- Create: `tests/pm/test_sprint_lint_v2.py`

- [ ] **Step 3.1: Write failing tests `tests/pm/test_sprint_lint_v2.py`**

```python
"""Tests for sprint_lint v2 backlog rules."""
import json
import tempfile
from pathlib import Path
from offices.pm.scripts.sprint_lint import lintBacklog, LintError, LintWarning


def _withTempBacklog(data: dict):
    """Return a Path with the JSON written; caller cleans up."""
    fp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, fp)
    fp.close()
    return Path(fp.name)


VALID_FIXTURE = {
    "schemaVersion": "2.0.0",
    "lastUpdated": "2026-05-27",
    "updatedBy": "test",
    "counters": {"epic": 2, "feature": 110, "story": 360},
    "epics": [{"id": "E-001", "title": "T", "description": "d",
               "status": "active", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
    "features": [{"id": "F-1", "parent": "E-001", "title": "T", "description": "d",
                  "status": "groomed", "createdAt": "2026-05-27", "updatedAt": "2026-05-27"}],
    "stories": [{
        "id": "US-1", "parent": "F-1", "title": "T", "type": "normal", "size": "S",
        "status": "groomed", "goal": "g", "definitionOfDone": ["d"],
        "conditionalOutcomes": ["c"], "validationCriteria": [{"action": "a", "outcome": "o"}],
        "deps": [], "sourceRefs": [], "tasks": [],
        "createdAt": "2026-05-27", "updatedAt": "2026-05-27"
    }],
}


def test_lintBacklog_valid_returnsNoErrors():
    path = _withTempBacklog(VALID_FIXTURE)
    errors, warnings = lintBacklog(path)
    assert errors == []


def test_lintBacklog_invalidStoryType_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["stories"][0]["type"] = "bogus"
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("type" in e.message for e in errors)


def test_lintBacklog_storyMissingValidationCriteria_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    del bad["stories"][0]["validationCriteria"]
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("validationCriteria" in e.message for e in errors)


def test_lintBacklog_orphanStory_returnsError():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["stories"][0]["parent"] = "F-999"
    path = _withTempBacklog(bad)
    errors, _ = lintBacklog(path)
    assert any("orphan" in e.message.lower() for e in errors)


def test_lintBacklog_unknownEpicStatusHandEdit_returnsWarning():
    bad = json.loads(json.dumps(VALID_FIXTURE))
    bad["epics"][0]["status"] = "complete"  # cache mismatch -- only 1 groomed feature
    path = _withTempBacklog(bad)
    _, warnings = lintBacklog(path)
    assert any("rollup" in w.message.lower() or "cache" in w.message.lower() for w in warnings)
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/pm/test_sprint_lint_v2.py -v`
Expected: 5 tests FAIL with ImportError.

- [ ] **Step 3.3: Add `lintBacklog` to `sprint_lint.py`**

Add to `offices/pm/scripts/sprint_lint.py`:

```python
from dataclasses import dataclass
from offices.pm.scripts.backlog_schema import validateBacklog, BacklogValidationError
from offices.pm.scripts.pm_status import computeRollups


@dataclass
class LintError:
    message: str


@dataclass
class LintWarning:
    message: str


def lintBacklog(path):
    """
    Lint a backlog.json v2.0.0 file. Returns (errors, warnings).
    Errors are validation failures; warnings are rollup-cache mismatches.
    """
    import json as _json
    data = _json.loads(path.read_text())
    errors: list[LintError] = []
    warnings: list[LintWarning] = []

    try:
        validateBacklog(data)
    except BacklogValidationError as e:
        errors.append(LintError(message=str(e)))
        return errors, warnings  # short-circuit on validation failure

    # rollup-cache check: recompute and compare to stored values
    stored_epic_statuses = {e["id"]: e["status"] for e in data["epics"]}
    stored_feature_statuses = {f["id"]: f["status"] for f in data["features"]}
    rolled = computeRollups({**data, "epics": [dict(e) for e in data["epics"]],
                             "features": [dict(f) for f in data["features"]]})
    for e in rolled["epics"]:
        if e["status"] != stored_epic_statuses[e["id"]]:
            warnings.append(LintWarning(
                message=f"Epic {e['id']} rollup cache stale: "
                        f"stored={stored_epic_statuses[e['id']]!r} computed={e['status']!r}"
            ))
    for f in rolled["features"]:
        if f["status"] != stored_feature_statuses[f["id"]]:
            warnings.append(LintWarning(
                message=f"Feature {f['id']} rollup cache stale: "
                        f"stored={stored_feature_statuses[f['id']]!r} computed={f['status']!r}"
            ))

    return errors, warnings
```

- [ ] **Step 3.4: Run tests to verify pass**

Run: `pytest tests/pm/test_sprint_lint_v2.py -v`
Expected: 5 tests PASS.

- [ ] **Step 3.5: Wire `lintBacklog` into sprint_lint main**

In `sprint_lint.py` `main()`, add a `--backlog` mode that calls `lintBacklog(REPO_ROOT / "offices/pm/backlog.json")` and prints errors + warnings. Keep existing sprint-contract lint path intact (it operates on `sprint.json`).

- [ ] **Step 3.6: Commit**

```bash
git add offices/pm/scripts/sprint_lint.py tests/pm/test_sprint_lint_v2.py
git commit -m "feat(pm-tooling): sprint_lint v2 backlog rules -- type enum + validationCriteria + orphan + rollup cache check"
```

---

### Task 4: `bump_passed_statuses.py` status-enum update

**Files:**
- Modify: `offices/pm/scripts/bump_passed_statuses.py`

- [ ] **Step 4.1: Read current `bump_passed_statuses.py`**

Run: `cat offices/pm/scripts/bump_passed_statuses.py | head -40`
Expected: see how it handles the current status enum (pending → passed).

- [ ] **Step 4.2: Update the recognized status enum**

In `bump_passed_statuses.py`, locate the status-mapping dict/set. Add new statuses to the recognized set:
```python
# old: VALID_TRANSITIONS = {"pending": "passed"}
VALID_TRANSITIONS = {
    "pending": "passed",         # legacy v1 path; kept for back-compat
    "sprint-ready": "in-progress",  # v2: Ralph picks up
    "in-progress": "passed",        # v2: Ralph code-complete
    # 'complete' is set by graduate_story.py, not here
}
```

If the script only operates on sprint.json (Ralph's contract), no other changes needed since sprint.json schema is mostly unchanged. Verify by reading.

- [ ] **Step 4.3: Quick smoke test**

Run: `python offices/pm/scripts/bump_passed_statuses.py --help` (or `--dry-run`).
Expected: runs without error.

- [ ] **Step 4.4: Commit**

```bash
git add offices/pm/scripts/bump_passed_statuses.py
git commit -m "feat(pm-tooling): bump_passed_statuses recognize v2 status enum (sprint-ready / in-progress / passed)"
```

---

### Task 5: NEW `prd_to_sprint.py` (PRD MD → sprint.json conversion)

**Files:**
- Create: `offices/pm/scripts/prd_to_sprint.py`
- Create: `tests/pm/test_prd_to_sprint.py`
- Create: `tests/pm/fixtures/prd_sample.md`

- [ ] **Step 5.1: Write fixture `tests/pm/fixtures/prd_sample.md`**

```markdown
---
sprint: 43
version: V0.28.0
status: sprint-ready
createdAt: 2026-05-27
createdBy: Marcus (PM)
selectedStories: [US-359]
argusReviewRequired: false
convertedAt: null
sprintJsonPath: null
---

# PRD — Sprint 43 (V0.28.0): test PRD

## Sprint goal
Test the PRD-to-sprint conversion.

## Selected stories
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-359 | Boot splash | F-103 | E-001 | normal | M |
```

- [ ] **Step 5.2: Ensure `python-frontmatter` is available**

Add to `requirements.txt` if missing:

```
python-frontmatter>=1.0
```

Run: `pip install python-frontmatter`
Expected: install succeeds.

- [ ] **Step 5.3: Write failing tests `tests/pm/test_prd_to_sprint.py`**

```python
"""Tests for prd_to_sprint -- PRD MD → sprint.json conversion."""
import json
import shutil
import tempfile
from pathlib import Path
from offices.pm.scripts.prd_to_sprint import convertPrdToSprint

FIXTURES = Path(__file__).parent / "fixtures"


def _setupFakeRepo(tmpRoot: Path):
    """Build a minimal repo layout that convertPrdToSprint can read."""
    (tmpRoot / "offices/pm/backlog").mkdir(parents=True)
    (tmpRoot / "offices/pm/prds").mkdir(parents=True)
    (tmpRoot / "offices/ralph").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json",
                tmpRoot / "offices/pm/backlog.json")
    shutil.copy(FIXTURES / "prd_sample.md",
                tmpRoot / "offices/pm/prds/prd-V0.28.0-sprint-43.md")
    # also need a Story.md for US-359 with full content
    storyMd = """---
id: US-359
parent: F-103
type: normal
size: M
status: sprint-ready
createdAt: 2026-05-27
deps: []
sourceRefs: []
---

# US-359 — Boot splash

## Goal
As CIO, I want a boot splash so I know when the Pi is ready.

## Definition of Done
- splash visible within 3s

## Conditional outcomes
- if collector fails → degraded amber

## Validation criteria
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | Boot Pi cold | Splash within 3s |
"""
    (tmpRoot / "offices/pm/backlog/US-359-boot-splash.md").write_text(storyMd)


def test_convertPrdToSprint_basicConversion(tmp_path):
    _setupFakeRepo(tmp_path)
    prdPath = tmp_path / "offices/pm/prds/prd-V0.28.0-sprint-43.md"
    outPath = tmp_path / "offices/ralph/sprint.json"
    convertPrdToSprint(prdPath, outPath, repoRoot=tmp_path)
    assert outPath.exists()
    sprint = json.loads(outPath.read_text())
    assert sprint["version"] == "V0.28.0"
    assert sprint["sprint"] == 43
    assert len(sprint["stories"]) == 1
    s = sprint["stories"][0]
    assert s["id"] == "US-359"
    assert s["parent"] == "F-103"
    assert s["epicId"] == "E-001"
    assert s["type"] == "normal"
    assert "validationCriteria" in s
    assert "validation" in sprint
    assert "bigDefinitionOfDone" in sprint["validation"]
    assert len(sprint["validation"]["bigDefinitionOfDone"]) > 0
```

- [ ] **Step 5.4: Run test to verify it fails**

Run: `pytest tests/pm/test_prd_to_sprint.py -v`
Expected: 1 test FAILS with ImportError.

- [ ] **Step 5.5: Implement `offices/pm/scripts/prd_to_sprint.py`**

```python
"""
File: offices/pm/scripts/prd_to_sprint.py
Purpose: Convert a PRD MD file (YAML frontmatter + markdown body) into
         a Ralph-readable sprint.json contract. Snapshots Story.md content
         at conversion time (sprint.json is frozen; later Story.md edits
         do not propagate).
"""
import json
import re
from pathlib import Path
from typing import Any

import frontmatter


def convertPrdToSprint(prdPath: Path, outPath: Path, repoRoot: Path) -> None:
    """
    Read PRD MD at prdPath, write generated sprint.json to outPath.
    repoRoot is the path containing offices/pm/backlog.json and
    offices/pm/backlog/US-*.md files.
    """
    prd = frontmatter.load(prdPath)
    meta = prd.metadata
    backlogPath = repoRoot / "offices" / "pm" / "backlog.json"
    backlog = json.loads(backlogPath.read_text())

    epicsById = {e["id"]: e for e in backlog["epics"]}
    featuresById = {f["id"]: f for f in backlog["features"]}
    storiesById = {s["id"]: s for s in backlog["stories"]}

    sprintStories = []
    bigDoD: list[str] = []
    for storyId in meta["selectedStories"]:
        story = storiesById.get(storyId)
        if not story:
            raise ValueError(f"PRD {prdPath.name}: selectedStory {storyId} not in backlog.json")
        feature = featuresById[story["parent"]]
        epic = epicsById[feature["parent"]]
        storyMdPath = _findStoryMd(repoRoot, storyId)
        storyContent = _parseStoryMd(storyMdPath) if storyMdPath else {}

        sprintStories.append({
            "id": story["id"],
            "title": story["title"],
            "parent": feature["id"],
            "epicId": epic["id"],
            "type": story["type"],
            "size": story["size"],
            "status": "sprint-ready",
            "passes": False,
            "acceptance": story.get("definitionOfDone", []),
            "validationCriteria": story.get("validationCriteria", []),
            "conditionalOutcomes": story.get("conditionalOutcomes", []),
            "goal": story.get("goal", ""),
            "tasks": story.get("tasks", []),
        })

        for vc in story.get("validationCriteria", []):
            bigDoD.append(f"({vc.get('action', '')}) → ({vc.get('outcome', '')})  [from {storyId}]")

    sprintJson = {
        "schemaVersion": "2.0.0",
        "sprint": meta["sprint"],
        "version": meta["version"],
        "createdFromPRD": str(prdPath.relative_to(repoRoot)),
        "stories": sprintStories,
        "validation": {
            "bigDefinitionOfDone": bigDoD,
        },
    }
    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.write_text(json.dumps(sprintJson, indent=2) + "\n")


def _findStoryMd(repoRoot: Path, storyId: str) -> Path | None:
    """Find offices/pm/backlog/<storyId>-*.md."""
    matches = list((repoRoot / "offices/pm/backlog").glob(f"{storyId}-*.md"))
    return matches[0] if matches else None


def _parseStoryMd(path: Path) -> dict[str, Any]:
    """
    Parse a Story.md file. Returns content extracted from frontmatter
    plus parsed body sections. Currently returns just frontmatter; body
    parsing reserved for future use.
    """
    return dict(frontmatter.load(path).metadata)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: prd_to_sprint.py <prd-md> <sprint-json>", file=sys.stderr)
        sys.exit(1)
    repoRoot = Path(__file__).resolve().parents[3]
    convertPrdToSprint(Path(sys.argv[1]), Path(sys.argv[2]), repoRoot)
    print(f"Wrote {sys.argv[2]}")
```

- [ ] **Step 5.6: Run test to verify pass**

Run: `pytest tests/pm/test_prd_to_sprint.py -v`
Expected: 1 test PASSES.

- [ ] **Step 5.7: Commit**

```bash
git add offices/pm/scripts/prd_to_sprint.py tests/pm/test_prd_to_sprint.py tests/pm/fixtures/prd_sample.md requirements.txt
git commit -m "feat(pm-tooling): prd_to_sprint.py -- PRD MD frontmatter + Story.md → sprint.json conversion"
```

---

### Task 6: NEW `graduate_story.py` (archive completed items)

**Files:**
- Create: `offices/pm/scripts/graduate_story.py`
- Create: `tests/pm/test_graduate_story.py`

- [ ] **Step 6.1: Write failing test `tests/pm/test_graduate_story.py`**

```python
"""Tests for graduate_story -- move completed items to archive."""
import json
import shutil
from pathlib import Path
from offices.pm.scripts.graduate_story import graduateStory

FIXTURES = Path(__file__).parent / "fixtures"


def test_graduateStory_movesMdAndUpdatesBacklog(tmp_path):
    (tmp_path / "offices/pm/backlog").mkdir(parents=True)
    (tmp_path / "offices/pm/archive/completed-work-products").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json", tmp_path / "offices/pm/backlog.json")
    storyMdPath = tmp_path / "offices/pm/backlog/US-359-test.md"
    storyMdPath.write_text("---\nid: US-359\nstatus: complete\n---\n# US-359\n")

    # mark story complete in backlog.json
    backlogPath = tmp_path / "offices/pm/backlog.json"
    data = json.loads(backlogPath.read_text())
    data["stories"][0]["status"] = "complete"
    backlogPath.write_text(json.dumps(data, indent=2))

    graduateStory("US-359", repoRoot=tmp_path, dryRun=False)

    # MD moved
    assert not storyMdPath.exists()
    assert (tmp_path / "offices/pm/archive/completed-work-products/US-359-test.md").exists()
    # JSON entry removed
    data = json.loads(backlogPath.read_text())
    assert all(s["id"] != "US-359" for s in data["stories"])


def test_graduateStory_storyNotComplete_raises(tmp_path):
    (tmp_path / "offices/pm/backlog").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json", tmp_path / "offices/pm/backlog.json")
    (tmp_path / "offices/pm/backlog/US-359-test.md").write_text("---\nid: US-359\n---\n# t\n")
    import pytest
    with pytest.raises(ValueError, match="not complete"):
        graduateStory("US-359", repoRoot=tmp_path, dryRun=False)
```

- [ ] **Step 6.2: Run test to verify it fails**

Run: `pytest tests/pm/test_graduate_story.py -v`
Expected: 2 tests FAIL with ImportError.

- [ ] **Step 6.3: Implement `offices/pm/scripts/graduate_story.py`**

```python
"""
File: offices/pm/scripts/graduate_story.py
Purpose: Move a completed Story/Feature/Epic out of the active backlog
         into offices/pm/archive/completed-work-products/. Removes from
         backlog.json. Refuses if status != 'complete'.
"""
import json
from pathlib import Path


def graduateStory(storyId: str, repoRoot: Path, dryRun: bool = False) -> None:
    backlogPath = repoRoot / "offices/pm/backlog.json"
    data = json.loads(backlogPath.read_text())
    story = next((s for s in data["stories"] if s["id"] == storyId), None)
    if not story:
        raise ValueError(f"Story {storyId} not found in backlog.json")
    if story["status"] != "complete":
        raise ValueError(f"Story {storyId} status is {story['status']!r}, not 'complete'")

    mdPath = next((p for p in (repoRoot / "offices/pm/backlog").glob(f"{storyId}-*.md")), None)
    if not mdPath:
        raise ValueError(f"Story {storyId}: no MD file found at offices/pm/backlog/{storyId}-*.md")

    archiveDir = repoRoot / "offices/pm/archive/completed-work-products"
    archiveDir.mkdir(parents=True, exist_ok=True)
    targetPath = archiveDir / mdPath.name

    if dryRun:
        print(f"[dry-run] would move {mdPath} → {targetPath}")
        print(f"[dry-run] would remove {storyId} from backlog.json")
        return

    mdPath.rename(targetPath)
    data["stories"] = [s for s in data["stories"] if s["id"] != storyId]
    backlogPath.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: graduate_story.py <US-id> [--dry-run]", file=sys.stderr)
        sys.exit(1)
    dryRun = "--dry-run" in sys.argv
    repoRoot = Path(__file__).resolve().parents[3]
    graduateStory(sys.argv[1], repoRoot=repoRoot, dryRun=dryRun)
    print("Graduation complete.")
```

- [ ] **Step 6.4: Run test to verify pass**

Run: `pytest tests/pm/test_graduate_story.py -v`
Expected: 2 tests PASS.

- [ ] **Step 6.5: Commit**

```bash
git add offices/pm/scripts/graduate_story.py tests/pm/test_graduate_story.py
git commit -m "feat(pm-tooling): graduate_story.py -- archive completed items + remove from backlog.json"
```

---

### Task 7: NEW `migrate_backlog_v1_to_v2.py` (one-time helper)

**Files:**
- Create: `offices/pm/scripts/migrate_backlog_v1_to_v2.py`
- Create: `tests/pm/test_migrate_v1_to_v2.py`
- Create: `tests/pm/fixtures/v1_backlog_sample.json`

- [ ] **Step 7.1: Write fixture `tests/pm/fixtures/v1_backlog_sample.json`**

Build a small v1-shape fixture (matches the current `offices/pm/backlog.json` structure — top-level epics array with nested features+stories; or whatever the v1 actual shape is). Inspect current file first:

Run: `head -50 offices/pm/backlog.json`

Then write a fixture matching that shape with 1 epic + 2 backlog items.

- [ ] **Step 7.2: Write failing test `tests/pm/test_migrate_v1_to_v2.py`**

```python
"""Tests for v1 → v2 backlog migration helper."""
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
```

- [ ] **Step 7.3: Run test to verify it fails**

Run: `pytest tests/pm/test_migrate_v1_to_v2.py -v`
Expected: tests FAIL with ImportError.

- [ ] **Step 7.4: Implement `offices/pm/scripts/migrate_backlog_v1_to_v2.py`**

```python
"""
File: offices/pm/scripts/migrate_backlog_v1_to_v2.py
Purpose: One-time helper to convert v1 backlog.json (flat B-XXX items)
         into a draft v2.0.0 backlog.json (4-tier hierarchy with proposed
         Epic taxonomy from the design spec §9.2). PM hand-reviews + corrects
         the suggested Epic parents per item.
"""
import json
from datetime import date
from pathlib import Path


# Initial Epic taxonomy per spec §9.2
EPICS_INITIAL = [
    {"id": "E-001", "title": "UI/UX Polish",
     "description": "Pi-side display: boot/shutdown splash, status surfaces, touch UI.",
     "keywords": ["splash", "display", "touch", "ui", "ux"]},
    {"id": "E-002", "title": "Data Pipeline & Analytics",
     "description": "Server analytics, schema normalization, drive detection.",
     "keywords": ["drive", "analytics", "schema", "server", "sync", "data"]},
    {"id": "E-003", "title": "Tuning Intelligence",
     "description": "Thresholds, GEMs, Spool layer, ECMLink integration.",
     "keywords": ["threshold", "gem", "knock", "ecmlink", "fuel", "tuning"]},
    {"id": "E-004", "title": "Infrastructure & Deploy",
     "description": "Pi pipeline, sync, deploy, hostnames, alerts.",
     "keywords": ["deploy", "sync", "pi", "hostname", "infrastructure"]},
    {"id": "E-005", "title": "Reports & CLI",
     "description": "Export, Ollama, CLI tooling.",
     "keywords": ["export", "report", "cli", "ollama"]},
    {"id": "E-OPS", "title": "Operational Hygiene",
     "description": "Bugs / tech debt / housekeeping without a domain Feature home.",
     "keywords": []},
]


def _suggestEpicParent(itemTitle: str, itemSlug: str) -> str:
    """Return best-guess E-XXX id by keyword match."""
    text = (itemTitle + " " + itemSlug).lower()
    best, bestHits = "E-OPS", 0
    for epic in EPICS_INITIAL:
        hits = sum(1 for kw in epic["keywords"] if kw in text)
        if hits > bestHits:
            best, bestHits = epic["id"], hits
    return best


def migrate(v1Path: Path, v2Path: Path) -> None:
    """Generate a draft v2 backlog.json from a v1 backlog.json."""
    v1 = json.loads(v1Path.read_text())
    today = date.today().isoformat()

    epics = [
        {"id": e["id"], "title": e["title"], "description": e["description"],
         "status": "active", "createdAt": today, "updatedAt": today}
        for e in EPICS_INITIAL
    ]

    features = []
    stories = []

    # v1 shape: data["epics"][n]["features"][m]["items"][k] OR data["items"][k]
    # Be defensive about both shapes.
    items = _flattenV1Items(v1)
    for item in items:
        bId = item.get("id") or item.get("backlogId") or ""
        if not bId.startswith("B-"):
            continue
        fId = "F-" + bId.split("-", 1)[1]
        parentEpic = _suggestEpicParent(item.get("title", ""), bId.lower())
        features.append({
            "id": fId,
            "parent": parentEpic,
            "title": item.get("title", "(unknown)"),
            "description": item.get("description", item.get("summary", ""))[:280],
            "status": _mapStatusToV2Feature(item.get("status", "pending")),
            "renamedFrom": bId,
            "createdAt": today,
            "updatedAt": today,
        })

    counters = {
        "epic": max((int(e["id"].split("-")[1]) for e in epics if e["id"].split("-")[1].isdigit()), default=5) + 1,
        "feature": max((int(f["id"].split("-")[1]) for f in features), default=109) + 1,
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
    v2Path.write_text(json.dumps(v2, indent=2) + "\n")


def _flattenV1Items(v1: dict) -> list[dict]:
    """v1 may have multiple shapes; flatten to a single list of backlog items."""
    out = []
    if "items" in v1 and isinstance(v1["items"], list):
        out.extend(v1["items"])
    for epic in v1.get("epics", []):
        if isinstance(epic, dict):
            out.extend(epic.get("items", []))
            for feature in epic.get("features", []):
                if isinstance(feature, dict):
                    out.extend(feature.get("items", []))
    return out


def _mapStatusToV2Feature(v1Status: str) -> str:
    mapping = {
        "pending": "pending",
        "groomed": "groomed",
        "in_progress": "active",
        "in-progress": "active",
        "in_sprint": "in-sprint",
        "blocked": "groomed",
        "complete": "complete",
    }
    return mapping.get(v1Status, "pending")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: migrate_backlog_v1_to_v2.py <v1.json> <v2-out.json>", file=sys.stderr)
        sys.exit(1)
    migrate(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Drafted v2 backlog at {sys.argv[2]} -- PM hand-review owed.")
```

- [ ] **Step 7.5: Run test to verify pass**

Run: `pytest tests/pm/test_migrate_v1_to_v2.py -v`
Expected: 2 tests PASS.

- [ ] **Step 7.6: Commit**

```bash
git add offices/pm/scripts/migrate_backlog_v1_to_v2.py tests/pm/test_migrate_v1_to_v2.py tests/pm/fixtures/v1_backlog_sample.json
git commit -m "feat(pm-tooling): migrate_backlog_v1_to_v2.py -- one-time draft generator with epic keyword matching"
```

---

### Task 8: Templates (Epic + Feature + Story + PRD)

**Files:**
- Create: `offices/pm/backlog/_template-epic.md`
- Create: `offices/pm/backlog/_template-feature.md`
- Create: `offices/pm/backlog/_template-story.md`
- Create: `offices/pm/prds/_template-prd.md`

- [ ] **Step 8.1: Write `offices/pm/backlog/_template-epic.md`**

```markdown
---
id: E-XXX
status: pending
createdAt: YYYY-MM-DD
---

# E-XXX — <title>

## Description
<1–3 sentences. Categorical theme. Multi-sprint capability.>

## Features
- F-XXX <feature title> (<status>)

## Context / rationale
<Why this epic exists; what user value it serves.>
```

- [ ] **Step 8.2: Write `offices/pm/backlog/_template-feature.md`**

```markdown
---
id: F-XXX
parent: E-XXX
status: pending
renamedFrom: (optional; B-XXX for migration audit)
createdAt: YYYY-MM-DD
---

# F-XXX — <title>

## Description
<1–3 sentences. Categorical sprint-scope user value.>

## Scope notes
- <key scope point>
- <key scope point>

## Stories
- US-XXX <story title> (<status>, <size>)

## Risks
- <risk + mitigation if known>

## Cross-references
- <link to spec / inbox note / prior gate verdict if any>
```

- [ ] **Step 8.3: Write `offices/pm/backlog/_template-story.md`**

```markdown
---
id: US-XXX
parent: F-XXX
type: normal
size: S
status: pending
createdAt: YYYY-MM-DD
deps: []
sourceRefs: []
---

# US-XXX — <title>

## Goal
<Connextra: As <role>, I want <goal> so that <benefit>.>
<OR Gherkin: Given <precondition>, when <action>, then <outcome>.>

## Definition of Done
- <criterion>
- <criterion>

## Conditional outcomes
- if <condition> → <expected system response>

## Validation criteria (testable action + expected outcome)
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | <action> | <outcome> |

## Tasks (optional; inline; pre-sprint planned)
- [ ] **T-1** <title> (added YYYY-MM-DD)
  - Output: <concrete artifact produced>

## Dependencies
<None | depends on US-XXX in F-YYY>

## Grounded references
- <link>

## Review notes (populated during PRD grooming)
*Atlas review:* (pending)
*Argus review:* (not requested | pending)

## Audit trail
- YYYY-MM-DD created
```

- [ ] **Step 8.4: Write `offices/pm/prds/_template-prd.md`**

```markdown
---
sprint: <N>
version: V<X>.<Y>.<Z>
status: draft
createdAt: YYYY-MM-DD
createdBy: Marcus (PM)
selectedStories: [US-XXX, US-YYY]
argusReviewRequired: false
convertedAt: null
sprintJsonPath: null
---

# PRD — Sprint <N> (V<X>.<Y>.<Z>): <theme line>

## Sprint goal
<1–3 sentences. What this sprint delivers.>

## Selected stories
| Story | Title | Feature | Epic | Type | Size |
|---|---|---|---|---|---|
| US-XXX | <title> | F-XXX | E-XXX | normal | M |

## Open questions
| # | Question | Raised by | Resolution | Resolved by |
|---|---|---|---|---|

## Atlas architecture review
*Date: TBD*

## Argus QA review (only if required)
*Date: TBD*

## Sprint-level `validation.bigDefinitionOfDone`

## Refinements made during grooming
| Story | Refinement | Made by | Date |
|---|---|---|---|

## Dependencies & sequencing

## Conversion record

## Audit trail
- YYYY-MM-DD draft created
```

- [ ] **Step 8.5: Commit**

```bash
git add offices/pm/backlog/_template-epic.md offices/pm/backlog/_template-feature.md offices/pm/backlog/_template-story.md offices/pm/prds/_template-prd.md
git commit -m "feat(pm-templates): add Epic/Feature/Story/PRD MD templates for backlog v2"
```

---

### Task 9: Pre-flight backup + archive dirs

**Files:**
- Create: `offices/pm/archive/completed-work-products/.gitkeep`
- Create: `offices/pm/archive/intake-records/.gitkeep`
- Create (backups, not committed): `offices/pm/backlog.v1-backup.json`, `offices/pm/backlog.v1-backup/`, `offices/pm/story_counter.v1-backup.json`

- [ ] **Step 9.1: Create archive directories**

```bash
mkdir -p offices/pm/archive/completed-work-products offices/pm/archive/intake-records
touch offices/pm/archive/completed-work-products/.gitkeep
touch offices/pm/archive/intake-records/.gitkeep
```

- [ ] **Step 9.2: Backup current v1 backlog**

```bash
cp offices/pm/backlog.json offices/pm/backlog.v1-backup.json
cp -r offices/pm/backlog offices/pm/backlog.v1-backup
cp offices/pm/story_counter.json offices/pm/story_counter.v1-backup.json
```

Add the backups to `.gitignore` (they're local-only safety nets):

```
# v0.28 migration backups -- local only
offices/pm/backlog.v1-backup.json
offices/pm/backlog.v1-backup/
offices/pm/story_counter.v1-backup.json
```

- [ ] **Step 9.3: Commit (archive dirs + gitignore only; backups uncommitted)**

```bash
git add offices/pm/archive/completed-work-products/.gitkeep offices/pm/archive/intake-records/.gitkeep .gitignore
git commit -m "chore(pm-migration): create archive dirs + gitignore v1 backups"
```

---

### Task 10: Run migration helper + PM hand-review

**Files:**
- Modify: `offices/pm/backlog.json` (v1 → v2 draft → PM-corrected v2)

- [ ] **Step 10.1: Run migration helper**

```bash
python offices/pm/scripts/migrate_backlog_v1_to_v2.py offices/pm/backlog.json offices/pm/backlog.v2-draft.json
```

Expected: file `offices/pm/backlog.v2-draft.json` created with draft v2 shape; output says "PM hand-review owed".

- [ ] **Step 10.2: PM hand-review (judgement step)**

Open `offices/pm/backlog.v2-draft.json` and review every Feature entry:
- Is `parent: E-XXX` the right Epic per the §9.2 taxonomy?
- Is `title` clear?
- Is `description` populated?
- Is `status` correct?

Correct any wrong Epic assignments by hand. The keyword-match in the helper is a suggestion, not a verdict.

Save corrected draft as `offices/pm/backlog.json` (overwriting v1):

```bash
cp offices/pm/backlog.v2-draft.json offices/pm/backlog.json
rm offices/pm/backlog.v2-draft.json
```

- [ ] **Step 10.3: Validate the migrated backlog**

```bash
python -c "import json; from offices.pm.scripts.backlog_schema import validateBacklog; validateBacklog(json.load(open('offices/pm/backlog.json')))"
```

Expected: no output (validation passes).

If `BacklogValidationError`: fix the offending entry by hand, re-validate.

- [ ] **Step 10.4: Run pm_status to render the new tree**

```bash
python offices/pm/scripts/pm_status.py
```

Expected: v2 tree view renders. Spot-check a few rolled-up Epic statuses look right.

- [ ] **Step 10.5: Commit migrated backlog**

```bash
git add offices/pm/backlog.json
git commit -m "feat(pm-migration): migrate backlog.json v1 → v2 -- 4-tier hierarchy active"
```

---

### Task 11: Re-tier per-item MD files

**Files:**
- For each active B-XXX in `offices/pm/backlog/`: rename to F-XXX-*.md + rewrite body to Feature.md template
- For known-decomposed B-items (B-103, B-104): also create child US-XXX Story.md files

- [ ] **Step 11.1: List the active B-XXX files**

```bash
ls offices/pm/backlog/B-*.md
```

Expected: see ~10 active files (some files are tracked in pm/archive/ for completed items; only re-tier the ACTIVE ones, per the migration helper's output).

- [ ] **Step 11.2: For each active B-XXX file, rename + rewrite**

For each B-XXX file:

1. Determine the new F-XXX number (matches the entry in `backlog.json` features[]).
2. Rename: `git mv offices/pm/backlog/B-XXX-<slug>.md offices/pm/backlog/F-XXX-<slug>.md`
3. Open the new file. Rewrite the body following `_template-feature.md`. Preserve information from the original; reorganize into Description / Scope notes / Stories / Risks / Cross-references.
4. Update the frontmatter:
   ```yaml
   ---
   id: F-XXX
   parent: E-???  # matches backlog.json
   status: <matches backlog.json>
   renamedFrom: B-XXX
   createdAt: <original date if known, else 2026-05-27>
   ---
   ```
5. Save.

Repeat for all ~10 active items. This is judgement-heavy work; ~5–10 min per file.

- [ ] **Step 11.3: For B-103 specifically, create its child Story files**

B-103 (now F-103) has 4 stories per Atlas's gate verdict (US-A boot / US-B shutdown / US-C deploy / US-D defects). Create real Story.md files:

```bash
cp offices/pm/backlog/_template-story.md offices/pm/backlog/US-359-boot-splash.md
# edit per Atlas v1.1 spec §10 M-1
```

Story IDs allocated: US-359 (boot), US-360 (shutdown, Rule-10), US-361 (deploy), US-362 (defects).

Update `backlog.json` counters.story → 363 after these are filed.

Story content sourced from the v1.1 spec at `docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md`.

Add story entries to `backlog.json` stories[] with proper goal/DoD/conditional outcomes/validation criteria.

- [ ] **Step 11.4: Validate after re-tier**

```bash
python offices/pm/scripts/sprint_lint.py --backlog
```

Expected: 0 errors. Warnings OK.

- [ ] **Step 11.5: Commit**

```bash
git add offices/pm/backlog/
git commit -m "feat(pm-migration): re-tier active B-XXX → F-XXX + file B-103 child stories US-359..US-362"
```

---

### Task 12: Write the 6 Epic MD files

**Files:**
- Create: `offices/pm/backlog/E-001-uiux-polish.md`
- Create: `offices/pm/backlog/E-002-data-pipeline-analytics.md`
- Create: `offices/pm/backlog/E-003-tuning-intelligence.md`
- Create: `offices/pm/backlog/E-004-infrastructure-deploy.md`
- Create: `offices/pm/backlog/E-005-reports-cli.md`
- Create: `offices/pm/backlog/E-OPS-operational-hygiene.md`

- [ ] **Step 12.1: Copy template into 6 Epic files**

```bash
for slug in "E-001-uiux-polish" "E-002-data-pipeline-analytics" "E-003-tuning-intelligence" "E-004-infrastructure-deploy" "E-005-reports-cli" "E-OPS-operational-hygiene"; do
  cp offices/pm/backlog/_template-epic.md "offices/pm/backlog/${slug}.md"
done
```

- [ ] **Step 12.2: For each Epic file, fill in real content**

Open each file and replace placeholders with real content. The list of Features per Epic is in `backlog.json` (or `pm_status.py` output). Brief description per spec §9.2. Categorical context paragraph.

(Judgement step; ~5 min per file.)

- [ ] **Step 12.3: Validate Epic MD ↔ JSON sync**

```bash
python offices/pm/scripts/sprint_lint.py --backlog
```

Expected: 0 errors.

- [ ] **Step 12.4: Commit**

```bash
git add offices/pm/backlog/E-*.md
git commit -m "feat(pm-migration): file 6 Epic MD files (E-001..E-005 + E-OPS)"
```

---

### Task 13: Fold open I-/BL-/TD- intake into typed Stories

**Files:**
- Modify: `offices/pm/issues/`, `offices/pm/blockers/`, `offices/pm/tech_debt/` (move to archive)
- Create: typed Story MD files in `offices/pm/backlog/` for still-actionable items

- [ ] **Step 13.1: Audit open intake records**

```bash
ls offices/pm/issues/ offices/pm/blockers/ offices/pm/tech_debt/
```

For each file: open it, determine if still actionable.
- If RESOLVED / SUPERSEDED: move to `offices/pm/archive/intake-records/`.
- If STILL ACTIONABLE: continue to Step 13.2.

- [ ] **Step 13.2: For each actionable item, create a typed Story**

For an actionable I-XXX → file `US-NNN-<slug>.md` under the relevant Feature with `type: issue` and `sourceRefs: [I-XXX]`. Likewise `type: blocker` for BL-XXX and `type: tech-debt` for TD-XXX.

Update `backlog.json` stories[] + counters.story.

- [ ] **Step 13.3: Move original intake records to archive**

```bash
git mv offices/pm/issues/*.md offices/pm/archive/intake-records/ 2>/dev/null || true
git mv offices/pm/blockers/*.md offices/pm/archive/intake-records/ 2>/dev/null || true
git mv offices/pm/tech_debt/*.md offices/pm/archive/intake-records/ 2>/dev/null || true
```

Leave the empty `offices/pm/issues/`, `offices/pm/blockers/`, `offices/pm/tech_debt/` directories with `.gitkeep` files marked `# retired 2026-05-27; new intake files as typed Stories under offices/pm/backlog/`.

- [ ] **Step 13.4: Validate**

```bash
python offices/pm/scripts/sprint_lint.py --backlog
```

Expected: 0 errors.

- [ ] **Step 13.5: Commit**

```bash
git add offices/pm/issues/ offices/pm/blockers/ offices/pm/tech_debt/ offices/pm/archive/intake-records/ offices/pm/backlog/ offices/pm/backlog.json
git commit -m "feat(pm-migration): fold open I-/BL-/TD- intake into typed Stories + retire intake folders"
```

---

### Task 14: PM Rules amendments (`projectManager.md`)

**Files:**
- Modify: `offices/pm/projectManager.md`

- [ ] **Step 14.1: Locate "PM Rules" section**

Open `offices/pm/projectManager.md` and find the numbered rules (lines 70+).

- [ ] **Step 14.2: Rewrite PM Rule 5**

Replace existing Rule 5 with:

```markdown
5. **Story contract.** Every Story carries `goal` (Connextra or Gherkin form), `definitionOfDone`, `conditionalOutcomes`, and `validationCriteria` (testable action + expected outcome pairs) at backlog stage. These are *defined* in the backlog and become *crystal-clear* at the PRD stage. Acceptance criteria, validation scripts, and database checks live within these fields, not as separate artifacts. (CIO 2026-05-23 directive #2: validation-criteria-upfront.)
```

- [ ] **Step 14.3: Add new PM Rule 11**

After Rule 10, append:

```markdown
11. **Hierarchy discipline (backlog v2 — 2026-05-27).** Every Story has a Feature parent; every Feature has an Epic parent. No orphans. Typed Stories (`type: issue|blocker|tech-debt|research|housekeeping|security`) without a natural Feature home file under standing **E-OPS Operational Hygiene** Epic. `sprint_lint --backlog` enforces. (See `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md`.)
```

- [ ] **Step 14.4: Add new PM Rule 12**

```markdown
12. **Graduation (backlog v2 — 2026-05-27).** Completed Epics / Features / Stories move from `offices/pm/backlog.json` + `offices/pm/backlog/` to `offices/pm/archive/completed-work-products/`. Tasks travel inline with their parent Story. Use `offices/pm/scripts/graduate_story.py <ID>` (PM-triggered, refuses if status ≠ `complete`).
```

- [ ] **Step 14.5: Update header `Last Updated`**

Update the `**Last Updated**:` line at top of `projectManager.md` to note the backlog-v2 migration session.

- [ ] **Step 14.6: Commit**

```bash
git add offices/pm/projectManager.md
git commit -m "docs(pm): PM Rule 5 rewrite + new Rules 11+12 for backlog-v2 hierarchy + graduation"
```

---

### Task 15: Final validation & smoke tests

**Files:**
- None modified; verification only.

- [ ] **Step 15.1: Run all PM tests**

```bash
pytest tests/pm/ -v
```

Expected: all tests PASS (Tasks 1, 2, 3, 5, 6, 7 contributed test files; should be ~20+ tests, 0 failures).

- [ ] **Step 15.2: Run full backlog validation**

```bash
python offices/pm/scripts/sprint_lint.py --backlog
```

Expected: 0 errors. Warnings may exist for rollup cache staleness — that's fine, pm_status fixes those on next invocation.

- [ ] **Step 15.3: Run pm_status with fresh rollup**

```bash
python offices/pm/scripts/pm_status.py
```

Expected: clean v2 tree view. Verify:
- 6 Epics displayed
- Each Feature has a parent Epic
- Each Story has a parent Feature
- Statuses look sane (no `pending` Epic with all its Features `complete`)

- [ ] **Step 15.4: Spot-check 3 Story files for JSON↔MD sync**

Pick 3 random Story files in `offices/pm/backlog/`. For each:
1. Read frontmatter
2. Find the matching entry in `backlog.json`
3. Verify `id`, `parent`, `status`, `type`, `size` all match

- [ ] **Step 15.5: Verify sprint.json untouched**

```bash
git diff main -- offices/ralph/sprint.json
```

Expected: no diff (per spec §2 non-goals; sprint.json schema additions are deferred until first V0.28.0 sprint spin).

- [ ] **Step 15.6: Run the non-slow Python test suite**

```bash
pytest -m "not slow" -q
```

Expected: 0 failures. Backlog-v2 migration must not have broken any unrelated tests.

- [ ] **Step 15.7: Commit migration-complete marker**

```bash
git commit --allow-empty -m "chore(pm-migration): backlog v2 hierarchy migration complete -- ready for V0.28.0 sprint 1 grooming on new templates"
```

---

## Self-review checklist (after writing this plan)

Run inline against the spec at `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md`:

1. **Spec coverage:**
   - §3 architecture overview → Task 1 (schema), Task 2 (pm_status), Task 8 (templates), Task 12 (Epic files), Task 10 (migration)
   - §4 JSON contract → Task 1 (validator)
   - §5 status schema → Task 1 (validators) + Task 2 (rollup)
   - §6 MD templates → Task 8
   - §7 PRD lifecycle → Task 5 (prd_to_sprint) + Task 8 (template)
   - §8 typed Stories → Task 1 (type enum) + Task 13 (fold-in)
   - §9 migration plan → Task 7 (helper) + Tasks 9–13 (execution)
   - §10 tooling → Tasks 1–7
   - §11 sprint.json schema → DEFERRED (per spec §2 non-goals; first V0.28.0 sprint spin lands these)
   - §12 PM Rules amendments → Task 14
   - All sections covered.

2. **Placeholder scan:** searched plan for "TBD", "TODO", "implement later" — only legitimate uses in template files (TBDs are placeholders FOR THE TEMPLATES, not in plan steps).

3. **Type consistency:** function names verified across tasks (`validateBacklog`, `BacklogValidationError`, `computeRollups`, `renderTree`, `lintBacklog`, `LintError`, `LintWarning`, `convertPrdToSprint`, `graduateStory`, `migrate`). No drift.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-27-backlog-hierarchy-v2.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task with two-stage review between tasks. Best for the TDD-heavy Tasks 1–7. Slower but produces cleaner code with explicit checkpoints. Use `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`. Faster; you watch progress live and gate via the checkbox sequence. Best for the imperative/judgement Tasks 10–13.

**Recommended hybrid:** Subagent for Tasks 1–7 (tooling TDD; clean parallelizable units), inline for Tasks 8–15 (templates + migration + PM Rules; PM-judgement-heavy).

Which approach?
