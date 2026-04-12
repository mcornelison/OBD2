# Findings

This folder contains evidence-based findings from test runs.

## Purpose

Store detailed analysis with evidence:
- Data audits and analysis
- Compliance checks
- Root cause investigations
- Solution proposals

## Naming Convention

`YYYY-MM-DD-description.md`

Examples:
- `2026-02-04-api-response-analysis.md`
- `2026-02-04-data-quality-audit.md`
- `2026-02-04-transformation-rule-compliance.md`

## Finding Template

```markdown
# Finding: [Brief Title]

**Date**: YYYY-MM-DD
**Severity**: Critical / High / Medium / Low
**Layer/Component**: [What part of system]

## Summary
[One paragraph describing what was found]

## Evidence
[SQL queries, logs, screenshots, error messages]

## Impact
[What does this affect? What doesn't work?]

## Root Cause (if known)
[Why is this happening?]

## Recommended Action
[What should be done to fix this?]
```

## Guidelines

1. **Include evidence** - Findings without proof are just opinions
2. **Be specific** - Reference exact files, line numbers, query results
3. **Assess impact** - What breaks if this isn't fixed?
4. **Propose solutions** - If you know the fix, suggest it
5. **Link to gaps** - If a developer task is needed, create a gap file too
