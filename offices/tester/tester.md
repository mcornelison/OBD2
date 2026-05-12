

### Finding File Template

```markdown
# Finding: [Brief Title]

**Date**: YYYY-MM-DD
**Severity**: Critical / High / Medium / Low
**Layer/Component**: [What part of system]

## Summary
[One paragraph describing what was found]

## Evidence
[SQL queries, logs, screenshots, error messages]

## Impact
[What does this affect? What doesn't work?]

## Root Cause (if known)
[Why is this happening?]

## Recommended Action
[What should be done to fix this?]
```

### Gap File Template

```markdown
# Gap: [Brief Title]

**Date**: YYYY-MM-DD
**Component**: [What needs fixing]
**For**: Developer

## Issue
[Brief, focused description - one issue only]

## Evidence
[Proof of the issue]

## Expected Behavior
[What should happen]

## Actual Behavior
[What is happening]
```

### Test Report Template

```markdown
# Test Report: [Test Name]

**Date**: YYYY-MM-DD
**Duration**: [X seconds/minutes]
**Result**: PASS / FAIL

## Summary
| Component | Status | Notes |
|-----------|--------|-------|
| [Component 1] | PASS/FAIL | [Brief note] |

## Test Details

### [Test 1 Name]
- **Status**: PASS/FAIL
- **Details**: [What was tested and result]

## Issues Found
[List any issues discovered, with references to finding/gap files]

## Recommendations
[Any follow-up actions needed]
```

## Session Protocol

### Weekly Recurring Checks

Every Monday (or designated day):
- [ ] Verify Documentation Accuracy (specs vs implementation)
- [ ] Check Business Rule Compliance (rules working correctly)
- [ ] Spot-check data quality thresholds
- [ ] Document any violations or drift

### Status Definitions

| Status | Criteria |
|--------|----------|
| **Green** | All tests pass, no issues |
| **Yellow** | Minor issues, non-blocking |
| **Red** | Critical issues, blocking progress |

## Best Practices

1. **Test early, test often** - Don't wait for "complete" features
2. **Document everything** - Future you will thank present you
3. **One issue per gap file** - Keeps it manageable for developers
4. **Include evidence** - Screenshots, logs, query results
5. **Track what you've tested** - Maintain session logs
6. **Verify fixes** - Re-test after developer changes
7. **Communicate promptly** - Report blockers immediately

---

# Knowledge Base

## Stakeholders

| Who | Role |
|-----|------|
| Michael Cornelison (CIO) | Human in the loop; hardware/wiring; runs the car for IRL drives |
| Ralph / Rex / Torque | Developers (autonomous) — `offices/ralph/` |
| Marcus | Project Manager — `offices/pm/` (never edit his files; file notes in `offices/pm/issues|blockers|tech_debt/`) |
| Spool (Tuner SME) | Tuning subject-matter expert — `offices/tuner/`; owns drive/drain analysis; files PM notes |
| OBD2-Server Tester | Companion-service tester (coordinate; the server now runs from the NAS monorepo, not a separate repo) |

## Project State (as of 2026-05-11, Sprint 32 in flight)

- **Workflow rule (Mike 2026-05-08, refined 2026-05-10)**: `main` = "fully functional working system." Feature sprints = `V0.X.0`; subsequent bug-fix sprints iterate the patch (`V0.X.1`, `.2`, …) **on sprint branches**. A whole minor-version *chain* merges to `main` together via `/chain-validated`, only after the chain is IRL-validated. `/sprint-deploy-pm` deploys from the sprint branch (no merge); `/sprint-validated` updates `regression_manifest.json` after a real-hardware drill.
- **Current**: V0.27 chain = Sprints 28/29/30/31 = V0.27.2/.3/.4/.5, all DEPLOYED-AWAITING-IRL-VALIDATION on stacked sprint branches. Sprint 32 (V0.27.6) is groomed and Ralph has shipped US-320; it absorbs Spool's 2026-05-11 audit (pymysql, sqlite fallback, orphan cleanup, stranded-row backfill, drive_statistics writer).
- **The gate for the whole chain**: **B-063** — the Pi is on an undersized stereo-USB-C feed (~2.4-3 A; Pi 5 wants 5 V/5 A); it browns out mid-drive (Drives 9 & 10 both failed). Until Mike swaps to a fuse-box buck converter and gets one clean drive ("Drive 11"), `drive_summary`/`drive_counter`/sync/`drive_state` acceptance can't be IRL-validated. CIO says the fix is "imminent."
- **Drive-11 checklist**: `offices/tester/test-reports/2026-05-11-drive-11-validation-checklist.md` — run it the moment Drive 11 happens.
- **`offices/pm/regression_manifest.json`** — 14 user-facing features (F-001…F-014) with `lastValidated` + `staleThresholdDays`. `offices/pm/scripts/pm_regression_status.py` reports OK/STALE/NEVER. F-005 (drive_summary INSERT on drive_end) and F-007 (sync to chi-srv-01) are correctly `null` pending Drive 11; F-013/F-014 (Pi self-update / auto-rollback) are synthetic-only pending B-066.

## Environment Facts

| Item | Value | Notes |
|------|-------|-------|
| **SSH access** | **WORKS** — `ssh chi-eclipse-01` (Pi, 10.27.27.28) and `ssh chi-srv-01` (10.27.27.10), user `mcornelison`, key `~/.ssh/id_ed25519` | Pi has passwordless sudo; chi-srv-01 needs `sudo -S` (prompts CIO live) — see memory `feedback_chi_srv_01_sudo_dash_S.md` |
| **MariaDB CLI** | local client at `C:\Program Files\MariaDB 12.2\bin` — `mysql -h 10.27.27.10 -u obd2 -p<pw> obd2db` | `<pw>` = the password in `DATABASE_URL` in repo-root `.env` (`mysql+aiomysql://obd2:<pw>@localhost/obd2db`) |
| Pi deploy | `~/Projects/Eclipse-01` on the Pi (a file copy, not a git clone); `eclipse-obd.service` runs `obd2-venv/bin/python src/pi/main.py`; DB at `~/Projects/Eclipse-01/data/obd.db` (SQLite) | `.deploy-version` JSON has version + gitHash; hostname still reports `Chi-Eclips-Tuner` |
| Server deploy | `obd-server.service` on chi-srv-01 runs `obd2-server-venv/bin/uvicorn src.server.main:app` with `WorkingDirectory=/mnt/projects/O/OBD2v2` (= the NAS = this repo). The `~/Projects/OBD2v2` clone on chi-srv-01 is a stale Sprint-7 leftover — ignore it. | EnvironmentFile = `/mnt/projects/O/OBD2v2/.env` |
| This working dir | `Z:\O\OBD2v2` = `\\chi-nas-01\PPS-Projects\O\OBD2v2` = `/mnt/projects/O/OBD2v2` (same files the server runs) | currently on branch `sprint/sprint31-bugfixes-V0.27.5` (Sprint 32 work layered on top) |
| OBDLink LX MAC | `00:04:3E:85:0D:FB` | paired/bonded/trusted since Session 23 |
| MariaDB prod / test DB | `obd2db` / `obd2db_test` | server-side; Pi-side tables differ in some column names (e.g. `battery_health_log` PK is `drain_event_id` on Pi, `id` on server; Pi renamed `start_soc`→`start_vcell_v` per US-289, server kept old names) |
| `drive_statistics` table | server-side only; **0 rows** as of 2026-05-11 — no production writer fires for it (Sprint 32 US-324 builds one) | needed for `calibration` (MIN_REAL_DRIVES=5) |
| Ollama | `llama3.1:8b` @ `http://10.27.27.10:11434` | drive_summary writer was decoupled from the Ollama trigger in US-317 (V0.27.4) |

## Test Suite State

### Cleanup Session 2026-02-05

**Before**: 1171 tests across 27 files (787 were mock theatre)
**After**: 384 tests across 15 files (all test real behavior)

**Deleted (mock-heavy, prove nothing):**

| File | Tests | Mock Refs | Reason |
|------|-------|-----------|--------|
| test_orchestrator.py | 291 | 403 | Pure mock theatre, tested getters/log messages |
| test_status_display.py | 67 | 54 | Mocked pygame |
| test_ups_monitor.py | 58 | 43 | Mocked I2C |
| test_telemetry_logger.py | 57 | 19 | Mocked system calls |
| test_gpio_button.py | 56 | 68 | Mocked gpiozero |
| test_shutdown_handler.py | 45 | 19 | Mocked subprocess |
| test_main.py | 44 | 19 | Mocked entire workflow |
| test_obd_connection.py | 41 | 5 | Mocked python-obd |
| test_test_utils.py | 40 | 4 | Test utility meta-tests |
| test_google_drive_uploader.py | 37 | 59 | Mocked rclone |
| test_i2c_client.py | 37 | 31 | Mocked SMBus |
| test_hardware_manager.py | 28 | 100 | All hardware mocked |
| test_remote_ollama.py | 24 | 29 | Mocked urllib |

**Kept (test real behavior):**

| File | Tests | What It Validates |
|------|-------|-------------------|
| test_config_validator.py | 54 | Real config validation logic |
| test_database.py | 50 | Real SQLite operations |
| test_obd_config_loader.py | 38 | Real OBD config parsing |
| test_error_handler.py | 29 | Real error classification & retry |
| test_secrets_loader.py | 28 | Real env var resolution |
| test_orchestrator_integration.py | 27 | Real orchestrator with temp SQLite |
| test_logging_config.py | 47 | Real PII masking & log filtering |
| test_backup_manager.py | 39 | Real file I/O operations |
| test_platform_utils.py | 18 | Platform detection |
| test_verify_database.py | 14 | Real DB schema verification |
| test_sqlite_connection.py | ~40 | Real SQLite connectivity |

## Component Health (as of 2026-05-11)

| Component | Status | Last Checked | Notes |
|-----------|--------|--------------|-------|
| Test suite (`pytest tests/`, Windows) | Yellow | 2026-05-11 | ~4147 pass, 2 fail (both `@slow @integration` simulator tests — boot_id ERROR on Windows; dupe-timestamp in simulator output). Not feature regressions. `make lint` RED (16 auto-fixable ruff errors). |
| Pi deploy lifecycle (`eclipse-obd.service`) | Green | 2026-05-11 | Pi UP, running V0.27.5 (`bb744d1`); reconnect heartbeat alive; FORENSIC instrumentation emitting; OBD connect fails as expected with engine off |
| Server deploy lifecycle (`obd-server.service`) | Green | 2026-05-11 | chi-srv-01 UP, running V0.27.5 NAS checkout; MariaDB reachable |
| Sync Pi→server (US-194/US-315) | Green (battery_health_log path) / Pending (drive_summary path) | 2026-05-11 | dual-cursor wired; `battery_health_log` row 16 closed via UPDATE on server; drive_summary side awaits Drive 11 |
| `drive_summary` writer (F-005, B-059/US-310) | RED — fix deployed, not yet IRL-validated | 2026-05-11 | Pi has drive_summary for drives 2-5 only; 6-10 missing; 12-field metadata never populated. US-310 fix is deployed but no real drive has exercised it. Drive 11 is the test. |
| `drive_counter` server advance (US-314/US-315) | Pending Drive 11 | 2026-05-11 | server `last_drive_id=3` (stale), Pi=10 |
| `drive_statistics` writer | RED — no production writer exists | 2026-05-11 | 0 rows server-side; Sprint 32 US-324 builds the writer |
| Drain ladder / `startup_log` (F-008/F-011/F-012, US-308) | Green | 2026-05-11 | Drain Tests 14/15/16 closed cleanly Pi-side; `startup_log` `prior_boot_clean=1` after graceful poweroffs |
| `/chain-validated` slash command (US-318) | Green w/ note | 2026-05-11 | command + helper scripts present; 10/10 tests; aggregate double-counts the active sprint in the post-deploy window (gap filed) |
| DriveDetector / engine telemetry capture (F-002/F-003/F-004/F-006/F-009) | Last IRL-validated 2026-05-08 (Drives 6+7) | — | engine-on; awaiting Drive 11 for re-confirmation under the new power feed |
| Pi self-update + auto-rollback (F-013/F-014) | Synthetic-only | — | gated on B-066 (B-047 self-update IRL drill) |
| Calibration CLI / `baselines` | RED — multiple downstream gates | 2026-05-11 | `baselines=0`; needs US-320 (pymysql, done) + drive_statistics writer + ≥5 real drives |

## Issue Tracker

| ID | Issue | Severity | Status | File Reference |
|----|-------|----------|--------|----------------|
| TI-002 | `chain_validate_aggregate.py` double-counts the active sprint when `sprint.json` `currentVersion` matches an archived sprint's | Low | OPEN — gap filed for Ralph | `gaps/2026-05-11-chain-validate-aggregate-double-count.md` |
| TI-003 | `pytest tests/` 2 failures on Windows (`test_gracefulShutdown_noErrorsInLogs` boot_id ERROR; `test_noDuplicateTimestampParameterCombinations` simulator dupe timestamps) | Med | OPEN — gap filed for Ralph | `gaps/2026-05-11-windows-simulator-test-failures.md` |
| TI-004 | `make lint` RED — 16 auto-fixable ruff errors (debt outside Ralph's per-iteration touch set) | Low | OPEN — noted to PM | `pm/issues/2026-05-11-from-tester-v0.27-chain-validation-status.md` |
| TI-001 | test_utils.py TestDataManager `__init__` PytestCollectionWarning | Low | likely stale (file may no longer exist) | tests/test_utils.py |

## Session Log

### 2026-05-11 — Re-engaged by CIO: V0.27 chain validation pass

- CIO brought the Tester role back online. New rule since last session: `main` = "fully functional working system"; minor-version chains merge to main together via `/chain-validated` only after IRL validation. CIO clarified "validate" = acceptance-level ("did the user story deliver its promised behaviour"), not code quality.
- Got SSH access to Pi (`chi-eclipse-01`) and chi-srv-01; got local MariaDB client (`C:\Program Files\MariaDB 12.2\bin`) for `obd2db`. Updated Environment Facts.
- Full `pytest tests/` run: ~4147 pass, 2 fail (both `@slow @integration` simulator tests; not regressions). `make lint` RED (16 auto-fixable ruff errors).
- Validated the verifiable parts of the V0.27 chain (per CIO scope):
  - **US-318** (`/chain-validated`): PASS w/ note — command + 2 helper scripts present, 10/10 tests; aggregate double-counts the active sprint in the post-deploy window → gap filed.
  - **US-319** (Drive-11 forensic instrumentation): PASS (Pi-side) — `FORENSIC sync_push_table_entry`/`_table_advance` lines emitting in the live Pi journal; DriveDetector + drive_summary surfaces await Drive 11.
  - **US-315** (sync UPDATE propagation): PASS for `battery_health_log` (server row 16 closed via UPDATE; Pi `sync_log.last_synced_modified_at` populated); `drive_summary` side awaits Drive 11.
  - **US-316** (calibration.py local): literal AC PASS; intent (CIO can run calibration) still gated downstream — already in Sprint 32 (US-320 done).
  - **US-317** (drive_summary decoupled from Ollama): code deployed; can't IRL-validate without Drive 11.
- Live DB snapshot corroborates Spool's 2026-05-11 audit exactly (server: `baselines=0`, `drive_statistics=0`, `drive_summary`=3 ghost rows, `battery_health_log` 11-15 stranded; Pi: 61,293 NULL-`drive_id` orphans, `drive_summary` drives 2-5 only with NULL metadata, `drive_counter`=10).
- Pi was unreachable for ~the first hour (the B-063 brownout/key-off pattern), then CIO brought it up — running V0.27.5 correctly.
- Deliverables: `test-reports/2026-05-11-v0.27-chain-validation-status.md` (main report), `test-reports/2026-05-11-drive-11-validation-checklist.md` (CIO-requested; run it the moment Drive 11 happens), `gaps/2026-05-11-chain-validate-aggregate-double-count.md`, `gaps/2026-05-11-windows-simulator-test-failures.md`, `pm/issues/2026-05-11-from-tester-v0.27-chain-validation-status.md`.
- **Headline**: nothing in the V0.27 chain needs backing out or rework; everything verifiable today is green or green-pending-Drive-11; the chain's remaining IRL acceptance is correctly blocked on B-063 → Drive 11.
- Then re-walked the full 14-feature regression manifest (`test-reports/2026-05-11-regression-manifest-rewalk.md`; PM note `pm/issues/2026-05-11-from-tester-regression-manifest-rewalk.md`). Findings: manifest broadly accurate; **F-005 stays REGRESSED** (Pi drive_summary drives 2-5 only, fix deployed-not-exercised); **F-008/F-011/F-012 under-rated** — fresher real evidence (Drain Test 16, 2026-05-10) than recorded (Drain 8, 2026-05-08); recommended bumps + F-007 wording refresh (mechanism works — Pi pushed a connection_log delta to the server live + battery_health_log row 16 UPDATE-synced — but the post-V0.27.4 drive round-trip is still outstanding, partly blocked by F-005). F-013/F-014 stay synthetic-only (B-066). Also confirmed B-063 still active (power_log flicker ~70/day 2026-05-10, ~23 already 2026-05-11).
- Packaged it all into a single grooming brief: `test-reports/2026-05-11-state-of-system-for-sprint-32-grooming.md`; sent the pointer to the PM inbox in A2AL/0.4.0 format (`pm/inbox/2026-05-11-from-tester-state-of-system-grooming-brief.md`). Recommendations: Sprint 32 scope is good as-is; pencil in V0.27.7 as contingency for (a) F-005 if Drive 11 fails it, (b) chain_validate double-count, (c) test/lint hygiene; queue B-066 near B-063. Note: a2al skill ships only SKILL.md locally (no `library/*.yaml`); wrote from the documented patterns + standard PM jargon.
- **Next session**: when CIO reports B-063 done + Drive 11 captured → run the Drive-11 checklist; report pass/fail per `bigDefinitionOfDone` clause to the PM.

### 2026-02-05 - Initial Session (Onboarding + Test Cleanup)

- Read all tester workspace files
- Explored full project (specs, PM, PRDs, src, tests)
- Audited all 27 test files, classified each as KEEP/CUT
- Deleted 12 mock-heavy test files (787 tests)
- Verified remaining 384 tests all pass (81.49s)
- Created this knowledge base
- Created evidence-based test strategy (`test-reports/2026-02-05-test-strategy.md`)
- Added Mock Theatre anti-pattern to `specs/anti-patterns.md`
- Collected environment facts from Michael:
  - Real config: `src/obd_config.json` (test against it)
  - Real DB: `data/obd.db`
  - Pi SSH: Michael setting up access
  - OBD2-Server coordination: TBD
- Merged AGENT.md into this file (single source of truth)
- Next: Wait for dev to mark stories complete, then validate
