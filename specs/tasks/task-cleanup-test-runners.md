# Task: Clean Up Test Runner Scripts

## Summary
Evaluate and clean up the 40+ `run_tests_*.py` files in the tests directory.

## Background
The tests directory contains many `run_tests_*.py` scripts alongside the standard pytest test files. It's unclear if these are:
- Legacy scripts from before pytest was adopted
- Module-specific test runners
- CI/CD artifacts
- Redundant with `pytest` command

## Current State
- 13 core test modules (`test_*.py`)
- 40+ test runner scripts (`run_tests_*.py`)
- pytest configuration in `pyproject.toml`
- Standard `pytest tests/` command works

## Investigation Tasks
- [ ] List all `run_tests_*.py` files
- [ ] Determine purpose of each (read contents)
- [ ] Check if any are referenced in CI/CD or Makefile
- [ ] Identify which can be safely deleted
- [ ] Identify any that provide unique functionality

## Likely Outcomes
1. **Delete most**: If they just call pytest with specific arguments
2. **Keep some**: If they provide complex setup or unique functionality
3. **Consolidate**: Merge useful functionality into conftest.py or Makefile

## Cleanup Plan
1. Document what each script does
2. Migrate useful logic to:
   - `pytest.ini` / `pyproject.toml` for pytest config
   - `conftest.py` for fixtures and setup
   - `Makefile` for common test commands
3. Delete redundant scripts
4. Update documentation

## Acceptance Criteria
- [ ] All test runners evaluated and documented
- [ ] Redundant scripts deleted
- [ ] Useful functionality preserved elsewhere
- [ ] `pytest tests/` still works
- [ ] Test coverage unchanged
- [ ] Documentation updated if needed

## Priority
Low - Cleanup task

## Estimated Effort
Small - Investigation and deletion

## Created
2026-01-25 - Tech debt review
