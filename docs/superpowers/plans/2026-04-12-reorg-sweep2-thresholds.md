# Sweep 2 — Legacy Threshold Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the legacy profile threshold system. Remove `alertThresholds` from `src/profile/types.py` Profile dataclass. Remove `profiles.availableProfiles[*].alertThresholds` from `src/obd_config.json`. Delete `src/alert/thresholds.py`. Update `src/alert/manager.py` and related modules to consume only the tiered threshold system. Zero tuning-value changes. All tests green.

**Architecture:** Two parallel alert-threshold systems exist in the codebase: the legacy `profiles.availableProfiles[*].alertThresholds` (single "critical" values per parameter) and the tiered `tieredThresholds` section (normal/caution/danger levels per parameter). The legacy system was built first; the tiered system replaced it but the legacy was left in place as dead weight. Nothing is in production. Spool has already audited both systems and confirmed the tiered values are authoritative. This sweep deletes the legacy code path.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git on Windows (MINGW64_NT). No new dependencies.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — read section 7 (sweep 2) before starting.

**Estimated effort:** 1–3 days. The unknown is ProfileManager coupling depth.

**Prerequisites:**
- Sweep 1 merged to `main`
- On a clean checkout of `main` with sweep 1 commits present
- `main` test suite is green

**Exit criteria:**
1. `src/alert/thresholds.py` deleted
2. `src/profile/types.py` Profile dataclass has no `alertThresholds` field
3. `src/obd_config.json` has no `alertThresholds` key under any profile
4. `src/alert/manager.py` consumes only the tiered threshold system
5. Profile concept (`daily`/`performance`) still works for non-threshold settings (polling interval, name, description)
6. **Every Spool-authoritative tuning value in `tieredThresholds` is unchanged** (verified by exact diff)
7. All tests green
8. Design doc session log updated
9. PR merged to `main`

**Risk**: Medium. `ProfileManager` may couple to legacy thresholds in non-obvious ways. The first task audits this before touching anything.

**Key safety constraint:** The tiered threshold values are Spool-authoritative. This sweep may NOT change any value in `tieredThresholds`. If any legacy value was unique (i.e., not represented in tiered), stop the sweep and file to Spool's inbox — do not delete it.

---

## Task 1: Setup — Create sweep branch, verify starting state

**Files:**
- No file changes

- [ ] **Step 1: Start from clean main**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git pull --ff-only 2>/dev/null || true
git status
git log --oneline -3
```
Expected: on `main`, last commit is the sweep 1 merge. Working tree clean.

- [ ] **Step 2: Create sweep 2 branch**

Run:
```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep2-thresholds main
git branch --show-current
```
Expected: `sprint/reorg-sweep2-thresholds`.

- [ ] **Step 3: Verify baseline green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```
Expected: same baseline count as end of sweep 1.

- [ ] **Step 4: Capture the current tieredThresholds values for later diff**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-before.json
cat /tmp/tiered-before.json | head -20
```

Expected: full `tieredThresholds` section dumped. This file is the "before" snapshot for the Spool-value preservation check in task 8.

---

## Task 2: Audit legacy threshold coupling

**Goal:** Map every file that touches `alertThresholds`, `rpmRedline`, `coolantTempCritical`, `boostPressureMax`, or `oilPressureLow` and classify its purpose:
- **THRESHOLD-LOGIC**: uses the value to decide whether to fire an alert → replace with tiered lookup
- **DISPLAY-REFERENCE**: uses the value for display (e.g., redline indicator on the tach) → preserve via a different mechanism
- **TEST-DATA**: test fixtures using legacy keys → rewrite to use tiered
- **OTHER**: classify case-by-case

**Files to audit:**
- Read: `src/profile/types.py`, `src/profile/manager.py`, `src/profile/helpers.py`, `src/alert/thresholds.py`, `src/alert/manager.py`, `src/alert/types.py`, `src/alert/helpers.py`
- Search: `tests/test_*.py` for references

- [ ] **Step 1: Create audit notes file**

Create `docs/superpowers/plans/sweep2-audit-notes.md`:
```markdown
# Sweep 2 Audit Notes (scratch — deleted before merge)

For each file: classification + symbols/functions affected + migration plan.
```

- [ ] **Step 2: Audit `src/alert/thresholds.py`**

Read the entire file.

Fill in audit notes:
```
## src/alert/thresholds.py
- Classification: THRESHOLD-LOGIC (entire file)
- Public symbols: convertThresholds, checkThresholdValue (confirm via dir())
- Callers: (fill in from step 3 below)
- Migration plan: delete file entirely, callers must stop using it
```

- [ ] **Step 3: Find callers of `src/alert/thresholds.py`**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "from src\.alert\.thresholds\|from alert\.thresholds\|from \.thresholds\|convertThresholds" src tests 2>/dev/null
```

Expected: hits inside `src/alert/` files (which import `thresholds.py` via the package `__init__.py`) and possibly in tests. Record every caller in the audit notes under `## src/alert/thresholds.py → Callers`.

- [ ] **Step 4: Audit `src/alert/manager.py` for legacy threshold usage**

Read: `src/alert/manager.py` fully (it's under 500 lines — read the whole thing).

For each occurrence of `alertThresholds`, `convertThresholds`, `rpmRedline`, `coolantTempCritical`, `boostPressureMax`, or `oilPressureLow`, note:
- Line number
- Classification (THRESHOLD-LOGIC / DISPLAY-REFERENCE / TEST-DATA / OTHER)
- What it does

Also note whether `AlertManager` currently consumes BOTH the legacy system AND the tiered system, or only one. Look for `tieredThresholds` references.

Write to `sweep2-audit-notes.md` under `## src/alert/manager.py`.

- [ ] **Step 5: Audit `src/alert/types.py`**

Read: `src/alert/types.py` fully.

Look for any types/constants tied to the legacy system (e.g., `AlertThreshold` dataclass). The `AlertThreshold` type itself is probably shared between legacy and tiered — do NOT classify it as legacy-only unless you verify it's unused by the tiered system.

Write findings to audit notes.

- [ ] **Step 6: Audit `src/alert/helpers.py`**

Read: `src/alert/helpers.py` fully.

Classify each function using legacy threshold keys.

Write findings to audit notes.

- [ ] **Step 7: Audit `src/profile/types.py`**

Read: `src/profile/types.py` fully.

Record:
- The `Profile` dataclass has an `alertThresholds: dict[str, Any]` field (line 82). This field must be removed.
- The `DEFAULT_ALERT_THRESHOLDS` constant (line 43-47) must be removed.
- `Profile.toDict()`, `Profile.fromDict()`, `Profile.fromConfigDict()`, and `Profile.getAlertConfigJson()` all reference `alertThresholds` — they must be updated.
- The `getAlertConfigJson()` method's entire purpose is to serialize `alertThresholds` for database storage. Check if anything consumes this method. If nothing does, delete the method. If something does, update the caller to not need it.

Write to audit notes.

- [ ] **Step 8: Audit `src/profile/manager.py`**

Read: `src/profile/manager.py` fully.

For each reference to `alertThresholds`:
- Line number
- Classification
- Does it read the legacy values to make a decision, or just pass them through?

Pay special attention to:
- `setAlertThresholds()` or similar mutation methods — probably need to be deleted
- Code that loads profile from config — will need update when `alertThresholds` comes out of the config file
- Code that writes profile to the database — may store `alertThresholds` as a JSON blob

Write detailed findings to audit notes. This module is the most likely source of hidden coupling per the design doc.

- [ ] **Step 9: Audit `src/profile/helpers.py`**

Read: `src/profile/helpers.py` fully.

Record all legacy threshold references and classifications.

- [ ] **Step 10: Search the database schema for legacy threshold columns**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "alert_threshold\|alertThreshold\|rpm_redline\|rpmRedline\|coolant_temp_critical\|CREATE TABLE.*profile\|ALTER TABLE.*profile" src 2>/dev/null
```

Look for:
- Database schema definitions (CREATE TABLE for profiles)
- Columns storing legacy threshold data
- Migration SQL that adds these columns

If the database schema has legacy-threshold columns, we need a schema migration. Record this in audit notes as **SCHEMA-MIGRATION-NEEDED**.

- [ ] **Step 11: Search tests for legacy threshold references**

Run:
```bash
cd Z:/o/OBD2v2
grep -rln "alertThresholds\|rpmRedline.*6500\|rpmRedline.*7000\|coolantTempCritical\|boostPressureMax\|oilPressureLow" tests 2>/dev/null
```

For each test file returned, note what it tests and whether the legacy reference is:
- A test fixture (needs rewrite to use tiered)
- A direct assertion (test must be updated or deleted)
- A parametrize input (rewrite)

Write to audit notes under `## tests/`.

- [ ] **Step 12: Find display-side references to legacy threshold keys**

Critical step: `rpmRedline` is a value that the display driver probably uses to draw the redline indicator on the tach. If we delete it from the profile config, the display breaks.

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "rpmRedline\|redline" src/display src/obd/display_manager.py 2>/dev/null
grep -rn "getAlertThreshold\|getProfile.*threshold" src 2>/dev/null
```

If the display references `rpmRedline` from the profile, we need to preserve that value somewhere the display can still read it. The tiered system already has `tieredThresholds.rpm.dangerMin` (= 7000) which IS the redline. Display code should read from there instead.

Record findings. If any display code reads `profile.alertThresholds['rpmRedline']`, plan to rewrite it to read `tieredThresholds['rpm']['dangerMin']`.

- [ ] **Step 13: Summarize audit**

Add a summary at the top of `sweep2-audit-notes.md`:
```
## Audit summary
- Files with THRESHOLD-LOGIC: N (list)
- Files with DISPLAY-REFERENCE coupling: N (list)
- Tests referencing legacy thresholds: N files (list)
- Schema migration needed: YES/NO
- Potential blockers: (list anything AMBIGUOUS or unclear)
```

If any blockers are identified:
- Create `offices/pm/tech_debt/TD-reorg-sweep2-profile-coupling.md` describing the coupling and what's needed to break it
- Stop sweep 2 and surface to CIO

- [ ] **Step 14: Commit audit notes**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep2-audit-notes.md
git commit -m "chore: sweep 2 audit notes"
```

---

## Task 3: Remove legacy threshold section from `src/obd_config.json`

**Goal:** Strip `alertThresholds` from each profile in the config. Verify `thresholdUnits` becomes dead (it existed only to describe legacy keys) and remove it too.

**Files:**
- Modify: `src/obd_config.json`

- [ ] **Step 1: Read current profiles section**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['profiles'], indent=2))"
```

Record the current structure for reference.

- [ ] **Step 2: Remove `alertThresholds` from each profile**

Edit `src/obd_config.json`. Find the `profiles.availableProfiles` array. For each profile object in the array, delete the `alertThresholds` key.

Before (daily profile example):
```json
{
  "id": "daily",
  "name": "Daily",
  "description": "Normal daily driving profile",
  "alertThresholds": {
    "rpmRedline": 6500,
    "coolantTempCritical": 220,
    "oilPressureLow": 20
  },
  "pollingIntervalMs": 1000
}
```

After:
```json
{
  "id": "daily",
  "name": "Daily",
  "description": "Normal daily driving profile",
  "pollingIntervalMs": 1000
}
```

Apply the same removal to the `performance` profile and any other profiles.

- [ ] **Step 3: Remove `profiles.thresholdUnits`**

The `thresholdUnits` section exists only to describe units for the legacy threshold keys. With the legacy keys gone, this section is dead.

Remove the entire `profiles.thresholdUnits` block from the config.

Before:
```json
"profiles": {
  "activeProfile": "daily",
  "thresholdUnits": {
    "rpmRedline": "rpm",
    "coolantTempCritical": "fahrenheit",
    "oilPressureLow": "psi",
    "boostPressureMax": "psi"
  },
  "availableProfiles": [...]
}
```

After:
```json
"profiles": {
  "activeProfile": "daily",
  "availableProfiles": [...]
}
```

- [ ] **Step 4: Verify the config is still valid JSON**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print('VALID'); print('Profiles count:', len(c['profiles']['availableProfiles']))"
```

Expected: `VALID` and profile count unchanged.

- [ ] **Step 5: Verify tieredThresholds is untouched**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-after-task3.json
diff /tmp/tiered-before.json /tmp/tiered-after-task3.json && echo "UNCHANGED"
```

Expected: `UNCHANGED` and no diff output. If there's any diff, you accidentally touched tiered values — revert and retry.

- [ ] **Step 6: Run config validator**

Run:
```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -20
```

Expected: passes, OR produces errors about missing `alertThresholds` fields (which the validator may still require). If it errors on missing `alertThresholds`, that's a validator coupling we need to fix — add to task 4 audit scope and continue.

- [ ] **Step 7: Commit config change**

Run:
```bash
cd Z:/o/OBD2v2
git add src/obd_config.json
git commit -m "refactor: remove legacy alertThresholds from profiles in obd_config.json (sweep 2, task 3)

The legacy profile threshold system is superseded by tieredThresholds.
Profile entries now contain only non-threshold settings (id, name,
description, pollingIntervalMs).

tieredThresholds values unchanged (verified via diff)."
```

---

## Task 4: Update `src/common/config_validator.py` if needed

**Goal:** If the config validator required `alertThresholds`, relax the requirement. If it didn't, skip this task.

**Files:**
- Conditionally modify: `src/common/config_validator.py`

- [ ] **Step 1: Check if validator requires alertThresholds**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "alertThresholds\|alert_thresholds" src/common/config_validator.py 2>/dev/null
```

If zero hits: this task is a no-op. Skip to task 5.

If hits: continue to step 2.

- [ ] **Step 2: Read the referenced lines with context**

Read: `src/common/config_validator.py`, the lines where `alertThresholds` appears plus 10 lines of context around each.

Decide:
- If the reference is a `DEFAULTS` dot-notation key (e.g., `'profiles.availableProfiles.alertThresholds.rpmRedline': 6500`), delete that entry.
- If the reference is a REQUIRED_FIELDS entry, remove the entry from the list.
- If the reference is in a validation function, replace the validation logic to either skip alertThresholds or require tieredThresholds instead.

- [ ] **Step 3: Delete legacy-threshold validator logic**

Apply the removals identified in step 2. Do NOT add tieredThresholds validation logic here — that's sweep 4's scope. For sweep 2, we're only REMOVING legacy refs from the validator, not adding new ones.

- [ ] **Step 4: Rerun validator**

Run:
```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -10
```

Expected: passes cleanly.

- [ ] **Step 5: Commit validator change (if made)**

Run:
```bash
cd Z:/o/OBD2v2
git add src/common/config_validator.py
git commit -m "refactor: remove legacy alertThresholds from config validator (sweep 2, task 4)"
```

---

## Task 5: Remove `alertThresholds` field from `src/profile/types.py`

**Goal:** Strip the legacy field and all references to it from the Profile dataclass and helpers.

**Files:**
- Modify: `src/profile/types.py`

- [ ] **Step 1: Delete the DEFAULT_ALERT_THRESHOLDS constant**

Read `src/profile/types.py`. Find:
```python
# Default alert thresholds for the default profile
DEFAULT_ALERT_THRESHOLDS: dict[str, Any] = {
    'rpmRedline': 6500,
    'coolantTempCritical': 220,
    'oilPressureLow': 20,
}
```

Delete this block (constant + comment).

- [ ] **Step 2: Remove `alertThresholds` field from Profile dataclass**

Find:
```python
@dataclass
class Profile:
    ...
    id: str
    name: str
    description: str | None = None
    alertThresholds: dict[str, Any] = field(default_factory=dict)
    pollingIntervalMs: int = DEFAULT_POLLING_INTERVAL_MS
    createdAt: datetime | None = None
    updatedAt: datetime | None = None
```

Delete the `alertThresholds` line.

Also update the docstring `Attributes:` section to remove the `alertThresholds:` entry.

- [ ] **Step 3: Update `Profile.toDict()`**

Find:
```python
def toDict(self) -> dict[str, Any]:
    return {
        'id': self.id,
        'name': self.name,
        'description': self.description,
        'alertThresholds': self.alertThresholds.copy(),
        'pollingIntervalMs': self.pollingIntervalMs,
        ...
    }
```

Remove the `'alertThresholds': self.alertThresholds.copy(),` line.

- [ ] **Step 4: Update `Profile.fromDict()`**

Find:
```python
return cls(
    id=data['id'],
    name=data['name'],
    description=data.get('description'),
    alertThresholds=data.get('alertThresholds', {}),
    pollingIntervalMs=data.get('pollingIntervalMs', DEFAULT_POLLING_INTERVAL_MS),
    createdAt=createdAt,
    updatedAt=updatedAt,
)
```

Remove the `alertThresholds=...` line.

- [ ] **Step 5: Update `Profile.fromConfigDict()`**

Find:
```python
return cls(
    id=configProfile['id'],
    name=configProfile['name'],
    description=configProfile.get('description'),
    alertThresholds=configProfile.get('alertThresholds', {}),
    pollingIntervalMs=configProfile.get(
        'pollingIntervalMs', DEFAULT_POLLING_INTERVAL_MS
    ),
)
```

Remove the `alertThresholds=...` line.

- [ ] **Step 6: Delete `Profile.getAlertConfigJson()` method**

Find:
```python
def getAlertConfigJson(self) -> str:
    """
    Get alert thresholds as JSON string for database storage.
    """
    import json
    return json.dumps(self.alertThresholds)
```

Delete the entire method.

- [ ] **Step 7: Import usage check**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "DEFAULT_ALERT_THRESHOLDS\|getAlertConfigJson" src tests 2>/dev/null
```

Expected: zero hits. If any exist, they're broken references — update them in the next task.

- [ ] **Step 8: Quick smoke test — import the module**

Run:
```bash
cd Z:/o/OBD2v2
python -c "from src.profile.types import Profile; p = Profile(id='daily', name='Daily'); print(p.toDict())"
```

Expected: prints a dict with `id`, `name`, `description`, `pollingIntervalMs`, `createdAt`, `updatedAt` (no `alertThresholds`).

- [ ] **Step 9: Commit the profile types change**

Run:
```bash
cd Z:/o/OBD2v2
git add src/profile/types.py
git commit -m "refactor: remove alertThresholds from Profile dataclass (sweep 2, task 5)"
```

---

## Task 6: Update ProfileManager and helpers to not reference legacy thresholds

**Goal:** Find every remaining reference to `alertThresholds` in `src/profile/manager.py` and `src/profile/helpers.py`, and fix them.

**Files:**
- Modify: `src/profile/manager.py`
- Modify: `src/profile/helpers.py` (if needed)

- [ ] **Step 1: Find all alertThresholds references in profile package**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "alertThresholds\|DEFAULT_ALERT_THRESHOLDS" src/profile/manager.py src/profile/helpers.py 2>/dev/null
```

Record each line number.

- [ ] **Step 2: Open `src/profile/manager.py` and review each reference**

For each line with `alertThresholds`:
- If it's a method that MUTATES the profile's thresholds (e.g., `updateAlertThresholds(self, profile_id, thresholds)`), delete the method.
- If it's a read that returns `profile.alertThresholds`, delete the accessor or return `{}`.
- If it's a database write storing `profile.alertThresholds` as JSON, delete that column from the SQL and the Python write path.
- If it's a read from the database loading `alert_config_json`, delete the column from the SELECT and the Python read path.

Cross-reference with the task 2 audit notes (`sweep2-audit-notes.md`) for the specific migration plan per reference.

- [ ] **Step 3: Remove any database schema references to legacy thresholds**

If task 2 step 10 found `alert_config_json` or similar columns in the profile table schema, remove them from:
- The `CREATE TABLE` SQL in the profile manager (or wherever the schema lives)
- Any migration SQL
- Any INSERT / UPDATE statements referencing those columns
- Any SELECT lists reading those columns

**Do NOT try to migrate existing data** — nothing is in production, there's no data to preserve.

- [ ] **Step 4: Clean up `src/profile/helpers.py`**

If helpers.py has functions like `buildDefaultThresholds()` or `migrateLegacyThresholds()`, delete them.

Also check for references to `DEFAULT_ALERT_THRESHOLDS` (which we deleted in task 5) — any remaining reference is a broken import.

- [ ] **Step 5: Run profile package tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -k "profile" --tb=short 2>&1 | tail -30
```

Expected: most profile tests pass. Failures will be either:
- Tests asserting on `profile.alertThresholds` — need rewriting (task 8)
- Tests importing `DEFAULT_ALERT_THRESHOLDS` — need rewriting (task 8)
- Legitimate breakage because we removed something still used

If legitimate breakage, fix it before moving on.

- [ ] **Step 6: Commit profile manager update**

Run:
```bash
cd Z:/o/OBD2v2
git add src/profile/manager.py src/profile/helpers.py
git commit -m "refactor: remove legacy alertThresholds from ProfileManager (sweep 2, task 6)"
```

---

## Task 7: Delete `src/alert/thresholds.py` and update `src/alert/manager.py`

**Goal:** Remove the legacy alert threshold helper module and break the AlertManager's dependency on it.

**Files:**
- Delete: `src/alert/thresholds.py`
- Modify: `src/alert/manager.py`
- Modify: `src/alert/__init__.py` (to stop re-exporting thresholds symbols)
- Possibly modify: `src/alert/helpers.py`

- [ ] **Step 1: Review the audit findings for `src/alert/manager.py`**

Open `docs/superpowers/plans/sweep2-audit-notes.md` and re-read the `## src/alert/manager.py` section.

Key questions:
- Does AlertManager already use `tieredThresholds` for its alert logic? If yes, the legacy path is dead code and removal is cheap.
- If no, AlertManager currently uses ONLY the legacy system and must be rewritten to consume the tiered system. This is larger scope than expected — stop, surface to CIO, consider splitting into a separate sub-sweep.

- [ ] **Step 2: Remove `from .thresholds import ...` from `src/alert/manager.py`**

Find in `src/alert/manager.py`:
```python
from .thresholds import convertThresholds, ...
```
(or whatever the exact import is)

Delete the import line.

- [ ] **Step 3: Remove `convertThresholds()` calls from AlertManager**

Find every call to `convertThresholds()` in `src/alert/manager.py`. For each:
- If the call was converting a legacy-format dict to `AlertThreshold` objects, delete the call and the surrounding legacy code path
- If the AlertManager now uses tiered thresholds directly, there's no replacement needed — just delete

- [ ] **Step 4: Update AlertManager initialization**

If `AlertManager.__init__()` or `createAlertManagerFromConfig()` reads from `profiles.availableProfiles[*].alertThresholds`, remove that code. The constructor should only read `config['tieredThresholds']`.

- [ ] **Step 5: Update `src/alert/__init__.py`**

Read: `src/alert/__init__.py`

If it re-exports symbols from `thresholds.py` (e.g., `from .thresholds import convertThresholds`), remove those re-exports. Also remove the re-exported symbol names from `__all__`.

- [ ] **Step 6: Delete `src/alert/thresholds.py`**

Run:
```bash
cd Z:/o/OBD2v2
git rm src/alert/thresholds.py
git status
```

Expected: file deleted, staged.

- [ ] **Step 7: Update `src/alert/helpers.py` if needed**

If helpers.py imports from `.thresholds` or uses legacy threshold keys, remove those references.

- [ ] **Step 8: Run alert package tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -k "alert" --tb=short 2>&1 | tail -30
```

Expected: most pass. Failures:
- Tests importing `from src.alert.thresholds import ...` — need rewriting (task 8)
- Tests asserting on legacy AlertManager behavior — need rewriting (task 8)
- Legitimate breakage because AlertManager logic now differs — stop and fix

- [ ] **Step 9: Commit the alert cleanup**

Run:
```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: delete src/alert/thresholds.py, remove legacy path from AlertManager (sweep 2, task 7)"
```

---

## Task 8: Rewrite or delete tests that referenced legacy thresholds

**Goal:** Update every test that broke due to the removals in tasks 3-7. Rewrite using tiered threshold patterns where the test coverage is still valuable; delete tests that only verified legacy behavior.

**Files:**
- Modify: test files identified in task 2 step 11

- [ ] **Step 1: Run the full fast suite and capture failures**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -q -m "not slow" --tb=short 2>&1 | tail -60
```

Record every failing test and its error message. Common patterns:
- `AttributeError: 'Profile' object has no attribute 'alertThresholds'` — test fixture uses legacy field
- `ModuleNotFoundError: src.alert.thresholds` — test imports the deleted module
- `KeyError: 'alertThresholds'` — test reads from config
- `TypeError: __init__() got an unexpected keyword argument 'alertThresholds'` — test creates a Profile with the removed kwarg

- [ ] **Step 2: Fix each failing test one at a time**

For each failing test:
1. Read the test function
2. Decide: rewrite to use tiered, or delete because legacy-specific
3. Make the minimal edit
4. Run just that test to confirm it passes:
   ```bash
   pytest tests/test_X.py::test_Y -v
   ```
5. Commit if the test file is fully fixed:
   ```bash
   git add tests/test_X.py
   git commit -m "test: update test_X for tiered thresholds (sweep 2, task 8)"
   ```

**Decision criteria** — rewrite vs. delete:
- If the test verifies end-to-end alert firing: rewrite to use tiered
- If the test verifies the legacy format specifically: delete (the behavior being tested no longer exists)
- If the test verifies Profile serialization includes `alertThresholds`: delete or rewrite to verify the new serialized shape
- If the test is a parametrize with legacy values: replace the values with tiered equivalents

- [ ] **Step 3: Run the fast suite again**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```

Expected: all pass.

If still failing, repeat step 2 for remaining failures.

- [ ] **Step 4: Run the full suite (slow tests included)**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: all pass, same or slightly lower count than baseline (some legacy-only tests were deleted, that's OK — coverage should not drop below 80%).

- [ ] **Step 5: Check coverage did not drop**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ --cov=src --cov-report=term 2>&1 | tail -10
```

Expected: coverage ≥ 80%. If it dropped below, either the deletions went too far (add back a test that exercises the non-legacy behavior) or the sweep uncovered a coverage gap that already existed (file a tech-debt note, don't block the sweep on it).

---

## Task 9: Spool-value preservation check

**Goal:** Verify that tiered threshold values are unchanged from the sweep 2 start. This is the single most important safety check in the sweep.

**Files:**
- Read-only: `src/obd_config.json`
- Read-only: `/tmp/tiered-before.json`

- [ ] **Step 1: Re-dump the current tieredThresholds**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-after.json
```

- [ ] **Step 2: Diff against the snapshot from task 1**

Run:
```bash
diff /tmp/tiered-before.json /tmp/tiered-after.json
```

Expected: **zero output** (no diff). If any diff appears, a Spool-authoritative value was accidentally modified during sweep 2. **Stop immediately.** Surface to CIO: "sweep 2 step 9 failed — tiered values drifted." Do not merge.

- [ ] **Step 3: Double-check a few specific Spool-authoritative values**

Run:
```bash
cd Z:/o/OBD2v2
python <<'PY'
import json
c = json.load(open('src/obd_config.json'))
t = c['tieredThresholds']
# Values confirmed by Spool's 2026-04-12 audit (Known Non-Variances section)
checks = {
    ('coolantTemp', 'caution'): 180,
    ('coolantTemp', 'warningMax'): 210,
    ('coolantTemp', 'dangerMax'): 220,
    ('rpm', 'dangerMin'): 7000,
    ('stft', 'caution'): 5,
}
for (param, key), expected in checks.items():
    actual = t.get(param, {}).get(key)
    status = 'OK' if actual == expected else 'DRIFT'
    print(f"{status}: {param}.{key} = {actual} (expected {expected})")
PY
```

Expected: all `OK`. Any `DRIFT` is a blocker — stop and surface to CIO.

**Note**: the threshold key names in the check above (`caution`, `warningMax`, `dangerMax`, `dangerMin`) may not match the actual schema. If the check errors out with `None` for all keys, the schema uses different key names. Read `src/obd_config.json` to find the actual keys and adjust the check dict. The GOAL is to confirm the Spool-authoritative numeric values (180, 210, 220, 7000, 5) still appear in the file somewhere — the exact key path is secondary.

---

## Task 10: Full test suite, lint, type check, simulator smoke test

**Files:**
- No changes — verification only

- [ ] **Step 1: Full test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 2: Ruff**

Run:
```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -10
```
Expected: no new errors.

- [ ] **Step 3: Mypy**

Run:
```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -10
```
Expected: no new errors.

- [ ] **Step 4: Simulator smoke test**

Run:
```bash
cd Z:/o/OBD2v2
timeout 30 python src/main.py --simulate --dry-run 2>&1 | tail -30
```

Expected: clean startup, no missing-import errors, no unhandled exceptions.

- [ ] **Step 5: Confirm alert firing still works in simulator**

The simulator exercises alert logic. If it runs clean, alerts are still firing correctly via the tiered system.

---

## Task 11: Design doc session log, cleanup, merge

**Files:**
- Modify: `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 12)
- Delete: `docs/superpowers/plans/sweep2-audit-notes.md`

- [ ] **Step 1: Delete audit notes scratch file**

Run:
```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep2-audit-notes.md
git commit -m "chore: remove sweep 2 audit notes scratch file"
```

- [ ] **Step 2: Append sweep 2 status to design doc section 12**

Read: `docs/superpowers/specs/2026-04-12-reorg-design.md`, find section 12.

Append a row:
```markdown
| YYYY-MM-DD | 2 | Sweep 2 complete. Deleted src/alert/thresholds.py, removed alertThresholds from Profile dataclass and obd_config.json profiles section, rewrote AlertManager/ProfileManager to consume only tieredThresholds. Spool-value preservation verified (diff empty). Full test suite passes (NNN tests). Simulator smoke test green. |
```

Replace `YYYY-MM-DD` and `NNN` with actuals.

- [ ] **Step 3: Commit the design doc update**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 2 status update"
```

- [ ] **Step 4: Surface to CIO for approval to merge**

Tell the CIO:
> "Sweep 2 complete. Legacy threshold system removed, tiered system is now the only alert-threshold path. Spool-authoritative values verified unchanged. All tests green, simulator green. Ready to merge to main?"

Wait for explicit approval.

- [ ] **Step 5: After CIO approval, merge to main**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep2-thresholds -m "Merge sprint/reorg-sweep2-thresholds: Sweep 2 complete — legacy threshold merge

Sweep 2 of 6 for the structural reorganization (B-040).
- Deleted src/alert/thresholds.py (legacy 169-line helper)
- Removed alertThresholds field from Profile dataclass
- Removed profiles.*.alertThresholds and thresholdUnits from obd_config.json
- Updated AlertManager and ProfileManager to consume only tieredThresholds
- Spool-authoritative values preserved byte-for-byte (verified via diff)
- Full test suite passing
- Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md"
git log --oneline -5
```

- [ ] **Step 6: Confirm main is green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 7: Announce completion**

Tell the CIO:
> "Sweep 2 merged to main. Sweep 3 (tier split + contracts) is the next and highest-risk sweep. Ready to start whenever you're ready."

Wait for CIO direction.

---

## End of Sweep 2 Plan

**Success criteria:**
- ✅ `src/alert/thresholds.py` deleted
- ✅ `alertThresholds` removed from Profile dataclass and config
- ✅ AlertManager consumes only tiered system
- ✅ All Spool-authoritative values unchanged
- ✅ All tests green
- ✅ Merged to main

**On to sweep 3**: `docs/superpowers/plans/2026-04-12-reorg-sweep3-tier-split.md`
