# TD-042: `theme` field on release schema broke US-246/247/248 test stubs (24 tests)

| | |
|---|---|
| Severity | medium |
| Status | Resolved |
| Filed By | Rex (Ralph Agent 1) — Session 121 |
| Surfaced In | US-245 full-suite verification, 2026-04-30 |
| Closed In | US-268 (Rex Session 140), 2026-05-02 |
| Blocking | Sprint 20 contract integrity — 3 stories listed `passes:true` are no longer passing |

## Closure (US-268, 2026-05-02)

Mechanical schema-sync fix per the "Expected behavior / Proper fix" section below: added `"theme": "test sprint"` to the four stub helpers (`_writeLocalDeployVersion` + `_serverRecord` in `tests/pi/update/test_update_checker.py`, `_writePostDeployVersion` in `tests/pi/update/test_update_applier.py`, `_validRecord` in `tests/server/test_release_reader.py`, `_validRecord` in `tests/server/test_release_endpoint.py`). Intentionally-invalid `bad` fixture in `test_release_reader.py:98` (negative-path coverage for missing-keys schema rejection) left untouched. No production code changes; `composeReleaseRecord` regression test from `57bdda6` still passes.

Pre-flight: targeted suite ran 24 failed / 40 passed, exact match to TD-042 baseline. Post-fix: 64 passed / 0 failed across the same 4 files. Full fast-suite went from 3845 passed / 26 failed (Session 139 baseline) to **3869 passed / 2 failed** — delta +24 pass, -24 fail, ZERO regressions. The 2 residual failures are pre-existing on main and out of scope: B-044 lint on `scripts/seed_eclipse_vin.py` (already on main), TD-044 `test_appendedAtEnd` (closure scheduled by US-269 in same sprint).

Run time: 993.83s (16:33).

## Problem

CIO commit `57bdda6` (Thu Apr 30 22:21:34 2026, "feat(release): add theme field (50-char max) to release record schema") made `theme` a hard-required key in `RELEASE_RECORD_KEYS`. Validation now rejects records that lack `theme` or have it empty.

The Pi-side update-checker tests (Session 118 / US-247) and server-side release-reader/endpoint tests (Session 117 / US-246) were authored BEFORE `57bdda6` landed. Their stub records (`_serverRecord`, `_writeLocalDeployVersion`, JSONL test fixtures) have no `theme` field, so `validateRelease` now rejects them and the checker/reader silently bails out before the assertions can fire.

**24 failing tests across 4 files** (full-suite run 2026-04-30 23:39, exit code 1):

```
tests/pi/update/test_update_checker.py            — 12 failures (TestVersionComparisonDecision,
                                                     TestHttpRequestShape, TestNetworkErrors,
                                                     TestDriveStateGating,
                                                     TestMarkerFileParentCreation,
                                                     TestCheckResultShape)
tests/pi/update/test_update_applier.py            — 5 failures (TestSafetyGates, TestEnabledGate,
                                                     TestSuccessPath)
tests/server/test_release_reader.py               — 6 failures (TestReadCurrent, TestReadHistory)
tests/server/test_release_endpoint.py             — 1 failure (TestReaderResolution)
                                          ─────────────────────────────────────────────
                                          24 failed, 3669 passed, 17 skipped, 19 deselected
                                          (787s / 13:07; full fast-suite, 2026-04-30)
```

Sample failure — `test_checkForUpdates_sendsXApiKeyHeader`:
```
assert len(opener.calls) == 1
E   assert 0 == 1
E    +  where 0 = len([])
E    +    where [] = <function _jsonOpener.<locals>._opener at 0x...>.calls
```
The opener never got invoked because `validateRelease` rejected the test stub (`_serverRecord(version="V0.20.0")` returns a dict without `theme`).

## Why this surfaced now

Stories US-246/247/248 reported `passes:true` in their respective sessions (117/118/119 closeouts) and the test files run cleanly at the time. Commit `57bdda6` landed AFTER Session 119 closeout. None of US-249 / US-242 / US-243 / US-244 ran the full fast-suite to a finish post-`57bdda6` (Session 119 ran 3621 passed before the bump; Session 120 documented an SDK pipe-buffering issue that prevented full-suite completion). So this regression sat hidden in the working tree until US-245 (this session) re-ran the full fast-suite to a clean finish.

Note: the relevant source files (`src/pi/update/`, `src/server/api/release.py`, `src/server/services/release_reader.py`) and their test files are still **untracked in git** (`?? src/pi/update/`, `?? tests/pi/update/...`). PM has not yet committed them. So the regression is in the working tree only; no commit-side fix is needed beyond updating the stubs before the eventual commit.

## Expected behavior / Proper fix

Update test stubs to include the new `theme` field per the CIO push schema. Mechanical addition; no logic changes:

```python
# Before (current, broken):
def _serverRecord(version="V0.20.0"):
    return {
        "version": version,
        "releasedAt": "2026-04-30T...",
        "gitHash": "abc1234",
        "description": "test",
    }

# After (with theme):
def _serverRecord(version="V0.20.0"):
    return {
        "version": version,
        "releasedAt": "2026-04-30T...",
        "gitHash": "abc1234",
        "theme": "test sprint",
        "description": "test",
    }
```

Apply to each stub site:
1. `tests/pi/update/test_update_checker.py` — `_serverRecord` helper + `_writeLocalDeployVersion` helper (writes JSON to `.deploy-version`)
2. `tests/pi/update/test_update_applier.py` — `_writeLocalDeployVersion` helper if used; any inline test fixtures
3. `tests/server/test_release_reader.py` — JSONL fixture lines + dict-literal stubs
4. `tests/server/test_release_endpoint.py` — `_serverRecord` or equivalent

## Acceptance for fix

* All 24 listed failing tests pass when run individually.
* Full fast-suite reaches green (`pytest tests/ -m 'not slow' -q` exits 0).
* `composeReleaseRecord` regression test (added in `57bdda6`) still passes — no rollback of the schema change.
* Story handoff notes in `ralph_agents.json` updated to reflect the post-fix passing state.

## Related

* CIO push `57bdda6` (the schema change that surfaced this).
* US-241 (Session 113) — original release-record DDL; predates `theme`.
* US-246 / US-247 / US-248 (Sessions 117/118/119) — the 3 stories whose tests this breaks. All listed `passes:true` in `sprint.json` so this is a sprint-contract-integrity issue that PM should track.
* TD-040 (Session 114) — earlier deploy-version test breakage from main@5025508 Sprint 19 close PM bump; closed by the same `57bdda6` push that broke this. Pattern: schema changes from CIO/PM landing on main between Ralph sessions cause silent test breakage that surfaces only when the next session runs the full fast-suite to completion.
