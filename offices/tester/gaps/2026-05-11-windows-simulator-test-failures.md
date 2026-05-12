# Gap: 2 test failures on the Windows dev box (`pytest tests/`)

**Date**: 2026-05-11
**Component**: `tests/test_e2e_simulator.py`, `tests/test_simulate_db_validation.py` (+ `src/pi/diagnostics/boot_reason.py`)
**For**: Developer (Ralph)
**Severity**: Low/Medium — `pytest tests/` is not green on the primary dev platform. Neither failure is a feature regression, but the suite should be green where it runs.

## Issue

Running `pytest tests/` on Windows produces 2 failures, both in `@pytest.mark.slow @pytest.mark.integration` simulator tests:

### Failure 1 — `test_e2e_simulator.py::TestE2eSimulator::test_gracefulShutdown_noErrorsInLogs`

```
AssertionError: Found 1 error(s) in logs:
  ... | ERROR | pi.diagnostics.boot_reason | readCurrentBootId |
  Cannot read boot_id from /proc/sys/kernel/random/boot_id:
  [Errno 2] No such file or directory: '/proc/sys/kernel/random/boot_id'
```

Root: `boot_reason.recordBootReason()` is invoked from `lifecycle.py:425` on every orchestrator start (wired in Sprint 25, commit `3603436`), including in `--simulate` mode. On any platform without `/proc/sys/kernel/random/boot_id` (i.e. Windows, the dev box) `readCurrentBootId()` logs the miss at **ERROR** level, and the e2e test asserts no ERROR-level lines in the simulator's output. So this test has been red on Windows since Sprint 25; it passes on the Pi (Linux has that file).

### Failure 2 — `test_simulate_db_validation.py::TestParameterCompletenessAndDataQuality::test_noDuplicateTimestampParameterCombinations`

```
AssertionError: Found 161 duplicate (timestamp, parameter_name) combinations:
  [('2026-05-11T14:23:08Z', 'RPM'), ('2026-05-11T14:23:08Z', 'SPEED'), ...]
```

Root: the simulator wrote multiple rows for the same `(timestamp, parameter_name)` because the simulated poll loop emits all PIDs faster than 1 s and the timestamp is at **second** resolution (`2026-05-11T14:23:08Z`). Production (`src/pi/obdii/data/realtime.py:520-527`) explicitly uses a microsecond-precision timestamp, so this doesn't happen there — but the simulator's data path uses the coarser canonical-ISO form. Either the simulator should write the same high-precision timestamp production does, or this test's "no dupes" assumption is stale and should be relaxed (e.g. assert dupes only across *different* values, or assert per-second row counts are bounded).

## Expected behavior

`pytest tests/` is green on Windows (and the Pi).

## Actual behavior

2 failures as above. Exit code 1.

## Suggested fixes (pick one each)

- **Failure 1**: in `boot_reason.readCurrentBootId()`, treat "the boot-id surface doesn't exist on this platform" (`FileNotFoundError` / non-Linux) as a `WARNING`/`DEBUG` skip, not an `ERROR` — the existing `recordBootReason()` already logs a WARNING "boot-reason detection skipped" right after, so the ERROR is redundant noise. (Reserve ERROR for "the file exists but is unreadable / malformed".) Alternatively, short-circuit `recordBootReason()` when running under `--simulate`. Either fixes the test without weakening it.
- **Failure 2**: make the simulator's realtime-data writer use the same microsecond/millisecond timestamp production uses (preferred — keeps the test meaningful), or, if second-resolution is intentional for the simulator, adjust the test to assert "no duplicate `(timestamp, parameter_name, value)`" or a per-second cap.

## Note

These are `@pytest.mark.slow` tests, so a `pytest -m "not slow"` run is green — which is probably why the sprint baselines say "fastSuite/fullSuite: 4149" with 0 failures (the count was measured without the slow simulator tests, or on the Pi). Worth deciding whether the canonical baseline should include them.
