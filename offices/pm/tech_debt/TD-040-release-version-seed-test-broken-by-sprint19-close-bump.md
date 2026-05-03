# TD-040: test_releaseVersionFile_seedVersionIsV0_18_0 broken by Sprint 19 close version bump

| Field | Value |
|---|---|
| Filed by | Rex (Ralph), Session 114, US-242 verification |
| Date | 2026-04-30 |
| Severity | P1 — fast suite red since 2026-04-30 commit `5025508` |
| Category | test-suite / release-versioning |
| Spotted in scope of | US-242 (B-049 idle-poll escalation) |
| Filed under | CIO Q1 rule — drift outside sprint = TD immediate |
| Status | **Resolved** |
| Closed In | commit `57bdda6` (CIO, 2026-04-30 — primary closure-in-fact via test deletion) + US-272 (Rex Session 145, 2026-05-03 — added explicit shape-not-literal regex test per Sprint 23 spec) |

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

## Closure (2026-05-03, US-272 Rex Session 145)

Closure happened in **two stages** (records-drift example):

**Stage 1 — closure in fact (commit `57bdda6`, CIO, 2026-04-30 22:21 CDT)**

The theme-field schema addition commit explicitly removed the broken test as a side-channel cleanup. The commit message reads: *"Removed seedVersionIsV0_18_0 (stale Sprint 19 acceptance gate; closes TD-040 via deletion -- Sprint 19 closeout already bumped to V0.19.0)."* This silently closed the TD bug class but the TD record was never updated, so Marcus groomed Sprint 23 still treating TD-040 as red.

**Stage 2 — spec follow-up (US-272, Rex, 2026-05-03)**

Sprint 23 US-272 spec required adding the shape-not-literal test mirror of US-269/TD-044 (`r'^V\d+\.\d+\.\d+$'` regex + non-empty description). Since the rename target was gone, the test was added (not renamed) at `tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_holdsValidSemver`. The new test catches both bug classes the recommended-fix-shape-(a) called for: (a) RELEASE_VERSION malformed (regex fails) and (b) description blank (len-zero fails). Runtime-validation gate per `feedback_runtime_validation_required.md`: mutated `deploy/RELEASE_VERSION` to drop the V prefix → test FAILED with `AssertionError: ...must match V<major>.<minor>.<patch>: got '0.22.0'`; restored, then mutated description to empty → test FAILED with `AssertionError: ...must be non-empty`; restored → test PASSED. Both bug classes now have an explicit gate.

The two-stage closure is itself evidence for AI-001 / US-274 (sprint_lint precondition checking): a TD verifier that runs each open TD's reproduction command against current main would have surfaced this records drift before Sprint 23 grooming consumed a story slot.

## Verification (post-closure)

```bash
# Confirm the broken test is gone
git grep -n 'seedVersionIsV0_18_0' tests/  # no matches expected

# Confirm the replacement test exists and passes
python -m pytest tests/deploy/test_release_versioning.py::TestReleaseVersionFile::test_releaseVersionFile_holdsValidSemver -v
```
