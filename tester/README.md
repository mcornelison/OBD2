# Tester Workspace

This folder is the tester agent's workspace for end-to-end validation.

## Contents

| File/Folder | Purpose |
|-------------|---------|
| `tester.md` | Tester instructions + living knowledge base |
| `findings/` | Evidence-based findings and analysis |
| `gaps/` | Developer gap documentation |
| `test-reports/` | Formal test execution reports |

## Role

The tester focuses on **BIG PICTURE validation**:
- End-to-end data/workflow movement
- Documentation accuracy
- Business rule compliance
- Acceptance criteria verification

**NOT responsible for**: Unit tests, code fixes, architecture decisions

## Workflow

1. **Start of session**: Run `/init-tester` (reads `tester.md`)
2. **During session**: Run tests, document findings
3. **End of session**: Update `tester.md`, create reports

## Communication

| To | Folder | Content |
|----|--------|---------|
| PM | `../pm/blockers/` | Critical issues |
| PM | `../pm/issues/` | Bugs found |
| PM | `../pm/tech_debt/` | Technical debt |
| Developer | `gaps/` | Specific issues to fix |

## Key Principle

**One issue per gap file** - Keep it focused and actionable for developers.

## Evidence-Based

All findings must include proof:
- SQL queries and results
- Error logs
- Screenshots
- Record counts
