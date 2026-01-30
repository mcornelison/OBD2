# Tech Debt Report: Large Files, Empty Packages, and Misc Items

**Reported by**: Ralph (Agent 1)
**Date**: 2026-01-29
**Priority**: Medium
**Type**: Tech Debt

---

## 1. Oversized Source Files

Per the new "keep files small" coding rule, the following source files exceed the 300-line guideline and are candidates for splitting:

| File | Lines | Severity |
|------|-------|----------|
| `src/obd/orchestrator.py` | 2,500 | CRITICAL - 8x over limit |
| `src/obd/data_exporter.py` | 1,309 | HIGH |
| `src/obd/simulator/drive_scenario.py` | 1,234 | HIGH |
| `src/obd/shutdown_command.py` | 1,159 | HIGH |
| `src/obd/simulator_integration.py` | 1,078 | HIGH |
| `src/obd/simulator/simulator_cli.py` | 991 | MEDIUM |
| `src/obd/simulator/failure_injector.py` | 984 | MEDIUM |
| `src/power/power.py` | 902 | MEDIUM |
| `src/ai/analyzer.py` | 882 | MEDIUM |
| `src/obd/obd_config_loader.py` | 871 | MEDIUM |
| `src/obd/obd_parameters.py` | 844 | MEDIUM |

**Recommendation**: Start with `orchestrator.py` (2,500 lines). Extract initialization, shutdown, backup, and status logic into submodules.

## 2. Oversized Test Files

| File | Lines | Notes |
|------|-------|-------|
| `tests/test_orchestrator.py` | 7,516 | CRITICAL - should split by test category |
| `tests/test_orchestrator_integration.py` | 1,200 | HIGH |
| `tests/test_status_display.py` | 1,144 | MEDIUM |
| `tests/test_ups_monitor.py` | 1,138 | MEDIUM |
| `tests/test_telemetry_logger.py` | 1,061 | MEDIUM |
| `tests/test_gpio_button.py` | 987 | MEDIUM |
| 13+ additional test files over 500 lines | | |

## 3. Empty Placeholder Packages

Three `src/obd/` subdirectories contain only `__init__.py` with no actual module code:

| Package | Likely Intended Content |
|---------|----------------------|
| `src/obd/export/` | Should contain `data_exporter.py` logic (currently in `src/obd/data_exporter.py`) |
| `src/obd/shutdown/` | Should contain `shutdown_command.py` logic (currently in `src/obd/shutdown_command.py`) |
| `src/obd/service/` | Should contain `service.py` logic (currently in `src/obd/service.py`) |

These were likely created during a refactoring pass that was never completed. Either populate them by moving the monolithic files into the subpackages, or remove the empty directories.

## 4. Pytest Warning

`tests/test_utils.py` contains a `TestDataManager` class with an `__init__` constructor. Pytest cannot collect it as a test class, producing a `PytestCollectionWarning` on every test run. If it's a utility (not a test), rename it to not start with `Test`.

## 5. Config Drift in obd_config.json

- `display.width: 240, display.height: 240` -- should be `480, 320` per OSOYOO display hardware update
- `dataRetention.realtimeDataDays: 7` -- should be `365` per US-TD-003 update (was changed in code defaults but not in the config file)

## 6. Unpushed Commits

77 commits on `master` are ahead of `origin/master`. This will be addressed in the current housekeeping session.

---

*Submitted by Ralph via pm/techDebt/ per established protocol.*
