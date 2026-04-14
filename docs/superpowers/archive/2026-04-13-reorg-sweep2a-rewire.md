# Sweep 2a — AlertManager Rewire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire `AlertManager` and its callers to consume thresholds from `config['tieredThresholds']` instead of `profile.alertThresholds`. **No deletions** — every legacy file, field, column, and config block stays in place. Sweep 2b (separate plan, separate merge) performs the dead-code cleanup after 2a proves stable.

**Why split:** The original monolithic Sweep 2 plan assumed `AlertManager` already consumed `tieredThresholds`. The Task 2 audit proved it doesn't — AlertManager is 100% legacy-bound. A single delete would leave alert firing inert. Splitting isolates the logic change (2a, medium risk) from the cleanup (2b, trivial).

**Architecture:** `AlertManager` currently stores `list[AlertThreshold]` per-profile in `_profileThresholds[profileId]`, populated via `setProfileThresholds(profileId, legacyDict)` which calls `convertThresholds()` to translate legacy key names into `AlertThreshold` objects. In 2a, we add a new method `setThresholdsFromConfig(config)` that reads `config['tieredThresholds']` and builds equivalent `AlertThreshold` objects — then rewire orchestrator.py + helpers.py to call the new method and stop reading `profile.alertThresholds`.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git on Windows (MINGW64_NT). No new dependencies.

**Design doc:** `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 7 — sweep 2, now superseded for 2a by this plan).

**Audit notes (required read):** `docs/superpowers/plans/sweep2-audit-notes.md` — committed on sprint branch, contains per-file line numbers and migration instructions. Every 2a task references it.

**Estimated effort:** 1–2 days.

**Prerequisites:**
- Sweep 1 merged to `main` (commit `21029e8`)
- On branch `sprint/reorg-sweep2a-rewire` (renamed from `sprint/reorg-sweep2-thresholds`)
- Task 1 (setup) and Task 2 (audit) of the original Sweep 2 plan **already complete** on this branch; the audit notes file is committed
- `/tmp/tiered-before.json` still exists on disk (snapshot from original Task 1)
- Baseline: 1517 full-suite passing, 1499 fast-suite passing

**Exit criteria:**
1. `AlertManager` has a new public method `setThresholdsFromConfig(config: dict) -> None` that builds thresholds from `config['tieredThresholds']`
2. `src/obd/orchestrator.py` profile-switch handler no longer reads `profile.alertThresholds` (passes through or no-ops)
3. `src/alert/helpers.py.createAlertManagerFromConfig()` calls `setThresholdsFromConfig()` instead of the legacy loop
4. `AlertManager._profileThresholds` at runtime contains `AlertThreshold` objects derived from tiered values: RPM threshold = 7000 (ABOVE), COOLANT_TEMP threshold = 220 (ABOVE). Verified by assertion test.
5. RPM redline alert fires at 7000 RPM (not 6500), coolant temp alert fires at 220°F — **semantic changes documented in merge commit**
6. Boost and oil pressure alerts **silent** (not fired) — documented as expected, PM inbox note filed
7. `tieredThresholds` config section byte-identical to `/tmp/tiered-before.json`
8. Full test suite green (1517 ± N passing, N accounts for new tests added and old tests rewritten)
9. Ruff clean, mypy clean, simulator smoke test green
10. `src/alert/thresholds.py`, `Profile.alertThresholds`, `alert_config_json` column, `profiles.alertThresholds`, `profiles.thresholdUnits` — **all still present** (Sweep 2b's job)
11. PM inbox note filed: `offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md`
12. Design doc session log (section 12) updated with sweep 2a row
13. Merged to `main` with CIO approval

**Risk:** Medium. The rewire touches alert-firing code paths; a bug could make alerts fire at wrong values or not fire at all. Mitigations: explicit preservation test (Task 6), simulator smoke test (Task 7), isolated sprint branch, each task commits independently for git bisect.

**Safety constraint:** `tieredThresholds` values in `src/obd_config.json` are Spool-authoritative and must not change. Task 6 diffs against the snapshot. Any drift = immediate stop + tuner inbox note.

---

## Task 1: Setup — branch sanity + scope verification

**Files:** No file changes. Pure verification task.

- [ ] **Step 1: Confirm branch state**

Run:
```bash
cd Z:/o/OBD2v2
git branch --show-current
git log --oneline -5
git status
```

Expected:
- Branch: `sprint/reorg-sweep2a-rewire`
- Recent commits: `chore: sweep 2 audit notes` on top of sweep 1 merge (`21029e8`)
- Working tree: only the known unrelated `offices/pm/.claude/*` noise from the parallel PM session; do not touch it

- [ ] **Step 2: Confirm audit notes present and readable**

Run:
```bash
cd Z:/o/OBD2v2
ls -la docs/superpowers/plans/sweep2-audit-notes.md
wc -l docs/superpowers/plans/sweep2-audit-notes.md
```

Expected: file exists, ~345 lines, committed on branch.

- [ ] **Step 3: Confirm baseline snapshot still present**

Run:
```bash
ls -la /tmp/tiered-before.json
wc -l /tmp/tiered-before.json
head -3 /tmp/tiered-before.json
```

Expected: 64 lines, valid JSON starting with `{` and `"coolantTemp": {`.

If `/tmp/tiered-before.json` is missing (e.g., system reboot), re-create it:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-before.json
```

- [ ] **Step 4: Confirm PM inbox note filed**

Run:
```bash
ls -la Z:/o/OBD2v2/offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md
```

Expected: file exists. (Already written by controller before Task 1.)

---

## Task 2: Map the STFT / battery / IAT / timing alert paths (investigation only)

**Files:** No code changes. Produces findings appended to `sweep2-audit-notes.md` under `## Sweep 2a Task 2 — non-AlertManager alert paths`.

**Why:** The audit flagged that AlertManager never consumes `tieredThresholds`, but the `tiered_thresholds.py`, `iat_thresholds.py`, and `timing_thresholds.py` evaluation modules clearly exist. We need to know if STFT/battery/IAT/timing alerts are fired through a different path today, or if they're a pre-existing coverage gap. The answer shapes whether 2a's scope should widen.

- [ ] **Step 1: Find callers of the tiered evaluation functions**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "from .*tiered_thresholds\|from .*iat_thresholds\|from .*timing_thresholds\|evaluateTiered\|evaluateIat\|evaluateTiming" src tests 2>/dev/null
```

Record every hit. In particular, note any non-test `src/` files that import from these modules.

- [ ] **Step 2: Trace each caller**

For each non-test caller found in step 1, open the file and determine:
- Does the caller produce an `AlertEvent` (or equivalent) when the evaluate function returns a non-normal result?
- Does that AlertEvent flow to the user (display, log, sound, telemetry)?
- Or does the evaluation result just sit in a return value that nothing propagates?

- [ ] **Step 3: Classify the finding**

Write one of these verdicts into `sweep2-audit-notes.md`:

**Verdict A: Separate path exists and is live.** STFT/battery/IAT/timing alerts fire today via a non-AlertManager path. Sweep 2a does NOT need to wire these through AlertManager. Record the path (file + function) for 2b reference.

**Verdict B: Pre-existing coverage gap.** The tiered evaluation modules exist but nothing consumes their results — STFT/battery/IAT/timing alerts do not fire today. File `offices/pm/tech_debt/TD-alert-coverage-stft-battery-iat-timing.md` with the finding. Sweep 2a scope stays narrow (rpm + coolant only).

**Verdict C: Mixed.** Some parameters have live paths (e.g., via `statistics/analyzer.py`), others don't. Document per-parameter.

- [ ] **Step 4: Commit the appended findings**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep2-audit-notes.md
git commit -m "chore: sweep 2a task 2 — trace non-AlertManager alert paths"
```

If a tech debt file was created in verdict B or C, include it in the same commit.

---

## Task 3: Implement `AlertManager.setThresholdsFromConfig()` with unit tests

**Files:**
- Modify: `src/alert/manager.py` (add new method, DO NOT remove old one)
- Modify: `tests/test_alert_manager.py` (add test class for new method) — verify file exists and is the right location; if not, use `tests/test_alert_threshold.py` or whichever file currently tests AlertManager

**Why:** This is the core of the rewire. The new method is additive — the old `setProfileThresholds(profileId, legacyDict)` stays in place for now (deleted in 2b).

**Design:**

New method signature:
```python
def setThresholdsFromConfig(self, config: dict[str, Any]) -> None:
    """
    Build AlertThreshold objects from config['tieredThresholds'] and
    store them under all profile IDs found in config['profiles']['availableProfiles'].

    After this method runs, every profile has the SAME threshold set (derived
    from tiered), because tiered values are global. Profile-switching no longer
    changes threshold values.

    Args:
        config: Full validated config dict (the same object returned by the config loader)

    Raises:
        AlertManagerError: if config is missing required tieredThresholds keys
    """
```

Internal mapping (2a initial coverage — rpm + coolantTemp only):

```python
# RPM redline — AlertThreshold(parameterName='RPM', alertType='rpm_redline',
#                              threshold=tieredThresholds['rpm']['dangerMin'],
#                              direction=ABOVE, priority=2)
#
# Coolant temp critical — AlertThreshold(parameterName='COOLANT_TEMP', alertType='coolant_temp_critical',
#                                        threshold=tieredThresholds['coolantTemp']['dangerMin'],
#                                        direction=ABOVE, priority=1)
```

**Note on the coolant key**: the tiered schema uses `dangerMin` for coolant (NOT `dangerMax`) because the "danger zone" is defined as "at or above dangerMin". For rpm, it's `dangerMin` for the same reason (above this value = danger). The audit's claim that coolant uses `dangerMax` was an error — verify against `/tmp/tiered-before.json`:
```bash
python -c "import json; t=json.load(open('src/obd_config.json'))['tieredThresholds']; print('coolant dangerMin:', t['coolantTemp']['dangerMin']); print('rpm dangerMin:', t['rpm']['dangerMin'])"
```
Expected: coolant 220, rpm 7000.

**Boost and oil**: Not covered in 2a. The method silently skips parameters not present in `tieredThresholds`. This is intentional (see CIO-approved Option A, semantic changes documented).

- [ ] **Step 1: Read the current AlertManager file fully**

Read: `src/alert/manager.py`. Note the constructor signature, the existing `setProfileThresholds()` method body, where `_profileThresholds` is declared, and the `checkValue()` method (which consumers call to test a reading against thresholds).

- [ ] **Step 2: Read the current AlertManager tests**

Run:
```bash
cd Z:/o/OBD2v2
find tests -name "test_alert*.py" -type f
```

Open each file. Note which test file tests `AlertManager.setProfileThresholds()` — that's where the new unit test class goes.

- [ ] **Step 3: Write unit tests FIRST (TDD)**

Add a new test class `TestAlertManagerSetThresholdsFromConfig` in the AlertManager test file with these tests (write them before the implementation exists — they should fail):

1. `test_setThresholdsFromConfig_buildsRpmRedline_fromTieredDangerMin`
2. `test_setThresholdsFromConfig_buildsCoolantTempCritical_fromTieredDangerMin`
3. `test_setThresholdsFromConfig_populatesAllProfileIds`  — asserts that after calling, `_profileThresholds[profileId]` is populated for each profile in `availableProfiles`
4. `test_setThresholdsFromConfig_missingTieredSection_raisesError`
5. `test_setThresholdsFromConfig_skipsParametersNotInTiered` — given a tieredThresholds with only rpm, the method populates only the RPM threshold, no crash on missing coolantTemp
6. `test_setThresholdsFromConfig_rpmThresholdIs7000_matchesSpoolAuthoritative` — builds from the real `src/obd_config.json` (or equivalent fixture) and asserts threshold=7000, direction=ABOVE
7. `test_setThresholdsFromConfig_boostAndOilNotSet_documented` — asserts that no BOOST_PRESSURE or OIL_PRESSURE threshold is created (this test documents the intentional gap; update it in the future backlog item when Spool adds boost/oil to tiered)

Use existing test fixtures (`config_fixture` or similar) — build minimal `{tieredThresholds: {rpm: {dangerMin: 7000}}, profiles: {availableProfiles: [{id: 'daily'}, {id: 'performance'}]}}` dicts.

Run the new tests to confirm they fail:
```bash
cd Z:/o/OBD2v2
pytest tests/test_alert_manager.py::TestAlertManagerSetThresholdsFromConfig -v 2>&1 | tail -30
```

Expected: all 7 fail with `AttributeError` (method doesn't exist).

- [ ] **Step 4: Implement the method**

Add `setThresholdsFromConfig()` to `AlertManager` in `src/alert/manager.py`. Place it near `setProfileThresholds()` for readability. Follow the signature and design notes above.

Implementation outline (not exact code — adapt to the existing style):
```python
def setThresholdsFromConfig(self, config: dict[str, Any]) -> None:
    tieredThresholds = config.get('tieredThresholds', {})
    if not tieredThresholds:
        raise AlertManagerError(
            "setThresholdsFromConfig: config missing required 'tieredThresholds' section"
        )

    thresholds: list[AlertThreshold] = []

    # RPM redline
    rpmCfg = tieredThresholds.get('rpm', {})
    if 'dangerMin' in rpmCfg:
        thresholds.append(AlertThreshold(
            parameterName='RPM',
            alertType=ALERT_TYPE_RPM_REDLINE,
            threshold=float(rpmCfg['dangerMin']),
            direction=AlertDirection.ABOVE,
            priority=ALERT_PRIORITIES[ALERT_TYPE_RPM_REDLINE],
        ))

    # Coolant temp critical
    coolantCfg = tieredThresholds.get('coolantTemp', {})
    if 'dangerMin' in coolantCfg:
        thresholds.append(AlertThreshold(
            parameterName='COOLANT_TEMP',
            alertType=ALERT_TYPE_COOLANT_TEMP_CRITICAL,
            threshold=float(coolantCfg['dangerMin']),
            direction=AlertDirection.ABOVE,
            priority=ALERT_PRIORITIES[ALERT_TYPE_COOLANT_TEMP_CRITICAL],
        ))

    # Populate every profileId with the same threshold set
    profiles = config.get('profiles', {}).get('availableProfiles', [])
    profileIds = [p['id'] for p in profiles if 'id' in p]
    if not profileIds:
        profileIds = ['default']  # safety fallback

    for profileId in profileIds:
        self._profileThresholds[profileId] = list(thresholds)  # copy per profile

    self._logger.info(
        "setThresholdsFromConfig: built %d thresholds for %d profile(s) from tiered config",
        len(thresholds), len(profileIds),
    )
```

Import what you need (`ALERT_TYPE_*`, `ALERT_PRIORITIES`, `AlertThreshold`, `AlertDirection`) at the top of the file. Do NOT remove the existing `from .thresholds import convertThresholds` — that stays until 2b.

- [ ] **Step 5: Run the new tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_alert_manager.py::TestAlertManagerSetThresholdsFromConfig -v 2>&1 | tail -30
```

Expected: all 7 pass. Fix any failures before proceeding.

- [ ] **Step 6: Run the full alert test subset**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -q -k "alert" --tb=short 2>&1 | tail -30
```

Expected: all pass (old tests still use the old method, new tests use the new method, both coexist).

- [ ] **Step 7: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/alert/manager.py tests/test_alert_manager.py
git commit -m "feat: AlertManager.setThresholdsFromConfig — tiered source of truth (sweep 2a task 3)

Adds a new method that builds AlertThreshold objects from
config['tieredThresholds']. Covers rpm (dangerMin -> ABOVE redline) and
coolantTemp (dangerMin -> ABOVE critical). Boost and oil pressure are
intentionally skipped — Spool has not specified them in tiered yet; see
offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md.

Legacy setProfileThresholds() method stays in place; removed in sweep 2b."
```

---

## Task 4: Rewire callers — orchestrator + helpers

**Files:**
- Modify: `src/obd/orchestrator.py` (profile-switch handler, line 1013)
- Modify: `src/alert/helpers.py` (`createAlertManagerFromConfig`)

**Why:** The new AlertManager method exists but nothing calls it yet. This task switches the wiring over.

- [ ] **Step 1: Update `src/alert/helpers.py.createAlertManagerFromConfig()`**

Read the function (audit notes: legacy code at lines 63-70 of helpers.py). The legacy body loops over `config['profiles']['availableProfiles']` and calls `manager.setProfileThresholds(profile['id'], profile.get('alertThresholds', {}))`.

Replace the loop with a single call:
```python
manager.setThresholdsFromConfig(config)
```

Do NOT delete or modify `getAlertThresholdsForProfile()` — that's 2b's job.

- [ ] **Step 2: Update `src/obd/orchestrator.py` profile-switch handler**

Read lines 1005-1025 of `src/obd/orchestrator.py` (audit notes: the handler reads `newProfile.alertThresholds` at line 1013 and passes it to `self._alertManager.setProfileThresholds(newProfileId, thresholds)` at line 1015).

The correct 2a behavior is that **profile switching does not change threshold values** — thresholds are global (tiered), bound at AlertManager construction, and never rebound on profile switch. So the profile-switch handler should simply **not touch AlertManager**.

Delete the two lines (1013 and 1015), plus any surrounding no-longer-needed setup. Leave any non-threshold profile-switch logic intact (polling interval, display update, etc.).

Add a one-line comment at the deletion site:
```python
# Note: thresholds are global (tiered) and bound at AlertManager construction.
# Profile switching no longer rebinds them.
```

- [ ] **Step 3: Verify `createAlertManagerFromConfig` is the single wiring point**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "setProfileThresholds\|setThresholdsFromConfig" src tests 2>/dev/null
```

Expected:
- `src/alert/manager.py` — method definitions (both old and new)
- `src/alert/helpers.py` — one call to `setThresholdsFromConfig(config)` (the new one)
- `tests/test_alert_manager.py` (and possibly other test files) — test invocations
- **ZERO** references to `setProfileThresholds` in `src/obd/orchestrator.py`

If any production (non-test) file still calls `setProfileThresholds`, fix it before proceeding.

- [ ] **Step 4: Run fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: failures are limited to `test_orchestrator_alerts.py` and `test_orchestrator_profiles.py` (they test the old profile-switch-rebinds-thresholds behavior which no longer exists). Any other failures are bugs — fix them.

If the test failure count is > ~5 tests or the failures span files beyond the two expected, STOP and report — the scope of the rewire may be larger than expected.

- [ ] **Step 5: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add src/alert/helpers.py src/obd/orchestrator.py
git commit -m "refactor: rewire AlertManager wiring to tiered source (sweep 2a task 4)

- alert/helpers.createAlertManagerFromConfig now calls
  setThresholdsFromConfig(config) instead of the per-profile legacy loop.
- orchestrator profile-switch handler no longer re-binds thresholds on
  profile change — thresholds are global/tiered and bound at construction.

Expected test fallout: test_orchestrator_alerts and test_orchestrator_profiles
will fail until updated in sweep 2a task 5."
```

---

## Task 5: Update tests broken by the rewire

**Files:**
- Modify: `tests/test_orchestrator_alerts.py`
- Modify: `tests/test_orchestrator_profiles.py`
- **Leave untouched**: every other test file (fixture-only references stay until 2b)

**Why:** The rewire broke exactly the tests that asserted on the "profile switch rebinds thresholds" behavior. These tests must be updated to match the new reality: thresholds are global, profile switching doesn't change them, RPM threshold is now 7000 (not 6500/6000).

**Important:** Per audit step 12, 14 other `test_orchestrator_*.py` files reference `alertThresholds` but only in fixture dicts — they pass those dicts through the config-loading path but never assert on threshold behavior. Those tests should continue to pass without modification because the rewire doesn't reject unknown keys in profile dicts — `profile.alertThresholds` still exists as a Profile field (deleted in 2b).

- [ ] **Step 1: Read test_orchestrator_alerts.py failing tests**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_alerts.py -v --tb=short 2>&1 | tail -80
```

Note each failing test and its specific assertion.

- [ ] **Step 2: Rewrite test_orchestrator_alerts.py tests**

For each failing test:
- If it verifies "alert fires at the configured threshold" — update the expected threshold to 7000 (for RPM) or 220 (for coolant), pulling from `config['tieredThresholds']` instead of `profile.alertThresholds`
- If it verifies "profile switch rebinds AlertManager thresholds" — rewrite to verify the opposite: profile switching does NOT change AlertManager threshold state (this test documents the 2a semantic)
- If it directly calls `setProfileThresholds(profileId, legacyDict)` — replace with a call to `setThresholdsFromConfig(config)` using a minimal config dict fixture
- If it reads `profile.alertThresholds` to compare — replace with reading from `config['tieredThresholds']`

Do NOT delete tests unless they test a behavior that is now semantically meaningless (e.g., a test that's literally "profile switch produces different threshold values" — that behavior no longer exists, so the test is obsolete).

- [ ] **Step 3: Rewrite test_orchestrator_profiles.py tests**

Audit findings: line 441 asserts `profile.alertThresholds.get('rpmRedline') == 6000`. This test is testing the Profile dataclass's field, not AlertManager behavior. Since `Profile.alertThresholds` is still alive in 2a (deleted in 2b), this assertion should still pass — UNLESS the fixture it's loading has the alertThresholds key removed, OR the config-load path strips it, OR Profile.fromConfigDict() ignores the key.

Read the failing test. If it's a Profile-field assertion that still works because Profile.alertThresholds field exists, leave it alone. If it's an AlertManager-behavior assertion about profile switching, rewrite it (same patterns as test_orchestrator_alerts.py).

- [ ] **Step 4: Run both test files**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/test_orchestrator_alerts.py tests/test_orchestrator_profiles.py -v --tb=short 2>&1 | tail -40
```

Expected: all pass.

- [ ] **Step 5: Run fast full suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: all pass. Target: ≥ 1499 fast-suite passing (same as baseline, allowing +N for new tests).

- [ ] **Step 6: Commit**

Run:
```bash
cd Z:/o/OBD2v2
git add tests/test_orchestrator_alerts.py tests/test_orchestrator_profiles.py
git commit -m "test: update orchestrator alert/profile tests for tiered rewire (sweep 2a task 5)

- RPM threshold expectations now 7000 (Spool-authoritative dangerMin)
  instead of legacy 6500/6000
- Profile-switch tests no longer expect threshold rebinding (thresholds
  are global under tiered)
- Fixture-only test files (12x test_orchestrator_*.py) untouched; their
  legacy alertThresholds dicts still load into Profile.alertThresholds
  field which is alive until sweep 2b"
```

---

## Task 6: Spool-value preservation check (real this time)

**Files:** No changes. Verification only.

**Why:** In the original plan, Task 9 was the preservation check — but it was a byte-diff of `tieredThresholds` in the config file. That check is still valid (and must still pass), BUT 2a adds a stronger check: AlertManager's runtime state must actually contain the Spool values. This is the first time Spool's values are load-bearing in alert firing — preserving them at the config-file layer is necessary but not sufficient.

- [ ] **Step 1: Config-file diff (original preservation check)**

Run:
```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('src/obd_config.json')); print(json.dumps(c['tieredThresholds'], indent=2))" > /tmp/tiered-after.json
diff /tmp/tiered-before.json /tmp/tiered-after.json && echo "UNCHANGED"
```

Expected: `UNCHANGED` with zero diff output. Any diff = immediate stop + tuner inbox note.

- [ ] **Step 2: Spot-check specific Spool values in the config file**

Run:
```bash
cd Z:/o/OBD2v2
python <<'PY'
import json
c = json.load(open('src/obd_config.json'))
t = c['tieredThresholds']
checks = {
    ('coolantTemp', 'normalMin'): 180,
    ('coolantTemp', 'cautionMin'): 210,
    ('coolantTemp', 'dangerMin'): 220,
    ('rpm', 'dangerMin'): 7000,
    ('stft', 'cautionMin'): 5,
}
failed = False
for (param, key), expected in checks.items():
    actual = t.get(param, {}).get(key)
    status = 'OK' if actual == expected else 'DRIFT'
    if status == 'DRIFT':
        failed = True
    print(f"{status}: {param}.{key} = {actual} (expected {expected})")
if failed:
    raise SystemExit(2)
PY
```

Expected: all `OK`, exit 0.

- [ ] **Step 3: Runtime check — AlertManager actually has the tiered values**

Run:
```bash
cd Z:/o/OBD2v2
python <<'PY'
import json
from alert.helpers import createAlertManagerFromConfig
from obd.config import loadConfig  # adjust import to match actual config load path

cfg = loadConfig('src/obd_config.json')  # or whatever the canonical loader is
mgr = createAlertManagerFromConfig(cfg)

# Verify AlertManager internal state
profileIds = list(mgr._profileThresholds.keys())
print(f"Profile IDs with thresholds: {profileIds}")
assert len(profileIds) > 0, "AlertManager has no thresholds after construction"

# Verify RPM threshold is 7000 for each profile
for pid in profileIds:
    rpmThresholds = [t for t in mgr._profileThresholds[pid] if t.parameterName == 'RPM']
    assert len(rpmThresholds) == 1, f"Profile {pid} missing RPM threshold"
    rpm = rpmThresholds[0]
    assert rpm.threshold == 7000.0, f"Profile {pid} RPM threshold is {rpm.threshold}, expected 7000"
    assert rpm.direction.value == 'above', f"Profile {pid} RPM direction is {rpm.direction}"
    print(f"OK: {pid} RPM threshold = {rpm.threshold} ABOVE")

    # Coolant
    coolantThresholds = [t for t in mgr._profileThresholds[pid] if t.parameterName == 'COOLANT_TEMP']
    assert len(coolantThresholds) == 1, f"Profile {pid} missing coolant threshold"
    coolant = coolantThresholds[0]
    assert coolant.threshold == 220.0, f"Profile {pid} coolant threshold is {coolant.threshold}"
    print(f"OK: {pid} COOLANT_TEMP threshold = {coolant.threshold} ABOVE")

print("All preservation checks PASS")
PY
```

Expected: all assertions pass, final `All preservation checks PASS`. Any failure = stop + surface to CIO.

**Note**: adjust imports at the top of the script to match the actual package layout (`from src.alert.helpers` vs `from alert.helpers` etc. — recall the path convention lesson from sweep 1: top-level packages import without `src.` prefix; `src/` is on sys.path via conftest).

---

## Task 7: Full suite + ruff + mypy + simulator smoke test

**Files:** No changes. Verification only.

- [ ] **Step 1: Full test suite (including slow)**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -15
```

Expected: all pass. Target: ≥ 1517 passing (baseline), with new AlertManager tests added. Some tests may have been rewritten (not deleted); count should be approximately 1517 + new-test-count.

Record the final count in the commit message.

- [ ] **Step 2: Ruff**

Run:
```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -15
```

Expected: no new errors compared to baseline. If baseline has pre-existing warnings, they may still appear — compare to main, not zero.

If there are new I001 import-order warnings from the files you edited, run:
```bash
cd Z:/o/OBD2v2
ruff check --fix --select I001 src/alert/manager.py src/alert/helpers.py src/obd/orchestrator.py tests/test_alert_manager.py tests/test_orchestrator_alerts.py tests/test_orchestrator_profiles.py
```

Only fix files you touched in 2a. Don't sweep pre-existing warnings.

- [ ] **Step 3: Mypy**

Run:
```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -15
```

Expected: no new errors. If baseline has pre-existing errors, they may still appear — only new errors are a problem.

- [ ] **Step 4: Simulator smoke test**

Run:
```bash
cd Z:/o/OBD2v2
timeout 30 python src/main.py --simulate --dry-run 2>&1 | tail -40
```

Expected: clean startup, no missing imports, no unhandled exceptions. Simulator runs for 30 seconds and exits cleanly. If the simulator doesn't exit, kill it after 30s and inspect output.

Pay attention to:
- Alert-firing log lines mentioning RPM or coolant — they should reference the correct thresholds (7000, 220)
- No log lines about `alertThresholds` being empty or missing
- No exceptions in the AlertManager initialization path

- [ ] **Step 5: Commit (if any ruff/fixup changes)**

If step 2 produced ruff fixes, commit them:
```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "chore: sweep 2a ruff autofix on touched files (task 7)"
```

Otherwise skip the commit step.

---

## Task 8: Design doc log update, commit, surface to CIO, merge

**Files:**
- Modify: `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 12 — session log)

- [ ] **Step 1: Append sweep 2a entry to design doc section 12**

Read `docs/superpowers/specs/2026-04-12-reorg-design.md` section 12. Append:
```markdown
| 2026-04-13 | 2a | Sweep 2a complete (split from original Sweep 2 after audit found AlertManager was 100% legacy-bound). Added AlertManager.setThresholdsFromConfig() — rewired orchestrator profile-switch and createAlertManagerFromConfig helper to source thresholds from config['tieredThresholds']. RPM threshold is now 7000 (Spool-authoritative, was 6500/6000 legacy). Coolant unchanged at 220. Boost and oil pressure alerts intentionally silent pending Spool tiered specs — backlog items filed in offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md. Full test suite passes (NNN tests). Simulator smoke test green. Sweep 2b (delete pass) queued. |
```

Replace NNN with actual test count.

- [ ] **Step 2: Commit the design doc update**

Run:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 2a status update"
```

- [ ] **Step 3: Surface to CIO for merge approval**

Tell the CIO:
> "Sweep 2a complete. AlertManager now consumes tieredThresholds directly — no more legacy profile-dict dependency for threshold values. RPM alerts fire at 7000 (was 6500/6000 — 7000 is the Spool-authoritative value from US-139). Coolant alerts unchanged at 220°F. Boost and oil pressure alerts are silent until Spool adds tiered specs — backlog note filed in PM inbox.
>
> Legacy files (`src/alert/thresholds.py`, `Profile.alertThresholds`, `alert_config_json` column, `profiles.*.alertThresholds` config) are all still in place — Sweep 2b handles their removal next.
>
> Full test suite passes (NNN tests). Simulator smoke test green. Spool-value preservation checks pass at both the config-file layer and the AlertManager runtime layer.
>
> Ready to merge `sprint/reorg-sweep2a-rewire` to main?"

Wait for explicit approval.

- [ ] **Step 4: After CIO approval, merge to main**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep2a-rewire -m "Merge sprint/reorg-sweep2a-rewire: Sweep 2a complete — AlertManager tiered rewire

Sweep 2a of 6 for the structural reorganization (B-040), split from the
original Sweep 2 plan after audit found AlertManager was 100% legacy-bound.

Changes:
- AlertManager.setThresholdsFromConfig() — new method sources thresholds
  from config['tieredThresholds'] instead of profile.alertThresholds
- alert/helpers.createAlertManagerFromConfig() rewired to call the new method
- obd/orchestrator profile-switch handler no longer re-binds thresholds
  (they are global under tiered)
- Tests updated: test_orchestrator_alerts, test_orchestrator_profiles

Semantic changes (CIO approved, Option A):
- RPM redline: 6500/6000 legacy -> 7000 Spool-authoritative (US-139 value)
- Coolant temp critical: 220F unchanged
- Boost pressure and oil pressure alerts: SILENT until Spool adds tiered
  specs. Backlog items filed in offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md

Legacy code still present (deleted in sweep 2b):
- src/alert/thresholds.py
- Profile.alertThresholds field
- alert_config_json DB column
- profiles.availableProfiles[*].alertThresholds + profiles.thresholdUnits

Spool-authoritative values in tieredThresholds unchanged (byte-diff verified).

Full test suite green. Simulator smoke test green."
git log --oneline -5
```

- [ ] **Step 5: Confirm main is green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 6: Announce completion**

Tell the CIO:
> "Sweep 2a merged to main. Legacy alert code is orphaned (alive but unused). Sweep 2b (pure dead-code delete) is the next sweep — separate plan, separate merge, low risk. Ready to start whenever you are."

Wait for CIO direction.

---

## End of Sweep 2a Plan

**Success criteria:**
- ✅ AlertManager.setThresholdsFromConfig() implemented and unit-tested
- ✅ Orchestrator + helpers rewired; no production code calls setProfileThresholds
- ✅ RPM redline fires at 7000, coolant at 220 (verified at both config layer and AlertManager runtime layer)
- ✅ Boost/oil alerts silent, documented, backlog-noted
- ✅ Legacy files untouched (alive but orphaned, cleaned up in 2b)
- ✅ All Spool-authoritative tiered values unchanged (byte-diff)
- ✅ Full test suite green
- ✅ Merged to main
