# Sweep 2b — Legacy Threshold Dead-Code Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the legacy profile-threshold system that Sweep 2a orphaned. **Zero behavior change** — every production path already uses `config['tieredThresholds']` via `AlertManager.setThresholdsFromConfig()`. This sweep removes the corpses: `src/alert/thresholds.py`, `Profile.alertThresholds`, `alert_config_json` DB column, `profiles.*.alertThresholds` config keys, and every re-export / fixture that still references them.

**Why split from Sweep 2a:** Sweep 2 was split after the Task 2 audit proved `AlertManager` was 100% legacy-bound. Sweep 2a rewired the runtime path (medium risk). Sweep 2b is pure cleanup (low risk). Separating them protects the runtime change with an independent merge and keeps each PR reviewable.

**Architecture (post-2a baseline):**
- `AlertManager.setThresholdsFromConfig(config)` consumes `config['tieredThresholds']` and populates `_profileThresholds[profileId]` with `AlertThreshold` objects. Profile switching no longer changes thresholds (every profile gets the same tiered-derived list).
- `Profile.alertThresholds`, `DEFAULT_ALERT_THRESHOLDS`, `convertThresholds()`, `setProfileThresholds()`, `getAlertThresholdsForProfile()`, `THRESHOLD_KEY_TO_PARAMETER`, `_validateAlertThresholds()`, and the `alert_config_json` column are all orphaned — loaded and stored but never consumed for alert-firing decisions.
- The 15 test fixtures Sweep 2a updated have BOTH `alertThresholds` (legacy) AND `tieredThresholds` (new) adjacent — the legacy keys are no-ops but still present.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git on Windows (MINGW64_NT). No new dependencies.

**Design doc:** `docs/superpowers/specs/2026-04-12-reorg-design.md` — section 7 (sweep 2), now superseded by 2a plan + this 2b plan.

**Audit notes (required read):** `docs/superpowers/plans/sweep2-audit-notes.md` — still committed on `main`, contains per-file line numbers and migration instructions from the original audit. **This plan deletes the audit notes file in Task 11.**

**Estimated effort:** Half a day to 1 day. Pure mechanical delete, no design decisions outside the two flagged below.

**Prerequisites:**
- Sweep 2a merged to `main` (commit `418b55b`)
- On a clean checkout of `main` with 2a commits present
- Baseline: **1503 fast-suite passing, 1521 full-suite passing, 3 fast-suite skipped, 4 full-suite skipped, 19 deselected** (numbers per `project_sweep2a_complete.md` memory)
- `main` test suite is green

**Exit criteria:**
1. `src/alert/thresholds.py` deleted
2. `Profile` dataclass (`src/profile/types.py`) has no `alertThresholds` field, no `getAlertConfigJson()` method, no `DEFAULT_ALERT_THRESHOLDS` constant
3. `src/obd_config.json` has no `profiles.*.alertThresholds` and no `profiles.thresholdUnits`; `tieredThresholds` byte-identical to pre-sweep snapshot
4. `src/obd/database.py` `SCHEMA_PROFILES` has no `alert_config_json` column
5. `src/profile/manager.py` INSERT/UPDATE/SELECT/row-parse paths have no `alert_config_json` references
6. `src/alert/manager.py` has no `from .thresholds import` and no `setProfileThresholds()` legacy method; `convertThresholds` is unused anywhere
7. `src/alert/__init__.py`, `src/alert/types.py`, `src/alert/helpers.py`, `src/obd/__init__.py` have no references to `convertThresholds`, `checkThresholdValue`, `getDefaultThresholds`, `validateThresholds`, `THRESHOLD_KEY_TO_PARAMETER`, `getAlertThresholdsForProfile`
8. `src/obd/config/loader.py` has no `_validateAlertThresholds()` function, no call to it, and the default-profile injection dict has no `alertThresholds` key
9. Every test in `tests/` has zero matches for `alertThresholds`, `alert_config_json`, `getAlertConfigJson`, `DEFAULT_ALERT_THRESHOLDS`, `getAlertThresholdsForProfile` (outside comments explicitly marking the key as removed)
10. The 3 mark-skipped tests from Sweep 2a are disposed per the table in the "Design decisions" section: Tests 1 & 2 deleted + backlog filed; Test 3 rewritten (mock `setActiveProfile` raising instead of `setProfileThresholds`) and unskipped
11. Backlog entry `offices/pm/backlog/B-XXX-per-profile-tiered-threshold-overrides.md` filed
12. `docs/superpowers/plans/sweep2-audit-notes.md` deleted
13. Full fast suite green (**target: 1504 passing, 0 skipped** — up from 1503/3 because Test 3 is now running; Tests 1 & 2 no longer exist); full suite green
14. Ruff clean, mypy clean on touched files
15. Simulator smoke test green
16. Design doc section 12 session log appended with sweep 2b row
17. Merged to `main` with CIO approval

**Risk:** Low. The audit in Sweep 2a already proved every production path was rewired. Sweep 2b only touches code that nothing reads from. The single risk is accidentally deleting something we thought was dead but isn't — mitigated by running the fast suite after each task.

**Safety constraint:** `tieredThresholds` values in `src/obd_config.json` are Spool-authoritative and **must not change**. Task 9 diffs against a snapshot. Any drift = immediate stop + `offices/tuner/inbox/` note.

**Design decisions (confirmed with CIO 2026-04-13):**

1. **Database schema change: no migration, no schema-version bump.** Nothing is in production; the codebase has no existing schema-version machinery. This sweep removes `alert_config_json` from the `CREATE TABLE profiles` DDL directly. Test DBs are per-test `tempfile.mktemp()` so they inherit the new schema automatically. Any long-lived dev DB on CIO's workstation must be deleted and recreated manually.

2. **Mark-skipped test policy: rewrite-first, delete+backlog only when square-peg.** CIO directive: prefer rewrites to deletions for clean architecture going forward, but do NOT force a test into a shape that no longer makes sense — if a test asserts behavior that can no longer exist, delete it and file a backlog entry for the future feature that would resurrect it. Per-test decisions (each test was read end-to-end before classification):
    - **Test 1 — `test_orchestrator_alerts.py::test_profileChange_updatesAlertThresholds`** (line 561): **delete + backlog**. Square-peg. Asserts that profile switch rebinds thresholds *per profile*. Post-Sweep-2a, thresholds are global (not per-profile), so this behavior cannot happen. Adjacent test `test_profileChange_setsActiveProfile` (line 597) already covers the remaining valid assertion (`setActiveProfile` being called).
    - **Test 2 — `test_orchestrator_profiles.py::test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds`** (line 608): **delete + backlog**. Same scenario as Test 1, tested from the profile side. Adjacent test `test_handleProfileChange_updatesActiveProfile_onAlertManager` (line 643) already covers `setActiveProfile` being called.
    - **Tests 1 & 2 share one backlog entry**: `offices/pm/backlog/B-XXX-per-profile-tiered-threshold-overrides.md` — future feature where profiles override specific `tieredThresholds` values (e.g., a track profile with higher RPM `dangerMin`). If that feature ships, these tests get recreated against the new API.
    - **Test 3 — `test_orchestrator_profiles.py::test_handleProfileChange_survivesAlertManagerError_continuesRunning`** (line 710): **rewrite**. The underlying concern — "orchestrator survives AlertManager errors during profile change and keeps running" — is still valid robustness coverage. Only the mocked method that throws changes from `setProfileThresholds` → `setActiveProfile`.

---

## Task 1: Setup — branch, baseline, snapshot, decision review

**Files:** No file changes.

- [ ] **Step 1: Start from clean main**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git status
git log --oneline -5
```
Expected: on `main`, top commit is `12188b3 docs: Sweep 2a session closeout — handoff updated for Sweep 2b pickup`. Working tree may have known unrelated `offices/pm/.claude/*` noise from parallel PM sessions — do not touch it.

- [ ] **Step 2: Create sweep 2b branch**

Run:
```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep2b-delete main
git branch --show-current
```
Expected: `sprint/reorg-sweep2b-delete`.

- [ ] **Step 3: Verify baseline green (fast suite)**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -5
```
Expected: `1503 passed, 3 skipped, 19 deselected` (or equivalent matching the `main` baseline). Record the exact count in the task comment.

- [ ] **Step 4: Snapshot the current `tieredThresholds`**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-before-2b.json
wc -l /tmp/tiered-before-2b.json
head -5 /tmp/tiered-before-2b.json
```
Expected: file created, starts with `{`, ~60-70 lines. This is the snapshot for Task 9's preservation check.

- [ ] **Step 5: Acknowledge the two confirmed design decisions**

Both decisions were confirmed by CIO 2026-04-13 during plan review (see "Design decisions" section above):
1. Schema change direct (no migration, no version bump) — proceed to Task 4 as written
2. Test policy: rewrite-first, but delete+backlog for the 2 square-peg tests; rewrite the 1 robustness test — proceed to Task 8 as written

No further confirmation needed. Move to Task 2.

---

## Task 2: Remove `alertThresholds` and `thresholdUnits` from `src/obd_config.json`

**Goal:** Strip the legacy keys from the config. Verify `tieredThresholds` byte-identical.

**Files:**
- Modify: `src/obd_config.json`

- [ ] **Step 1: Remove `alertThresholds` from `daily` profile**

Read `src/obd_config.json`, find the `daily` profile entry (around line 108-118). Delete the `alertThresholds` dict block and its trailing comma such that `pollingIntervalMs` is still valid JSON.

Before:
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

- [ ] **Step 2: Remove `alertThresholds` from `performance` profile**

Same removal around lines 119-130.

After:
```json
{
    "id": "performance",
    "name": "Performance",
    "description": "Track day / spirited driving profile",
    "pollingIntervalMs": 500
}
```

- [ ] **Step 3: Remove `profiles.thresholdUnits` block**

Delete the entire `thresholdUnits` block (around lines 101-106). The `profiles` section should go directly from `activeProfile` to `availableProfiles`.

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
    "availableProfiles": [ ... ]
}
```

After:
```json
"profiles": {
    "activeProfile": "daily",
    "availableProfiles": [ ... ]
}
```

- [ ] **Step 4: Verify JSON still parses**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print('VALID'); print('Profile count:', len(c['profiles']['availableProfiles'])); print('Has tieredThresholds:', 'tieredThresholds' in c)"
```
Expected: `VALID`, profile count `2`, `Has tieredThresholds: True`.

- [ ] **Step 5: Verify `tieredThresholds` untouched**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-after-task2.json
diff /tmp/tiered-before-2b.json /tmp/tiered-after-task2.json && echo "UNCHANGED"
```
Expected: `UNCHANGED`, no diff output. If any diff, revert and retry.

- [ ] **Step 6: Run config validator**

Run:
```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -20
```
Expected: either passes cleanly, OR errors about `_validateAlertThresholds` finding missing fields — that's expected because Task 3 hasn't run yet. If the error matches that pattern, note it and continue; Task 3 fixes it. If the error is different, stop and investigate.

- [ ] **Step 7: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/obd_config.json
git commit -m "refactor(sweep2b): remove legacy alertThresholds and thresholdUnits from obd_config.json

Part of Sweep 2b dead-code delete. AlertManager consumes tieredThresholds
only (rewired in Sweep 2a). These legacy keys were no-ops.

tieredThresholds byte-identical (verified)."
```

---

## Task 3: Clean up `src/obd/config/loader.py`

**Goal:** Delete `_validateAlertThresholds()`, its call site, and the default-profile injection dict.

**Files:**
- Modify: `src/obd/config/loader.py`

- [ ] **Step 1: Delete the call to `_validateAlertThresholds(config)`**

Find line 258 in `src/obd/config/loader.py`:
```python
    _validateAlertThresholds(config)
```
Delete this line.

- [ ] **Step 2: Remove `alertThresholds` key from default profile injection**

Find around lines 343-353 (`_validateProfilesConfig` function, default profile creation branch):
```python
        config['profiles']['availableProfiles'] = [{
            'id': 'daily',
            'name': 'Daily',
            'description': 'Default daily driving profile',
            'alertThresholds': {
                'rpmRedline': 6500,
                'coolantTempCritical': 220
            },
            'pollingIntervalMs': 1000
        }]
```

Delete the `alertThresholds` key block:
```python
        config['profiles']['availableProfiles'] = [{
            'id': 'daily',
            'name': 'Daily',
            'description': 'Default daily driving profile',
            'pollingIntervalMs': 1000
        }]
```

- [ ] **Step 3: Delete the entire `_validateAlertThresholds()` function**

Find lines ~420-456, the function definition:
```python
def _validateAlertThresholds(config: dict[str, Any]) -> None:
    """
    Validate alert threshold values are reasonable.
    ...
    """
    ...
```

Delete the entire function body (def through last `raise`/`logger.warning` line). Also delete the blank line separator before the next function.

- [ ] **Step 4: Verify no dangling references**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "_validateAlertThresholds\|alertThresholds" src/obd/config/loader.py
```
Expected: zero matches.

- [ ] **Step 5: Run config validator**

Run:
```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -15
```
Expected: passes cleanly.

- [ ] **Step 6: Run fast suite for loader tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_obd_config_loader.py -x -q --tb=short 2>&1 | tail -30
```
Expected: if failures reference `alertThresholds` in test fixtures, that's Task 7 scope — note the count and continue. Any other failure is a real problem — stop and investigate.

- [ ] **Step 7: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/obd/config/loader.py
git commit -m "refactor(sweep2b): delete _validateAlertThresholds and default injection

Removes the legacy validator function, its call from loadAndValidateObdConfig,
and the alertThresholds dict from the default-profile fallback injection in
_validateProfilesConfig.

Tests updated in Task 7."
```

---

## Task 4: Profile package atomic cleanup

**Goal:** Remove the legacy threshold surface from the Profile dataclass and everything that reads from it: `src/profile/types.py`, `src/profile/manager.py`, `src/profile/helpers.py`, `src/profile/__init__.py`, and `src/obd/database.py` `SCHEMA_PROFILES`. These files must all change together — the Profile dataclass and its consumers are tightly coupled.

**Files:**
- Modify: `src/profile/types.py`
- Modify: `src/profile/manager.py`
- Modify: `src/profile/helpers.py`
- Modify: `src/profile/__init__.py`
- Modify: `src/obd/database.py`

- [ ] **Step 1: `src/profile/types.py` — delete `DEFAULT_ALERT_THRESHOLDS` constant**

Find lines 42-47:
```python
# Default alert thresholds for the default profile
DEFAULT_ALERT_THRESHOLDS: dict[str, Any] = {
    'rpmRedline': 6500,
    'coolantTempCritical': 220,
    'oilPressureLow': 20,
}
```
Delete these 6 lines (constant + comment).

- [ ] **Step 2: `src/profile/types.py` — remove `alertThresholds` field from Profile dataclass**

Find line 82:
```python
    alertThresholds: dict[str, Any] = field(default_factory=dict)
```
Delete this line.

Also update the class docstring (around line 69-77) — remove the `alertThresholds: Dictionary of alert threshold settings` line from `Attributes:`.

- [ ] **Step 3: `src/profile/types.py` — update `toDict()`**

Find line 98:
```python
            'alertThresholds': self.alertThresholds.copy(),
```
Delete this line.

- [ ] **Step 4: `src/profile/types.py` — update `fromDict()`**

Find line 134:
```python
            alertThresholds=data.get('alertThresholds', {}),
```
Delete this line.

- [ ] **Step 5: `src/profile/types.py` — update `fromConfigDict()`**

Find line 155:
```python
            alertThresholds=configProfile.get('alertThresholds', {}),
```
Delete this line.

- [ ] **Step 6: `src/profile/types.py` — delete `getAlertConfigJson()` method**

Find lines 161-169:
```python
    def getAlertConfigJson(self) -> str:
        """
        Get alert thresholds as JSON string for database storage.

        Returns:
            JSON string of alert thresholds
        """
        import json
        return json.dumps(self.alertThresholds)
```
Delete the entire method.

- [ ] **Step 7: `src/profile/types.py` — audit `from typing import Any` usage**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "Any" src/profile/types.py
```
If `Any` still appears in remaining code (e.g., in `ProfileChangeEvent.toDict`), keep the import. If zero non-import matches, remove `from typing import Any` at line 30.

- [ ] **Step 8: `src/profile/__init__.py` — remove `DEFAULT_ALERT_THRESHOLDS` re-export**

Find the import block near line 96 and the `__all__` entry near line 121. Delete both `DEFAULT_ALERT_THRESHOLDS` entries.

- [ ] **Step 9: `src/profile/helpers.py` — remove `DEFAULT_ALERT_THRESHOLDS` use in `getDefaultProfileConfig`**

Find around lines 297-315:
```python
def getDefaultProfileConfig() -> dict[str, Any]:
    ...
    from .types import (
        DEFAULT_ALERT_THRESHOLDS,
        DEFAULT_POLLING_INTERVAL_MS,
        DEFAULT_PROFILE_DESCRIPTION,
        DEFAULT_PROFILE_ID,
        DEFAULT_PROFILE_NAME,
    )

    return {
        'activeProfile': DEFAULT_PROFILE_ID,
        'availableProfiles': [
            {
                'id': DEFAULT_PROFILE_ID,
                'name': DEFAULT_PROFILE_NAME,
                'description': DEFAULT_PROFILE_DESCRIPTION,
                'alertThresholds': DEFAULT_ALERT_THRESHOLDS.copy(),
                'pollingIntervalMs': DEFAULT_POLLING_INTERVAL_MS,
            }
        ]
    }
```

Remove `DEFAULT_ALERT_THRESHOLDS` from the import tuple AND remove the `'alertThresholds': DEFAULT_ALERT_THRESHOLDS.copy(),` line from the dict literal.

- [ ] **Step 10: `src/profile/manager.py` — remove `DEFAULT_ALERT_THRESHOLDS` import**

Find line 46:
```python
    DEFAULT_ALERT_THRESHOLDS,
```
Delete this line from the import tuple.

- [ ] **Step 11: `src/profile/manager.py` — remove `alert_config_json` from INSERT**

Find around lines 136-149 in `createProfile`:
```python
                cursor.execute(
                    """
                    INSERT INTO profiles
                    (id, name, description, alert_config_json, polling_interval_ms)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.name,
                        profile.description,
                        profile.getAlertConfigJson(),
                        profile.pollingIntervalMs,
                    )
                )
```

Rewrite to:
```python
                cursor.execute(
                    """
                    INSERT INTO profiles
                    (id, name, description, polling_interval_ms)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.name,
                        profile.description,
                        profile.pollingIntervalMs,
                    )
                )
```

- [ ] **Step 12: `src/profile/manager.py` — remove `alert_config_json` from SELECT (getProfile)**

Find around lines 172-182 in `getProfile`:
```python
                cursor.execute(
                    """
                    SELECT id, name, description, alert_config_json,
                           polling_interval_ms, created_at, updated_at
                    FROM profiles
                    WHERE id = ?
                    """,
                    (profileId,)
                )
```

Rewrite to:
```python
                cursor.execute(
                    """
                    SELECT id, name, description,
                           polling_interval_ms, created_at, updated_at
                    FROM profiles
                    WHERE id = ?
                    """,
                    (profileId,)
                )
```

- [ ] **Step 13: `src/profile/manager.py` — remove `alert_config_json` from SELECT (getAllProfiles)**

Find around lines 205-215 in `getAllProfiles` — same change: remove `alert_config_json,` from the SELECT list.

- [ ] **Step 14: `src/profile/manager.py` — remove `alert_config_json` from UPDATE**

Find around lines 246-264 in `updateProfile`:
```python
                cursor.execute(
                    """
                    UPDATE profiles
                    SET name = ?,
                        description = ?,
                        alert_config_json = ?,
                        polling_interval_ms = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        profile.name,
                        profile.description,
                        profile.getAlertConfigJson(),
                        profile.pollingIntervalMs,
                        profile.id,
                    )
                )
```

Rewrite to:
```python
                cursor.execute(
                    """
                    UPDATE profiles
                    SET name = ?,
                        description = ?,
                        polling_interval_ms = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        profile.name,
                        profile.description,
                        profile.pollingIntervalMs,
                        profile.id,
                    )
                )
```

- [ ] **Step 15: `src/profile/manager.py` — rewrite `_rowToProfile`**

Find lines 478-504:
```python
    def _rowToProfile(self, row: Any) -> Profile:
        """
        Convert database row to Profile.
        ...
        """
        # Parse alert thresholds from JSON
        alertThresholds: dict[str, Any] = {}
        if row['alert_config_json']:
            try:
                alertThresholds = json.loads(row['alert_config_json'])
            except json.JSONDecodeError:
                logger.warning(f"Invalid alert config JSON for profile {row['id']}")

        return Profile(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            alertThresholds=alertThresholds,
            pollingIntervalMs=row['polling_interval_ms'] or DEFAULT_POLLING_INTERVAL_MS,
            createdAt=row['created_at'],
            updatedAt=row['updated_at'],
        )
```

Rewrite to:
```python
    def _rowToProfile(self, row: Any) -> Profile:
        """
        Convert database row to Profile.

        Args:
            row: Database row

        Returns:
            Profile instance
        """
        return Profile(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            pollingIntervalMs=row['polling_interval_ms'] or DEFAULT_POLLING_INTERVAL_MS,
            createdAt=row['created_at'],
            updatedAt=row['updated_at'],
        )
```

- [ ] **Step 16: `src/profile/manager.py` — prune `json` import if now unused**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "\bjson\b" src/profile/manager.py
```
If `json` appears only in `import json`, remove the import. If it's used elsewhere, keep it.

- [ ] **Step 17: `src/profile/manager.py` — update `getDefaultProfile()`**

Find lines 511-524:
```python
def getDefaultProfile() -> Profile:
    """
    Get the default 'Daily' profile.

    Returns:
        Default Profile instance
    """
    return Profile(
        id=DEFAULT_PROFILE_ID,
        name=DEFAULT_PROFILE_NAME,
        description=DEFAULT_PROFILE_DESCRIPTION,
        alertThresholds=DEFAULT_ALERT_THRESHOLDS.copy(),
        pollingIntervalMs=DEFAULT_POLLING_INTERVAL_MS,
    )
```

Rewrite to:
```python
def getDefaultProfile() -> Profile:
    """
    Get the default 'Daily' profile.

    Returns:
        Default Profile instance
    """
    return Profile(
        id=DEFAULT_PROFILE_ID,
        name=DEFAULT_PROFILE_NAME,
        description=DEFAULT_PROFILE_DESCRIPTION,
        pollingIntervalMs=DEFAULT_POLLING_INTERVAL_MS,
    )
```

- [ ] **Step 18: `src/obd/database.py` — remove `alert_config_json` column from `SCHEMA_PROFILES`**

Find lines 111-131:
```python
# Profiles for different driving modes
SCHEMA_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Profile details
    name TEXT NOT NULL,
    description TEXT,

    -- JSON-encoded alert configuration
    alert_config_json TEXT,

    -- Profile-specific polling interval
    polling_interval_ms INTEGER DEFAULT 1000,

    -- Audit columns
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
```

Rewrite to:
```python
# Profiles for different driving modes
SCHEMA_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    -- Primary key
    id TEXT PRIMARY KEY,

    -- Profile details
    name TEXT NOT NULL,
    description TEXT,

    -- Profile-specific polling interval
    polling_interval_ms INTEGER DEFAULT 1000,

    -- Audit columns
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
```

**Note:** Per Task 1 Step 5 CIO decision: no DROP COLUMN migration. Existing dev databases must be rebuilt manually. Test DBs are ephemeral (`tempfile.mktemp()` per test) so they inherit the new schema automatically.

- [ ] **Step 19: Smoke test — import and instantiate Profile**

Run:
```bash
cd Z:/o/OBD2v2
python -c "
from profile.types import Profile
p = Profile(id='daily', name='Daily')
d = p.toDict()
print('Fields:', list(d.keys()))
assert 'alertThresholds' not in d
print('OK')
"
```
Expected: `Fields:` lists `id`, `name`, `description`, `pollingIntervalMs`, `createdAt`, `updatedAt` (no `alertThresholds`). Then `OK`.

- [ ] **Step 20: Run profile + database tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_profile_types.py tests/test_profile_manager.py tests/test_database.py -x -q --tb=short 2>&1 | tail -40
```
Expected: failures in tests that still reference `alertThresholds` or `alert_config_json` — those are Task 7 scope. Any failure NOT in that pattern is a real breakage — stop and fix.

If `test_profile_types.py` or `test_profile_manager.py` don't exist, skip those filenames (different project naming).

- [ ] **Step 21: Ruff + mypy on touched files**

Run:
```bash
cd Z:/o/OBD2v2
ruff check src/profile/ src/obd/database.py 2>&1 | tail -20
mypy src/profile/ src/obd/database.py 2>&1 | tail -20
```
Expected: no new errors beyond pre-existing noise (pre-existing errors are not this sweep's responsibility).

- [ ] **Step 22: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/profile/ src/obd/database.py
git commit -m "refactor(sweep2b): delete Profile.alertThresholds and alert_config_json column

- Profile dataclass: remove alertThresholds field, DEFAULT_ALERT_THRESHOLDS
  constant, getAlertConfigJson() method, references in toDict/fromDict/
  fromConfigDict
- ProfileManager: remove alert_config_json from INSERT/UPDATE/SELECT, remove
  JSON parsing in _rowToProfile, remove alertThresholds from getDefaultProfile
- profile/helpers.getDefaultProfileConfig: remove DEFAULT_ALERT_THRESHOLDS use
- profile/__init__: remove DEFAULT_ALERT_THRESHOLDS re-export
- database.SCHEMA_PROFILES: drop alert_config_json column

No schema migration: nothing in production, no existing schema-version
machinery. Dev DBs rebuild manually. Test DBs are ephemeral (tempfile)."
```

---

## Task 5: Alert package atomic cleanup (non-`thresholds.py` files)

**Goal:** Remove every reference to the legacy threshold surface from the alert subpackage, leaving `src/alert/thresholds.py` file present but orphan-imported (Task 6 deletes it).

**Files:**
- Modify: `src/alert/helpers.py`
- Modify: `src/alert/manager.py`
- Modify: `src/alert/types.py`
- Modify: `src/alert/__init__.py`

- [ ] **Step 1: `src/alert/helpers.py` — delete `getAlertThresholdsForProfile()`**

Find lines 79-99:
```python
def getAlertThresholdsForProfile(
    config: dict[str, Any],
    profileId: str
) -> dict[str, float]:
    """
    Get alert thresholds for a specific profile from config.
    ...
    """
    profilesConfig = config.get('profiles', {})

    for profile in profilesConfig.get('availableProfiles', []):
        if profile.get('id') == profileId:
            return profile.get('alertThresholds', {})

    return {}
```
Delete the entire function.

- [ ] **Step 2: `src/alert/manager.py` — delete `setProfileThresholds()` method**

Find lines 200-217:
```python
    def setProfileThresholds(
        self,
        profileId: str,
        thresholds: dict[str, float]
    ) -> None:
        """
        Set thresholds for a profile.
        ...
        """
        alertThresholds = convertThresholds(thresholds)
        self._profileThresholds[profileId] = alertThresholds
        logger.info(
            f"Set {len(alertThresholds)} thresholds for profile '{profileId}'"
        )
```
Delete the entire method.

- [ ] **Step 3: `src/alert/manager.py` — delete `from .thresholds import convertThresholds`**

Find line 39:
```python
from .thresholds import convertThresholds
```
Delete this line.

- [ ] **Step 4: `src/alert/manager.py` — update class docstring example**

Find lines 70-84 (the class docstring `Example:` block that uses `setProfileThresholds`):
```python
    Example:
        manager = AlertManager(
            database=db,
            displayManager=display,
            cooldownSeconds=30
        )
        manager.setProfileThresholds('daily', {
            'rpmRedline': 6500,
            'coolantTempCritical': 220
        })
        manager.start()

        # In data acquisition loop
        manager.checkValue('RPM', currentRpm, profileId='daily')
```

Rewrite to:
```python
    Example:
        manager = AlertManager(
            database=db,
            displayManager=display,
            cooldownSeconds=30
        )
        manager.setThresholdsFromConfig(config)
        manager.setActiveProfile('daily')
        manager.start()

        # In data acquisition loop
        manager.checkValue('RPM', currentRpm, profileId='daily')
```

Also update the feature bullet `- Profile-specific threshold definitions` (around line 66) to `- Tiered threshold definitions loaded from config`.

- [ ] **Step 5: `src/alert/types.py` — delete `THRESHOLD_KEY_TO_PARAMETER` constant**

Find lines 52-58:
```python
# Threshold config keys to parameter mapping
THRESHOLD_KEY_TO_PARAMETER = {
    'rpmRedline': 'RPM',
    'coolantTempCritical': 'COOLANT_TEMP',
    'boostPressureMax': 'INTAKE_PRESSURE',
    'oilPressureLow': 'OIL_PRESSURE',
}
```
Delete this block (comment + constant).

- [ ] **Step 6: `src/alert/__init__.py` — remove thresholds.py imports**

Find lines 64-70:
```python
# Threshold checking
from .thresholds import (
    checkThresholdValue,
    convertThresholds,
    getDefaultThresholds,
    validateThresholds,
)
```
Delete this block (comment + import).

- [ ] **Step 7: `src/alert/__init__.py` — remove `getAlertThresholdsForProfile` import**

Find in the `.helpers` import block (lines 44-51):
```python
from .helpers import (
    createAlertManagerFromConfig,
    getAlertConfig,
    getAlertThresholdsForProfile,
    getDefaultAlertConfig,
    isAlertingEnabled,
    validateAlertConfig,
)
```
Remove `getAlertThresholdsForProfile,` from the tuple.

- [ ] **Step 8: `src/alert/__init__.py` — remove `THRESHOLD_KEY_TO_PARAMETER` import**

Find in the `.types` import block (around lines 93-109):
```python
from .types import (
    # Constants
    ALERT_PRIORITIES,
    ...
    THRESHOLD_KEY_TO_PARAMETER,
    ...
)
```
Remove `THRESHOLD_KEY_TO_PARAMETER,` from the tuple.

- [ ] **Step 9: `src/alert/__init__.py` — prune `__all__`**

Find `__all__` around lines 111-168. Remove these entries:
- `'convertThresholds'`
- `'checkThresholdValue'`
- `'getDefaultThresholds'`
- `'validateThresholds'`
- `'getAlertThresholdsForProfile'`
- `'THRESHOLD_KEY_TO_PARAMETER'`

Also remove their section comments (e.g., `# Threshold functions` may become empty — remove the comment too).

- [ ] **Step 10: Smoke test — import the alert package**

Run:
```bash
cd Z:/o/OBD2v2
python -c "
import alert
assert not hasattr(alert, 'convertThresholds')
assert not hasattr(alert, 'checkThresholdValue')
assert not hasattr(alert, 'getDefaultThresholds')
assert not hasattr(alert, 'validateThresholds')
assert not hasattr(alert, 'getAlertThresholdsForProfile')
assert not hasattr(alert, 'THRESHOLD_KEY_TO_PARAMETER')
assert hasattr(alert, 'AlertManager')
assert hasattr(alert, 'createAlertManagerFromConfig')
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 11: Run alert tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_alert_manager.py tests/test_alert_helpers.py tests/test_alert_types.py -x -q --tb=short 2>&1 | tail -30
```
Expected: any failures point to tests that still import the deleted symbols — those are Task 7 scope. Skip filenames that don't exist.

- [ ] **Step 12: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/alert/
git commit -m "refactor(sweep2b): delete legacy helpers from alert package

- alert/helpers.py: delete getAlertThresholdsForProfile
- alert/manager.py: delete setProfileThresholds, convertThresholds import;
  update class docstring example to use setThresholdsFromConfig
- alert/types.py: delete THRESHOLD_KEY_TO_PARAMETER constant
- alert/__init__.py: remove thresholds.py re-exports, prune __all__

src/alert/thresholds.py still present; deleted in Task 6."
```

---

## Task 6: Delete `src/alert/thresholds.py`

**Goal:** The file is now unreferenced by any production code. Delete it.

**Files:**
- Delete: `src/alert/thresholds.py`

- [ ] **Step 1: Verify no remaining imports of `.thresholds`**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "from .thresholds\|from alert.thresholds\|from src.alert.thresholds\|import alert.thresholds" src tests 2>/dev/null
```
Expected: zero matches. If any hit, fix it before deleting the file.

- [ ] **Step 2: Delete the file**

Run:
```bash
cd Z:/o/OBD2v2
git rm src/alert/thresholds.py
git status
```
Expected: file staged as deleted.

- [ ] **Step 3: Smoke test**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import alert; import alert.manager; print('OK')"
```
Expected: `OK`. No `ModuleNotFoundError`.

- [ ] **Step 4: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git commit -m "refactor(sweep2b): delete src/alert/thresholds.py

169 lines of dead code. All callers rewired in Sweep 2a / Task 5."
```

---

## Task 7: Clean up `src/obd/__init__.py`

**Goal:** Remove the `getAlertThresholdsForProfile` re-export now that the underlying function is gone.

**Files:**
- Modify: `src/obd/__init__.py`

- [ ] **Step 1: Remove the import**

Find line ~194:
```python
    getAlertThresholdsForProfile,
```
(inside the `from alert import (...)` or similar block — locate the exact import statement)

Delete the line.

- [ ] **Step 2: Remove from `__all__`**

Find line ~472:
```python
    'getAlertThresholdsForProfile',
```
Delete the line.

- [ ] **Step 3: Smoke test**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import obd; assert not hasattr(obd, 'getAlertThresholdsForProfile'); print('OK')"
```
Expected: `OK`.

- [ ] **Step 4: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/obd/__init__.py
git commit -m "refactor(sweep2b): remove getAlertThresholdsForProfile re-export from obd/__init__"
```

---

## Task 8: Test fixture cleanup + skipped-test disposition

**Goal:** Remove `alertThresholds` keys from every test profile fixture Sweep 2a touched. Dispose of the 3 mark-skipped tests from Sweep 2a: 2 deletes (square-peg, file one shared backlog entry) + 1 rewrite (robustness coverage still valid). Remove `alert_config_json` assertions from `test_database.py`.

**Files:**
- Modify: the ~18 test files identified in the audit (grep below will find the live set)
- Modify: `tests/test_database.py`
- Modify: `tests/test_orchestrator_alerts.py` (delete Test 1)
- Modify: `tests/test_orchestrator_profiles.py` (delete Test 2, rewrite Test 3)
- Create: `offices/pm/backlog/B-XXX-per-profile-tiered-threshold-overrides.md` (backlog entry for Tests 1 & 2)

- [ ] **Step 1: Enumerate every test file referencing the legacy surface**

Run:
```bash
cd Z:/o/OBD2v2
grep -rln "alertThresholds\|alert_config_json\|getAlertConfigJson\|DEFAULT_ALERT_THRESHOLDS\|getAlertThresholdsForProfile\|setProfileThresholds\|convertThresholds\|THRESHOLD_KEY_TO_PARAMETER" tests/ 2>/dev/null
```

Record every file. Expected: ~18 files based on pre-plan audit.

- [ ] **Step 2: File the backlog entry for Tests 1 & 2 first**

Before deleting the tests, create the backlog entry that captures the feature they were testing so nothing is lost.

Look up the next backlog ID: read `offices/pm/backlog/` and find the highest `B-NNN-*.md` number. Use the next one. Also check `offices/pm/backlog.json` if it exists to confirm the ID range.

Create `offices/pm/backlog/B-XXX-per-profile-tiered-threshold-overrides.md` (substitute the real ID):

```markdown
# B-XXX — Per-profile tiered threshold overrides

**Status:** Pending
**Priority:** Low
**Created:** 2026-04-14
**Source:** Sweep 2b dead-code delete — Tests 1 & 2 deleted because their premise no longer exists

## Summary

Allow a profile (e.g., `performance`, track day) to override specific values
in `tieredThresholds` without duplicating the whole section. Today, tiered
thresholds are a single global section under `tieredThresholds` and
AlertManager builds the same threshold list for every profile. There is no
way for a track profile to say "my RPM dangerMin is 7500, use the global
coolantTemp".

## Why this is backlog, not a bug

- Sweep 2a consolidated alerts on the tiered system. Consolidation was the
  right call (the legacy per-profile thresholds were inconsistent and
  Spool-unauthoritative).
- A future per-profile override layer is a clean additive feature on top of
  the consolidated base.
- CIO has no current need for per-profile variance. Ships E85 conversion
  with ECMLink V3 summer 2026 — after that, track-specific tuning becomes
  relevant.

## Tests that would be recreated

Sweep 2b deleted two tests from 2026-04-14 whose premise was exactly this
feature:

1. `tests/test_orchestrator_alerts.py::test_profileChange_updatesAlertThresholds`
2. `tests/test_orchestrator_profiles.py::test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds`

Both asserted "profile switch rebinds AlertManager thresholds with the new
profile's values." Resurrect them against whatever override API this item
ships.

## Design questions (future)

- Override syntax: `profiles.overrides.performance.rpm.dangerMin = 7500`?
- Merge semantics: deep-merge over tiered, or replace the whole parameter's
  tier block?
- Does AlertManager rebuild on profile switch, or do thresholds get scoped
  per call?
- Does Spool sign off on the override values, or does the profile author?

## Related

- Sweep 2a: merged 2026-04-13, `418b55b` — consolidated to tieredThresholds
- Sweep 2b: merged 2026-04-14 (pending) — deleted the legacy per-profile path
```

Commit the backlog entry standalone:
```bash
cd Z:/o/OBD2v2
git add offices/pm/backlog/B-XXX-per-profile-tiered-threshold-overrides.md
git commit -m "docs(sweep2b): file backlog entry for per-profile tiered threshold overrides

Captures the feature that Tests 1 & 2 of the Sweep 2a skipped-test trio
were asserting. Those tests are deleted in the next commit because their
premise is a square peg in the post-2a architecture; this backlog item
restores the feature's visibility so the tests get recreated if/when it ships."
```

- [ ] **Step 3: Delete Test 1 — `test_profileChange_updatesAlertThresholds`**

Open `tests/test_orchestrator_alerts.py`, find the test at line ~557-595 (decorator + function). Delete the entire block including the `@pytest.mark.skip(...)` decorator, function signature, docstring, and body. Also delete any preceding blank line pair so the file doesn't end up with a double-blank-line gap.

If removing this test leaves any import unused (e.g., a specific MagicMock pattern only this test used), remove the import too.

Verify the neighboring test still passes:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_alerts.py::TestProfileChangeUpdatesAlerts::test_profileChange_setsActiveProfile -v
```
(Substitute the real class name — find it by reading the file.)

Expected: pass.

- [ ] **Step 4: Delete Test 2 — `test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds`**

Open `tests/test_orchestrator_profiles.py`, find the test at line ~604-641 (decorator + function). Delete the entire block.

Verify the neighboring test still passes:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_profiles.py -k "updatesActiveProfile_onAlertManager" -v
```
Expected: pass.

- [ ] **Step 5: Rewrite Test 3 — `test_handleProfileChange_survivesAlertManagerError_continuesRunning`**

Open `tests/test_orchestrator_profiles.py`, find the test at line ~706 (decorator + function). The original asserted that if `setProfileThresholds` raises, the orchestrator logs a warning and continues. Rewrite it to assert the same robustness property against `setActiveProfile` (the method that still exists).

Remove the `@pytest.mark.skip(...)` decorator entirely.

Inside the function, change the mock setup block:

Before:
```python
mockAlertManager = MagicMock()
mockAlertManager.setProfileThresholds = MagicMock(
    side_effect=RuntimeError("alert update failed")
)
orchestrator._alertManager = mockAlertManager
```

After:
```python
mockAlertManager = MagicMock()
mockAlertManager.setActiveProfile = MagicMock(
    side_effect=RuntimeError("alert manager failed on profile switch")
)
orchestrator._alertManager = mockAlertManager
```

Also update the docstring's `Given:` line to reflect the new mock target:

Before:
```python
"""
Given: Alert manager that raises an exception
When: _handleProfileChange is called
Then: Orchestrator continues (no crash), logs warning
"""
```

After:
```python
"""
Given: Alert manager whose setActiveProfile raises on profile switch
When: _handleProfileChange is called
Then: Orchestrator continues (no crash), logs warning
"""
```

The rest of the test (the `caplog` assertions, the "orchestrator still running" check) stays as-is — that's the behavior we're preserving.

- [ ] **Step 6: Run the rewritten Test 3 in isolation**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_profiles.py -k "survivesAlertManagerError_continuesRunning" -v --tb=short 2>&1 | tail -30
```

Expected: pass. If it fails, inspect the orchestrator's `_handleProfileChange` error-handling path — the method may need to wrap `setActiveProfile` calls in try/except (if it doesn't already), in which case either fix the orchestrator (scope-appropriate for a robustness fix) or adjust the test's expectation to match actual current behavior. Do not blindly change the test to make it pass without understanding why.

- [ ] **Step 7: Commit the 3-test disposition**

Run:
```bash
cd Z:/o/OBD2v2
git add tests/test_orchestrator_alerts.py tests/test_orchestrator_profiles.py
git commit -m "test(sweep2b): dispose of 3 mark-skipped tests from Sweep 2a

- Delete test_profileChange_updatesAlertThresholds (alerts.py): square-peg,
  adjacent test_profileChange_setsActiveProfile covers the valid remainder
- Delete test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds
  (profiles.py): same scenario as Test 1, adjacent test covers the remainder
- Rewrite test_handleProfileChange_survivesAlertManagerError_continuesRunning
  (profiles.py): robustness concern still valid, swapped mocked method from
  setProfileThresholds to setActiveProfile

Backlog entry B-XXX-per-profile-tiered-threshold-overrides filed in prior
commit for the two deleted tests."
```

- [ ] **Step 8: Remove `alertThresholds` dict from each orchestrator test fixture**

For each of the 15 orchestrator tests that Sweep 2a touched (identified via Step 1), open the file, find the profile fixture dict (often a `_makeConfig()` helper or an inline `{'profiles': {'availableProfiles': [...]}}` literal), and delete the `'alertThresholds': {...}` key from each profile entry. Leave `tieredThresholds` untouched.

Before:
```python
{
    'id': 'daily',
    'name': 'Daily',
    'alertThresholds': {'rpmRedline': 7000, 'coolantTempCritical': 220},
    'pollingIntervalMs': 1000,
}
```

After:
```python
{
    'id': 'daily',
    'name': 'Daily',
    'pollingIntervalMs': 1000,
}
```

Run the affected file after each edit to catch issues early:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_<name>.py -x -q --tb=short 2>&1 | tail -15
```

- [ ] **Step 9: Clean up `tests/test_database.py`**

Find and fix the two `alert_config_json` references:

- Line ~464: `assert 'alert_config_json' in columnNames` — delete this assertion line
- Lines ~520-524: `INSERT INTO profiles (id, name, description, alert_config_json) VALUES (?, ?, ?, ?)` — rewrite to `INSERT INTO profiles (id, name, description) VALUES (?, ?, ?)` and drop the `'{"rpmRedline": 6500}'` bind value

Also grep for any other references in this file and fix them:
```bash
grep -n "alert_config_json\|alertThresholds" tests/test_database.py
```

- [ ] **Step 10: Clean up `tests/test_obd_config_loader.py`**

This file is likely testing `_validateAlertThresholds` directly. Run:
```bash
cd Z:/o/OBD2v2
grep -n "alertThresholds\|_validateAlertThresholds\|rpmRedline\|coolantTempCritical" tests/test_obd_config_loader.py
```

For each reference:
- If the test asserts that `_validateAlertThresholds` raises on bad values — delete the test (function is gone)
- If the test is a fixture with `alertThresholds` keys — delete the keys, keep the test
- If the test asserts on `profile['alertThresholds']` after load — delete the assertion or the test if that was its only purpose

- [ ] **Step 11: Clean up the remaining test files from Step 1 enumeration**

For each remaining file in the grep output from Step 1, apply the same three rules:
1. Remove `alertThresholds` keys from fixtures
2. Delete assertions that depend on the removed behavior
3. Remove imports of deleted symbols (`DEFAULT_ALERT_THRESHOLDS`, `getAlertThresholdsForProfile`, etc.)

Group commits logically (e.g., all orchestrator fixture cleanups in one commit, test_database in another, test_obd_config_loader in another).

- [ ] **Step 12: Final sweep — zero matches for the legacy surface**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "alertThresholds\|alert_config_json\|getAlertConfigJson\|DEFAULT_ALERT_THRESHOLDS\|getAlertThresholdsForProfile\|setProfileThresholds\|convertThresholds\|THRESHOLD_KEY_TO_PARAMETER" tests/ 2>/dev/null
```

Expected: **zero matches** — every reference gone. If any remain, fix them.

- [ ] **Step 13: Run the fast suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```
Expected: `1504 passed, 0 skipped, 19 deselected`. Baseline was `1503 passed, 3 skipped`; Tests 1 & 2 are deleted (no longer in the suite) and Test 3 transitions from skipped to passing, so passing count goes up by 1 and skipped drops to 0. Full-suite target: `1522 passed, 1 skipped` (down 3 skipped, up 1 passed from 1521).

If any fail, fix them before moving on.

- [ ] **Step 14: Commit**

If test fixture cleanup wasn't already committed per-file in Steps 8/9/10/11, commit everything remaining:
```bash
cd Z:/o/OBD2v2
git add tests/
git commit -m "test(sweep2b): strip legacy alertThresholds keys from fixtures

Sweep 2a added tieredThresholds adjacent to legacy alertThresholds in
15 orchestrator test fixtures plus test_main, test_e2e_simulator,
test_simulate_db_validation. Legacy keys are no-ops post-2a and are
removed here. test_database.py alert_config_json assertions removed.
test_obd_config_loader.py references to deleted _validateAlertThresholds
removed."
```

---

## Task 9: Spool-value preservation check

**Goal:** Verify `tieredThresholds` in `src/obd_config.json` is byte-identical to the Task 1 Step 4 snapshot. This is the single most important safety check in Sweep 2b.

**Files:**
- Read-only: `src/obd_config.json`, `/tmp/tiered-before-2b.json`

- [ ] **Step 1: Re-dump current `tieredThresholds`**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-after-2b.json
```

- [ ] **Step 2: Diff against snapshot**

Run:
```bash
diff /tmp/tiered-before-2b.json /tmp/tiered-after-2b.json && echo "UNCHANGED"
```

Expected: `UNCHANGED`, **zero output**. If any diff, a Spool-authoritative value drifted. **Stop immediately.** File `offices/tuner/inbox/2026-04-14-from-ralph-sweep2b-drift.md` with the diff and do NOT merge.

- [ ] **Step 3: Double-check specific values**

Run:
```bash
cd Z:/o/OBD2v2
python <<'PY'
import json
c = json.load(open('src/obd_config.json'))
t = c['tieredThresholds']
checks = {
    ('rpm', 'dangerMin'): 7000,
    ('coolantTemp', 'dangerMin'): 220,
    ('coolantTemp', 'cautionMin'): 210,
    ('coolantTemp', 'normalMin'): 180,
    ('stft', 'cautionMin'): 5,
    ('stft', 'dangerMin'): 15,
}
allOk = True
for (param, key), expected in checks.items():
    actual = t.get(param, {}).get(key)
    status = 'OK' if actual == expected else 'DRIFT'
    if actual != expected:
        allOk = False
    print(f"{status}: {param}.{key} = {actual} (expected {expected})")
print('ALL OK' if allOk else 'DRIFT DETECTED — STOP')
PY
```
Expected: every line `OK`, final line `ALL OK`. Any `DRIFT` is a blocker.

---

## Task 10: Full verification — test suite, lint, type check, simulator

**Files:** No changes — verification only.

- [ ] **Step 1: Full fast suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -q -m "not slow" --tb=short 2>&1 | tail -10
```
Expected: `1504 passed, 0 skipped, 19 deselected`. Baseline was `1503 passed, 3 skipped` — net: 2 tests deleted, 1 test rewritten (skipped → passing), so passing +1 and skipped -3.

- [ ] **Step 2: Full slow suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -q --tb=short 2>&1 | tail -10
```
Expected: `1522 passed, 1 skipped`. Baseline was `1521 passed, 4 skipped` — same delta as fast suite.

- [ ] **Step 3: Ruff**

Run:
```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -20
```
Expected: no new errors compared to the main baseline. Any new error must come from files this sweep touched; fix it.

- [ ] **Step 4: Mypy**

Run:
```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -20
```
Expected: no new errors. Same rule as ruff — pre-existing noise is fine, new errors from touched files are not.

- [ ] **Step 5: Simulator smoke test**

Run:
```bash
cd Z:/o/OBD2v2
timeout 30 python src/main.py --simulate --dry-run 2>&1 | tail -40
```
Expected:
- Clean startup, no `ModuleNotFoundError` (especially not for `alert.thresholds`)
- No `AttributeError: 'Profile' object has no attribute 'alertThresholds'`
- AlertManager initializes, prints/logs "built N thresholds for M profile(s) from tiered config"
- No tracebacks

If the simulator hangs or errors, stop and diagnose — this is the integration smoke test.

- [ ] **Step 6: Coverage spot check**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -q -m "not slow" --cov=src/alert --cov=src/profile --cov=src/obd/config --cov-report=term 2>&1 | tail -25
```
Expected: alert and profile subpackages ≥80% coverage. If coverage dropped significantly (>5%), investigate — we may have deleted tests that were actually covering non-legacy code paths.

---

## Task 11: Cleanup, design doc, merge

**Files:**
- Delete: `docs/superpowers/plans/sweep2-audit-notes.md`
- Modify: `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 12)

- [ ] **Step 1: Delete audit notes scratch file**

Run:
```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep2-audit-notes.md
git commit -m "chore(sweep2b): delete sweep 2 audit notes scratch file"
```

- [ ] **Step 2: Append Sweep 2b row to design doc section 12**

Read `docs/superpowers/specs/2026-04-12-reorg-design.md`, find section 12 (session log table). Append:

```markdown
| 2026-04-14 | 2b | Sweep 2b complete. Deleted src/alert/thresholds.py (169 lines); removed Profile.alertThresholds field, DEFAULT_ALERT_THRESHOLDS, getAlertConfigJson; dropped alert_config_json column from SCHEMA_PROFILES (no migration — nothing in prod); removed profiles.alertThresholds and profiles.thresholdUnits from obd_config.json; pruned AlertManager.setProfileThresholds, alert/__init__ re-exports, obd/__init__ re-export, _validateAlertThresholds validator; disposed of 3 Sweep-2a skipped tests (2 deleted with backlog entry B-XXX-per-profile-tiered-threshold-overrides filed, 1 rewritten to mock setActiveProfile); stripped legacy alertThresholds keys from 18 test files. Spool-value preservation verified (diff empty). Fast suite: 1504 passing / 0 skipped (up from 1503/3). Simulator smoke test green. |
```

- [ ] **Step 3: Commit the design doc update**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs(sweep2b): session log update for Sweep 2b completion"
```

- [ ] **Step 4: Surface to CIO for merge approval**

Tell the CIO:

> "Sweep 2b complete on branch `sprint/reorg-sweep2b-delete`.
>
> Deleted: `src/alert/thresholds.py` (169 lines), `Profile.alertThresholds` field + `DEFAULT_ALERT_THRESHOLDS`, `getAlertConfigJson()`, `alert_config_json` DB column, `profiles.alertThresholds` / `profiles.thresholdUnits` in obd_config.json, `setProfileThresholds` legacy method, `getAlertThresholdsForProfile` helper, `THRESHOLD_KEY_TO_PARAMETER` constant, `_validateAlertThresholds` validator + its call.
>
> Skipped-test disposition: Tests 1 & 2 deleted (square-peg), Test 3 rewritten to mock `setActiveProfile` raising (robustness concern still valid). Backlog entry filed: `B-XXX-per-profile-tiered-threshold-overrides` for future feature that would resurrect Tests 1 & 2.
>
> Preserved: every Spool-authoritative value in `tieredThresholds` — diff is empty.
>
> Tests: fast suite `1504 passed, 0 skipped` (baseline was 1503 passing + 3 skipped — net: 2 deleted, 1 rewritten now running). Slow suite `1522 passed, 1 skipped`. Ruff clean, mypy clean, simulator smoke test green.
>
> No database migration: per Task 1 decision, nothing in production, no existing schema-version machinery. Existing dev DBs (if any) must be deleted and recreated manually. Test DBs are ephemeral.
>
> Ready to merge to main?"

Wait for explicit approval.

- [ ] **Step 5: Merge to main (after CIO approval)**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep2b-delete -m "Merge sprint/reorg-sweep2b-delete: Sweep 2b complete — legacy threshold dead-code delete

Sweep 2b of 6 for the structural reorganization (B-040). Pure cleanup pass
following Sweep 2a's runtime rewire.

Deleted:
- src/alert/thresholds.py (169 lines)
- Profile.alertThresholds field, DEFAULT_ALERT_THRESHOLDS, getAlertConfigJson
- alert_config_json column from SCHEMA_PROFILES (no migration: nothing in prod)
- profiles.alertThresholds and profiles.thresholdUnits from obd_config.json
- AlertManager.setProfileThresholds, convertThresholds import
- getAlertThresholdsForProfile (alert/helpers.py)
- THRESHOLD_KEY_TO_PARAMETER constant
- _validateAlertThresholds() validator + its call
- 2 mark-skipped tests from Sweep 2a whose premise is permanently invalid
  (Tests 1 & 2 — backlog entry B-XXX-per-profile-tiered-threshold-overrides
  filed for the future feature that would resurrect them)
- Legacy alertThresholds keys stripped from 18 test files

Rewritten:
- 1 mark-skipped test (Test 3) — mock setActiveProfile raising instead of
  setProfileThresholds; robustness coverage preserved

Preserved:
- tieredThresholds byte-identical to pre-sweep snapshot (verified via diff)
- AlertManager runtime path unchanged — setThresholdsFromConfig still fires
  RPM at 7000 and coolant at 220

Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md section 12.
Next: Sweep 3 (tier split) — highest risk, 24-hour cooling period after this merge."
git log --oneline -5
```

- [ ] **Step 6: Confirm main is green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -5
```
Expected: matches the post-Sweep-2b count.

- [ ] **Step 7: Announce completion**

Tell the CIO:

> "Sweep 2b merged to main. Legacy threshold system fully excised. Sweep 3 (tier split — physical Pi/server split) is next and highest-risk. 24-hour cooling period recommended per reorg design doc before starting. Plan file: `docs/superpowers/plans/2026-04-12-reorg-sweep3-tier-split.md`. Ready when you are."

---

## End of Sweep 2b Plan

**Success criteria recap:**
- ✅ `src/alert/thresholds.py` deleted
- ✅ `Profile.alertThresholds`, `DEFAULT_ALERT_THRESHOLDS`, `getAlertConfigJson()` gone
- ✅ `alert_config_json` column removed from SCHEMA_PROFILES
- ✅ `profiles.alertThresholds` and `profiles.thresholdUnits` removed from config
- ✅ `AlertManager.setProfileThresholds` and `convertThresholds` import gone
- ✅ `getAlertThresholdsForProfile`, `THRESHOLD_KEY_TO_PARAMETER`, `_validateAlertThresholds` gone
- ✅ Sweep 2a skipped tests disposed: 2 deleted + backlog filed, 1 rewritten against `setActiveProfile`
- ✅ Backlog entry `B-XXX-per-profile-tiered-threshold-overrides` filed
- ✅ 18 test files cleaned of legacy fixture keys
- ✅ Spool-authoritative values preserved byte-for-byte
- ✅ Fast suite `1504 / 0 skipped`, slow suite `1522 / 1 skipped`, ruff/mypy clean, simulator green
- ✅ Audit notes scratch file deleted
- ✅ Design doc session log updated
- ✅ Merged to main

**On to Sweep 3:** `docs/superpowers/plans/2026-04-12-reorg-sweep3-tier-split.md`. Highest risk in the reorg. 24-hour cooling period after Sweep 2b merges before starting.
