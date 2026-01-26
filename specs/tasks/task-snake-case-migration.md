# Task: Migrate from camelCase to snake_case

## Summary
Refactor all Python code from camelCase naming convention to PEP 8 compliant snake_case for functions and variables.

## Background
The project currently uses camelCase for Python functions and variables (e.g., `loadConfigWithSecrets`, `parseArgs`). This deviates from Python's PEP 8 standard which recommends snake_case. This task will bring the codebase into alignment with Python community standards.

## Scope
- **Total LOC**: ~31,000 lines across ~120+ Python files
- **Approach**: Module by module refactoring
- **Classes**: Keep PascalCase (already PEP 8 compliant)
- **Constants**: Keep UPPER_SNAKE_CASE (already PEP 8 compliant)

## Affected Modules (in suggested order)
1. `src/common/` - Foundation utilities (start here, smallest impact)
2. `src/alert/` - Alert system
3. `src/profile/` - Profile management
4. `src/analysis/` - Data analysis
5. `src/calibration/` - Calibration tools
6. `src/power/` - Power management
7. `src/display/` - Display drivers
8. `src/ai/` - AI integration
9. `src/obd/` - Core OBD system (largest, do last)
10. `tests/` - Update all test files to match

## Migration Strategy
1. Pick one module
2. Rename all functions/variables to snake_case
3. Update all imports and references across the codebase
4. Run full test suite to verify
5. Update `specs/standards.md` after first module
6. Commit after each module
7. Repeat for next module

## Files to Update After Migration
- [ ] `specs/standards.md` - Update naming conventions section
- [ ] `CLAUDE.md` - Update naming conventions section
- [ ] `ralph/agent.md` - Update naming conventions in tips section

## Acceptance Criteria
- [ ] All Python functions use snake_case
- [ ] All Python variables use snake_case
- [ ] All tests pass after migration
- [ ] Documentation updated to reflect new standards
- [ ] No camelCase functions/variables remain (except external library calls)

## Risks
- Large refactoring effort - high risk of introducing bugs
- All developers must be aware of the change
- External code examples in docs need updating

## Priority
Medium - Important for code consistency but not blocking features

## Estimated Effort
Large - Multiple sessions, one module at a time

## Created
2026-01-25 - Tech debt review
