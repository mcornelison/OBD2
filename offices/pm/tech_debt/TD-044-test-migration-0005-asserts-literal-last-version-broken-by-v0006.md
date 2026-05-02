# TD-044 -- test_migration_0005_dtc_log asserts literal '0005' as last version, broken by v0006

| Field | Value |
|-------|-------|
| Filed | 2026-05-01 |
| Filed By | Rex (Ralph agent), Sprint 21 Session 124 (US-252 work) |
| Severity | Low (test-only; no production impact) |
| Origin | CIO push `2800c6d fix(migrations): v0006 captures TD-043 hotfix as version-controlled migration` (Sprint 21 grooming, between Session 123 close and Session 124 start) |
| Status | Pending |

## Summary

`tests/server/test_migration_0005_dtc_log.py:158` (`TestModuleExports::test_appendedAtEnd`) asserts:

```python
assert versions[-1] == '0005'
```

This test was correct when v0005 was the last migration in `ALL_MIGRATIONS`. After Marcus's Sprint 21 grooming commit `2800c6d` added v0006 (TD-043 hotfix capture), v0006 is now last and the test fails:

```
AssertionError: assert '0006' == '0005'
- 0005
+ 0006
```

## Analogue to TD-042

Same sprint-contract-integrity class as TD-042 (which catches US-246/US-247/US-248 test stub drift after the `theme` field was added).  The pattern: a test fixture or assertion was hard-coded against a then-current literal rather than a shape, then a later cross-cutting change broke the assertion without anyone updating the test.

## Remediation Options

(a) **Tighten the assertion** -- assert `versions[-1]` matches a SemVer-shape regex (e.g. `r'^\d{4}$'`) rather than a literal value.  This matches the pattern proposed for TD-040 (the V0.18.0 seed test).

(b) **Update to current literal** -- assert `versions[-1] == '0006'`.  Will break again on the next migration.

(c) **Drop the assertion** -- the spirit was "v0005 should be appended, not inserted in the middle"; the reordering/insertion-resistance test could check that v0005's position doesn't change rather than asserting it's last forever.

Recommendation: (a) -- mirrors the shape-not-literal direction from prior TDs.

## Why Not Fixed In-Story

Per Refusal Rule #3 (Scope Fence), US-252 (PowerDownOrchestrator + power_log) cannot touch unrelated test assertions in `tests/server/test_migration_0005_dtc_log.py`.  Per CIO Q1 rule, this drift is filed for PM to wrap into a follow-up story.

## Acceptance Criteria For Closure

- [ ] `tests/server/test_migration_0005_dtc_log.py::TestModuleExports::test_appendedAtEnd` passes against the current `ALL_MIGRATIONS` list.
- [ ] Test asserts shape (SemVer-style 4-digit string) rather than a specific literal so the next migration doesn't break it.
- [ ] Fast suite passes 3646+ stories (one fewer red).

## Cross-References

- TD-042 (sprint-contract-integrity for theme field schema break -- analogous remediation pattern)
- TD-040 (V0.18.0 seed test -- analogous shape-not-literal recommendation)
- CIO commit `2800c6d` (the v0006 migration that triggered this drift)
