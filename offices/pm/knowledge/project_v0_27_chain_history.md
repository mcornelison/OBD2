---
name: project-v0-27-chain-history
description: Per-sprint detail for V0.27 chain Sprints 27-35 (Sprint 36 ongoing in [[project-v027-chain-status]]). All stories shipped, all deployed; per Mike chain-end-merge rule none merged to main until whole chain IRL-validated.
metadata:
  type: project
---

# V0.27 chain detailed history (Sprints 27-35)

Current sprint (36) lives in [[project-v027-chain-status]]. This file is the closed-sprint detail.

## Sprint 27 — V0.27.0 + V0.27.1 hotfix (validated + on main 2026-05-09)

Spool's two engine-on critical-path P0 bugs + bench harness regression gate.

- **US-301** (M, P0) obd-reconnect-heartbeat — 10s INFO heartbeat + boot canary + loud-bail logging (V0.24.1 anti-pattern lesson applied)
- **US-302** (M, P0) data-logger-restart-on-connection-restored — idempotent dataLogger.start + new `data_logger_last_row_seconds_ago` health field
- **US-303** (S, P0) engine-on bench harness — adapter-late-arrives e2e flow; regression gate Spool had been asking for since Sprint 25

**V0.27.1 hotfix** (Mike, post-Sprint-27-deploy 2026-05-08): cross-thread connect lock + heartbeat in-flight probe + `HEARTBEAT_ATTEMPT_TIMEOUT_SEC` 5s → 30s for K-line cold protocol detection. Mike Q1-Q5 confirmed Path A (narrowed validatesFeatures to 9; F-005 + F-007 marked REGRESSED in manifest pending V0.27.2). **V0.27.1 stable on main** (commit `156a58e` 2026-05-09 04:20:35Z).

## Sprint 28 — V0.27.2 (deployed 2026-05-10; commit `f9be758`)

PRD COMPLETE 5/5 actionable + 1 wontfix. validatesFeatures = [F-005].

- **US-304** drive_summary regression
- **US-306** statistics drive_id NULL
- **US-307** drain_event forensic instrumentation
- **US-308** startup_log graceful detection
- **US-309** battery_health SocPct seam

US-305 wontfix per BL-011 Option A. Three blockers caught + resolved mid-sprint:
BL-011 (US-305 sync_history premise wrong), BL-012 (US-307 close already wired), BL-013 (US-309 scope-blast).

Three V0.27.3+ follow-ups filed: B-060 (UpsMonitor SOC% wire-through Step 2), B-061 (drop legacy columns Step 3), B-062 (drain_event close targeted fix post-Drain-11; later bumped P3→P2 per Spool 2026-05-10).

## Sprint 29 — V0.27.3 (deployed 2026-05-10)

PRD COMPLETE 4/4 stories `passes:true`. validatesFeatures = [F-005, F-007].

- **US-310** drive_summary 12-field writer (5 files)
- **US-311** DriveDetector warm-restart fix (5 files; I-019)
- **US-312** calibration.py types.py shadow + missing baselines migration (14 files; rename + importers + v0008 migration + tests; sprint_lint warned size M vs cap-5)
- **US-314** drive_counter sync gap (7 files; B-064 area)

## Sprint 30 — V0.27.4 (deployed 2026-05-10)

PRD COMPLETE 3/3 stories `passes:true`. validatesFeatures = [F-007].

- **US-315** sync UPDATE propagation for delta-tables (B-065; 6 files)
- **US-316** calibration.py local-invocation PYTHONPATH bootstrap (I-020; 2 files)
- **US-317** drive_summary writer decouple from Ollama trigger (I-021; 3 files)

## Sprint 31 — V0.27.5 (deployed 2026-05-11)

PRD COMPLETE 2/2 stories `passes:true`. validatesFeatures = [].

- **US-318** `/chain-validated` slash command (B-067; 9 files)
- **US-319** Drive 11+ end-to-end forensic instrumentation (B-071; 5 files)

## Sprint 32 — V0.27.6 (deployed 2026-05-11)

PRD COMPLETE. Tester re-engaged this session.

- **US-320** pymysql to requirements-server.txt (I-022)
- **US-321** remove phantom sqlite fallback in report.py (I-023)
- **US-322** Pi realtime_data orphan cleanup (B-072)
- **US-323** server battery_health_log backfill rows 11-15 (B-073)
- **US-324** drive_statistics writer (I-024)
- **US-325** BT reconnect exponential backoff when OBDLink absent + Pi rebuild durability (I-025)

## Sprint 33 — V0.27.7 (deployed 2026-05-12; gitHash 911d6b2)

4 actionable stories all passes:true. Drive 11 (2026-05-12 first clean car-coupled post-B-063) captured cleanly Pi-side (10,839 realtime_data rows / ~470 rows/min) but exposed the server-side analytics tier broken at every layer; V0.27.7 fixes it.

- **US-326** drive_summary server-side analytics writer (I-026 — root cause: `_ensureDriveSummary` looked up by the never-populated `drive_id` mirror instead of `source_id` → IntegrityError → `_writeDriveAnalytics` transaction rolled back silently → analytics fields + drive_statistics never committed; fix heals `drive_id` on UPDATE)
- **US-327** US-323 backfill wired into deploy-server.sh idempotently (I-027 — script existed but nothing auto-ran it; new Step 4.6 + `--count-stranded` pre-check)
- **US-328** drive_statistics Pi-side table migration, Option C hybrid per BL-015 (I-028 — thin `CREATE TABLE IF NOT EXISTS` only; no Pi-side writer; server-side Approach 1 path now produces rows post-US-326; full Approach 2 = B-075 for V0.28+)
- **US-330** startup_log prior_boot_clean regression, race-guard fix (I-030 — `journalctl --list-boots` timing out under boot-time SD-card I/O contention from V0.27.6 US-322's orphan-cleanup.timer → `_readBootList` retries 3×; unit-ordering alternative = TD-051)

**US-329** (drive_counter server-side stale) DEFERRED to V0.28 server-schema-normalization epic B-076 per BL-016 — CIO directive is "drop the table"; zero server-side consumers. Blockers resolved mid-sprint: BL-015 (US-328 architecture → Option C), BL-016 (US-329 → defer/Option B). Open residual: I-031 (Step 4.6 backfill fails from Windows + from chi-srv-01 — fixed by US-331 in V0.27.8).

## Sprint 34 — V0.27.8 (deployed 2026-05-13; commit `c7bdd20`)

5/5 actionable stories all passes:true; US-332 REMOVED per BL-017 as Option A defer to V0.28.

- **US-331** I-031 deploy-context fix for the US-327 backfill — MSYS_NO_PATHCONV guard + localhost detection in loadServerCreds. **FALSE-PASSED** synthetic tests (Python-level only); V0.27.8 deploy reproduced identical mangle error from V0.27.7. Filed I-032.
- **US-333** B-079 sync_history started_at/completed_at both UTC
- **US-334** TD-051 orphan-cleanup.service IOSchedulingClass=idle + After=eclipse-obd.service (durable complement to US-330's race-guard)
- **US-335** Spool Story E Pi-side drain_event_id 1+9 backfill from power_log stage_trigger rows
- **US-336** Spool Story F 199-orphan leak — 4h-cutoff second-pass sweep in cleanup_orphan_realtime_data.py

US-332 (`pi_state.no_new_drives`) DEFERRED to V0.28 per BL-017 — that flag is US-225/TD-034 drain-WARNING drive-id-mint gate, NOT a sync-state flag; corrected V0.28+ framing in B-078.

## Sprint 35 — V0.27.9 (deployed 2026-05-13; commit `588e0e0`)

1/1 actionable story `passes:true`. Redoes US-331's false-passed fix.

- **US-337** Fix US-331's MSYS path-mangle guard — adds effective `makeMsysSafePath()` in scanPiRows + a real-subprocess regression test (not just Python mocks). Empirical RED-proof real: with fix bypassed, regression reproduces byte-identical mangle error; with fix restored, all 28 tests pass.

**🎯 US-337 IRL gate GREEN on first try.** Post-V0.27.9 `deploy-server.sh` from Windows Git-Bash: `Step 4.6 ... No stranded battery_health_log rows; backfill no-op (idempotent)`. `--count-stranded` ran cleanly through MSYS (no mangle); returned 0 (rows 11-15 already populated via CIO manual SQL earlier same session); no-op as designed. **I-031 + I-032 both closed.**

## PM tooling shipped during the chain

- `offices/pm/regression_manifest.json` — 14 user-facing features tracked with `lastValidated` dates
- `offices/pm/scripts/pm_regression_status.py` — STALE/NEVER query
- sprint.json `validation` block — bigDefinitionOfDone + validationMethod + validatesFeatures (FK to manifest); required Sprint 28+ per `sprint_lint.lintSprintValidation`
- `/sprint-deploy-pm` slash command — deploys from sprint branch, no merge
- `/sprint-validated` slash command — marks sprint validated + bumps manifest
- `/chain-validated` slash command (US-318 V0.27.5) — final merge for whole chain
- Extracted Python helpers per Mike 2026-05-08 reusable-utilities directive: `bump_passed_statuses.py` + `archive_sprint_artifacts.py` + `verify_release_version.py` + `repair_ralph_agents.py`

## Cross-references

- [[project-v027-chain-status]] — current Sprint 36 status
- [[project-workflow-chain-end-merge]] — ritual reference
- [[project-v0-24-to-v0-26-history]] — prior epoch
- [[feedback-pm-validate-cli-in-cio-shell]] — I-032 lesson
- [[feedback-tester-validate-deploy-fixes-irl-not-just-code]] — I-032 lesson
