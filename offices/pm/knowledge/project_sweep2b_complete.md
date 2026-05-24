---
name: Sweep 2b Complete
description: Sweep 2b legacy-threshold dead-code delete merged to main 2026-04-13 (commit d65d52f). Final removal of the orphaned legacy alert threshold system.
type: project
originSessionId: ff63b873-43d6-4637-ad1f-bdfd89d7fcd3
---
**Status:** Merged to main as commit `d65d52f` on 2026-04-13.

**Why:** Sweep 2a rewired AlertManager to consume `config['tieredThresholds']` but left the legacy surface alive as dead weight. Sweep 2b excised it — pure cleanup pass, no behavior change.

**How to apply:** This sweep is closed. When working in src/alert/, src/profile/, or src/obd/config/, do not look for `alertThresholds`, `getAlertConfigJson`, `DEFAULT_ALERT_THRESHOLDS`, `convertThresholds`, `setProfileThresholds`, `getAlertThresholdsForProfile`, `THRESHOLD_KEY_TO_PARAMETER`, `_validateAlertThresholds`, or `alert_config_json` — they're gone. AlertManager uses `setThresholdsFromConfig(config)` only.

## What was deleted

- `src/alert/thresholds.py` (169 lines — the whole file)
- `Profile.alertThresholds` field, `DEFAULT_ALERT_THRESHOLDS` constant, `getAlertConfigJson()` method in `src/profile/types.py`
- `alert_config_json TEXT` column from `SCHEMA_PROFILES` in `src/obd/database.py` (direct DDL rewrite, no migration)
- `profiles.*.alertThresholds` and `profiles.thresholdUnits` blocks from `src/obd_config.json`
- `AlertManager.setProfileThresholds()` + `convertThresholds` import
- `getAlertThresholdsForProfile()` helper in `src/alert/helpers.py`
- `THRESHOLD_KEY_TO_PARAMETER` constant in `src/alert/types.py`
- `_validateAlertThresholds()` function + call + default-profile injection dict in `src/obd/config/loader.py`
- Stale re-exports from `alert/__init__.py`, `profile/__init__.py`, `obd/__init__.py`
- All `alert_config_json` references in ProfileManager SQL

## Skipped-test disposition

CIO rewrite-first policy applied per test:
- **Test 1** (`test_orchestrator_alerts.py::test_profileChange_updatesAlertThresholds`) — **deleted**, square-peg (profile-switch-rebinds-thresholds premise can't exist post-2a)
- **Test 2** (`test_orchestrator_profiles.py::test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds`) — **deleted**, same scenario
- **Test 3** (`test_orchestrator_profiles.py::test_handleProfileChange_survivesAlertManagerError_continuesRunning`) — **rewritten** to mock `setActiveProfile` raising instead of `setProfileThresholds`; robustness concern still valid
- **Backlog entry B-035** filed: `offices/pm/backlog/B-035-per-profile-tiered-threshold-overrides.md` captures the future feature that would resurrect Tests 1 & 2

## Tests preserved

- Fast suite: 1504 passed, 0 skipped (baseline 1503/3)
  - Wait: corrected post-merge: the actual fast-suite count on main after Sweep 2b merge is **1501 / 0 skipped** because my earlier math didn't factor the 3 deleted `TestValidateAlertThresholds` tests. The 1504 number in the merge commit body is wrong but content-wise the deletion list is accurate.
- Full suite: 1519 passed, 1 skipped (baseline 1521/4 − 3 − 2 + 1)
- `tieredThresholds` byte-identical to pre-sweep snapshot (verified via diff — empty)
- Simulator smoke test green

## Mid-sweep recovery

Parallel PM session flipped the working tree mid-sweep; Tasks 3 and 4 committed to `main` instead of the sprint branch. Recovery: cherry-picked onto sprint branch, reset main back to plan commit. Zero data loss. Lesson learned: every subagent prompt now includes a preflight `git branch --show-current` check as the first instruction.

## Spin-off artifacts

- **B-035** per-profile-tiered-threshold-overrides backlog entry
- `feedback_parallel_session_branch_gotcha.md` memory (already existed, strengthened)
- Preflight branch check pattern in subagent prompts (standardized for Sweeps 3+)
