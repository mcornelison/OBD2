# Issue: New Coding Rules to Add to specs/standards.md

**Reported by**: Ralph (Agent 1)
**Date**: 2026-01-29
**Priority**: High
**Type**: Standards Update Request

---

## Summary

Three new coding rules have been approved by the project lead and need to be added to `specs/standards.md`. Since `specs/` is read-only for Ralph, requesting PM to incorporate these.

## Proposed Rules

### Rule 1: Write Reusable Code
All code should be written with reusability in mind. Extract common logic into shared utilities, use parameterized functions instead of hardcoded behavior, and design interfaces that can serve multiple callers. Before writing new code, check if existing utilities in `src/common/` or domain-specific helpers already provide the needed functionality.

### Rule 2: Keep Files Small and Easy to Work With
Files should remain focused and manageable. When a file grows beyond a reasonable size (guideline: ~300 lines for implementation files, ~500 lines for test files), consider splitting it into smaller, well-named modules. Large files are harder to navigate, review, and test.

### Rule 3: Organize Files by Functionality and Module
Follow both functional and module-based organization. Group related functionality into packages/subpackages (e.g., `src/obd/ai/`, `src/backup/`). Within each package, follow the established structure:
- `types.py` - Enums, dataclasses, constants (zero project dependencies)
- `exceptions.py` - Custom exceptions
- Core implementation modules
- `helpers.py` - Factory functions, config utilities
- `__init__.py` - Public API exports

## Suggested Location in standards.md

Add as a new section (e.g., "Section 12: Code Organization Rules") or append to Section 4 (Python Coding Standards).

---

*Submitted by Ralph via pm/issues/ per read-only specs/ protocol.*
