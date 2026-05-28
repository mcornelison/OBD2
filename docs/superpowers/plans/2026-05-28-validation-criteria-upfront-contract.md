# Validation-Criteria-Upfront Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the validation-criteria-upfront contract per spec `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`. Enforces non-empty `validationCriteria` + `definitionOfDone` on every Story, freezes `bigDefinitionOfDone` via hash at PRD→sprint conversion, ERRORs on freeze drift in sprint_lint, adds PM Rule 13 (Atlas validation-block sign-off), updates sprint contract spec + PRD template, updates MEMORY.md.

**Architecture:** Three lanes of enforcement (backlog grooming → PRD→sprint conversion → sprint dispatch), each with a TDD-friendly script change. SHA-256 hash + ISO timestamp form the freeze. PM Rule 13 + template/spec updates are textual. No new files; no git bootstrap.

**Tech Stack:** Python 3.11+ (pytest, hashlib stdlib), markdown, git. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md` — sections cited by §N below.

---

## File Structure

**Files modified (no new files):**

- `offices/pm/scripts/backlog_schema.py` — `_validateValidationCriteria` errors on empty list + empty strings; new `_validateDefinitionOfDone`
- `tests/pm/test_backlog_schema.py` — 3 new tests for empty-list + empty-string ERRORs
- `offices/pm/scripts/prd_to_sprint.py` — adds `frozenAt` + `bigDoDHash` to generated sprint.json
- `tests/pm/test_prd_to_sprint.py` — 2 new tests (freeze fields set; hash deterministic)
- `offices/pm/scripts/sprint_lint.py` — freeze-drift check; per-story empty-list ERRORs
- `tests/pm/test_sprint_lint_feedback_vs_diff.py` (or a new `test_sprint_lint_freeze.py`) — 4 new tests
- `offices/pm/projectManager.md` — new PM Rule 13; Last Updated header bump
- `offices/pm/backlog/_template-story.md` — one-line clarification reinforcing "at least 1 V-row required"
- `offices/pm/prds/_template-prd.md` — grooming-checklist note: verify non-empty + route to Atlas for Rule 13
- `docs/superpowers/specs/2026-04-14-sprint-contract-design.md` — append `Validation-Criteria-Upfront Addendum`
- `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` — mark §2 DONE
- `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` — Standing CIO directives entry + Current State pointer

**Out of scope (explicit non-goals from spec §10):**
- Bulk backfill of existing Stories with placeholder validationCriteria (backlog currently has 0 Stories per session-start pm_status — enforcement is naturally prospective).
- Unfreeze ritual/command (handled by patch-sprint pattern from directive #1).
- DoD shape enforcement beyond non-empty.
- Atlas review automation.
- Backfilling freeze fields on V0.27 archived sprint.json files (graceful degradation when `frozenAt` is absent).

---

## Task 1: `backlog_schema.py` — empty-list ERRORs (TDD)

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/backlog_schema.py` (`_validateValidationCriteria`; new `_validateDefinitionOfDone`)
- Modify: `Z:/o/OBD2v2/tests/pm/test_backlog_schema.py` (3 new tests)

- [ ] **Step 1: Read existing schema + test file**

Run: `Read Z:/o/OBD2v2/offices/pm/scripts/backlog_schema.py` (full) + `Read Z:/o/OBD2v2/tests/pm/test_backlog_schema.py` (full).

Note the existing test pattern (plain pytest functions, fixture-based: `v2_backlog_sample.json`). Identify the helper that builds a minimal valid story for tests (or the fixture story shape).

- [ ] **Step 2: Write 3 failing tests**

Append to `tests/pm/test_backlog_schema.py`:

```python
def test_validateBacklog_storyValidationCriteriaEmpty_raises():
    """
    Given: a Story with validationCriteria = []
    When: validateBacklog is called
    Then: BacklogValidationError raised mentioning the Story id + 'non-empty'
    """
    data = _minimalValidBacklog()
    data["stories"][0]["validationCriteria"] = []
    with pytest.raises(BacklogValidationError, match="non-empty"):
        validateBacklog(data)


def test_validateBacklog_storyDefinitionOfDoneEmpty_raises():
    """
    Given: a Story with definitionOfDone = []
    When: validateBacklog is called
    Then: BacklogValidationError raised mentioning the Story id + 'non-empty'
    """
    data = _minimalValidBacklog()
    data["stories"][0]["definitionOfDone"] = []
    with pytest.raises(BacklogValidationError, match="non-empty"):
        validateBacklog(data)


def test_validateBacklog_validationCriteriaEmptyStrings_raises():
    """
    Given: a Story with validationCriteria containing an empty action or outcome
    When: validateBacklog is called
    Then: BacklogValidationError raised
    """
    data = _minimalValidBacklog()
    data["stories"][0]["validationCriteria"] = [{"action": "", "outcome": "x"}]
    with pytest.raises(BacklogValidationError, match="non-empty"):
        validateBacklog(data)
```

If `_minimalValidBacklog()` doesn't exist in the file, add a helper at the top of the test module that builds a minimal valid backlog dict with 1 epic + 1 feature + 1 story (with non-empty validationCriteria + DoD). Pattern: mirror the existing `test_computeRollups_featureWithAllStoriesComplete_status_complete` shape from `test_pm_status_v2.py`.

- [ ] **Step 3: Run tests, confirm fail**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_backlog_schema.py -k "Empty" -v`

Expected: 3 FAIL with errors raised but not matching "non-empty" (or no error raised, since current code permits empty lists).

- [ ] **Step 4: Implement the non-empty checks**

Edit `offices/pm/scripts/backlog_schema.py`:

```python
def _validateValidationCriteria(story: dict[str, Any]) -> None:
    """
    Validate that validationCriteria is a non-empty list of {action, outcome} dicts.

    Per spec 2026-05-28 (CIO directive #2): every Story must have at least one
    testable (action, outcome) pair so Ralph has a completion signal and Atlas
    has reviewable criteria.

    Raises:
        BacklogValidationError: If validationCriteria is missing, not a list,
            empty, or contains items without exactly {action, outcome} non-empty strings.
    """
    vc = story.get("validationCriteria")
    if not isinstance(vc, list):
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be a list"
        )
    if len(vc) == 0:
        raise BacklogValidationError(
            f"Story {story['id']}: validationCriteria must be non-empty "
            f"(at least 1 (action, outcome) pair) per directive 2026-05-23 #2"
        )
    for i, item in enumerate(vc):
        if not isinstance(item, dict) or set(item.keys()) != {"action", "outcome"}:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] must have keys "
                f"{{action, outcome}}, got {item!r}"
            )
        if not item["action"] or not item["outcome"]:
            raise BacklogValidationError(
                f"Story {story['id']}: validationCriteria[{i}] action and outcome "
                f"must both be non-empty strings"
            )


def _validateDefinitionOfDone(story: dict[str, Any]) -> None:
    """
    Validate that definitionOfDone is a non-empty list of non-empty strings.

    Per spec 2026-05-28 (CIO directive #2): every Story must have at least one
    DoD criterion so Ralph knows when complete.

    Raises:
        BacklogValidationError: If definitionOfDone is missing, not a list,
            empty, or contains non-string / empty-string items.
    """
    dod = story.get("definitionOfDone")
    if not isinstance(dod, list):
        raise BacklogValidationError(
            f"Story {story['id']}: definitionOfDone must be a list"
        )
    if len(dod) == 0:
        raise BacklogValidationError(
            f"Story {story['id']}: definitionOfDone must be non-empty "
            f"(at least 1 criterion) per directive 2026-05-23 #2"
        )
    for i, item in enumerate(dod):
        if not isinstance(item, str) or not item.strip():
            raise BacklogValidationError(
                f"Story {story['id']}: definitionOfDone[{i}] must be a non-empty string, "
                f"got {item!r}"
            )
```

Also call `_validateDefinitionOfDone(story)` from the story-loop in `validateBacklog`, alongside the existing `_validateValidationCriteria(story)` call.

- [ ] **Step 5: Run tests, confirm pass**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_backlog_schema.py -v`

Expected: all tests PASS (8 pre-existing + 3 new).

- [ ] **Step 6: Run sprint_lint --backlog to confirm current backlog still passes**

Run: `cd Z:/o/OBD2v2 && python offices/pm/scripts/sprint_lint.py --backlog`

Expected: 0 errors (current backlog has 0 Stories per session start pm_status; only Features + Epics, which don't trigger Story enforcement).

If errors emerge (Stories added since session start), abort and report — bulk backfill is out of scope per spec §10; would need CIO direction.

- [ ] **Step 7: Commit Task 1**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/backlog_schema.py tests/pm/test_backlog_schema.py
git commit -m "feat(backlog_schema): non-empty validationCriteria + DoD per CIO directive #2

Per spec 2026-05-28: every Story must carry at least 1 testable
(action, outcome) pair + at least 1 DoD criterion. Empty list or
empty-string item ERRORs. Ralph needs a completion signal; Atlas
needs reviewable criteria.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `prd_to_sprint.py` — freeze fields (TDD)

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/prd_to_sprint.py`
- Modify: `Z:/o/OBD2v2/tests/pm/test_prd_to_sprint.py`

- [ ] **Step 1: Read existing test file + the sample PRD fixture**

Run: `Read Z:/o/OBD2v2/tests/pm/test_prd_to_sprint.py` + `Read Z:/o/OBD2v2/tests/pm/fixtures/prd_sample.md`.

Note the existing test pattern for `convertPrdToSprint` (input fixture → write output → assert content).

- [ ] **Step 2: Write 2 failing tests**

Append to `tests/pm/test_prd_to_sprint.py`:

```python
import re


def test_convertPrdToSprint_writesFreezeFields(tmp_path, repoRootFixture):
    """
    Given: the sample PRD fixture is converted
    When: convertPrdToSprint runs
    Then: sprint.json validation block carries frozenAt (ISO format) + bigDoDHash (64 char hex)
    """
    from offices.pm.scripts.prd_to_sprint import convertPrdToSprint
    prdPath = FIXTURES / "prd_sample.md"
    outPath = tmp_path / "sprint.json"
    convertPrdToSprint(prdPath, outPath, repoRootFixture)
    data = json.loads(outPath.read_text(encoding="utf-8"))
    v = data["validation"]
    # ISO 8601 'Z' suffix
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v["frozenAt"])
    # SHA-256 hex
    assert re.match(r"^[0-9a-f]{64}$", v["bigDoDHash"])


def test_convertPrdToSprint_freezeHash_deterministic(tmp_path, repoRootFixture):
    """
    Given: the same PRD converted twice
    When: convertPrdToSprint runs both times
    Then: bigDoDHash is identical (deterministic over canonical bigDoD content)
    """
    from offices.pm.scripts.prd_to_sprint import convertPrdToSprint
    prdPath = FIXTURES / "prd_sample.md"
    outA = tmp_path / "a.json"
    outB = tmp_path / "b.json"
    convertPrdToSprint(prdPath, outA, repoRootFixture)
    convertPrdToSprint(prdPath, outB, repoRootFixture)
    dataA = json.loads(outA.read_text(encoding="utf-8"))
    dataB = json.loads(outB.read_text(encoding="utf-8"))
    assert dataA["validation"]["bigDoDHash"] == dataB["validation"]["bigDoDHash"]
```

(If `repoRootFixture` doesn't exist in the test module, look at `test_prd_to_sprint.py`'s existing test pattern and use whatever fixture setup it uses — likely a direct `REPO_ROOT` constant or a tmp_path-populated fixture.)

- [ ] **Step 3: Run tests, confirm fail**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_prd_to_sprint.py -k "Freeze" -v`

Expected: 2 FAIL — KeyError or assertion fail because frozenAt/bigDoDHash not yet written.

- [ ] **Step 4: Implement freeze fields**

Edit `offices/pm/scripts/prd_to_sprint.py`. Add at the top of imports:

```python
import hashlib
from datetime import datetime, timezone
```

Then modify `convertPrdToSprint` — after the bigDoD list is fully built (just before `sprintJson` assembly):

```python
    # Freeze the contract per spec 2026-05-28 (CIO directive #2).
    # Canonicalize: sort lines + strip whitespace + join with \n.
    canonicalBigDoD = "\n".join(sorted(line.strip() for line in bigDoD))
    bigDoDHash = hashlib.sha256(canonicalBigDoD.encode("utf-8")).hexdigest()
    frozenAt = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    sprintJson: dict[str, Any] = {
        "schemaVersion": "2.0.0",
        "sprint": meta["sprint"],
        "version": meta["version"],
        "createdFromPRD": str(prdPath.relative_to(repoRoot)).replace("\\", "/"),
        "stories": sprintStories,
        "validation": {
            "bigDefinitionOfDone": bigDoD,
            "frozenAt": frozenAt,
            "bigDoDHash": bigDoDHash,
        },
    }
```

- [ ] **Step 5: Run tests, confirm pass**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_prd_to_sprint.py -v`

Expected: all tests PASS (existing + 2 new).

- [ ] **Step 6: Commit Task 2**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/prd_to_sprint.py tests/pm/test_prd_to_sprint.py
git commit -m "feat(prd_to_sprint): freeze bigDoD via frozenAt + SHA-256 hash per CIO directive #2

Per spec 2026-05-28: sprint.json carries validation.frozenAt (ISO timestamp)
+ validation.bigDoDHash (SHA-256 of canonicalized bigDefinitionOfDone).
Canonicalization: sort lines + strip whitespace + join with newline.
Deterministic; cross-platform stable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `sprint_lint.py` — freeze-drift + per-story empty-list (TDD)

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/sprint_lint.py` (`lintSprintValidation`)
- Modify: `Z:/o/OBD2v2/tests/pm/` — add new test file `test_sprint_lint_freeze.py` (keep existing test files focused on their original scope)

- [ ] **Step 1: Read existing sprint_lint + most-relevant test file**

Run: `Read Z:/o/OBD2v2/offices/pm/scripts/sprint_lint.py` (full) + check tests in `tests/pm/test_sprint_lint_*.py` to match test fixture/style.

Identify how a minimal valid sprint.json dict is constructed in tests (or where the fixture is).

- [ ] **Step 2: Create new test file with 4 failing tests**

Write to `Z:/o/OBD2v2/tests/pm/test_sprint_lint_freeze.py`:

```python
"""Tests for sprint_lint freeze-drift + per-story empty-list checks (spec 2026-05-28)."""
import hashlib
from pathlib import Path

import pytest

from offices.pm.scripts.sprint_lint import lintSprintValidation


def _hash(lines):
    canonical = "\n".join(sorted(line.strip() for line in lines))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _minimalSprintDict(bigDoD, hash_=None, withStory=True):
    """Build a minimal sprint.json dict with valid required validation fields."""
    sprintDict = {
        "schemaVersion": "2.0.0",
        "sprint": "Sprint 99 -- test",
        "stories": [],
        "validation": {
            "bigDefinitionOfDone": bigDoD,
            "validationMethod": "test drill",
            "validatesFeatures": ["F-005"],
            "currentVersion": "V0.28.0",
            "validatedAt": None,
            "validatedBy": None,
            "frozenAt": "2026-05-28T12:00:00Z",
            "bigDoDHash": hash_ if hash_ is not None else _hash(bigDoD),
        },
    }
    if withStory:
        sprintDict["stories"].append({
            "id": "US-359",
            "title": "T",
            "parent": "F-005",
            "type": "normal",
            "size": "S",
            "status": "sprint-ready",
            "passes": False,
            "acceptance": ["DoD-1"],
            "validationCriteria": [{"action": "a", "outcome": "o"}],
        })
    return sprintDict


def test_lintSprintValidation_noDrift_passes(tmp_path):
    """Given freeze fields match bigDoD content, no error."""
    bigDoD = ["clause A", "clause B"]
    d = _minimalSprintDict(bigDoD)
    errs = lintSprintValidation(d, tmp_path)
    # No drift errors. (Other errors may exist due to missing manifest,
    # but no error mentioning 'modified after freeze'.)
    assert not any("modified after freeze" in e for e in errs)


def test_lintSprintValidation_driftDetected_errors(tmp_path):
    """Given bigDoD edited after freeze hash was computed, ERROR."""
    bigDoD = ["clause A", "clause B"]
    d = _minimalSprintDict(bigDoD)
    # Modify bigDoD after the hash was set
    d["validation"]["bigDefinitionOfDone"].append("late addition clause")
    errs = lintSprintValidation(d, tmp_path)
    assert any("modified after freeze" in e for e in errs)


def test_lintSprintValidation_storyValidationCriteriaEmpty_errors(tmp_path):
    """Given a sprint story with empty validationCriteria, ERROR."""
    d = _minimalSprintDict(["clause A"])
    d["stories"][0]["validationCriteria"] = []
    errs = lintSprintValidation(d, tmp_path)
    assert any("validationCriteria empty" in e for e in errs)


def test_lintSprintValidation_storyAcceptanceEmpty_errors(tmp_path):
    """Given a sprint story with empty acceptance/DoD, ERROR."""
    d = _minimalSprintDict(["clause A"])
    d["stories"][0]["acceptance"] = []
    errs = lintSprintValidation(d, tmp_path)
    assert any("definitionOfDone empty" in e for e in errs)
```

- [ ] **Step 3: Run tests, confirm fail**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_sprint_lint_freeze.py -v`

Expected: 4 FAIL — error strings don't match because checks aren't implemented yet.

- [ ] **Step 4: Implement freeze-drift + per-story checks**

Edit `offices/pm/scripts/sprint_lint.py`. Add to imports at top:

```python
import hashlib
```

Find `lintSprintValidation()` and add to the end of its existing checks (before `return errs`):

```python
    # Freeze-drift check per spec 2026-05-28 (CIO directive #2)
    frozenAt = v.get("frozenAt")
    if frozenAt:
        stored = v.get("bigDoDHash")
        if not stored:
            errs.append(
                "validation.frozenAt set but validation.bigDoDHash missing -- "
                "contract corrupt"
            )
        else:
            bdod = v.get("bigDefinitionOfDone", [])
            canonical = "\n".join(sorted(line.strip() for line in bdod))
            computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if computed != stored:
                errs.append(
                    f"validation.bigDefinitionOfDone modified after freeze at "
                    f"{frozenAt}; computed={computed[:8]}, stored={stored[:8]}. "
                    f"Late additions are forbidden per directive 2026-05-23 #2 -- "
                    f"create a patch sprint instead."
                )

    # Per-story empty-list checks per spec 2026-05-28
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
```

- [ ] **Step 5: Run new tests, confirm pass**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_sprint_lint_freeze.py -v`

Expected: 4 PASS.

- [ ] **Step 6: Run sprint_lint against current sprint.json**

Run: `cd Z:/o/OBD2v2 && python offices/pm/scripts/sprint_lint.py 2>&1 | tail -15`

Expected: existing Sprint 42 sprint.json predates the freeze (no `frozenAt` field), so the freeze check is skipped (graceful degradation per spec §10). Per-story checks may surface NEW errors if the Sprint 42 story (US-358) has empty validationCriteria — that's diagnostic feedback, not blocking; Sprint 42 is closed/archived. Note any output but do NOT fix Sprint 42 in this task (out of scope; V0.27 chain is closed).

- [ ] **Step 7: Run full pm test suite to confirm nothing broke**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/ -v 2>&1 | tail -10`

Expected: ALL tests pass (existing 51 + 9 new from this plan ≈ 60).

- [ ] **Step 8: Commit Task 3**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/sprint_lint.py tests/pm/test_sprint_lint_freeze.py
git commit -m "feat(sprint_lint): freeze-drift + per-story empty-list errors per CIO directive #2

Per spec 2026-05-28: lintSprintValidation recomputes the bigDoD SHA-256
from current content and ERRORs if it diverges from the stored hash.
Also ERRORs on any sprint story with empty validationCriteria or DoD.
Graceful degradation for legacy sprint.json files without frozenAt
(V0.27 archived sprints unaffected).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add PM Rule 13 to `projectManager.md`

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/projectManager.md`

- [ ] **Step 1: Locate PM Rules section**

In `offices/pm/projectManager.md`, find `## PM Rules`. After Rule 12 (graduation), add Rule 13.

- [ ] **Step 2: Insert Rule 13 text**

Insert after Rule 12:

```markdown
13. **Validation-block sign-off (CIO directive 2026-05-23 #2 + spec 2026-05-28; Atlas owns the gate).** Every sprint's `validation.bigDefinitionOfDone` + per-story `validationCriteria` get Atlas reviewer-lane sign-off before Ralph dispatch. Atlas verifies: (a) each Story's validationCriteria is testable + complete; (b) bigDoD aggregates faithfully; (c) no holes in coverage relative to the Story's stated `goal`. Atlas may raise a formal validation-block BLOCK; PM/CIO clears it explicitly (same shape as Rule 10's design-gate BLOCK). The freeze hash gets cut by `prd_to_sprint.py` at PRD→sprint conversion; Atlas review happens between PRD draft and `prd_to_sprint.py` run.
```

- [ ] **Step 3: Bump the Last Updated header**

In the projectManager.md header `**Last Updated**:` line, prepend a new Session 44 entry (or append to existing Session 44 entry if same day):

```
**Last Updated**: 2026-05-28 (Session 44 -- **dev/main branching workflow LANDED + validation-criteria-upfront contract LANDED** per CIO directives #1 + #2. PM Rule 13 added (Atlas validation-block sign-off). backlog_schema requires non-empty validationCriteria + DoD; prd_to_sprint freezes bigDoD via frozenAt + bigDoDHash; sprint_lint ERRORs on drift + per-story empty-list. Spec at `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`; plan at `docs/superpowers/plans/2026-05-28-validation-criteria-upfront-contract.md`. Previous Last Updated below preserved:) [...existing text...]
```

(If the Session 44 entry from directive #1 already exists, merge the directive #2 details into it rather than nesting.)

- [ ] **Step 4: Commit Task 4**

```bash
cd Z:/o/OBD2v2
git add offices/pm/projectManager.md
git commit -m "docs(pm): add PM Rule 13 (validation-block sign-off; Atlas-owned)

Per spec 2026-05-28 + CIO directive #2. Every sprint's
validation.bigDefinitionOfDone + per-story validationCriteria get Atlas
reviewer-lane sign-off before Ralph dispatch. Atlas verifies testable
criteria, faithful aggregation, no coverage holes vs Story goal.

Last Updated header bumped for Session 44 directive #2 landing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Append sprint contract addendum + update PRD/Story templates

**Files:**
- Modify: `Z:/o/OBD2v2/docs/superpowers/specs/2026-04-14-sprint-contract-design.md`
- Modify: `Z:/o/OBD2v2/offices/pm/prds/_template-prd.md`
- Modify: `Z:/o/OBD2v2/offices/pm/backlog/_template-story.md`

- [ ] **Step 1: Append addendum to sprint contract spec**

Read `docs/superpowers/specs/2026-04-14-sprint-contract-design.md` to find the end of the file (after the existing `## Sprint-Level DoD Addendum — Design Gate (added 2026-05-18, CIO directive)` section).

Append:

```markdown

## Validation-Criteria-Upfront Addendum (added 2026-05-28, CIO directive #2)

Per spec `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`:

Every sprint.json `validation` block includes:
- `frozenAt`: ISO timestamp set by `prd_to_sprint.py` at PRD→sprint conversion
- `bigDoDHash`: SHA-256 of canonicalized `bigDefinitionOfDone` content

`sprint_lint.py` ERRORs on:
- Hash drift (`bigDoD` modified after freeze)
- Any story with empty `validationCriteria`
- Any story with empty `definitionOfDone` / `acceptance`

Atlas reviews the validation block before freeze per PM Rule 13. Late additions to bigDoD after freeze require a patch sprint (per dev/main workflow spec 2026-05-28). The natural unfreeze path is forking a new patch sprint from `dev`; no explicit unfreeze command exists.

`backlog_schema.py` enforces non-empty `validationCriteria` + `definitionOfDone` on every Story at backlog grooming time. Stories cannot enter a PRD without populated content.
```

- [ ] **Step 2: Add grooming-checklist note to PRD template**

Read `offices/pm/prds/_template-prd.md`. Find the grooming-checklist or "before running prd_to_sprint" section. Add:

```markdown
**Before running `prd_to_sprint.py`** (per spec 2026-05-28 / CIO directive #2):

1. Verify each selected Story carries non-empty `validationCriteria` + `definitionOfDone` in its Story.md (testable action + outcome pairs).
2. Route the draft to Atlas for validation-block review per PM Rule 13. Atlas verifies criteria are testable, bigDoD aggregates faithfully, no coverage holes vs Story `goal`.
3. Atlas PASS clears the freeze gate; PM then runs `prd_to_sprint.py` which pins the bigDoDHash. After that, late additions to bigDoD are ERRORs in `sprint_lint.py` — drill-discovered gaps require a patch sprint.
```

(If no grooming-checklist section exists, add it near the top of the template under a `## Grooming Checklist` heading.)

- [ ] **Step 3: Reinforce "at least 1 V-row" in Story template**

Read `offices/pm/backlog/_template-story.md`. Find the validation-criteria table section. Update the caption to:

```markdown
## Validation criteria (testable action + expected outcome; **at least 1 row required** per spec 2026-05-28)
| # | Testable action | Expected outcome |
|---|---|---|
| V-1 | <action> | <outcome> |
```

Similarly update the DoD section caption:

```markdown
## Definition of Done (**at least 1 criterion required** so Ralph knows when complete)
- <criterion>
- <criterion>
```

- [ ] **Step 4: Commit Task 5**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-14-sprint-contract-design.md offices/pm/prds/_template-prd.md offices/pm/backlog/_template-story.md
git commit -m "docs(pm): sprint contract addendum + PRD/Story template reinforcement (directive #2)

Per spec 2026-05-28:
- Sprint contract spec: new Validation-Criteria-Upfront Addendum documents
  freeze fields (frozenAt + bigDoDHash) + sprint_lint ERRORs + Atlas Rule 13.
- PRD template: grooming-checklist note requires non-empty validationCriteria
  + DoD before prd_to_sprint runs; route to Atlas for Rule 13 sign-off.
- Story template: captions reinforce 'at least 1 row required' for both
  validation criteria + DoD.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Mark agenda directive #2 DONE

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md`

- [ ] **Step 1: Read current agenda doc**

Run: `Read Z:/o/OBD2v2/offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md`.

- [ ] **Step 2: Mark §2 as DONE**

At the top of section "## 2. Validation criteria defined UPFRONT (before sprint work begins)", insert:

```markdown
**STATUS**: DONE 2026-05-28 -- spec committed `2bf40a6` (`docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`); implementation landed per `docs/superpowers/plans/2026-05-28-validation-criteria-upfront-contract.md`. backlog_schema enforces non-empty validationCriteria + DoD on every Story; prd_to_sprint freezes bigDoD via frozenAt + SHA-256 bigDoDHash; sprint_lint ERRORs on hash drift + per-story empty-list. PM Rule 13 (Atlas validation-block sign-off) landed. Sprint contract spec gained Validation-Criteria-Upfront Addendum; PRD + Story templates updated.
```

- [ ] **Step 3: Update Sequencing list (bottom of agenda doc)**

In the "## Sequencing (post-chain-merge order)" section, mark item 4 (which is Item 2 in the agenda numbering) as DONE:

```markdown
4. **Item 2** [DONE 2026-05-28]: sprint contract template updated to require user-story-level testable validation criteria; sprint_lint updated to enforce
```

(Note: the agenda's Sequencing list numbers items differently from the agenda section numbers. Item 4 in Sequencing corresponds to Item 2 (validation-criteria-upfront) in the agenda sections.)

- [ ] **Step 4: Commit Task 6**

```bash
cd Z:/o/OBD2v2
git add offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md
git commit -m "docs(pm): mark CIO directive #2 (validation-criteria-upfront) DONE in V0.28.0 agenda

Spec 2bf40a6; implementation landed via plan 2026-05-28-validation-criteria-upfront-contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update MEMORY.md standing directives + Current State pointer

**Files:**
- Modify: `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`

- [ ] **Step 1: Read current MEMORY.md**

Run: `Read C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`.

- [ ] **Step 2: Add Standing CIO directive entry**

In the "## Standing CIO directives (preserved)" section, append below the branching workflow line (which was added during directive #1):

```markdown
- **Validation-criteria-upfront (CIO directive 2026-05-23 #2; landed 2026-05-28):** every Story carries non-empty `validationCriteria` ([{action, outcome}]) + `definitionOfDone` (enforced by backlog_schema.py). sprint.json `validation.bigDefinitionOfDone` is frozen at PRD→sprint conversion via `frozenAt` + SHA-256 `bigDoDHash` (set by prd_to_sprint.py). sprint_lint ERRORs on hash drift + per-story empty-list. PM Rule 13 makes Atlas the reviewer at sprint-spin time. Spec at `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`. Natural unfreeze path = patch sprint per directive #1 dev/main workflow.
```

- [ ] **Step 3: Update Current State pointer**

Update the "## Current state pointer" line to reflect both directive #1 + #2 landings:

```markdown
## Current state pointer (2026-05-28 Session 44 -- dev/main BRANCHING WORKFLOW + VALIDATION-CRITERIA-UPFRONT CONTRACT both LANDED on main; dev bootstrapped; V0.28.0 Sprint 1 PRD draft is the next item)
```

Also update the V0.28.0 prep status block to reflect that BOTH #1 and #2 are now done:

```markdown
**V0.28.0 prep complete**: directive #1 (dev/main branching workflow) DONE 2026-05-28; directive #2 (validation-criteria-upfront) DONE 2026-05-28; directive #3 (backlog v2 migration) DONE 2026-05-27. V0.28.0 Sprint 1 PRD draft is the next item.
```

- [ ] **Step 4: Verify MEMORY.md well-formed**

Quick check via `head -50` that the edit didn't corrupt frontmatter or break the structure. (No commit step; MEMORY.md lives outside the OBD2v2 git tree.)

---

## Task 8: Final integration verify + push

**Files:**
- No file changes — verification + push only.

- [ ] **Step 1: Full pm test suite green**

```bash
cd Z:/o/OBD2v2
python -m pytest tests/pm/ -v 2>&1 | tail -10
```

Expected: 60+ pass, 0 fail (51 pre-existing + ~9 new from Tasks 1-3).

- [ ] **Step 2: pm_status.py renders cleanly**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/pm_status.py | head -20
```

Expected: `=== BRANCHES ===` block, then backlog tree. No crashes.

- [ ] **Step 3: sprint_lint green on current state**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/sprint_lint.py 2>&1 | tail -15
```

Expected: 0 errors (Sprint 42 is closed; its sprint.json predates freeze fields → graceful skip per spec §10). Possible new warnings on US-358 empty validationCriteria — that's correct diagnostic feedback, not blocking; Sprint 42 is closed.

- [ ] **Step 4: sprint_lint --backlog green**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/sprint_lint.py --backlog 2>&1 | tail -10
```

Expected: 0 errors (backlog has 0 Stories per session start; enforcement is on Stories only).

- [ ] **Step 5: Push both main + dev**

```bash
cd Z:/o/OBD2v2
# Push main (where this plan's work lives)
git push origin main

# Fast-forward dev to match main so V0.28.0 Sprint 1 starts from a clean dev = main
git checkout dev
git merge --ff-only main
git push origin dev
git checkout main
```

Expected: both branches end at the same tip; `git ls-remote origin main dev` shows matching hashes.

- [ ] **Step 6: Verify dev = main**

```bash
cd Z:/o/OBD2v2
git ls-remote origin main dev
```

Expected: two lines, both with the SAME hash.

---

## Self-Review

### Spec coverage check (against `docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`)

- §3 Backlog-side enforcement (Story content) → Task 1 (TDD). ✓
- §4 Sprint-side enforcement (the freeze):
  - §4.1 prd_to_sprint freeze fields → Task 2. ✓
  - §4.2 sprint_lint freeze-drift → Task 3. ✓
  - §4.3 per-story empty-list ERROR → Task 3. ✓
  - §4.4 fields legitimately changing after freeze (validatedAt etc.) — no code change needed; freeze only covers bigDoD. Verified Task 3 implementation does NOT hash other fields. ✓
  - §4.5 Natural unfreeze path — no code; documented in PM Rule 13 + spec addendum. Covered by Tasks 4 + 5. ✓
- §5 PM Rule 13 → Task 4. ✓
- §6 Sprint contract spec addendum → Task 5. ✓
- §7 PRD template note → Task 5. ✓
- §8 Script impacts summary — Tasks 1, 2, 3 cover the three scripts that change; others marked "no change required" → no task needed. ✓
- §9 TDD scope — 9 new tests across Tasks 1, 2, 3 (3 + 2 + 4). ✓
- §10 Bootstrap + rollout — no git op; Tasks 6 + 7 cover agenda + MEMORY.md. ✓
- §11 Cross-references — Task 6 updates the agenda doc; Task 7 updates MEMORY.md. ✓
- §12 Open questions deferred — Story template `_template-story.md` wording fix folded into Task 5 (step 3). sprint_lint warning on missing freeze fields → not folded in (current `if frozenAt` guard provides graceful degradation, which is silent — no warning emitted). The spec listed this as "PM lean: yes; small warning text" but it's truly optional. **Note for future enhancement**: could add a warn-only branch in Task 3 that prints "sprint.json predates freeze fields (legacy V0.27)" when `frozenAt` is absent + the sprint version starts with V0.27. Deferred to a separate housekeeping commit if PM wants it; not load-bearing.

### Placeholder scan

No "TBD", "TODO", "fill in later", or "similar to Task N" patterns. Each step has either exact code or exact bash with expected output. ✓

### Type / name consistency

- `_validateValidationCriteria(story)` — same signature in spec + Task 1 impl. ✓
- `_validateDefinitionOfDone(story)` — new helper, same shape as the existing one. ✓
- `convertPrdToSprint(prdPath, outPath, repoRoot)` — signature unchanged from existing code. ✓
- `lintSprintValidation(sprintData, repoRoot)` — signature unchanged. ✓
- Hash field name: `bigDoDHash` consistent across Tasks 2 + 3 + 5 spec addendum. ✓
- Timestamp field name: `frozenAt` consistent. ✓
- File paths: absolute `Z:/o/OBD2v2/...` consistent throughout. ✓

---

## Execution handoff notes

- Tasks 1, 2, 3 (TDD scripts) are mostly independent — each touches a different script + its own test file. Could parallelize via subagent dispatch but commits should stay sequential to keep audit trail clean.
- Tasks 4 (Rule 13) and 5 (templates + spec addendum) are textual; can land before or after Tasks 1-3.
- Task 6 (agenda mark DONE) requires Tasks 1-5 done (it's the seal).
- Task 7 (MEMORY.md) is a noop for git; can land anytime.
- Task 8 (final verify + push) MUST be last.
- Total commits: 7 (Tasks 1, 2, 3, 4, 5, 6 + final push has no commit). Task 7 not a git commit (MEMORY.md is outside repo).
