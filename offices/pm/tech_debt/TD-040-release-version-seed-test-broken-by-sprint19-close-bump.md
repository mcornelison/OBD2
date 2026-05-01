# TD-040: test_releaseVersionFile_seedVersionIsV0_18_0 broken by Sprint 19 close version bump

| Field | Value |
|---|---|
| Filed by | Rex (Ralph), Session 114, US-242 verification |
| Date | 2026-04-30 |
| Severity | P1 — fast suite red since 2026-04-30 commit `5025508` |
| Category | test-suite / release-versioning |
| Spotted in scope of | US-242 (B-049 idle-poll escalation) |
| Filed under | CIO Q1 rule — drift outside sprint = TD immediate |

## Summary

`tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_seedVersionIsV0_18_0` fails as of `main@5025508` (Sprint 19 close):

```
E   AssertionError: Story acceptance #2: seed version is V0.18.0 (post-Sprint-18)
E   assert 'V0.19.0' == 'V0.18.0'
```

## Root cause

US-241 (Session 113) shipped `deploy/RELEASE_VERSION` seeded at `V0.18.0` and authored the test to pin that exact value. PM then bumped `V0.18.0 -> V0.19.0` in commit `5025508` per `feedback_pm_sprint_close_version_bump.md` (auto rule: PM bumps version at every sprint close). The test was not updated alongside the bump, and the fast suite has been red on `main` since.

Sprint 20's testBaseline.fastSuite expectation of `3450 / 0 ruff errors` is therefore stale; verifying any Sprint 20 story against "fast suite passes" requires excluding this one test until the test is rewritten.

## Recommended fix shape (PM grooms; not Ralph in-line)

Two viable approaches:

**(a) Rename + relax the test**: `test_releaseVersionFile_holdsValidSemver` — assert shape (`V<major>.<minor>.<patch>` regex + non-empty description) rather than literal value. Stable across all future bumps. Better long-term.

**(b) Update the test alongside every bump**: rename to `test_releaseVersionFile_currentVersion` and embed the active version. Requires PM to remember to update it on every `chore(release)` commit. Brittle; would re-break next sprint close.

(a) is cheaper; (b) is more explicit. PM picks.

## Out of scope for US-242

US-242 is the orchestrator engine-on escalation hook — entirely unrelated to release versioning. Scope Fence preserves: I did not modify the failing test or `deploy/RELEASE_VERSION`. US-242's filesActuallyTouched are limited to `src/pi/obdii/orchestrator/core.py`, `src/pi/obdii/orchestrator/event_router.py`, `src/common/config/validator.py`, `config.json`, and the two new test files under `tests/pi/orchestrator/`.

## Verification commands

```bash
# Reproduce the failure
python -m pytest tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_seedVersionIsV0_18_0 -v

# Confirm the bump commit introduced it (not US-242)
git log --oneline -3 deploy/RELEASE_VERSION
# 5025508 chore(release): bump V0.18.0 -> V0.19.0 (Sprint 19 close)
# 79a28b0 feat(sprint-19): Runtime Fixes + Server Reconciliation SHIPPED 8/8
```

## Related

- US-241 (Session 113) authored the test
- `feedback_pm_sprint_close_version_bump.md` — the rule that triggered the bump
- B-047 (Pi self-update from server release registry) — downstream consumer of the version contract; this TD does not affect runtime behavior, just the test
