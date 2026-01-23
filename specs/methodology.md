# Development Methodology

## Overview

This document describes the development philosophy, workflows, and processes for the Eclipse OBD-II Performance Monitoring System.

**Last Updated**: 2026-01-22
**Author**: Michael Cornelison

---

## 1. Development Philosophy

### Core Principles

1. **Incremental Delivery**: Build in small, testable increments
2. **Test-Driven Development**: Write tests before implementation
3. **Configuration-Driven**: Externalize behavior to configuration
4. **Modular Architecture**: Single responsibility, loose coupling
5. **Documentation as Code**: Keep docs with the code they describe

### Quality Standards

- **Test Coverage**: Minimum 80% for all modules
- **Critical Paths**: 100% coverage for core functionality
- **Code Review**: All changes require peer review
- **Documentation**: Public APIs must have docstrings

---

## 2. Backlog-Driven Development

### Task Lifecycle

```
┌─────────┐    ┌─────────────┐    ┌─────────┐    ┌───────────┐
│ Pending │ -> │ In Progress │ -> │ Testing │ -> │ Completed │
└─────────┘    └─────────────┘    └─────────┘    └───────────┘
      │              │                 │
      │              │                 │
      ▼              ▼                 ▼
  ┌─────────┐    ┌─────────┐     ┌─────────┐
  │ Blocked │    │  Blocked │    │  Failed │
  └─────────┘    └─────────┘     └─────────┘
```

### Backlog Structure

Tasks in `specs/backlog.json` include:

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| title | Brief task summary |
| category | Grouping (config, core, api, database, testing, observability, security, documentation, deployment) |
| description | Detailed requirements |
| priority | high/medium/low |
| status | pending/in_progress/completed/blocked |
| steps | Implementation steps |
| testing | Verification criteria |
| passed | Test result (true/false) |
| completedDate | Completion timestamp |
| notes | Additional context and learnings |

### Working with the Backlog

1. **Select Task**: Choose highest priority pending task
2. **Update Status**: Mark as `in_progress`
3. **Implement**: Follow the defined steps
4. **Test**: Verify against testing criteria
5. **Complete**: Mark as `completed` with date
6. **Document**: Update notes with learnings

---

## 3. Test-Driven Development

### TDD Workflow

```
1. Write failing test
   │
2. Write minimal code to pass
   │
3. Run test (should pass)
   │
4. Refactor if needed
   │
5. Run all tests (should pass)
   │
6. Commit
```

### Test Categories

| Category | Purpose | Location |
|----------|---------|----------|
| Unit | Individual functions | `tests/test_*.py` |
| Integration | Component interaction | `tests/integration/` |
| End-to-End | Full workflow | `tests/e2e/` |

### Test Naming Convention

```python
def test_functionName_scenario_expectedResult():
    """
    Given: [preconditions]
    When: [action]
    Then: [expected outcome]
    """
    pass
```

### Running Tests

```bash
# All tests
pytest tests/

# With coverage
pytest tests/ --cov=src --cov-report=html

# Specific file
pytest tests/test_config_validator.py -v

# Specific test
pytest tests/test_main.py::TestParseArgs::test_parseArgs_noArgs_usesDefaults -v

# Skip slow tests
pytest tests/ -m "not slow"

# Manual test runners (when pytest unavailable)
python run_tests_config_validator.py
python run_all_tests.py

# Simulator-based testing
python src/main.py --simulate  # Run with simulated hardware
python src/main.py --simulate --verbose  # Debug output
```

### Test Fixtures

Common fixtures in `tests/conftest.py`:
- `sampleConfig`: Standard test configuration
- `minimalConfig`: Minimal valid configuration
- `invalidConfig`: Configuration with missing required fields
- `envVars`: Test environment variables
- `cleanEnv`: Context manager for clean environment
- `mockLogger`: Mocked logger for testing
- `tempConfigFile`: Temporary config file fixture
- `tempEnvFile`: Temporary .env file fixture

### Test Utilities

Helpers in `tests/test_utils.py`:
- `createTestConfig()`: Create test config with deep merge overrides
- `createTestRecord()`: Create single test record with custom fields
- `temporaryEnvVars()`: Set env vars for test scope, auto-restore
- `temporaryFile()`: Create temp file with content, auto-delete
- `assertDictSubset()`: Verify dict contains all subset keys/values
- `createMockResponse()`: Mock HTTP response
- `waitForCondition()`: Poll condition with timeout

---

## 4. Configuration-Driven Design

### Principles

1. **No Magic Numbers**: All values in configuration
2. **Environment Separation**: Different configs per environment
3. **Secrets Isolation**: Credentials only in .env
4. **Defaults**: Sensible defaults for optional settings
5. **Validation**: Fail fast on invalid configuration

### Configuration Layers

```
.env (secrets only)
    ↓
secrets_loader.py (resolve ${VAR} placeholders)
    ↓
config.json (application settings)
    ↓
config_validator.py (validate, apply defaults)
    ↓
Runtime Configuration
```

### Adding New Configuration

1. Add to `config.json` with `${ENV_VAR}` if secret
2. Add to `.env.example` if environment variable
3. Add validation in `config_validator.py` if required
4. Add default in `DEFAULTS` dict if optional
5. Document in README

### Configuration Patterns

**Dot-notation for nested defaults:**
```python
DEFAULTS = {
    'database.timeout': 30,
    'api.retry.maxRetries': 3,
    'logging.level': 'INFO'
}
```

**Placeholder syntax for secrets:**
```json
{
  "database": {
    "password": "${DB_PASSWORD}",
    "port": "${DB_PORT:1433}"  // With default
  }
}
```

---

## 5. Development Workflow

### Feature Development

```
1. Create/assign backlog task
   │
2. Create feature branch
   │  git checkout -b feature/task-id-description
   │
3. Write tests first (TDD)
   │
4. Implement feature
   │
5. Run all tests
   │
6. Update documentation
   │
7. Create pull request
   │
8. Code review
   │
9. Merge to main
   │
10. Mark task completed
```

### Branch Naming

| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feature/task-id-desc` | `feature/42-add-logging` |
| Bugfix | `bugfix/task-id-desc` | `bugfix/56-fix-timeout` |
| Hotfix | `hotfix/desc` | `hotfix/critical-auth-fix` |
| Ralph | `ralph/feature-name` | `ralph/eclipse-obd-ii` |

### Commit Messages

Format:
```
<type>: <short description>

<optional body with details>

Task: #<task-id>
Co-Authored-By: Claude <noreply@anthropic.com>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code restructuring
- `test`: Test additions
- `docs`: Documentation
- `chore`: Maintenance

Example:
```
feat: add configuration validation

- Added ConfigValidator class
- Implemented required field checks
- Added default value application

Task: #2
Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## 6. Code Review Process

### Review Checklist

- [ ] Code follows naming conventions (camelCase functions, PascalCase classes)
- [ ] File headers are present and correct
- [ ] Tests are included and passing (80% minimum coverage)
- [ ] No security vulnerabilities introduced
- [ ] Documentation updated if needed
- [ ] No unnecessary complexity
- [ ] Error handling is appropriate (5-tier classification)
- [ ] Logging is sufficient with PII masking
- [ ] Configuration is externalized

### Review Guidelines

1. **Be Constructive**: Suggest improvements, not just problems
2. **Ask Questions**: Understand the reasoning
3. **Focus on Important**: Don't nitpick formatting
4. **Test Locally**: Pull and run the code
5. **Approve or Request Changes**: Don't leave hanging

---

## 7. Error Handling Standards

### Error Classification

| Level | Type | Handling |
|-------|------|----------|
| 1 | RETRYABLE | Exponential backoff (1s, 2s, 4s, 8s, 16s), retry max 3 times |
| 2 | AUTHENTICATION | Log credentials issue, fail |
| 3 | CONFIGURATION | Fail fast, clear message |
| 4 | DATA | Log, skip record, continue |
| 5 | SYSTEM | Fail with full diagnostics |

### Retry Strategy

```python
# Using the @retry decorator
from common.error_handler import retry, RetryableError

@retry(maxRetries=3, initialDelay=1.0, backoffMultiplier=2.0)
def fetchData(endpoint):
    # Implementation
    pass
```

### Error Messages

Good:
```
Configuration error: Missing required field 'database.password'.
Add DB_PASSWORD to .env file.
```

Bad:
```
Error: KeyError
```

---

## 8. Logging Standards

### Log Levels

| Level | Usage |
|-------|-------|
| DEBUG | Variable values, flow tracing |
| INFO | Operation start/end, key milestones |
| WARNING | Unexpected but handled conditions |
| ERROR | Failures requiring attention |

### Log Format

```
2026-01-21 10:30:45 | INFO     | module_name | functionName | Message here
```

### Logging Guidelines

1. **Log entry and exit** of major operations
2. **Include context**: IDs, counts, durations
3. **Mask sensitive data**: passwords, tokens, PII (automatic via PIIMaskingFilter)
4. **Use structured data** for metrics via `logWithContext()`
5. **Don't log in tight loops** (use sampling)

### Using LogContext

```python
from common.logging_config import LogContext, logWithContext

# Add context to all log messages in a scope
with LogContext(requestId='abc123', userId=42):
    logger.info("Processing request")  # Includes context

# Or use logWithContext for single messages
logWithContext(logger, logging.INFO, "Batch completed",
               batchId=123, recordCount=500, durationMs=1250)
```

---

## 9. Security Best Practices

### Secrets Management

- Store secrets in `.env` only
- Never commit `.env` to version control
- Use `${VAR}` placeholders in config.json
- Use `maskSecret()` when logging secret values
- loadEnvFile() does NOT override existing env vars (safe for layered config)

### Input Validation

- Validate all external input
- Sanitize data before database operations
- Use parameterized queries
- Limit input lengths

### Logging Security

- PIIMaskingFilter automatically masks emails, phones, SSNs
- Never log passwords or tokens
- Use `[LOADED]` placeholder for secret values in logs

---

## 10. Documentation Standards

### Code Documentation

**File Headers** (required):
```python
################################################################################
# File Name: module_name.py
# Purpose/Description: Brief description
# Author: Author Name
# Creation Date: YYYY-MM-DD
# Copyright: (c) Year Author Name. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# YYYY-MM-DD    | A. Name      | Initial implementation
# ================================================================================
################################################################################
```

**Function Docstrings** (Google-style):
```python
def functionName(param1: str, param2: int) -> bool:
    """
    Brief description of function.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When param1 is empty
    """
    pass
```

### README Updates

Update README when:
- Adding new configuration options
- Changing installation steps
- Adding new commands
- Modifying project structure

---

## 11. Ralph Autonomous Agent

### How Ralph Works

Ralph is an autonomous development agent that works through the project backlog:

1. Reads `ralph/AGENT.md` for instructions
2. Selects highest priority `pending` task from `specs/backlog.json`
3. Writes tests first (TDD)
4. Implements solution following `specs/standards.md`
5. Runs tests to verify
6. Updates backlog with `completed` status and notes
7. Updates `ralph/progress.txt` with session notes

### Running Ralph

```bash
# Run Ralph for 1 iteration
./ralph/ralph.sh 1

# Run Ralph for 10 iterations
./ralph/ralph.sh 10

# Check Ralph status
make ralph-status
```

### Progress Tracking

Ralph maintains progress in:
- `specs/backlog.json` - Task status
- `ralph/progress.txt` - Session notes and learnings
- `ralph/ralph_agents.json` - Agent state

---

## 12. Continuous Improvement

### Retrospectives

After each milestone:
1. What went well?
2. What could improve?
3. Action items for next iteration

### Technical Debt

Track in backlog with `debt` category:
- Prioritize during planning
- Address before it accumulates
- Document why debt was incurred

### Codebase Patterns

Learnings are captured in `ralph/progress.txt` Codebase Patterns section:
- ConfigValidator uses dot-notation for nested key access
- SecretsLoader regex pattern for placeholder resolution
- PIIMaskingFilter patterns for email, phone, SSN
- Error classification follows 5-tier system
- Test utilities in tests/test_utils.py
- Module refactoring follows: types → exceptions → core → helpers
- Re-export facades maintain backward compatibility during refactoring

### Standards Evolution

1. Propose changes via pull request to specs/
2. Discuss in code review
3. Update all affected documentation
4. Communicate changes to team

---

## Modification History

| Date | Author | Description |
|------|--------|-------------|
| 2026-01-22 | Knowledge Update | Added module refactoring pattern to codebase patterns section |
| 2026-01-22 | Knowledge Update | Added simulator-based testing commands |
| 2026-01-21 | M. Cornelison | Updated methodology for Eclipse OBD-II project with project-specific details |
