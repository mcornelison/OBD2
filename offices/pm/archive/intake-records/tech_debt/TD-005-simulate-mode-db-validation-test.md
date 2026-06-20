# TD-005: Missing Simulation Output Database Validation Test

| Field        | Value                          |
|--------------|--------------------------------|
| Priority     | Medium                         |
| Status       | Open                           |
| Category     | testing / simulate / database  |
| Found By     | Torque (Pi 5 Agent)            |
| Related      | I-007, I-008                   |
| Created      | 2026-02-01                     |

## Summary

No automated test validates that running `--simulate` mode successfully logs all 13 OBD parameters to the `realtime_data` table with correct attributes. The current test suite covers component initialization and health stats but never inspects the actual database rows produced by a simulation run.

## Current Coverage Gaps

| Test File | What It Tests | What's Missing |
|-----------|--------------|----------------|
| `tests/test_orchestrator_integration.py` | Orchestrator init in simulate mode, health stats | Does not query realtime_data table |
| `tests/test_database.py` | Single RPM insert/retrieve | Does not test simulate mode or all 13 params |
| `tests/test_verify_database.py` | Schema validation, record counts | Does not test simulation output |
| `scripts/pi_smoke_test.py::checkSimulateStart()` | App starts cleanly with --simulate | Does not validate DB state afterward |

## What's Needed

A test (integration or smoke) that:

1. Runs the application with `--simulate` for a defined period (e.g., 15 seconds)
2. Queries `realtime_data` table for rows created during the run
3. Validates all 13 simulated parameters are present:
   - RPM, SPEED, COOLANT_TEMP, ENGINE_LOAD, THROTTLE_POS, MAF,
     INTAKE_TEMP, SHORT_FUEL_TRIM_1, LONG_FUEL_TRIM_1, FUEL_PRESSURE,
     TIMING_ADVANCE, INTAKE_PRESSURE, VOLTAGE (exact list may vary per config)
4. For each parameter verifies:
   - `timestamp` is a valid datetime
   - `value` is numeric
   - `unit` is set and correct for the parameter type
   - RPM is in a realistic simulated range (e.g., 600-1200 at idle)
5. Validates `connection_log` has a `drive_start` event
6. Validates graceful shutdown with exit_code=0

## Suggested Approach

- Integration test using a temporary database (`tmp_path` fixture)
- Run ApplicationOrchestrator in simulate mode programmatically (not subprocess)
- Use `threading.Timer` to call `stop()` after N seconds
- Query database directly via ObdDatabase

## Impact

Without this test, simulation regressions (e.g., a parameter silently returning None, a DB write silently failing) would go undetected until manual testing.
