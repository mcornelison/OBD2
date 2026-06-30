---
id: US-398
title: "Fix simulate duplicate (timestamp, parameter) rows -- test-fidelity vs data-quality ruling"
type: issue
parent: F-006
epicId: E-OPS
size: S
status: sprint-ready
sourceRefs: [F-006, prd-V0.29.2, I-simulate-duplicate-timestamp]
created: 2026-06-29
---

# US-398 — Fix simulate duplicate (timestamp, parameter) rows (bug)

## Context

`test_noDuplicateTimestampParameterCombinations` fails on a fast box (185 dups)
because the "no two rows share a (second-timestamp, parameter)" invariant is false
at sub-second poll rates (`realtime_data.timestamp` is second-granularity ISO). This
is investigation + fix, NOT investigation-only: rule between test-fidelity vs real
data-quality, then implement the corresponding fix. BENCH-ONLY validation.

## Goal

As the simulate-mode test suite, I want `test_noDuplicateTimestampParameterCombinations`
to pass deterministically, with the underlying data-quality question resolved.

## Definition of Done

- rule between **(a) test-fidelity** — the "no two rows share a (second-timestamp, parameter)" invariant is false at sub-second poll rates (`realtime_data.timestamp` is second-granularity ISO); the assertion should key on a higher-resolution timestamp or `id`; vs **(b) real data-quality** — if production also writes sub-second-duplicate rows, second-bucketed analytics could double-count → needs a finer timestamp or a uniqueness guard; then **implement the corresponding fix** (NOT investigation-only)
- the test passes deterministically (machine-speed-independent)
- the ruling (a vs b) + the fix are documented
- if (b), the `realtime_data` write path / analytics is corrected (NOT just the test)

## Validation Criteria (bench)

- (run `pytest tests/test_simulate_db_validation.py::...::test_noDuplicateTimestampParameterCombinations -q`) → (passes — and passes on a fast box, where it currently fails with 185 dups)
- (if ruling=(b): a query/test on production `realtime_data` for second-bucketed double-counting) → (confirms production no longer double-counts in second-bucketed analytics)

## Conditional Outcomes

- if ruling=(b) real data-quality, fix the `realtime_data` write path / analytics, not just the test

## Notes

Independent of the F-103 chain (US-393..396). Issue ref:
`offices/pm/issues/I-simulate-duplicate-timestamp-parameter-rows.md`.
