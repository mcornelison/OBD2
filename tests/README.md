# Tests Directory

This directory contains the test suite for the Eclipse OBD-II project.

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=src --cov-report=html

# Run a specific test file
pytest tests/test_config_validator.py -v

# Run without slow tests
pytest tests/ -v -m "not slow"

# Run a single test function
pytest tests/test_config.py::test_loadConfig_validFile_returnsDict -v
```

## Test Structure

All tests use pytest and follow these conventions:

### Naming Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>` (group related tests)
- Test functions: `test_<function>_<scenario>_<expected>` or descriptive names

### Test Pattern

Tests follow the AAA (Arrange-Act-Assert) pattern with Google-style docstrings:

```python
def test_functionName_scenario_expectedResult():
    """
    Given: preconditions
    When: action taken
    Then: expected outcome
    """
    # Arrange
    input_data = {"id": 1}
    processor = Processor()

    # Act
    result = processor.process(input_data)

    # Assert
    assert result is True
```

## Shared Fixtures

The `conftest.py` file provides shared fixtures available to all tests:

### Configuration Fixtures
- `sampleConfig` - Complete sample configuration for tests
- `minimalConfig` - Minimal configuration for testing defaults
- `invalidConfig` - Invalid configuration for error testing

### Environment Fixtures
- `envVars` - Sets up test environment variables (auto-cleanup)
- `cleanEnv` - Ensures clean environment with no test variables

### Mock Fixtures
- `mockLogger` - Mock logger for testing log calls
- `mockApiResponse` - Mock API response data
- `mockDbConnection` - Mock database connection

### File System Fixtures
- `tempConfigFile` - Temporary config file
- `tempEnvFile` - Temporary .env file

### Utility Fixtures
- `assertNoLogs` - Asserts no error logs were emitted during test

## Test Markers

Tests can be marked for selective running:

```python
@pytest.mark.slow          # Slow tests (skip with -m "not slow")
@pytest.mark.integration   # Integration tests
@pytest.mark.unit          # Unit tests
```

## Coverage Requirements

- Minimum 80% overall coverage (enforced in pyproject.toml)
- 100% coverage for critical paths
- Branch coverage is enabled

## Tips

1. **Use fixtures** - Leverage conftest.py fixtures instead of duplicating setup
2. **Mock external dependencies** - Database, network, hardware should be mocked
3. **Test edge cases** - Empty inputs, None values, error conditions
4. **Keep tests isolated** - Tests should not depend on each other
5. **Use descriptive names** - Test names should explain what they test

## File size guidance

Test files should target **≤500 lines**. This is a guideline, not a hard cap —
integration-style test modules that exercise a single subsystem often grow
past the target without a clean factoring opportunity.

Sweep 5 split every `test_orchestrator_*.py` file below 500 lines (13 files
→ 73 focused files, Task 3). Other oversized test files are listed below as
documented exemptions. Future refactors may revisit any of these if a natural
split emerges.

### Exemptions

Single-concern integration test modules where splitting would fragment the
AAA story rather than clarify it:

- `test_main.py` (1138) — Pi main entry point integration tests across startup, shutdown, config, and arg parsing.
- `test_polling_tiers.py` (1012) — OBD-II tiered polling schedule; tests cover priority, timing, and tier transitions.
- `test_database.py` (898) — SQLite schema, migrations, readings/alerts/recommendations round-trips.
- `test_fuel_detail.py` (882) — fuel-detail display screen rendering and touch interactions.
- `test_backup_manager.py` (852) — Google Drive backup scheduling, catchup, upload, cleanup.
- `test_parked_mode.py` (833) — parked-mode display screen and idle state transitions.
- `test_logging_config.py` (832) — logging setup, rotation, tier-aware formatters, log file paths.
- `test_remote_ollama.py` (803) — remote Ollama network reachability and connection handling.
- `test_simulate_db_validation.py` (773) — simulator database write validation (`@pytest.mark.slow`).
- `test_touch_interactions.py` (762) — touchscreen gesture handling across screens.
- `test_verify_hardware.py` (747) — hardware verification script end-to-end.
- `test_obd_config_loader.py` (742) — OBD config loader with tier-aware paths.
- `test_timing_thresholds.py` (716) — ignition timing threshold classifier.
- `test_system_detail.py` (711) — system detail display screen.
- `test_iat_thresholds.py` (667) — intake air temperature threshold classifier.
- `test_stft_thresholds.py` (645) — short-term fuel trim threshold classifier.
- `test_battery_voltage_thresholds.py` (623) — battery voltage bidirectional threshold.
- `test_thermal_detail.py` (618) — thermal detail display screen.
- `test_primary_screen.py` (618) — primary display screen (dashboard home).
- `test_test_utils.py` (602) — unit tests for the test utility module itself.
- `test_knock_detail.py` (591) — knock detail display screen.
- `test_boost_detail.py` (572) — boost detail display screen.
- `test_tiered_thresholds.py` (570) — tiered threshold dispatcher tests.
- `test_rpm_thresholds.py` (568) — RPM threshold classifier.
- `test_e2e_simulator.py` (564) — end-to-end simulator integration test (`@pytest.mark.slow`; spawns subprocess).
- `test_utils.py` (539) — shared test utility module (doubles as a tested module).
