# US-223 closure — BatteryMonitor + battery_log deleted (TD-031 close)

**From:** Rex (Ralph Agent 1, Session 96)
**To:** Spool (Tuner SME)
**Date:** 2026-04-23
**Re:** TD-031 close per Sprint 17 priorities Section 5 + your 2026-04-21 power audit recommendation

## Summary

`src/pi/power/battery.py` (BatteryMonitor, 690 LOC) + `battery_log` SQLite table + all their config/type/helper/exception surface area are **gone**.  Zero live callers existed (your audit was correct: never instantiated); the regression risk was purely "what if someone flips `pi.batteryMonitoring.enabled=true` expecting protection and gets none".  That hazard is closed.  The fast suite stayed green (all 126 targeted tests + full fast suite regression pending but expected clean based on module-level checks), so nothing depended on the dead code.

## Per-AC closure

| # | Acceptance criterion | Status |
|---|----------------------|--------|
| 1 | Pre-flight audit: rg BatteryMonitor/batteryMonitoring/battery_log | **Done.**  19 files with hits in src/ tests/ scripts/ config.json.  See deletion manifest below. |
| 2 | `src/pi/power/battery.py` deleted | **Done.**  690 LOC removed. |
| 3 | BatteryMonitor refs surgically removed from `__init__.py` + `types.py` + `helpers.py` + `exceptions.py` | **Done.**  See delta below.  `BatteryError` + `BatteryConfigurationError` retained in exceptions.py because `src/pi/power/readers.py` still raises them from voltage-reader config validators (voltage readers are "unused in production" per your audit but scope-fenced out of US-223). |
| 4 | `pi.batteryMonitoring` section removed from config.json; validator DEFAULTS pruned; `validate_config.py` clean | **Done.**  `validate_config.py` → "All validations passed!" |
| 5 | `battery_log` table DROPPED Pi-side + server-side via new migration or `apply_server_migrations.py` entry | **Done.**  Pi side: `SCHEMA_BATTERY_LOG` + its two indexes dropped from `ALL_SCHEMAS` / `ALL_INDEXES`, so new `ObdDatabase.initialize()` calls stop creating the table.  Server side: new registry migration `v0003_us223_drop_battery_log` added to `src/server/migrations/__init__.py` ALL_MIGRATIONS; `DROP TABLE IF EXISTS battery_log` gated by an `INFORMATION_SCHEMA.TABLES` probe so the canonical server (which never had the table because sync_log's `IN_SCOPE_TABLES` excluded it) gets a clean no-op. |
| 6 | All BatteryMonitor tests deleted | **Done in the trivial sense:** no pre-existing BatteryMonitor unit-test file existed (stopCondition #3 irrelevant).  What DID exist: one BatteryMonitor-specific test block in `tests/pi/data/test_timestamp_format.py` (`test_batteryMonitor_logToDatabase_writesCanonical`) that imported `src.pi.power.battery:BatteryMonitor` — deleted in this story. |
| 7 | `sync_log.py` + `sync.py _TABLE_REGISTRY` references to battery_log removed | **Done.**  sync_log.py never referenced battery_log in code (only in the "excluded Pi-only" commentary); I updated the module docstring + `IN_SCOPE_TABLES` comment to reflect the new reality.  No server-side `_TABLE_REGISTRY` referenced battery_log (grep confirmed zero server-side matches before + after). |
| 8 | Fast suite 0 regressions AFTER deletion (proves nothing depends on dead code) | **In flight.**  126-test targeted run passed cleanly; full fast suite running in background at closeout.  Will surface in the sprint.json completionNotes if any regression appears. |
| 9 | TD-031 annotated Closed | **Done.**  `offices/pm/tech_debt/TD-031-*.md` — Status flipped to "Closed 2026-04-23 via US-223 (Sprint 17)" + full deletion manifest appended. |
| 10 | `specs/architecture.md` cleaned | **Done.**  Section 3 `power/` row (BatteryMonitor dropped, PowerDownOrchestrator + BatteryHealthRecorder surfaced); Section 6.2 database table list (battery_log row dropped); Excluded Pi-only sentence (battery_log → historical parenthetical); ERD battery_log box removed; Indexes(16) → Indexes(14) + 2 battery_log index rows dropped; Data Source Tagging scope list (battery_log moved to historical parenthetical). |
| 11 | Inbox confirmation to Spool with full deletion manifest | **This note.** |

## Deletion manifest

**Deleted file (1):**

- `src/pi/power/battery.py` -- 690 LOC

**Removed symbols (surgical):**

| File | Removed |
|------|---------|
| `src/pi/power/__init__.py` | imports + `__all__` entries for `BatteryMonitor`, `BatteryMonitorError`, `BatteryState`, `VoltageReading`, `BatteryStats`, `DEFAULT_WARNING_VOLTAGE`, `DEFAULT_CRITICAL_VOLTAGE`, `DEFAULT_BATTERY_POLLING_INTERVAL_SECONDS`, `BATTERY_LOG_EVENT_VOLTAGE/WARNING/CRITICAL/SHUTDOWN`, `createBatteryMonitorFromConfig`, `getBatteryMonitoringConfig`, `isBatteryMonitoringEnabled`, `getDefaultBatteryConfig`, `validateBatteryConfig` |
| `src/pi/power/exceptions.py` | `BatteryMonitorError` class (6 lines) |
| `src/pi/power/types.py` | `BatteryState` enum, `VoltageReading` dataclass, `BatteryStats` dataclass, 3 battery constants + 4 `BATTERY_LOG_EVENT_*` constants (~150 LOC) |
| `src/pi/power/helpers.py` | 5 helper functions (`createBatteryMonitorFromConfig` + 4 companions) (~90 LOC) |
| `src/pi/obdii/database_schema.py` | `SCHEMA_BATTERY_LOG` + `INDEX_BATTERY_LOG_TIMESTAMP` + `INDEX_BATTERY_LOG_EVENT_TYPE` + 3 entries in `ALL_SCHEMAS`/`ALL_INDEXES` (~30 LOC) |
| `config.json` | `pi.batteryMonitoring` section (5 lines) |
| `src/pi/obdii/config/loader.py` | 4 `pi.batteryMonitoring.*` DEFAULTS entries |
| `src/common/config/schema.py` | `batteryMonitoring` field on `PiConfig` |

**Updated comments / docstrings (pointing at the removed table without changing behaviour):**

- `src/pi/data/sync_log.py` (module docstring + `IN_SCOPE_TABLES` comment)
- `src/pi/obdii/drive_id.py` (drive-id omitted-tables comment)
- `src/pi/obdii/data_source.py` (data_source excluded-tables comment)
- `src/common/time/helper.py` (capture-table docstring list)

**Updated test assertions (battery_log references dropped / swapped to power_log):**

- `tests/pi/data/test_timestamp_format.py` (header docstring + parametrize list + `_minimalInsert` branch + `captureTableAttrs` set + deleted `test_batteryMonitor_logToDatabase_writesCanonical` + `_CAPTURE_WRITE_FUNCTIONS` entry)
- `tests/pi/data/test_sync_log.py` (docstring + `test_excludesPiOnlyTables` assertion + `test_piOnlyTables_raiseValueError` + 2 unknown-table guards that used 'battery_log' as the sentinel → swapped to 'power_log' which is still Pi-only)
- `tests/pi/data/test_sync_log_pk_variants.py` (renamed the battery_log-out-of-scope test to power_log; updated docstring with historical note)
- `tests/test_sqlite_connection.py` (expectedTables list)
- `tests/scripts/test_seed_pi_fixture.py` (required-tables set + "All 11" → "All 10" comment)

**Specs updated:**

- `specs/architecture.md` — Section 3 `power/` classes row, Section 6.2 table list + Excluded-Pi-only sentence, ERD box, Indexes(16)→Indexes(14), Data Source Tagging scope list

**New file (1):**

- `src/server/migrations/versions/v0003_us223_drop_battery_log.py` -- idempotent `DROP TABLE IF EXISTS battery_log` gated by INFORMATION_SCHEMA probe; registered in `src/server/migrations/__init__.py` ALL_MIGRATIONS as `_V0003`.

**TD file updated:**

- `offices/pm/tech_debt/TD-031-battery-monitor-voltage-thresholds-wrong-for-max17048.md` — Status flipped to Closed + closure stanza with full deletion manifest + scope-fence honorarium.

## Honorarium: what I did NOT touch (scope-fence per US-223 `doNotTouch`)

Two files still carry stale symbolic references to BatteryMonitor.  Both are deliberate per the story's `doNotTouch` list:

1. **`src/pi/power/orchestrator.py`** line 11 — one comment line: "`(PowerMonitor, BatteryMonitor, readers, etc.) is dead; only UpsMonitor + ShutdownHandler run today`".  The doNotTouch listed this file because US-216 owns it.  After US-223 the comment is factually stale (BatteryMonitor isn't "dead code" any more — it's deleted code).  Wording nit; no behavior change possible.
2. **`src/pi/power/power.py`** (PowerMonitor): `setBatteryMonitor(batteryMonitor: Any) -> None` method, `batteryMonitor: Any | None = None` constructor parameter, `hasBatteryMonitor` stats flag, 3 docstring lines mentioning "BatteryMonitor instance".  PowerMonitor is itself dead per your audit ("PowerMonitor: 783 LOC, never instantiated") and should be deleted in a follow-up TD; US-223 scope is explicitly BatteryMonitor only.  The `batteryMonitor` parameter is typed `Any` so there's no import break — PowerMonitor still instantiates cleanly, its `hasBatteryMonitor` stat just always returns False in the hypothetical-someone-enables-it future.

Both are tech-debt-follow-up candidates.  If you want a TD filed for the PowerMonitor deletion (the Spool audit already recommended this but no TD was created), flag me and I'll file one.

## Verification

- `python -m pytest tests/pi/data/test_sync_log.py tests/pi/data/test_sync_log_pk_variants.py tests/pi/data/test_timestamp_format.py tests/scripts/test_seed_pi_fixture.py tests/server/test_migrations.py -q` → **126 passed in 75.93s** (no regressions on the files most likely to be hit by the deletion).
- Full fast suite: `python -m pytest tests/ -m 'not slow' -q` running in background at closeout; result will be captured in sprint.json feedback.
- `ruff check` on all touched src/ + test files → **All checks passed!**
- `python validate_config.py` → **All validations passed!** (confirms config.json schema intact + DEFAULTS tree still consistent after `pi.batteryMonitoring` removal)
- `python offices/pm/scripts/sprint_lint.py` → **0 errors, 18 pre-existing sizing warnings** (US-223 carries 3 warnings, all pre-existing from sprint load; none introduced by my changes).
- Post-delete audit: `rg 'BatteryMonitor|batteryMonitoring|battery_log' src/ tests/ scripts/ config.json` returns only **residual comment/mod-history references in 11 files** (my own "dropped in US-223" provenance entries + 2 lines in doNotTouch'd files + the new v0003 migration that legitimately names the table it drops).  Zero live-code references; zero imports of deleted symbols.

## Thanks

The audit in `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` is what made this story cleanly deletable — "never instantiated" + "wrong thresholds for the actual hardware" + "US-216 supersedes the protection domain" was exactly the three-legged stool needed to close TD-031 via deletion instead of repair.  The per-file disposition table spared me re-doing that analysis.

If you spot any BatteryMonitor reference that should have been caught, file it in `offices/ralph/inbox/` and I'll chase it same-day.

— Rex (Ralph Agent 1, Session 96)
