

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

## Project State (as of 2026-05-12, end of session — Sprint 34 / V0.27.8 in flight)

- **Workflow rule (Mike 2026-05-08, refined 2026-05-10)**: `main` = "fully functional working system." Feature sprints = `V0.X.0`; subsequent bug-fix sprints iterate the patch (`V0.X.1`, `.2`, …) **on sprint branches**. A whole minor-version *chain* merges to `main` together via `/chain-validated`, only after the chain is IRL-validated. `/sprint-deploy-pm` deploys from the sprint branch (no merge); `/sprint-validated` updates `regression_manifest.json` after a real-hardware drill.
- **Current**: V0.27 chain = Sprints 28-33 = V0.27.2 … V0.27.7, all DEPLOYED on stacked sprint branches, NOT yet merged to main. Sprint 34 / V0.27.8 (`sprint/sprint34-bugfixes-V0.27.8`) is groomed/in-flight — 6 stories US-331-336, all Drive-12-independent (deploy-fix + sync data-hygiene). **B-063 is DONE** (fuse-box buck converter; power steady on Drive 11). **Drive 11 happened (2026-05-12)** — Pi edge tier green; server analytics tier was broken at every layer; V0.27.7 (Sprint 33) shipped the fixes (US-326/327/328/330 passed/done; US-329 deferred to V0.28 per BL-016). **The chain-merge gate is now Drive 12** — validates US-326/328/330 IRL.
- **Drive-12 re-validation checklist**: `offices/tester/test-reports/2026-05-11-drive-11-validation-checklist.md` — PART 1 = Drive-11 results; **PART 2 = the Drive-12 checklist to run when it happens**; PART 3 = root-cause appendix for US-326's pre-flight.
- **`offices/pm/regression_manifest.json`** — 14 user-facing features (F-001…F-014) with `lastValidated` + `staleThresholdDays`. `offices/pm/scripts/pm_regression_status.py` reports OK/STALE/NEVER. As of this session: F-002/F-003/F-004/F-006/F-009 re-confirmed by Drive 11; F-005 still REGRESSED (fix shipped V0.27.7, awaiting Drive 12); F-007 PARTIAL (transport works, drive_summary round-trip blocked behind F-005); F-008/F-011/F-012 recommended bump → 2026-05-10/Drain Test 16 (PM note filed); F-013/F-014 synthetic-only pending B-066.

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

## Component Health (as of 2026-05-13, V0.27.8 deploy-validation pass — chi-srv-01 + Pi both on `c7bdd20`; Sprint 35 / V0.27.9 already groomed mid-session to redo US-331 per I-032)

| Component | Status | Last Checked | Notes |
|-----------|--------|--------------|-------|
| Test suite (`pytest tests/`, Windows) | Yellow | 2026-05-11 | ~4147 pass, 2 fail (both `@slow @integration` simulator tests — boot_id ERROR on Windows; dupe-timestamp in simulator output). Not feature regressions. `make lint` RED (16 auto-fixable ruff errors) — TI-004, not yet fixed as of V0.27.8 grooming. |
| Pi deploy lifecycle (`eclipse-obd.service`) | Green | 2026-05-13 | Pi UP on V0.27.8 / `c7bdd20` (released 15:10:19 UTC; uptime ~24min at validation time). Reconnect heartbeat alive; FORENSIC instrumentation emitting. |
| Server deploy lifecycle (`obd-server.service`) | Green | 2026-05-13 | chi-srv-01 UP on V0.27.8 / `c7bdd20` (released 15:11:14 UTC). MariaDB reachable. |
| Sync Pi→server transport (US-194/US-315) | Green (raw data + battery_health_log UPDATE path) | 2026-05-12 | Drive 11's 10,839 realtime_data rows fully synced; `battery_health_log` rows 16+18 closed on server via UPDATE-sync (dual-cursor works). Chatty at idle (sync_history ~20k rows, sweeps every ~5-26s) — V0.27.8 US-332/333 address. |
| `drive_summary` server-side analytics (F-005, I-026) | RED → **fix shipped in V0.27.7 (US-326 passed), awaiting Drive-12 validation** | 2026-05-12 | Drive 11 server row id=15/source_id=11 had `start_time`/`end_time`/`duration_seconds`/`row_count`/`is_real`/`profile_id`/`drive_id`/`device_id` ALL NULL (Pi-synced fields DID arrive). Root cause: server analytics writer never computed them. US-326 (Sprint 33) shipped a fix; Drive 12 is the test. |
| `drive_statistics` writer (I-028) | RED → **fix shipped in V0.27.7 (US-328 passed, Option C hybrid), awaiting Drive-12** | 2026-05-12 | Was 0 rows + no Pi table. US-328 added a Pi-side table + writer. Drive 12 should produce per-PID rows. (Note: `statistics` per-PID-per-profile aggregation already worked — got 21 rows tagged drive_id=11.) |
| `drive_counter` server advance (I-029) | RED → **deferred to V0.28 (US-329, per BL-016)** | 2026-05-12 | server `last_drive_id=3`, Pi=11. Drive-11 finding: `FORENSIC sync_push_drive_counter` count = 0 — the Pi never even POSTs it. Per CIO, the table gets dropped server-side in the V0.28 schema epic; consumers compute `MAX(drive_id) FROM drives`. |
| US-323 backfill (stranded `battery_health_log` rows) (I-027 → I-031 → I-032) | RED — **V0.27.8 US-331 FALSE-PASSED**; redo groomed as **US-337 in V0.27.9 / Sprint 35** (`b9b20be`) | 2026-05-13 | Server rows 11-15 still NULL. `--count-stranded` on chi-srv-01 still throws self-loop ssh `Host key verification failed`. US-331 fix code IS deployed but doesn't catch this in practice — synthetic unit test didn't cover the real Git-Bash subprocess argv translation. PM owns: `pm/issues/I-032-us331-fix-does-not-actually-work.md` + V0.27.9 US-337 redo. |
| `startup_log.prior_boot_clean` (US-308 → I-030) | RED → **fix shipped in V0.27.7 (US-330 done), awaiting next graceful-shutdown boot** | 2026-05-12 | Regressed to empty at V0.27.6 (post-Drain-17 boot). US-330 fixes the writer; next drain → reboot validates. |
| sync_history TZ both UTC (US-333 / B-079) | Green | 2026-05-13 | V0.27.8 US-333 validated IRL: last 25 rows show `started_at` + `completed_at` both in UTC tier (15:xx, matches `UTC_TIMESTAMP()`); deltas 0-1s; 18000s offset gone. |
| orphan-cleanup IO throttle + ordering (US-334 / TD-051) | Green w/ watch | 2026-05-13 | V0.27.8 US-334 validated: `IOSchedulingClass=3` (idle), `Nice=10`, `After=…eclipse-obd.service…`; 3 recent runs ≤2s. **Watch**: true IO-class stress proof pending next overnight-Pi-off → boot-with-cleanup-work. |
| Pi `battery_health_log` historical backfill (US-335 / Spool E) | Yellow (cond. pass) | 2026-05-13 | Script (`scripts/backfill_pi_battery_health_log_historical_drains.py`) delivered + correct + idempotent + refuses to fabricate. **Drains 1+9 stay NULL** — no `power_log stage_trigger` rows in their windows (Spool's premise didn't hold; both drains pre-date Sprint 22's structured power_log). Bonus warning flagged drain 18 also NULL. Nit: needs `PYTHONPATH=.` to run (US-316 class). |
| Pi orphan 4h second-pass sweep (US-336 / Spool F) | Green | 2026-05-13 | V0.27.8 US-336 validated: `DEFAULT_RECENT_ORPHAN_AGE_HOURS=4.0` + journal shows the sweep firing on every run; Pi NULL-drive_id orphans = **0** (was 199). Forward-looking efficacy proof awaits a future leak event. |
| Drain ladder (F-008/F-011/F-012) | Green | 2026-05-12 | Drains 17+18 since Drive 11; Drain 17 closed cleanly Pi+server (runtime 666s). Ladder + close-event continue to work. (Drain 18's close was unclear — one hypothesis is the Pi clock jump B-080.) |
| `/chain-validated` slash command (US-318) | Green w/ note | 2026-05-11 | command + helper scripts present; 10/10 tests; aggregate double-counts the active sprint in the post-deploy window (TI-002 gap filed) — must fix before the first real chain merge. |
| DriveDetector / engine telemetry capture (F-002/F-003/F-004/F-006/F-009) | Green — re-confirmed by Drive 11 (2026-05-12) | 2026-05-12 | 10,839 realtime rows, ~676/PID balanced, state machine ×3 clean monotonic, no warm-restart double-drive (but Drive 11 was cold-start — I-019/US-311 warm-restart path still untested; needs a warm-restart Drive 12+). |
| Pi self-update + auto-rollback (F-013/F-014) | Synthetic-only | — | gated on B-066 (B-047 self-update IRL drill). |
| Calibration CLI / `baselines` | RED — multiple downstream gates | 2026-05-12 | `baselines=0`. Needs US-320 (pymysql, done) + US-328's drive_statistics writer producing rows + ≥5 real drives (Drive 11 = real-drive #1). |
| Pi clock / timestamps (B-080) | Yellow | 2026-05-12 | Post-reboot `power_log` timestamps jump ~23h forward (showed 2026-05-13 when wall time was 2026-05-12) until NTP catches up. Recurred at the Drain-18 boot. RTC drift or timesyncd misconfig. P3, V0.28+ candidate; corrupts timestamps until NTP syncs. |

## Issue Tracker

| ID | Issue | Severity | Status | File Reference |
|----|-------|----------|--------|----------------|
| TI-002 | `chain_validate_aggregate.py` double-counts the active sprint when `sprint.json` `currentVersion` matches an archived sprint's | Low | OPEN — gap filed for Ralph; must fix before first real `/chain-validated` | `gaps/2026-05-11-chain-validate-aggregate-double-count.md` |
| TI-003 | `pytest tests/` 2 failures on Windows (`test_gracefulShutdown_noErrorsInLogs` boot_id ERROR; `test_noDuplicateTimestampParameterCombinations` simulator dupe timestamps) | Med | OPEN — gap filed for Ralph | `gaps/2026-05-11-windows-simulator-test-failures.md` |
| TI-004 | `make lint` RED — 16 auto-fixable ruff errors | Low | OPEN — noted to PM; still RED as of V0.27.8 grooming | `pm/issues/2026-05-11-from-tester-v0.27-chain-validation-status.md` |
| TI-005 | obd2db data-profile: 8 new bugs + 8 design smells (sync_history 42% failed rows; `connection_log.mac_address='profile:daily'` ×19; Pi has no `schema_migrations`; Pi zombie `battery_log`; server `battery_health_log` start_soc/end_soc hold VCELL not SOC%; `statistics` 63/84 NULL drive_id; etc.) | Mixed (1 Med, rest Low) | OPEN — findings filed; mostly V0.28 epic; N-5 (`pi_state.no_new_drives` hook) → picked up as Sprint-34 US-332 | `findings/2026-05-12-obd2db-data-profile-additional-findings.md` |
| TI-001 | test_utils.py TestDataManager `__init__` PytestCollectionWarning | Low | likely stale (file may no longer exist) | tests/test_utils.py |

### Tracked-by-PM items the Tester surfaced (now owned in sprints/backlog)
- **I-026 / US-326** (drive_summary server analytics NULL) — fix SHIPPED V0.27.7; awaiting Drive-12 validation.
- **I-027 / US-327 → I-031 / US-331** (US-323 backfill) — US-327 shipped V0.27.7; I-031 found it breaks in one deploy run-context → US-331 (V0.27.8).
- **I-028 / US-328** (drive_statistics writer, Option C hybrid) — SHIPPED V0.27.7; awaiting Drive-12.
- **I-029 / US-329** (drive_counter) — DEFERRED to V0.28 per BL-016 (table gets dropped server-side; Pi never POSTed it anyway).
- **I-030 / US-330** (startup_log prior_boot_clean regression) — fix SHIPPED V0.27.7; awaiting next graceful-shutdown boot.
- **B-NEW-2 / US-332** (sync-skip-when-no-new-data via `pi_state.no_new_drives`) — Tester's story proposal, picked up into V0.27.8.
- **B-NEW-3 / US-333** (sync_history started_at/completed_at both in UTC) — Tester finding, picked up into V0.27.8.
- **B-NEW-1 / US-334** (orphan-cleanup.service I/O throttle + ordering, TD-051) — related to Tester's reconnect-loop/orphan findings; V0.27.8.
- **B-080** (Pi clock jumps ~23h post-reboot — RTC drift / timesyncd) — Tester corroborated; PM filed; P3, V0.28+.
- The V0.28 server-schema-normalization epic (renames, `source_id`→`vehicle_id`, drop `source_device`, drop drive_counter both sides, FK normalization, devices+IP/OS cols, `(drive_id, vehicle_id)` composite uniqueness, + the 16 data-profile items) — CIO directive; auto-memory `project_v028_server_schema_epic.md` will surface it at V0.28.0 grooming.

## Session Log

### 2026-05-13 — V0.27.8 deploy validation (3 PASS / 1 COND-PASS / 1 FAIL)

- CIO re-engaged via `/init-tester`; sent the 2026-05-12 Ralph promise-tag fast-suite-blemish note to PM in plain markdown (`pm/inbox/2026-05-13-from-tester-promise-tag-contract-fast-suite-blemish.md`). Then CIO: "use A2AL for agent-to-agent going forward, no retro conversion."
- CIO directed: validate V0.27.8 against the existing handoff #2 checklist + the late-added US-335/336.
- Verified both tiers on V0.27.8 / `c7bdd20` (Pi released 15:10:19 UTC, server 15:11:14 UTC; deploy-server.sh re-run from Windows Git-Bash confirmed by CIO).
- **Per-story results:**
  - **US-331 FAIL** — independent confirmation of PM's I-032 finding. Same MSYS path-mangle survives V0.27.8; server `battery_health_log` rows 11-15 stay NULL. `python3 scripts/backfill_server_battery_health_log_stranded.py --count-stranded` on chi-srv-01 still throws "Host key verification failed" on mcornelison@10.27.27.10 — the exact Context 2 self-loop ssh failure. Fix code IS present in the deployed script (the 4 new helpers all there), it just doesn't catch this case in practice. PM already filed I-032 (`bb20aab`) + groomed V0.27.9 US-337 redo (`b9b20be`). Lesson recorded in I-032: synthetic unit test must cover the shell→subprocess argv path translation, not just in-Python command-string construction.
  - **US-333 PASS** — last 25 `sync_history` rows: `started_at` + `completed_at` both in UTC tier (15:xx matches `UTC_TIMESTAMP()`, NOT the SYSTEM=CDT 10:xx that `NOW()` returns); deltas 0-1s; 18000s offset gone.
  - **US-334 PASS** — `IOSchedulingClass=3` (idle), `Nice=10`, `After=…eclipse-obd.service…`; 3 recent service activations clean ≤2s; no journalctl-times-out symptoms. Real-world IO-class stress proof still pending (current runs are eligible=0 — no contention).
  - **US-335 COND-PASS** — script delivered + correct + idempotent + refuses to fabricate. Dry-run for drains 1+9: `no power_log stage_trigger row` in either drain's open-window — Spool's Story E premise didn't hold (both drains pre-date Sprint 22's structured `power_log` writer). `doNotTouch` fired correctly. Bonus: script's pre-flight flagged `drain_event_id=18 has NULL end_timestamp outside the configured set` — possibly the B-080 clock-jump's downstream symptom. Nit: needs `PYTHONPATH=.` from project root (same class as US-316).
  - **US-336 PASS** — `DEFAULT_RECENT_ORPHAN_AGE_HOURS=4.0` in code; journal confirms `[EXECUTE] sweep recent-orphan cutoff=… ageHours=4.0` firing on every run; Pi NULL-drive_id orphans = **0** (was 199). Attribution caveat: the 199→0 transition was mostly the 24h-default pass on 2026-05-12 22:12 (deleted 136 in one shot); the 4h sweep is now the forward-looking guard.
- Deliverables: `test-reports/2026-05-13-v0.27.8-deploy-validation.md` (full report); `pm/inbox/2026-05-13-from-tester-v0.27.8-deploy-validation.md` (A2AL pointer to PM). No new gaps filed (US-331 fail already owned by PM).
- **Open items I flagged (non-blocking, optional Spool/PM dispositions):**
  - US-335 drains 1+9 — accept NULL forever / find alt timing source (Pi journal logs from May 4 + May 9) / hand-close with placeholder + data_source tag.
  - US-335 PYTHONPATH bootstrap — add to V0.28 paper-trail or leave as manual-only.
  - US-334 IO-class real stress proof — watch item for next overnight-Pi-off → boot-with-cleanup scenario.
  - sync_history idle chatter (~5-40s cadence) — B-078 / removed US-332 territory; V0.28+ epic.
- **V0.27 chain-merge gate unchanged**: Drive 12 (V0.27.7 stories US-326/328/330) + V0.27.9 US-337 (US-331 redo). TI-002 chain_validate_aggregate.py double-count still must land before the first real `/chain-validated`.

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
- **2026-05-11 (later, same session)**: CIO reports **B-063 DONE** (fuse-box buck converter installed) — but Drive 11 not yet done. Pi telemetry post-fix looks healthy: `power_log` power-source transitions dropped from ~70/day (2026-05-10, brownout era) to ~1-2/hr brief blips (UPS micro-cutover, not sustained brownout). No engine data since Drive 10 (`realtime_data` MAX still 2026-05-10T01:14:30Z) — confirms no Drive 11 yet. OBD adapter connect path still functional (last `connect_success` 2026-05-10 19:46). Nothing to validate until Drive 11 produces data.
- **2026-05-12**: Drive 11 happened (post-B-063, 10,839 rows / ~461 rows/min — power healthy under sustained load, B-063 confirmed). PM's Drive-11 brief (`inbox/2026-05-12-from-pm-drive-11-and-v0277-sprint-brief.md`): Pi capture green; server analytics tier broken at every layer; V0.27.7 (`sprint/sprint33-bugfixes-V0.27.7`, US-326–330) groomed to close it. CIO also dropped a server-schema review (`inbox/db review fom Mike.txt`). Validated both against live `obd2db` via mysql CLI — all findings hold (drive_summary id=15/source_id=11 has analytics fields NULL but Pi-synced fields present; drive_statistics=0 both tiers; drive_counter server=3 vs Pi=11; battery_health_log 14/15 still stranded, row 18=drain 17 UPDATE-synced OK; connection_log ~6k & growing; sync_history ~20k & growing every ~5s; sync_history started_at/completed_at TZ mismatch; startup_log prior_boot_clean regression). CIO scoping decision: schema-architecture refactor (vehicle_info→vehicles, drive_summary→drives, source_id→vehicle_id, drop source_device, drop server-side drive_counter, FK normalization, devices+IP/OS cols) = **separate V0.28+ epic**; V0.27.7 stays bug-fixes-only. Sent bug-vs-tech-debt split to PM inbox: `pm/inbox/2026-05-12-from-tester-db-review-validation-bug-vs-techdebt.md` (+ 3 not-yet-ticketed bugs: B-NEW-1 OBD reconnect-loop chattiness, B-NEW-2 sync cadence not idling, B-NEW-3 sync_history TZ; + flagged US-329 conflict: Marcus "compute from drive_summary" vs CIO "drop the table" — recommended retarget; Pi-side drive_counter stays). Open: refresh the Drive-11 checklist with actual results + add a Drive-12 checklist (separate pass; not blocking V0.27.7 deploy).
- **2026-05-12 (later)**: CIO asked for a full data-profiling pass on every table (server `obd2db` + Pi `obd.db`) — "anything else beyond what I already flagged?" Profiled all 21 server tables + Pi schema. Live data is clean (no garbage values, no future-dated rows, Drive 11 realtime balanced ~676/PID). Found 8 new bugs/quirks + 8 design smells, none blocking V0.27.7, all V0.28-epic candidates — written up at `findings/2026-05-12-obd2db-data-profile-additional-findings.md`. Headliners: sync_history is 42% failed rows (8,505 — historical, last failure 2026-05-08, root causes since fixed; the rows are noise → fold into the prune; the `realtime_data` "Record has changed" race is latent); `connection_log.mac_address='profile:daily'` on 19 rows (Pi write bug, propagated); Pi has NO `schema_migrations` table; Pi still has the zombie `battery_log` table (server dropped it via migration 0003); `pi_state.no_new_drives` flag exists but isn't wired to gate sync (= the concrete hook for the V0.27.7 sync-chattiness fix, B-NEW-2); server `battery_health_log.start_soc`/`end_soc` hold VCELL voltage not SOC% (Pi renamed in US-289, server didn't); `statistics` 63/84 rows NULL drive_id + type mismatch w/ drive_statistics; whole analysis tier (8 tables) empty after 11 drives — worth confirming it's wired at all (D-6).
- Forwarded N-5 (the `pi_state.no_new_drives` hook for B-NEW-2) to Marcus for V0.27.7: `pm/inbox/2026-05-12-from-tester-pi-state-hook-for-sync-chattiness.md` + a standalone story proposal `pm/inbox/2026-05-12-from-tester-story-proposal-sync-skip-when-no-new-data.md` (sync-skip-when-no-new-data, S/P2 — full scope/pre-flight/acceptance, drop-in for V0.27.7).
- **2026-05-12 (later)**: refreshed `test-reports/2026-05-11-drive-11-validation-checklist.md` with Drive-11 ground truth (pulled the FORENSIC journal trail + DB state + power_log). Verdict: Pi edge tier GREEN (B-063 power steady ~99% of the 23.5-min drive, one 5s blip; drive_state_transition ×3 clean monotonic, no warm-restart double-drive; 10,839 realtime rows / ~676 per PID; drive_summary writer ran w/ start metadata — but `from_state=unknown` + `barometric_kpa`=NULL); server analytics tier FAIL at every layer (drive_summary computed fields all NULL — root cause: server-side analytics writer never computes them from synced realtime; sync_push_drive_counter FORENSIC count = **0**, Pi never even POSTs the counter; drive_statistics 0 rows / no Pi table; US-323 backfill never ran); regression: startup_log prior_boot_clean empty post-Drain-17. Added a full Drive-12 re-validation checklist (Steps 1-4 targeting US-326..330's acceptance + the things that should flip PASS) + a root-cause appendix for US-326's pre-flight (the `start_time` NOT-NULL → migration 0006 → succeeds-but-NULL chain).
- **2026-05-12 — SESSION CLOSEOUT**. The V0.27 chain moved fast while this session ran: V0.27.7 (Sprint 33) shipped + deployed mid-session — US-326 (drive_summary server analytics) **passed**, US-327 (US-323 backfill into deploy-server.sh, idempotent) **passed**, US-328 (drive_statistics Pi-side table + writer, Option C hybrid) **passed**, US-330 (startup_log prior_boot_clean fix) **done**; US-329 (drive_counter) **deferred to V0.28 per BL-016**. Then Sprint 34 / V0.27.8 was groomed (current branch `sprint/sprint34-bugfixes-V0.27.8`): US-331 (I-031 — US-327 backfill breaks in one deploy run-context), US-332 (sync-skip-when-no-new-data via `pi_state.no_new_drives` — **the Tester's story proposal, picked up**), US-333 (sync_history both timestamps in UTC — Tester's B-NEW-3), US-334 (orphan-cleanup.service I/O throttle, TD-051), US-335 (Pi-side drain backfill drain_event_id 1+9 — Spool), US-336 (investigate 199 leaked realtime_data orphans — Spool). New backlog item B-080 (Pi clock jumps ~23h post-reboot — RTC/timesyncd; Tester corroborated). All V0.27.8 stories are Drive-12-independent — they can ship without another drive. **Observation (not actioned — outside tester/ folder per CIO scope): there's a stray file literally named `=1.1.0` in the repo root (269 bytes, pip output captured by a shell-redirect typo, probably from the US-320 pymysql work) — repo housekeeping for whoever owns the root.**
- Tester deliverables this session (all on disk; `test-reports/2026-05-11-{v0.27-chain-validation-status,regression-manifest-rewalk,state-of-system-for-sprint-32-grooming}.md` + the two `gaps/2026-05-11-*.md` were committed by the PM mid-session; **still uncommitted at closeout: `tester.md`, `test-reports/2026-05-11-drive-11-validation-checklist.md` (refreshed with Drive-11 results + Drive-12 checklist), `findings/2026-05-12-obd2db-data-profile-additional-findings.md`** — leave for the next PM closeout to commit, or commit if CIO directs).
- **HANDOFF — next session (fresh context, via `/init-tester`)**:
  1. **Primary gate: Drive 12** — once it happens, run PART 2 of `test-reports/2026-05-11-drive-11-validation-checklist.md` (Steps 1-4). It should flip US-326 (server `drive_summary` computed fields populated), US-328 (Pi `drive_statistics` table exists + per-PID rows), US-330 (next graceful boot's `startup_log.prior_boot_clean` set) to PASS, and is the test for I-019/US-311 *only if Drive 12 is a warm restart* (Drive 11 was cold-start). If `drive_summary` analytics are still NULL after Drive 12 → US-326 didn't hold → V0.27.9 (same bug class as B-059/US-237/I-026).
  2. **V0.27.8 (Sprint 34) validation** — Drive-12-independent; when it deploys, verify: US-331 (the US-323 backfill now runs in both deploy contexts → server `battery_health_log` rows 14/15 get `end_timestamp`/`runtime_seconds`); US-332 (engine off + home WiFi + all-synced → ~zero new `sync_history` rows over 5 min — was ~11; `pi_state.no_new_drives` flips true after a synced drive); US-333 (`sync_history.started_at` and `completed_at` both UTC, no 5h offset); US-334 (orphan-cleanup service doesn't hammer I/O).
  3. **Chain merge gate** — when the whole V0.27 chain is IRL-validated, the Tester is the gate on `/chain-validated`; the `chain_validate_aggregate.py` double-count (TI-002) must be fixed first.
  4. **Open Tester items**: TI-003 (2 Windows pytest failures), TI-004 (`make lint` RED 16 errors), TI-005 (the 16 data-profile findings — mostly V0.28). B-066 (B-047 self-update IRL drill) still owed → validates F-013/F-014.
  5. **Access** (verified working this session): `ssh chi-eclipse-01` (Pi, passwordless sudo) + `ssh chi-srv-01` (needs `sudo -S` for sudo); MariaDB CLI at `C:\Program Files\MariaDB 12.2\bin` → `mysql -h 10.27.27.10 -u obd2 -p<pw from .env DATABASE_URL> obd2db`. Server-side journal needs sudo on chi-srv-01.
  6. **V0.28 grooming** — auto-memory `project_v028_server_schema_epic.md` carries the full schema-normalization epic + the data-profile items + the `drive_counter`-removal-both-sides + `(drive_id, vehicle_id)` composite-uniqueness discussion. CIO wants that conversation *before* the migration is designed.

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
