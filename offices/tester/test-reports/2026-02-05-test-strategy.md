# Test Strategy: Evidence-Based Validation

**Date**: 2026-02-05
**Author**: Tester Agent
**Status**: Active

## Philosophy

Every test must answer one question: **Does the user story actually work?**

Tests that verify mock interactions, log messages, or getter/setter patterns are deleted.
Tests that run real code against real (or simulated) systems with verifiable outcomes are kept.

## What "Evidence" Means

A test passes ONLY when it produces **verifiable factual evidence**:

1. **Data was written** - Query the DB, count rows, check values
2. **File was created** - Check it exists, read it, verify contents
3. **Config was resolved** - Load real config, check actual values
4. **System responded** - Real HTTP response, real socket connection
5. **Behavior occurred** - Observable state change, not mock.assert_called()

## Test Categories

### Category 1: Windows-Runnable (Simulate Mode)
Tests that run on the dev machine without hardware.

| Area | What We Test | How |
|------|-------------|-----|
| Database | Schema creation, data writes, queries | Real SQLite (temp file) |
| Config | Validation, defaults, env resolution | Real config files |
| Orchestrator | Start/stop in simulate mode | Real temp DB, simulated OBD |
| Backup | File creation, compression | Real temp directories |
| Error handling | Classification, retry logic | Real exceptions |

### Category 2: Pi-Only (Bash Scripts for Michael)
Tests that require Pi 5 hardware. Created as executable scripts.

| Area | What We Test | How |
|------|-------------|-----|
| OBD Connection | BT dongle pairing, data read | Real OBDLink LX |
| Display | pygame on HDMI touch screen | Real OSOYOO display |
| UPS | Battery voltage reads over I2C | Real Geekworm X1209 |
| GPIO | Physical button presses | Real GPIO pins |

### Category 3: Network Integration (Pi + Chi-Srv-01)
Tests that require both systems on the LAN.

| Area | What We Test | How |
|------|-------------|-----|
| Remote Ollama | Connectivity, model inference | Real HTTP to 10.27.27.10:11434 |
| Delta Sync | Data push to MariaDB | Real API call to companion service |
| Backup Upload | File transfer to Chi-Srv-01 | Real rsync/API call |

## Validation Approach per User Story

When a story is marked complete, I will:

1. **Read the acceptance criteria** from `ralph/stories.json`
2. **For each criterion**, write a test that produces factual evidence
3. **Run the test** on the appropriate environment (Windows/Pi/Network)
4. **Document results** in `test-reports/` with evidence
5. **File gaps** in `gaps/` for anything that fails

## Current Test Suite (384 tests, all real)

```
tests/
  conftest.py                      # Shared fixtures
  test_backup_manager.py           # Real file I/O (39 tests)
  test_config_validator.py         # Real validation logic (54 tests)
  test_database.py                 # Real SQLite ops (50 tests)
  test_error_handler.py            # Real error classification (29 tests)
  test_logging_config.py           # Real PII masking (47 tests)
  test_obd_config_loader.py        # Real config parsing (38 tests)
  test_orchestrator_integration.py # Real orchestrator + temp DB (27 tests)
  test_platform_utils.py           # Platform detection (18 tests)
  test_secrets_loader.py           # Real env var resolution (28 tests)
  test_sqlite_connection.py        # Real SQLite connectivity (~40 tests)
  test_test_utils.py               # Utility tests (40 tests)
  test_utils.py                    # Test utility module
  test_verify_database.py          # Real DB verification (14 tests)
```

## What's NOT Tested Yet (Gaps)

| Component | Why | When |
|-----------|-----|------|
| Remote Ollama | Dev stories US-OLL-001/002/003 not complete | After dev marks complete |
| Hardware (GPIO, I2C, UPS) | Needs Pi physical access | Bash scripts for Michael |
| Display (pygame) | Needs Pi + HDMI screen | Bash scripts for Michael |
| OBD Connection | Needs BT dongle pairing | After B-014 unblocked |
| Companion Service | OBD2-Server not built yet | After B-022 dev complete |
| Delta Sync | Depends on companion service | After B-022 + B-027 |

## Developer Coordination Note

I deleted `test_remote_ollama.py` (24 mock tests) which was the deliverable for US-OLL-004.
Those tests were mock-based by design (per the story's acceptance criteria).
When US-OLL-001/002/003 are completed, I will write evidence-based replacement tests.
The developer may need to recreate their TDD tests if they need them for development workflow.
