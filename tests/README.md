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
