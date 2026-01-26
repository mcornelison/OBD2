# Task: Evaluate Commented Dependencies in requirements.txt

## Summary
Review and decide on the commented-out dependencies in `requirements.txt` to determine which should be enabled for development.

## Background
Many dependencies in `requirements.txt` are commented out:
- Development tools: `black`, `ruff`, `mypy`
- HTTP clients: `requests`, `httpx`
- Data processing: `pandas`, `numpy`
- Database: `pyodbc`, `sqlalchemy`
- Logging: `structlog`

It's unclear if these are optional, deprecated, or simply not yet needed.

## Dependencies to Evaluate

### Development Tools (likely should be enabled)
- [ ] `black>=23.0.0` - Code formatter (referenced in CLAUDE.md)
- [ ] `ruff>=0.1.0` - Linter (referenced in CLAUDE.md)
- [ ] `mypy>=1.0.0` - Type checker (referenced in CLAUDE.md)

### HTTP Clients
- [ ] `requests>=2.28.0` - Common HTTP library
- [ ] `httpx>=0.24.0` - Async HTTP client
- Note: Code currently uses `urllib` to avoid dependencies

### Data Processing
- [ ] `pandas>=2.0.0` - Data analysis
- [ ] `numpy>=1.24.0` - Numerical computing

### Database
- [ ] `pyodbc>=4.0.0` - ODBC database connector
- [ ] `sqlalchemy>=2.0.0` - ORM
- Note: Project uses raw SQLite currently

### Logging
- [ ] `structlog>=23.0.0` - Structured logging
- Note: Project has custom logging in `src/common/logging_config.py`

## Questions to Answer
1. Are development tools (`black`, `ruff`, `mypy`) required for contributors?
2. Should we use `requests` instead of `urllib` for HTTP calls?
3. Is `pandas` needed for data analysis features?
4. Why was `sqlalchemy` considered but not used?

## Deliverables
- [ ] Document which packages are required vs optional
- [ ] Uncomment required packages
- [ ] Add comments explaining optional packages
- [ ] Consider splitting into `requirements-dev.txt` for dev-only tools

## Acceptance Criteria
- [ ] All needed dependencies are uncommented
- [ ] Optional dependencies are documented
- [ ] `make quality` commands work with dev dependencies
- [ ] README or docs explain how to install dev dependencies

## Priority
Medium - Affects developer experience

## Estimated Effort
Small - Investigation and documentation

## Created
2026-01-25 - Tech debt review
