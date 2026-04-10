# PRD: Simulate Mode Database Output Validation Test

**Parent Backlog Item**: B-026
**Status**: Active
**Origin**: TD-005, I-007, I-008

## Introduction

No automated test validates that `--simulate` mode logs all 13 OBD parameters to the `realtime_data` table with correct attributes. This PRD creates the **reference implementation** of the project's Definition of Done pattern: any story that writes to the database MUST include a test validating data was actually written.

## Goals

- Prove that simulate mode produces correct database output end-to-end
- Establish the DB validation test pattern for all future database-writing stories
- Catch regressions where simulator output changes silently

## Existing Infrastructure

| Component | File | Key Details |
|-----------|------|-------------|
| Orchestrator | `src/orchestrator/application_orchestrator.py` | Main app lifecycle, `--simulate` flag |
| Database | `src/obd/database.py` | `ObdDatabase`, `realtime_data` table, `connection_log` table |
| Simulator | `src/simulator/` | Physics-based sensor simulation, 13 OBD parameters |
| Config | `src/obd_config.json` | Database path, simulator settings |

### The 13 Simulated OBD Parameters

From the simulator's physics model (sourced from `specs/obd2-research.md`):

1. RPM
2. Vehicle Speed
3. Engine Load
4. Coolant Temperature
5. Intake Air Temperature
6. Throttle Position
7. Short Term Fuel Trim
8. Long Term Fuel Trim
9. Timing Advance
10. MAF Air Flow Rate
11. Fuel System Status
12. Oxygen Sensor Voltage
13. Barometric Pressure

## User Stories

### US-101: Write Simulate DB Validation Integration Test

**Description:** As a developer, I need an integration test that runs the application in `--simulate` mode and validates the database output is correct.

**Acceptance Criteria:**
- [ ] Create `tests/test_simulate_db_validation.py` with standard file header per `specs/standards.md`
- [ ] Test runs `ApplicationOrchestrator` in simulate mode programmatically (not subprocess)
- [ ] Uses a temporary database via `tmp_path` fixture (no side effects on real data)
- [ ] Runs simulation for ~15 seconds using `threading.Timer` to call graceful shutdown
- [ ] Queries `realtime_data` table and verifies rows exist for all 13 simulated parameters
- [ ] Validates each parameter row: timestamp is valid datetime, value is numeric, unit is set (non-empty)
- [ ] Validates RPM values are in realistic simulated idle range (600-1200)
- [ ] Validates `connection_log` has a `drive_start` event
- [ ] Validates graceful shutdown completes with no unhandled exceptions
- [ ] Test marked with `@pytest.mark.slow` and `@pytest.mark.integration`
- [ ] All existing tests still pass, typecheck passes

### US-102: Validate Parameter Completeness and Data Quality

**Description:** As a developer, I need the validation test to verify data quality beyond just existence -- timestamps should be sequential, values should be within physics-model ranges.

**Acceptance Criteria:**
- [ ] Test verifies `realtime_data` timestamps are monotonically increasing per parameter
- [ ] Test verifies at least 2 data points per parameter (confirms continuous logging, not just one sample)
- [ ] Test verifies no NULL values in required columns (timestamp, parameter_name, value, unit)
- [ ] Test verifies no duplicate (timestamp, parameter_name) combinations
- [ ] Test helper function `assertParameterInRange(rows, paramName, minVal, maxVal)` for reuse in future DB validation tests
- [ ] All tests pass, typecheck passes

### US-103: Document DB Validation Test Pattern

**Description:** As a developer, I need a brief docstring/comment block in the test file that explains the DB validation pattern so future stories can copy it.

**Acceptance Criteria:**
- [ ] Module-level docstring in `test_simulate_db_validation.py` explains the pattern: run orchestrator, query DB, assert rows
- [ ] Documents the `assertParameterInRange` helper and how to add new parameter checks
- [ ] References specs/methodology.md Definition of Done requirement
- [ ] References this PRD (B-026) as the origin
- [ ] No separate documentation file -- the test file IS the reference implementation

## Functional Requirements

- FR-1: Test must work on both Windows (MINGW64) and Linux (Pi)
- FR-2: Test must not require network access, Bluetooth, or Ollama
- FR-3: Test must clean up after itself (tmp_path handles this)
- FR-4: Test must complete within 60 seconds (15s sim + teardown overhead)

## Non-Goals

- No performance benchmarking (just correctness)
- No testing of real OBD connections (simulator only)
- No testing of AI analysis output (that's a separate concern)

## Success Metrics

- `pytest tests/test_simulate_db_validation.py -v` passes
- Pattern is reusable for future DB-writing stories
