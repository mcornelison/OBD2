# Test Reports

This folder contains formal test execution reports.

## Purpose

Store structured test run results:
- Layer/component test results
- Full system/pipeline tests
- Regression test suites
- Performance test results

## Naming Convention

`YYYY-MM-DD-[test-name]-test.md`

Examples:
- `2026-02-04-full-pipeline-test.md`
- `2026-02-04-silver-layer-test.md`
- `2026-02-04-api-integration-test.md`

## Test Report Template

```markdown
# Test Report: [Test Name]

**Date**: YYYY-MM-DD
**Duration**: [X seconds/minutes]
**Result**: PASS / FAIL

## Summary

| Component | Status | Notes |
|-----------|--------|-------|
| [Component 1] | PASS/FAIL | [Brief note] |
| [Component 2] | PASS/FAIL | [Brief note] |

## Test Details

### [Test 1 Name]
- **Status**: PASS/FAIL
- **Details**: [What was tested and result]

### [Test 2 Name]
- **Status**: PASS/FAIL
- **Details**: [What was tested and result]

## Metrics

- Total tests: X
- Passed: X
- Failed: X
- Duration: X seconds

## Issues Found

[List any issues discovered, with references to finding/gap files]

## Recommendations

[Any follow-up actions needed]
```

## Guidelines

1. **Be consistent** - Use the same format for all reports
2. **Include metrics** - Pass/fail counts, duration, record counts
3. **Reference issues** - Link to finding/gap files for failures
4. **Track trends** - Compare against previous test runs
5. **Note environment** - Which environment was tested (dev/stage/prod)
