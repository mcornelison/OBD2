# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Type

Python 3.11+ development template with TDD methodology, comprehensive specs, and Ralph autonomous agent system.

## Development Commands

### Testing
```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=src --cov-report=html

# Run specific test file
pytest tests/test_config_validator.py -v

# Run without slow tests
pytest tests/ -v -m "not slow"

# Single test function
pytest tests/test_config.py::test_loadConfig_validFile_returnsDict -v
```

### Code Quality
```bash
# Using Make (recommended)
make lint              # Run ruff linter
make lint-fix          # Auto-fix linting issues
make format            # Format with black
make typecheck         # Run mypy type checking
make quality           # Run all quality checks
make pre-commit        # Run quality + tests before committing

# Direct commands
ruff check src/ tests/
ruff check src/ tests/ --fix
black src/ tests/
mypy src/
```

### Application
```bash
# Validate configuration
python validate_config.py
python validate_config.py --verbose

# Run application
python src/main.py
python src/main.py --dry-run
python src/main.py --config path/to/config.json
```

### Ralph Agent System
```bash
# Run Ralph agent (1 iteration)
./ralph/ralph.sh 1

# Run Ralph agent (10 iterations)
./ralph/ralph.sh 10

# Check Ralph status
make ralph-status
```

## Architecture Overview

### Configuration System (3-Layer)
The project uses a sophisticated configuration system with three layers:

1. **Environment Variables** (`.env`) - Secrets only, never committed
2. **Secrets Loader** (`src/common/secrets_loader.py`) - Resolves `${ENV_VAR}` placeholders at runtime
3. **Config Validator** (`src/common/config_validator.py`) - Validates schema, applies defaults, ensures required fields

**Critical Pattern**: In `config.json`, use `${ENV_VAR}` syntax for secrets:
```json
{
  "database": {
    "password": "${DB_PASSWORD}"
  }
}
```

The validator uses dot-notation paths for nested defaults:
```python
DEFAULTS = {
    'database.timeout': 30,
    'api.retry.maxRetries': 3
}
```

### Error Classification System
Errors follow a 5-tier classification (`src/common/error_handler.py`):

1. **Retryable** (network timeouts, rate limits) → Exponential backoff retry
2. **Authentication** (401/403, credentials issues) → Fail, log credentials issue
3. **Configuration** (missing settings, invalid values) → Fail fast with clear message
4. **Data** (validation failures) → Log and continue/skip
5. **System** (unexpected errors) → Fail with full diagnostics

Retry pattern uses: `[1, 2, 4, 8, 16]` second delays with max 3 retries.

### Common Utilities Pattern
All utilities in `src/common/` follow these patterns:
- File headers required (see `specs/standards.md`)
- camelCase for functions/variables, PascalCase for classes
- Type hints on all public functions
- Google-style docstrings with Args/Returns/Raises
- Comprehensive error handling with specific exception types

## Coding Standards (Critical Points)

### Naming Conventions (STRICT)
- **Python functions/variables**: camelCase (`getUserData`, `recordCount`)
- **Python classes**: PascalCase (`ConfigValidator`, `DataProcessor`)
- **SQL tables/columns**: snake_case (`user_accounts`, `created_at`)
- **Constants**: UPPER_SNAKE_CASE (`MAX_RETRIES`, `DEFAULT_TIMEOUT`)

### File Headers (REQUIRED)
Every Python file must include the standard header. See `specs/standards.md` line 16-33 for the exact format.

### Documentation Requirements
- Public functions require Google-style docstrings
- Complex logic requires inline comments explaining "why" not "what"
- No comments for self-explanatory code

## Specs System

The `specs/` directory contains the project's knowledge base:

| File | Purpose |
|------|---------|
| `standards.md` | Complete coding conventions (naming, headers, SQL, testing) |
| `architecture.md` | System design, data flow, technology stack |
| `methodology.md` | TDD workflow, backlog management, error handling strategy |
| `anti-patterns.md` | Common mistakes and their solutions |
| `glossary.md` | Domain terminology |
| `backlog.json` | Task tracking with status/priority/testing criteria |

**Key Pattern**: When implementing features, follow TDD:
1. Read task from `specs/backlog.json`
2. Write tests first
3. Implement to pass tests
4. Update backlog status to `completed`
5. Add notes about implementation

## Ralph Autonomous Agent System

Ralph is an autonomous development agent that works through `specs/backlog.json`:

- **Instructions**: `ralph/agent.md` - Full agent guidelines
- **State**: `ralph/ralph_agents.json` - Agent assignment tracking
- **Progress**: `ralph/progress.txt` - Session notes
- **Launcher**: `ralph/ralph.sh` - Entry point with iteration control

**How Ralph Works**:
1. Reads `ralph/agent.md` for instructions
2. Selects highest priority `pending` task from `specs/backlog.json`
3. Writes tests first (TDD)
4. Implements solution following `specs/standards.md`
5. Runs tests to verify
6. Updates backlog with `completed` status and notes
7. Signals completion with `<promise>COMPLETE</promise>` or `<promise>HUMAN_INTERVENTION_REQUIRED</promise>`

## Testing Standards

### Test Structure (AAA Pattern)
```python
def test_functionName_scenario_expectedResult():
    """
    Given: preconditions
    When: action taken
    Then: expected outcome
    """
    # Arrange
    input = {"id": 1}
    processor = Processor()

    # Act
    result = processor.process(input)

    # Assert
    assert result is True
```

### Coverage Requirements
- Minimum 80% overall coverage (enforced in pyproject.toml)
- 100% coverage for critical paths
- Use pytest fixtures from `tests/conftest.py`

### Test Markers
```python
@pytest.mark.slow          # Slow tests (skip with -m "not slow")
@pytest.mark.integration   # Integration tests
@pytest.mark.unit          # Unit tests
```

## Windows Compatibility Notes

This project runs on Windows (MINGW64_NT). Key considerations:

- CSV files: Always use `newline=''` parameter when opening
- Path handling: Use `os.path.join()` or `pathlib.Path` for cross-platform compatibility
- Line endings: Git handles CRLF/LF conversion automatically

## Tool Configuration

All tools configured in `pyproject.toml`:
- **Black**: 100 char line length, Python 3.11 target
- **Ruff**: Pycodestyle, Pyflakes, isort, flake8-bugbear
- **MyPy**: Strict type checking, untyped defs disallowed
- **Pytest**: Coverage reports, test markers, filterwarnings
- **Coverage**: 80% minimum, branch coverage enabled

## Important Notes for Claude

1. **Always read before modifying**: Read existing code to understand patterns
2. **Follow established patterns**: Especially in `src/common/` - these are the foundation
3. **Test after changes**: Run `pytest tests/` before marking tasks complete
4. **Update backlog**: Mark tasks complete in `specs/backlog.json` when done
5. **Reference specs**: `specs/standards.md` for conventions, `specs/anti-patterns.md` for what to avoid
6. **Configuration validation**: Run `python validate_config.py` after config changes
7. **No magic numbers**: All values belong in config or as named constants
8. **Error handling**: Use the 5-tier classification system, never silent failures
9. **TDD approach**: Write tests first, then implementation

## Quick Reference

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Development cycle
make pre-commit              # Quality + tests
python validate_config.py    # Validate config
python src/main.py          # Run app

# Autonomous development
./ralph/ralph.sh 10         # Run Ralph for 10 iterations
```
