# Sweep 2 Audit Notes (scratch — deleted before merge)

For each file: classification + symbols/functions affected + migration plan.

Classifications:
- THRESHOLD-LOGIC: uses the value to decide whether to fire an alert → replace with tiered lookup
- DISPLAY-REFERENCE: uses the value for display (e.g. redline indicator) → preserve via tiered
- TEST-DATA: test fixtures using legacy keys → rewrite to use tiered
- OTHER: classify case-by-case

---

## Audit summary

- Files with THRESHOLD-LOGIC: 7
  - `src/alert/thresholds.py` (entire file — core legacy module)
  - `src/alert/manager.py` (setProfileThresholds + convertThresholds import)
  - `src/alert/helpers.py` (createAlertManagerFromConfig + getAlertThresholdsForProfile)
  - `src/alert/__init__.py` (re-exports all 4 legacy symbols from thresholds.py)
  - `src/obd/config/loader.py` (_validateAlertThresholds + default profile inject)
  - `src/obd/orchestrator.py` (profile-switch handler reads alertThresholds to feed AlertManager)
  - `src/profile/types.py` (Profile.alertThresholds field + DEFAULT_ALERT_THRESHOLDS + getAlertConfigJson)
  - `src/profile/manager.py` (reads/writes alertThresholds via alert_config_json DB column)
  - `src/profile/helpers.py` (getDefaultProfileConfig returns alertThresholds, fromConfigDict passes it through)

- Files with DISPLAY-REFERENCE coupling: 0 confirmed
  - No display code reads `profile.alertThresholds['rpmRedline']` or any legacy key.
  - `src/display/` and `src/obd/display_manager.py` contain zero references to `rpmRedline` or `redline`.

- Tests referencing legacy thresholds: 17 files
  - tests/test_database.py
  - tests/test_e2e_simulator.py
  - tests/test_main.py
  - tests/test_obd_config_loader.py
  - tests/test_orchestrator_alerts.py
  - tests/test_orchestrator_connection_recovery.py
  - tests/test_orchestrator_data_logging.py
  - tests/test_orchestrator_display.py
  - tests/test_orchestrator_drive_detection.py
  - tests/test_orchestrator_integration.py
  - tests/test_orchestrator_loop.py
  - tests/test_orchestrator_profiles.py
  - tests/test_orchestrator_shutdown.py
  - tests/test_orchestrator_signals.py
  - tests/test_orchestrator_startup.py
  - tests/test_orchestrator_statistics.py
  - tests/test_orchestrator_vin_decode.py
  - tests/test_simulate_db_validation.py

  Note: 14 of these (all test_orchestrator_*.py except test_orchestrator_alerts.py and test_orchestrator_profiles.py) use alertThresholds ONLY in the shared config fixture (the profile dict with rpmRedline/oilPressureLow). These are fixture-only references — updating the fixture removes all legacy coupling in those files.

- Schema migration needed: YES
  - Column: `alert_config_json TEXT` in the `profiles` table (defined at `src/obd/database.py` line 122, `SCHEMA_PROFILES`).
  - This column stores legacy `alertThresholds` dict as a JSON blob (via `Profile.getAlertConfigJson()`).
  - After sweep: column becomes dead weight. Options: drop column (requires migration script), or leave as NULL-filled dead column for now.
  - Decision for task owner: a `DROP COLUMN` requires a schema migration version bump. The Sweep 2 plan doc should specify whether to drop immediately or deprecate.

- AlertManager verdict: **LEGACY ONLY** — this is a BLOCKER (see details in step 4 section).
  - AlertManager consumes ONLY the legacy system (profile.alertThresholds → convertThresholds → AlertThreshold objects).
  - AlertManager has NO tieredThresholds consumption whatsoever.
  - The tiered system (tiered_thresholds.py, iat_thresholds.py, timing_thresholds.py) is entirely separate — standalone evaluate* functions that are NOT called by AlertManager.
  - Consequence: if legacy alertThresholds are deleted, AlertManager loses ALL its threshold data and fires NO alerts. Task 7 cannot be a trivial dead-code delete — it must rewire AlertManager to consume the tiered system OR the sweep must accept that AlertManager becomes inert until a follow-on sprint rewires it.

- Potential blockers:
  1. **BLOCKER — AlertManager is legacy-only**: AlertManager.setProfileThresholds() feeds exclusively from profile.alertThresholds via convertThresholds(). The tiered system produces TieredThresholdResult objects but AlertManager never reads them. Sweep 2 cannot simply delete the legacy system without either: (a) rewriting AlertManager to consume tieredThresholds, or (b) accepting that alert triggering becomes a no-op stub. CIO must decide before Task 7.
  2. **Schema migration ambiguity**: `alert_config_json` column in the `profiles` table holds legacy data. After sweep, the column is dead. Drop immediately (requires migration) or leave as dead column? Plan doc is silent.
  3. **`thresholdUnits` orphan in obd_config.json** (lines 101-106): `profiles.thresholdUnits` dictionary (`rpmRedline`, `coolantTempCritical`, `oilPressureLow`, `boostPressureMax`) is defined in the config file but has ZERO code references (no src or test file reads it). It should be deleted from `obd_config.json` as part of this sweep, but it is unmentioned in the plan doc.
  4. **orchestrator.py profile-switch handler** (line 1013) reads `newProfile.alertThresholds` to feed AlertManager — this is THRESHOLD-LOGIC, not just a pass-through. Removing alertThresholds field breaks this handler. Task scope must include this file.

---

## src/alert/thresholds.py

- Classification: THRESHOLD-LOGIC (entire file — target for deletion)
- Line count: 170
- Public symbols:
  - `convertThresholds(thresholds: dict[str, float]) -> list[AlertThreshold]`
  - `checkThresholdValue(parameterName, value, thresholds) -> str | None`
  - `getDefaultThresholds() -> dict[str, float]`
  - `validateThresholds(thresholds: dict[str, float]) -> list[str]`
- Docstring summary: Provides threshold conversion and checking without requiring a full AlertManager instance. Converts legacy profile dict keys (rpmRedline, coolantTempCritical, etc.) into AlertThreshold objects.
- Callers:
  - `src/alert/manager.py` line 37: `from .thresholds import convertThresholds` (used at line 207)
  - `src/alert/__init__.py` lines 65-69: re-exports all 4 public symbols; also in `__all__` lines 134-137
  - No external callers outside the alert package (grep found no test or src imports beyond the above)
- Migration plan: delete file entirely after rewiring AlertManager. Remove the 4 imports from `__init__.py` and their `__all__` entries. `convertThresholds` is the critical function — it is the bridge from legacy dict keys to AlertThreshold objects. Until AlertManager is rewired, this file cannot be deleted.

---

## src/alert/manager.py

### AlertManager legacy vs. tiered consumption
- Consumes legacy (alertThresholds): **YES**
  - Line 37: `from .thresholds import convertThresholds`
  - Line 207: `alertThresholds = convertThresholds(thresholds)` inside `setProfileThresholds()`
  - The entire internal `_profileThresholds` dict is populated exclusively via this legacy path
- Consumes tiered (tieredThresholds): **NO**
  - Zero references to `tieredThresholds` anywhere in the file
  - The tiered modules (`tiered_thresholds.py`, `iat_thresholds.py`, `timing_thresholds.py`) are never imported or called
- Verdict: **LEGACY ONLY**

### Line-by-line references

| Line | Symbol | Classification | Notes |
|------|--------|----------------|-------|
| 37 | `from .thresholds import convertThresholds` | THRESHOLD-LOGIC | Import of the target-for-deletion module |
| 71 | `'rpmRedline': 6500` in docstring example | OTHER | Docstring only — safe to update text |
| 205 | `'rpmRedline': 6500, 'coolantTempCritical': 110` in docstring | OTHER | Docstring only — safe to update text |
| 207 | `alertThresholds = convertThresholds(thresholds)` | THRESHOLD-LOGIC | Core conversion call; needs full rewire |
| 208 | `self._profileThresholds[profileId] = alertThresholds` | THRESHOLD-LOGIC | Stores converted objects by profile |
| 210 | `f"Set {len(alertThresholds)} thresholds for profile..."` | THRESHOLD-LOGIC | Side effect of line 207 |

Migration plan for manager.py (Task 7 scope):
- `setProfileThresholds(profileId, thresholds)` method signature and body must change — new version should accept tieredThresholds config section and build AlertThreshold objects from it (e.g., using `tieredThresholds['rpm']['dangerMin']` as the RPM threshold value).
- Remove `from .thresholds import convertThresholds` import.
- Internal `_profileThresholds` dict can remain if the new builder populates it with AlertThreshold objects derived from the tiered config.
- Alternatively, checkValue() could be rewritten to call the tiered evaluate* functions directly — but that is a larger refactor.

---

## src/alert/types.py

- Classification: MIXED — most symbols are shared/required by tiered system too; a subset are legacy-specific
- Legacy-specific symbols (tied exclusively to the profile-dict threshold system):
  - Lines 53-58: `THRESHOLD_KEY_TO_PARAMETER` dict — maps legacy key names (rpmRedline, coolantTempCritical, boostPressureMax, oilPressureLow) to parameter names. This constant exists solely to support `convertThresholds()` in thresholds.py.
- Shared symbols (used by both legacy and tiered paths):
  - `AlertThreshold` dataclass (lines 92-145): used by AlertManager internally (`_profileThresholds`), by tiered_thresholds.py indirectly (TieredThresholdResult is different but AlertThreshold.checkValue is reused). **Do NOT delete.**
  - `AlertDirection`, `AlertState`, `AlertEvent`, `AlertStats`: no legacy coupling; keep.
  - `ALERT_TYPE_*` string constants (lines 38-41): used by both paths — keep.
  - `PARAMETER_ALERT_TYPES` (lines 44-50): maps parameter names to alert type strings. Used in thresholds.py AND independently in tiered evaluation. Keep; or verify no orphaning after thresholds.py deletion.
  - `ALERT_PRIORITIES` (lines 61-66): used in thresholds.py. After thresholds.py deletion, verify if anything else reads it.

Migration plan: delete `THRESHOLD_KEY_TO_PARAMETER` constant only (after thresholds.py is gone). Audit `PARAMETER_ALERT_TYPES` and `ALERT_PRIORITIES` for live tiered consumers before deciding.

---

## src/alert/helpers.py

- Classification: THRESHOLD-LOGIC (partial — two functions are legacy; others are clean)
- Legacy functions:

| Line | Function | Classification | Notes |
|------|----------|----------------|-------|
| 63-70 | `createAlertManagerFromConfig()` — `profile.get('alertThresholds', {})` loop | THRESHOLD-LOGIC | Reads legacy alertThresholds from config profiles and calls `manager.setProfileThresholds()`. This is the primary wiring point between config and AlertManager for legacy data. |
| 82-102 | `getAlertThresholdsForProfile()` | THRESHOLD-LOGIC | Reads `profile.get('alertThresholds', {})` from config dict. Entire function exists only to serve legacy callers. |

- Clean functions (no legacy coupling):
  - `isAlertingEnabled()` — reads `alerts.enabled`; keep
  - `getAlertConfig()` — reads `alerts` section; keep
  - `getDefaultAlertConfig()` — returns cooldown/visual/log settings; keep
  - `validateAlertConfig()` — validates cooldown/enabled/bool settings only; keep

Migration plan:
- `createAlertManagerFromConfig()`: remove the `availableProfiles` loop (lines 66-70). The new wiring should pass the `tieredThresholds` config section to AlertManager instead.
- `getAlertThresholdsForProfile()`: delete function entirely (and remove from `__init__.py` exports and `__all__`).

---

## src/alert/__init__.py

- Re-exports from thresholds.py that must be removed:
  - Line 65-70: `from .thresholds import (checkThresholdValue, convertThresholds, getDefaultThresholds, validateThresholds,)`
  - `__all__` entries (lines 134-137): `'convertThresholds'`, `'checkThresholdValue'`, `'getDefaultThresholds'`, `'validateThresholds'`
- Re-export from helpers.py that must be removed or replaced:
  - Line 47: `getAlertThresholdsForProfile` (from helpers.py — to be deleted)
  - `__all__` line 142: `'getAlertThresholdsForProfile'`
- Note: `obd/__init__.py` also re-exports `getAlertThresholdsForProfile` (line 194, `__all__` line 472) — that must also be removed.

Migration plan: after thresholds.py deletion and helpers.py cleanup, remove the two import blocks and their `__all__` entries from both `alert/__init__.py` and `obd/__init__.py`.

---

## src/profile/types.py

- `DEFAULT_ALERT_THRESHOLDS` constant: **line 43-47**
  ```python
  DEFAULT_ALERT_THRESHOLDS: dict[str, Any] = {
      'rpmRedline': 6500,
      'coolantTempCritical': 220,
      'oilPressureLow': 20,
  }
  ```
  Classification: THRESHOLD-LOGIC (provides fallback values for legacy system)

- `Profile.alertThresholds` field: **line 82**
  ```python
  alertThresholds: dict[str, Any] = field(default_factory=dict)
  ```
  Classification: THRESHOLD-LOGIC

- Method references:
  - `Profile.toDict()` (line 87): includes `'alertThresholds': self.alertThresholds.copy()` at line 98 — must be removed.
  - `Profile.fromDict()` (line 104): reads `data.get('alertThresholds', {})` at line 134 — must be removed.
  - `Profile.fromConfigDict()` (line 141): reads `configProfile.get('alertThresholds', {})` at line 155 — must be removed.
  - `Profile.getAlertConfigJson()` (line 161-169): entire method is legacy; JSON-dumps self.alertThresholds for DB storage. **Delete entirely.**

- `getAlertConfigJson()` callers:
  - `src/profile/manager.py` line 146: `profile.getAlertConfigJson()` in `createProfile()` INSERT
  - `src/profile/manager.py` line 260: `profile.getAlertConfigJson()` in `updateProfile()` UPDATE
  - No test files import or call `getAlertConfigJson()` directly (it is invoked through manager.py)

Migration plan:
- Delete `DEFAULT_ALERT_THRESHOLDS` constant
- Remove `alertThresholds` field from `Profile` dataclass
- Remove `alertThresholds` key from `toDict()`, `fromDict()`, `fromConfigDict()`
- Delete `getAlertConfigJson()` method entirely
- In `profile/manager.py`, replace both `getAlertConfigJson()` calls with `''` or `NULL` (the column becomes dead weight — see schema note)

---

## src/profile/manager.py

Classification: THRESHOLD-LOGIC (reads/writes legacy data to DB; passes through to AlertManager via orchestrator)

### alertThresholds references (detailed)

| Line | Symbol | READ or PASS-THROUGH | Notes |
|------|--------|----------------------|-------|
| 46 | `from .types import DEFAULT_ALERT_THRESHOLDS` | READ | Used at line 522 to populate default profile |
| 139 | `INSERT INTO profiles (..., alert_config_json, ...)` | WRITE | DB persistence of legacy data |
| 146 | `profile.getAlertConfigJson()` | WRITE | Converts `Profile.alertThresholds` to JSON for INSERT |
| 176 | `SELECT id, name, description, alert_config_json, ...` | READ | SELECT includes alert_config_json column |
| 209 | same SELECT in getAllProfiles() | READ | Same as above |
| 252 | `alert_config_json = ?` in UPDATE | WRITE | DB persistence on update |
| 260 | `profile.getAlertConfigJson()` | WRITE | Converts alertThresholds to JSON for UPDATE |
| 489-500 | `_rowToProfile()` parses `alert_config_json` into `alertThresholds` | READ | JSON decode → Profile.alertThresholds |
| 522 | `alertThresholds=DEFAULT_ALERT_THRESHOLDS.copy()` in getDefaultProfile() | READ | Seeds default profile with legacy thresholds |

**Key finding**: ProfileManager does NOT make any threshold-based decisions itself. It is a pure pass-through and persistence layer — stores and retrieves alertThresholds as a JSON blob in the `alert_config_json` column.

**No `setAlertThresholds()` / `updateAlertThresholds()` methods exist.** The alertThresholds field is updated only via the generic `updateProfile()` method.

Migration plan:
- Remove `DEFAULT_ALERT_THRESHOLDS` import (line 46)
- In `createProfile()` INSERT: drop `alert_config_json` from column list AND value tuple (lines 139, 146). If column is kept for backward compat, pass `''` or omit.
- In `getProfile()` and `getAllProfiles()` SELECT: remove `alert_config_json` from SELECT list (lines 176, 209)
- In `updateProfile()` UPDATE: remove `alert_config_json = ?` clause (lines 252, 260)
- In `_rowToProfile()`: remove lines 489-492 (JSON parse) and remove `alertThresholds=alertThresholds` from `Profile()` constructor call (line 500)
- In `getDefaultProfile()` (line 522): remove `alertThresholds=...` kwarg

---

## src/profile/helpers.py

Classification: THRESHOLD-LOGIC (partial — two functions reference legacy data)

| Line | Reference | Classification | Notes |
|------|-----------|----------------|-------|
| 297-316 | `getDefaultProfileConfig()` — `'alertThresholds': DEFAULT_ALERT_THRESHOLDS.copy()` at line 312 | THRESHOLD-LOGIC | Returns a config dict used to bootstrap profiles; includes alertThresholds key |
| 303 | `from .types import DEFAULT_ALERT_THRESHOLDS` (local import in getDefaultProfileConfig) | THRESHOLD-LOGIC | Local import of legacy constant |

All other helper functions (createProfileManagerFromConfig, syncConfigProfilesToDatabase, getProfileByIdFromConfig, getActiveProfileFromConfig, etc.) are clean — they call `Profile.fromConfigDict()` which passes alertThresholds through, but after Profile.fromConfigDict() is cleaned up those callers become clean automatically.

Migration plan:
- In `getDefaultProfileConfig()`: remove `'alertThresholds': DEFAULT_ALERT_THRESHOLDS.copy()` from the returned dict, and remove the local `from .types import DEFAULT_ALERT_THRESHOLDS` import.

---

## src/obd/config/loader.py

Classification: THRESHOLD-LOGIC (two sites: default injection + validation function)

| Line | Reference | Classification | Notes |
|------|-----------|----------------|-------|
| 344-353 | `_validateProfiles()` default profile injection: hardcoded `'alertThresholds': {'rpmRedline': 6500, 'coolantTempCritical': 220}` | THRESHOLD-LOGIC | Creates a legacy-keyed default profile when none exist. After sweep: remove alertThresholds from injected default. |
| 420-456 | `_validateAlertThresholds()` function | THRESHOLD-LOGIC | Entire function validates legacy keys: iterates `profile.get('alertThresholds', {})`, validates rpmRedline (lines 437-447) and coolantTempCritical (lines 450-455). Delete entirely after sweep. |
| 433 | `thresholds = profile.get('alertThresholds', {})` | THRESHOLD-LOGIC | Entry into validation loop |
| 437-447 | rpmRedline validation block | THRESHOLD-LOGIC | Raises ObdConfigError if invalid |
| 449-455 | coolantTempCritical validation block | THRESHOLD-LOGIC | Raises ObdConfigError if invalid |

Migration plan:
- Remove `alertThresholds` from the hardcoded default profile dict in `_validateProfiles()` (lines 344-353).
- Delete the entire `_validateAlertThresholds()` function (lines 420-456).
- Find where `_validateAlertThresholds()` is called and remove that call.

Note: `src/obd/config/loader.py` is the `obd.config` canonical package (Option A from Sweep 1). It is the config validation layer that will also need updating in Task 4 (config validator update per Sweep 2 plan).

---

## src/obd/orchestrator.py

Classification: THRESHOLD-LOGIC (one site — profile-switch handler)

| Line | Reference | Classification | Notes |
|------|-----------|----------------|-------|
| 1013 | `thresholds = getattr(newProfile, 'alertThresholds', {})` | THRESHOLD-LOGIC | Reads legacy alertThresholds from Profile object to feed AlertManager.setProfileThresholds(). This is DECISION-MAKING — it actively wires legacy data to alert firing logic. |
| 1015 | `self._alertManager.setProfileThresholds(newProfileId, thresholds)` | THRESHOLD-LOGIC | Delivers legacy data to AlertManager |

Migration plan:
- After AlertManager is rewired (Task 7) to consume tieredThresholds, this handler must be updated to pass the tiered config instead of `newProfile.alertThresholds`.
- The new call would likely be: `self._alertManager.setTieredThresholds(config['tieredThresholds'])` or similar.
- Until AlertManager rewire is complete, this is the live coupling point that makes the BLOCKER real.

---

## Database schema — alert_config_json column

- Column definition: `src/obd/database.py` line 122: `alert_config_json TEXT,` inside `SCHEMA_PROFILES` (CREATE TABLE IF NOT EXISTS profiles, lines 113-131).
- This column is populated/read exclusively by `src/profile/manager.py`.
- After sweep: column becomes dead (no code writes or reads it).
- **SCHEMA-MIGRATION-NEEDED**: column drop requires ALTER TABLE. This is SQLite — SQLite supports `DROP COLUMN` since 3.35.0 (2021-03-12). A migration script or version-bumped schema re-creation is needed.
- Recommendation: add `-- DEPRECATED: alert_config_json removed in Sweep 2` comment and drop in the same PR, with a migration SQL file. But the plan doc is silent on this — flag for CIO decision.

---

## Tests — legacy threshold references

All 17 test files use `alertThresholds` / `rpmRedline` as **TEST-DATA** (fixture config dicts), NOT as direct imports of legacy symbols. There are NO imports of `convertThresholds`, `validateThresholds`, etc. in test files.

| File | Usage type | Notes |
|------|------------|-------|
| tests/test_orchestrator_alerts.py | Fixture config dict + direct Profile.alertThresholds assignment (line 573-574, 608) + assertions on alertThresholds (line 585) | MOST INVASIVE — 3 sites: fixture, direct attribute set, and direct call to `setProfileThresholds()` with legacy dict |
| tests/test_orchestrator_profiles.py | Fixture config dict + assertion at line 441 (`profile.alertThresholds.get('rpmRedline') == 6000`) | Needs fixture update + assertion removal |
| tests/test_obd_config_loader.py | Fixture config dict + mutation tests at lines 553-558 (rpmRedline=-100 validation) and 569 (coolantTempCritical='hot') + default profile alertThresholds at lines 752, 757 | Needs fixture update + delete validation-targeted tests (or replace with tiered validation tests) |
| tests/test_database.py | Line 524: hardcoded `'{"rpmRedline": 6500}'` JSON string in INSERT fixture | Single string literal — easy update (or drop alert_config_json entirely) |
| tests/test_e2e_simulator.py | Lines 176-177: alertThresholds dict in config fixture | Fixture only — update config fixture |
| tests/test_main.py | Line 110: `'alertThresholds': {}` | Fixture only — remove key |
| tests/test_simulate_db_validation.py | Lines 219-220: alertThresholds dict in config fixture | Fixture only — update config fixture |
| All other test_orchestrator_*.py (12 files) | All have identical 4-line fixture block with `'alertThresholds': {'rpmRedline': 6000/7000, ...}` | Fixture only — mechanical removal from config dict |

Total test files needing changes: 17
- 14 files: fixture-only update (remove alertThresholds key from profile dict in conftest/fixture)
- 3 files require deeper surgery: test_orchestrator_alerts.py, test_orchestrator_profiles.py, test_obd_config_loader.py

---

## src/obd_config.json — legacy threshold entries

Two legacy sections that must be removed:
1. `profiles.thresholdUnits` (lines 101-106): metadata dict (`rpmRedline`, `coolantTempCritical`, `oilPressureLow`, `boostPressureMax`) — ZERO code references; delete.
2. `profiles.availableProfiles[*].alertThresholds` (lines 112-116 for daily, 123-128 for performance): the actual legacy values — delete both `alertThresholds` objects from each profile entry.

---

## Task migration map (for controller to distribute to Tasks 3-7)

| Task | Files | Key actions |
|------|-------|-------------|
| Task 3: Config file cleanup | `src/obd_config.json` | Remove `profiles.thresholdUnits`, remove `profiles.availableProfiles[*].alertThresholds` from both profiles |
| Task 4: Validator update | `src/obd/config/loader.py` | Delete `_validateAlertThresholds()`, remove alertThresholds from default profile injection in `_validateProfiles()`, find and remove `_validateAlertThresholds()` call site |
| Task 5: Profile cleanup | `src/profile/types.py`, `src/profile/manager.py`, `src/profile/helpers.py` | Remove alertThresholds field, DEFAULT_ALERT_THRESHOLDS, getAlertConfigJson, DB write/read of alert_config_json; also schema migration for alert_config_json column drop |
| Task 6: Alert module cleanup | `src/alert/thresholds.py`, `src/alert/__init__.py`, `src/alert/helpers.py`, `src/alert/types.py`, `src/obd/__init__.py` | Delete thresholds.py, remove exports, delete getAlertThresholdsForProfile, delete THRESHOLD_KEY_TO_PARAMETER; depends on Task 7 being done first (AlertManager rewire) |
| Task 7: AlertManager rewire | `src/alert/manager.py`, `src/obd/orchestrator.py` | BLOCKER DECISION REQUIRED — rewire setProfileThresholds() to consume tieredThresholds config; update orchestrator profile-switch handler; until decided, Tasks 3-6 can proceed but thresholds.py cannot be deleted |
| Tests | 17 test files | 14 fixture-only (remove alertThresholds key); 3 files need deeper edits (test_orchestrator_alerts.py, test_orchestrator_profiles.py, test_obd_config_loader.py) |

---

## Sweep 2a Task 2 — non-AlertManager alert paths (investigation)

**Date**: 2026-04-13
**Verdict**: B — Pre-existing coverage gap

### Summary

The tiered evaluation modules (`tiered_thresholds.py`, `iat_thresholds.py`, `timing_thresholds.py`) exist with
full evaluation logic, but their results are never routed to a user-visible output (display, log, audio,
telemetry, AlertEvent) except for RPM and coolant temp via the primary screen display. STFT, battery voltage,
IAT, and timing advance alerts do not fire anywhere in the live runtime today.

### Import callers found (non-test, non-definition)

| File | Line | What it imports | In live path? |
|------|------|-----------------|---------------|
| `src/alert/iat_thresholds.py` | 36 | `AlertSeverity, TieredThresholdResult` from `.tiered_thresholds` | Internal to module only |
| `src/alert/timing_thresholds.py` | 36 | `AlertSeverity, TieredThresholdResult` from `.tiered_thresholds` | Internal to module only |
| `src/alert/__init__.py` | 54, 73, 88 | All evaluate/load/tracker symbols re-exported | Re-export only, no invocation |
| `src/display/screens/boost_detail.py` | 33 | `AlertSeverity` from `alert.tiered_thresholds` | Yes — enum used for display color logic only |
| `src/display/screens/fuel_detail.py` | 33 | `AlertSeverity` from `alert.tiered_thresholds` | Yes — enum used for display color logic only |
| `src/display/screens/primary_screen.py` | 35–41 | `AlertSeverity`, `TieredThresholdResult`, `evaluateCoolantTemp`, `evaluateRPM` | Yes — evaluateCoolantTemp and evaluateRPM called for display coloring |

### Function-name callers found (non-test, non-definition)

| File | Line | Function called | Result user-visible? |
|------|------|-----------------|----------------------|
| `src/display/screens/primary_screen.py` | 224 | `evaluateCoolantTemp(value, thresholds)` | Yes — severity drives screen color |
| `src/display/screens/primary_screen.py` | 233 | `evaluateRPM(value, thresholds)` | Yes — severity drives screen color |
| `src/alert/iat_thresholds.py` | 197, 200 | `evaluateIAT(value, self._thresholds)` | No — internal to `IATSensorTracker.evaluate()`; tracker never instantiated outside tests |

No production caller of `evaluateSTFT`, `evaluateBatteryVoltage`, `IATSensorTracker.evaluate()`, or
`TimingRetardTracker.evaluate()` was found anywhere in `src/`.

### Per-parameter verdict

- **STFT**: **Gap.** `evaluateSTFT` is defined in `tiered_thresholds.py` and exported from `alert/__init__.py`
  but never called by any runtime code. `fuel_detail.py` has its own inline `_evaluateFuelTrim()` that uses
  hardcoded thresholds independent of config.
- **Battery voltage**: **Gap.** `evaluateBatteryVoltage` is defined and exported but never called by any
  runtime code. No display screen or manager invokes it.
- **IAT**: **Gap.** `evaluateIAT` is wrapped inside `IATSensorTracker.evaluate()`, which is a well-designed
  stateful evaluator (with sensor-failure detection). However, `IATSensorTracker` is never instantiated in
  any runtime path — only in tests. The logic is ready but not wired.
- **Timing advance**: **Gap.** `TimingRetardTracker.evaluate()` is a sophisticated baseline-learning evaluator
  with knock-pattern detection. It is exported from `alert/__init__.py` but never instantiated in any runtime
  path — only in tests. Note: there is no standalone `evaluateTiming()` free function; evaluation requires
  the stateful tracker.

### AlertManager.checkValue() caller trace

`AlertManager.checkValue()` **is** live. It is called in two places:

1. `src/obd/orchestrator.py` line 978: every polled PID value passes through `self._alertManager.checkValue(paramName, value)` inside `_handleOBDReading()`. This is the main runtime alert path.
2. `src/obd/simulator_integration.py` line 740: same pattern, in the simulated drive path.

However, `AlertManager.checkValue()` dispatches only against `_profileThresholds` — a dict populated via
`setProfileThresholds()` which converts legacy `profile.alertThresholds` key-value pairs through
`convertThresholds()` into `AlertThreshold` objects. These legacy thresholds cover a handful of simple
high/low comparisons (`rpmRedline`, `coolantTempCritical`, etc.) — not STFT, battery voltage, IAT, or
timing advance. AlertManager is live and working, but it only checks legacy thresholds; tiered evaluation
modules are unused by it.

### Implication for Sweep 2a scope

**Stay narrow.** Sweep 2a should rewire AlertManager to consume `config['tieredThresholds']` for RPM and
coolant temp (replacing the legacy `rpmRedline`/`coolantTempCritical` keys) as planned. The STFT, battery
voltage, IAT, and timing advance gap is a separate, pre-existing problem: those evaluators are complete and
well-tested, they just have no call sites in runtime code. Widening Sweep 2a to wire all four parameters
through AlertManager would be a significant scope increase requiring new orchestrator plumbing (especially
`TimingRetardTracker`, which needs RPM + load alongside the value — a different signature from simple
`checkValue(paramName, value)`). File as tech debt, fix in a follow-on sprint.
