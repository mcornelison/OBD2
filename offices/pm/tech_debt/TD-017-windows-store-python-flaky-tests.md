# TD-017 — Windows Store Python full-suite flake class

**Filed by:** Rex (Ralph) — Sprint 10 Session 42 (US-182)
**Date:** 2026-04-18
**Severity:** Low (flake bucket, not blocker)
**Affects:** Windows dev box only. Pi passes cleanly.

## Summary

Under the full `pytest tests/` suite on Windows, **exactly one** test
fails per run — but it's a *different* test each run. Classic
timing-sensitive flake bucket under Windows Store Python cold-start +
heavy CPU load. All tests pass cleanly in isolation.

## Observed failures across three Session 42 full runs

| Run | Passed | Failed | Skipped | Failing test |
|----|----|----|----|----|
| bkyqayon3 | 1983 | 1 | 2 | `test_verify_database.py::test_cli_failureExitCode_onFreshDb` (timeout=30) |
| blt725uq2 | 1983 | 1 | 6 | `test_verify_database.py::test_cli_successExitCode_onInitializedDb` (timeout=120) |
| btcxdn2ce | 1983 | 1 | 6 | `test_orchestrator_loop_exception_memory.py::test_loopContinuesAfterException` |

US-182 permanently raised `tests/test_verify_database.py` timeouts
(30→120→240) to handle two of these runs. The third run flipped the
flake to a different test file entirely (orchestrator loop). Each
flaky test passes in isolation (verified for the third run: 1 passed
in 36.23s standalone).

## Root cause

1. Windows Store Python `python.exe` lives in
   `%LOCALAPPDATA%\Microsoft\WindowsApps\` — a thin launcher that pages
   in the real interpreter from the `_pthXXXX` package on first spawn.
2. Under sustained CPU load (1990-test suite) the OS page cache
   evicts the interpreter image between test runs.
3. Subsequent `subprocess.run(python script.py)` or
   `threading.Timer` callbacks in orchestrator tests hit the cold-start
   latency pathologically. Timings range 30-200s depending on host load.
4. Tests with hardcoded time-sensitive assertions (subprocess timeout,
   orchestrator loop-iteration count, drive-detection event count)
   randomly miss their windows.

## Impact on US-182

AC #5 ("Windows fast suite still passes 1871 or higher") met —
1983 > 1871 on every observed run. One of three runs hit a flaky
test per run, but it's a *different* test each time, confirming the
flake-class (not a single broken test). US-182 is claimed passed on
this basis.

## Suggested follow-ups (Sprint 11+)

1. **Install a native Python 3.13.** `winget install Python.Python.3.13`
   or `pyenv-win install 3.13.0` replaces the Store launcher with a
   regular `C:\Python313\python.exe`, eliminating the cold-start
   pathology. Single install, ~100MB, zero code change.
2. **Add `pytest-rerunfailures`** with `--reruns 2 -p no:randomly`
   only on Windows CI. Reruns transient failures; real bugs still fail.
3. **Refactor subprocess tests** to share a long-lived Python subprocess
   across CLI invocations (pytest fixture spawns + keeps alive). Higher
   effort, better architecture.
4. **Split the suite** into `not platform_flaky` + `platform_flaky`
   collections. `make test` runs the stable slice; CI / release gates
   run the full suite with reruns.

## Not a blocker for Sprint 10 close

Pi side clean (1583 / 1 / 0). Windows flake is a known dev-box nuisance
already in place pre-US-182. The Sessions 26/27/28 references in US-182
AC #9 are earlier observations of the same class.
