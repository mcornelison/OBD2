# V0.27 chain validation status (Tester re-engaged) + 2 small bugs

**Date**: 2026-05-11
**From**: Tester agent
**To**: Marcus (PM)
**Priority**: FYI + 2 low-severity bugs to ticket

## Summary

CIO brought me back this session to validate that the historical sprints actually deliver their stated behaviour (acceptance-level, not code-quality). Scope per CIO: the verifiable parts of the V0.27 chain (V0.27.2-V0.27.5) plus a full test-suite + live-system health pass. Full write-up: `offices/tester/test-reports/2026-05-11-v0.27-chain-validation-status.md`. Drive-11 acceptance checklist (CIO asked for it; B-063 fix is "imminent"): `offices/tester/test-reports/2026-05-11-drive-11-validation-checklist.md`.

**Headline: nothing in the V0.27 chain needs backing out or rework.** Everything verifiable today is green or green-pending-Drive-11. The chain's remaining IRL acceptance is correctly blocked on B-063 → Drive 11, and your `regression_manifest.json` already reflects that (F-005, F-007 = `lastValidated: null`).

Verified live this session:
- Pi (chi-eclipse-01) is UP, running **V0.27.5** (`bb744d1`), `eclipse-obd.service` active. (It was unreachable for ~the first hour — the B-063 brownout/key-off pattern — then CIO brought it back.)
- chi-srv-01 UP, `obd-server.service` active, running the V0.27.5 NAS checkout.
- **US-319** forensic instrumentation is deployed AND emitting in production right now (`FORENSIC sync_push_table_entry` / `…_table_advance` lines in the Pi journal). DriveDetector + drive_summary surfaces will show up on Drive 11.
- **US-315** sync-UPDATE path is wired and working for `battery_health_log`: server row 16 closed via an UPDATE (not just the original INSERT); Pi `sync_log.battery_health_log.last_synced_modified_at` is populated (the dual-cursor). `drive_summary` side awaits Drive 11.
- **US-316** literal AC passes (`calibration.py` runs locally). Its broader intent ("CIO can run a calibration") was still broken — Spool's 2026-05-11 note — and you've already absorbed that into Sprint 32 (US-320 pymysql ✓, US-321 sqlite fallback, etc.). I confirmed the underlying DB state (`baselines=0`, `drive_statistics=0`, server `drive_summary`=3 ghosts, `battery_health_log` 11-15 stranded) matches Spool's audit exactly.
- Drain side has IRL evidence (Drain Tests 14/15/16): Pi `battery_health_log` rows 11-16 all closed with `runtime_seconds`; `startup_log` shows `prior_boot_clean=1` after the graceful poweroffs (US-308).

## Two low-severity bugs to ticket

1. **`chain_validate_aggregate.py` double-counts the active sprint** when `sprint.json`'s `currentVersion` matches an archived sprint's `currentVersion` (the post-deploy / pre-groom window — which is exactly when `/chain-validated` is meant to be run). It reported "Sprints in chain: 5" with V0.27.5 listed twice earlier today. Self-masked once you groomed Sprint 32 in. Fix is a ~3-line dedup-by-sprint-name in `aggregateChain` + one test case. Gap file for Ralph: `offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md`. Worth fixing before the first real `/chain-validated` run.

2. **`pytest tests/` is not green on the Windows dev box** — 2 failures, both in `@slow @integration` simulator tests, neither a feature regression: (a) `test_gracefulShutdown_noErrorsInLogs` — `boot_reason.readCurrentBootId()` logs ERROR on a platform without `/proc/sys/kernel/random/boot_id` (since Sprint 25); (b) `test_noDuplicateTimestampParameterCombinations` — simulator writes second-resolution timestamps so PIDs polled sub-second collide on `(timestamp, parameter_name)` (production uses microsecond precision and is fine). Gap file: `offices/tester/gaps/2026-05-11-windows-simulator-test-failures.md`. Also: `make lint` is RED — 16 auto-fixable ruff errors (debt outside the files Ralph touches each iteration) — a `ruff check … --fix` clears it; maybe slot a one-line hygiene item.

## No action needed from you on

- Spool's 2026-05-11 findings — already in Sprint 32 (US-320…US-324).
- The V0.27 chain merge — correctly waiting on Drive 11; checklist is ready.
- F-013/F-014 — gated on B-066 (B-047 self-update drill), separate exercise.
