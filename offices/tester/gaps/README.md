# Gaps

This folder contains small, focused issue documentation for developers.

## Purpose

Document specific issues that need developer attention:
- Schema gaps
- Missing components
- DDL deployment issues
- Bug fixes needed
- Configuration problems

## Key Principle

**One issue per file** - Keeps it manageable and actionable for developers.

## Naming Convention

`gap-[component]-[issue].md`

Examples:
- `gap-silver-layer-missing-column.md`
- `gap-api-timeout-config.md`
- `gap-gold-dimension-ddl.md`

## Gap Template

```markdown
# Gap: [Brief Title]

**Date**: YYYY-MM-DD
**Component**: [What needs fixing]
**For**: Developer

## Issue
[Brief, focused description - one issue only]

## Evidence
[Proof of the issue]

## Expected Behavior
[What should happen]

## Actual Behavior
[What is happening]
```

## Guidelines

1. **Keep it focused** - One problem per file
2. **Be actionable** - Developer should know exactly what to fix
3. **Include evidence** - Show the error, not just describe it
4. **Small files** - Target 1-2 KB; if larger, consider splitting
5. **Track resolution** - Note in `tester.md` when gap is resolved
