# I-simulate-duplicate-timestamp-parameter-rows

**Filed by:** Rex (Ralph dev) · **Date:** 2026-06-29 · **During:** US-388 (Sprint 47 / V0.29.1)
**Severity:** Low–Med (test-suite red; data-quality question) · **Status:** OPEN, unowned

## Summary

`tests/test_simulate_db_validation.py::TestParameterCompletenessAndDataQuality::test_noDuplicateTimestampParameterCombinations`
FAILS: the simulate-mode run writes **185 duplicate `(timestamp, parameter_name)`
rows** into `realtime_data` (e.g. `('2026-06-29T13:03:01Z', 'RPM')` appearing
twice). The test asserts zero such duplicates.

## NOT a US-388 regression (verified)

I hit this in the US-388 full-suite sweep and verified it is **pre-existing**:

- US-388 touches only the drive-close state machine (`src/pi/obdii/drive/detector.py`)
  and an off-tick `evaluateTimeouts()` call in `runLoop` (`core.py`). Neither writes
  `realtime_data` rows — the duplicate is entirely in the `RealtimeDataLogger` write path.
- **Decisive check:** I temporarily restored both files to their `HEAD` baseline
  (`git show HEAD:…`) and re-ran the test — **it still FAILED with the same 185
  duplicates.** So the failure exists without any US-388 change. (Files restored;
  working tree intact.)

US-388 proceeded to `passes:true` on this basis (its scoped gates — the US-386
reproducer, off-tick unit tests, loop-wiring test, and the detector / drive /
orchestrator-loop regression suites — are all green).

## Likely root cause (hypothesis, not investigated to ground)

`realtime_data.timestamp` is a **second-granularity** ISO string (`utcIsoNow()` →
`YYYY-MM-DDTHH:MM:SSZ`). The simulator emits readings for a parameter **faster than
once per second**, so two readings of the same parameter land in the same
second-timestamp → a duplicate `(timestamp, parameter_name)` pair. This is
timing/rate-dependent (machine speed + poll cadence), which is why it can pass on a
slow box and fail on a fast one. Two real possibilities for the team to rule between:

1. **Test-fidelity bug** — the invariant "no two rows share a (second-timestamp,
   parameter)" is simply false at sub-second poll rates; the assertion should key on a
   higher-resolution timestamp or on `(id)` instead. (Most likely.)
2. **Real data-quality issue** — if production also writes sub-second-duplicate rows,
   downstream second-bucketed analytics could double-count. Worth a quick check of
   whether `realtime_data` has/needs a finer timestamp or a uniqueness guard.

## Recommendation

Route to a future grooming slice (server/Pi data-quality). Out of scope for US-388
(Scope Fence). Evidence above is sufficient to triage without re-deriving.
