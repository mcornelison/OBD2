# Tester Knowledge Base

## Operating Model

| Principle | Rule |
|-----------|------|
| **Testing trigger** | Wait for dev to mark stories complete, then validate |
| **Test philosophy** | Reality check. Factual evidence only. NEVER guess. |
| **Test ownership** | I own `tests/` folder, shared with developer |
| **Server coordination** | `../OBD2-Server` has its own tester - coordinate with them |
| **Human in the loop** | Michael Cornelison (CIO) |
| **Cadence** | Weekly recurring checks |

## Stakeholders

| Who | Role |
|-----|------|
| Michael Cornelison | CIO, human in the loop, BT dongle pairing |
| Ralph Agent | Developer (autonomous) |
| PM | Project Manager (restructuring in progress) |
| OBD2-Server Tester | Companion service tester (coordinate with) |

## Project State (as of 2026-02-05)

- **Phase**: 5.5 (Pi Deployment)
- **Platform**: Pi 5 @ 10.27.27.28, Chi-Srv-01 @ 10.27.27.120
- **Active Work**: B-015 (DB Verify), B-016 (Remote Ollama) - dev in progress
- **Blocked**: B-014 (Pi Testing) - needs BT dongle pairing
- **PM**: Restructuring in progress

## Environment Facts

| Item | Value | Source |
|------|-------|--------|
| Production config | `src/obd_config.json` | Michael confirmed - test against real config |
| Production DB path (Pi) | `data/obd.db` (SQLite) | Michael confirmed |
| Pi SSH | Pending setup by Michael | Remind him - will enable direct Pi testing |
| Pi hostname | chi-eclipse-tuner | 10.27.27.28 |
| OBDLink LX MAC | `00:04:3E:85:0D:FB` (FW 5.6.19) | Michael confirmed 2026-02-05 |
| Chi-Srv-01 | 10.27.27.120 | MariaDB + Ollama |
| MariaDB prod DB | `obd2db` | prd-companion-service.md |
| MariaDB test DB | `obd2db_test` | prd-companion-service.md |
| MariaDB user | `obd2` (access from `10.27.27.%`) | prd-companion-service.md |
| MariaDB password | `${DB_PASSWORD}` in Chi-Srv-01 `.env` | Will need when testing sync |
| Ollama model | `llama3.1:8b` on Chi-Srv-01 | prd-companion-service.md |
| Ollama URL | `http://10.27.27.120:11434` | specs/architecture.md |
| Sample data | Roadblock - Michael working with PM | Needed for grounded DB tests |
| OBD2-Server coordination | TBD | Michael hasn't decided yet |

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

## Component Health

| Component | Status | Last Tested | Notes |
|-----------|--------|-------------|-------|
| Config Validator | Green | 2026-02-05 | 54 tests pass |
| Database Layer | Green | 2026-02-05 | 50 tests pass |
| Secrets Loader | Green | 2026-02-05 | 28 tests pass |
| Error Handler | Green | 2026-02-05 | 29 tests pass |
| Orchestrator (integration) | Green | 2026-02-05 | 27 tests pass |
| Backup Manager | Green | 2026-02-05 | 39 tests pass |
| Hardware (GPIO, I2C, UPS) | Unknown | - | No real tests, needs Pi |
| Display | Unknown | - | No real tests, needs Pi |
| OBD Connection | Unknown | - | No real tests, needs BT dongle |
| Remote Ollama | Unknown | - | No real tests, needs Chi-Srv-01 |
| Companion Service | Unknown | - | Not started (../OBD2-Server) |

## Issue Tracker

| ID | Issue | Severity | Status | File Reference |
|----|-------|----------|--------|----------------|
| TI-001 | test_utils.py TestDataManager has __init__ causing PytestCollectionWarning | Low | OPEN | tests/test_utils.py:486 |

## Session Log

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
- Next: Wait for dev to mark stories complete, then validate
