# Task PRDs

This folder contains Product Requirements Documents (PRDs) for features and tasks.

## Naming Convention

Files follow the pattern: `prd-[feature-name].md`

Examples:
- `prd-user-authentication.md`
- `prd-dashboard-widgets.md`
- `prd-api-rate-limiting.md`

## Creating PRDs

Use the PRD skill to generate new PRDs:

1. Describe the feature to Claude
2. Answer clarifying questions
3. PRD is saved here automatically

See `specs/prd_skill.md` for detailed instructions.

## Converting to Ralph Format

Once a PRD is complete:

1. Use the Ralph skill to convert to JSON
2. Output goes to `specs/user-stories/[feature]-prd.json`
3. Copy to `ralph/prd.json` when ready to execute

See `specs/ralph_skill.md` for detailed instructions.

## PRD Template

```markdown
# PRD: [Feature Name]

## Introduction
Brief description of the feature and the problem it solves.

## Goals
- Goal 1
- Goal 2

## User Stories

### US-001: [Title]
**Description:** As a [user], I want [feature] so that [benefit].

**Acceptance Criteria:**
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Typecheck passes

## Functional Requirements
- FR-1: The system must...
- FR-2: When X happens...

## Non-Goals
- What this feature will NOT do

## Technical Considerations
- Dependencies
- Constraints
- Integration points

## Success Metrics
- How to measure success

## Open Questions
- Remaining questions
```
