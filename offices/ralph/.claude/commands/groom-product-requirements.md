---
name: groom-product-requirements
description: "Generate a Product Requirements Document (PRD) for a new feature. Use when planning a feature, starting a new project, or when asked to create a PRD. Triggers on: create a prd, write prd for, plan this feature, requirements for, spec out."
---

> **Workflow:** `/groom-product-requirements` (create PRD) → `/groom-user-stories` (convert to JSON, PM initial sign-off) → DW Architect reviews → Tester (QA) reviews → `/resize-sprint` (PM final sizing, moves to `offices/ralph/sprint.json`) → `ralph.sh` (execute) → `/ralph-status` (check progress)

# PRD Generator

Create detailed Product Requirements Documents that are clear, actionable, and suitable for implementation.

---

## CRITICAL: Lessons Learned (Read First)

Based on retrospective analysis of 23 sprints (2026-02-03), these patterns caused 27% rework:

| Anti-Pattern | Consequence | Prevention |
|--------------|-------------|------------|
| Assuming API fields exist | 21/24 Entity fields were phantom | Validate API schema FIRST |
| Treating Bronze/Silver/Gold as independent | Fixing Bronze broke 6 Silver pipelines | Include all layers in same sprint |
| "Update DDL" without "Deploy DDL" | Code expected schema that didn't exist | Always include verification query |
| No downstream impact analysis | Changes cascaded for 5 days | List all consumers in story |
| Acceptance criteria as instructions | "Remove field X" passes but pipeline broken | Write testable outcomes |

**The #1 cause of "going backwards":** Stories marked complete when code compiles, but downstream pipelines broken.

---

## The Job

1. Receive a feature description from the user
2. Ask 3-5 essential clarifying questions (with lettered options)
3. **[DataWarehouse] Validate prerequisites** (see Pre-Flight Checklist below)
4. Generate a structured PRD based on answers
5. Save to `specs/prds/prd-[feature-name].md`

**Important:** Do NOT start implementing. Just create the PRD.

---

## Step 0: Pre-Flight Checklist (DataWarehouse Projects)

Before creating ANY PRD that touches Bronze/Silver/Gold pipelines:

### For New Entity Pipelines
- [ ] **API Schema Validated** - Query live 3E endpoint, document actual fields returned
- [ ] **Source-to-Target Mapping** - Document which API field → which Bronze column → which Silver column
- [ ] **Downstream Consumers** - List all Silver pipelines that will read from Bronze, all Gold that read from Silver
- [ ] **DDL Deployment Plan** - Who deploys? When? How verified?

### For Schema Changes (DDL, FIELDS constants)
- [ ] **Impact Analysis** - List ALL files that reference the changed table/column
- [ ] **Cascade Plan** - If changing Bronze, include Silver fixes in SAME sprint
- [ ] **Verification Queries** - Write the INFORMATION_SCHEMA query that proves deployment worked

### For Bug Fixes
- [ ] **Batch Check** - Are there other entities with the same bug? Fix ALL in one story.
- [ ] **Root Cause** - Why did this happen? Add prevention to acceptance criteria.

**If these aren't done, the PRD will create rework.**

---

## Step 1: Clarifying Questions

Ask only critical questions where the initial prompt is ambiguous. Focus on:

- **Problem/Goal:** What problem does this solve?
- **Core Functionality:** What are the key actions?
- **Scope/Boundaries:** What should it NOT do?
- **Success Criteria:** How do we know it's done?
- **[DataWarehouse] API Validation:** Has the API schema been verified against a live endpoint?

### Format Questions Like This:

```
1. What is the primary goal of this feature?
   A. Improve user onboarding experience
   B. Increase user retention
   C. Reduce support burden
   D. Other: [please specify]

2. Who is the target user?
   A. New users only
   B. Existing users only
   C. All users
   D. Admin users only

3. What is the scope?
   A. Minimal viable version
   B. Full-featured implementation
   C. Just the backend/API
   D. Just the UI
```

This lets users respond with "1A, 2C, 3B" for quick iteration.

---

## Step 2: PRD Structure

Generate the PRD with these sections:

### 1. Introduction/Overview
Brief description of the feature and the problem it solves.

### 2. Goals
Specific, measurable objectives (bullet list).

### 3. User Stories
Each story needs:
- **Title:** Short descriptive name
- **Description:** "As a [user], I want [feature] so that [benefit]"
- **Acceptance Criteria:** Verifiable checklist of what "done" means
- **[DataWarehouse] Downstream Impact:** What else might break?

Each story should be small enough to implement in one focused session.

**Format:**
```markdown
### US-001: [Title]
**Description:** As a [user], I want [feature] so that [benefit].

**Acceptance Criteria:**
- [ ] Specific verifiable OUTCOME (not implementation step)
- [ ] Another outcome
- [ ] ruff check passes on modified files
- [ ] **[DDL stories]** DDL deployed to database
- [ ] **[DDL stories]** Verified: `SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'X'`
- [ ] **[Pipeline stories]** Pipeline executes successfully against live database
- [ ] **[Schema change stories]** All downstream consumers listed and updated (or follow-up stories created in SAME sprint)
```

**CRITICAL - Acceptance Criteria Rules (from retrospective):**

| BAD (Implementation Instruction) | GOOD (Verifiable Outcome) |
|----------------------------------|---------------------------|
| "Remove Email from FIELDS list" | "Pipeline extracts all fields that exist in API. No phantom columns." |
| "Update DDL file" | "DDL deployed. INFORMATION_SCHEMA query returns expected columns." |
| "Fix the delta load" | "Delta load completes successfully. Records flow from Bronze to Silver." |

**Why this matters:** 27% of stories were rework because criteria described code changes, not outcomes. Developer did exactly what was asked, but pipeline still broken.

**For DataWarehouse stories, ALWAYS include:**
- For Bronze: "Pipeline executes against live 3E API without errors"
- For Silver: "Delta load completes. Records in Silver_X match Bronze_X transformations"
- For Gold: "Dimension/fact populated. FK lookups resolve (no -1 unknown keys for valid data)"
- For DDL: "Deployed AND verified via INFORMATION_SCHEMA"
- For any shared artifact change: List downstream consumers

**MANDATORY: Final Story in Every Sprint**
The LAST user story in every PRD must be a Documentation Sync story:
```markdown
### US-XXX: Sprint Documentation Sync
**Description:** As the PM, I need all spec documentation to reflect the current state of the system after this sprint's changes.

**Acceptance Criteria:**
- [ ] Review all files changed in this sprint
- [ ] If any data movement changed: `specs/source-to-target-mappings.md` updated
- [ ] If any transformation logic changed: `specs/transformation-rules.md` updated
- [ ] If any Bronze FIELDS changed: `specs/3e-api-field-mappings.md` updated
- [ ] If new pipelines/config/commands added: `CLAUDE.md` updated
- [ ] If new patterns established: `specs/dataWarehouseGuidelines.md` updated
- [ ] If new/renamed pipelines: `orchestration.json` verified
- [ ] All spec docs reflect current system state (no stale references)
```
This story runs LAST because it reviews the aggregate of all sprint changes.

### 4. Functional Requirements
Numbered list of specific functionalities:
- "FR-1: The system must allow users to..."
- "FR-2: When a user clicks X, the system must..."

Be explicit and unambiguous.

### 5. Non-Goals (Out of Scope)
What this feature will NOT include. Critical for managing scope.

### 6. Design Considerations (Optional)
- UI/UX requirements
- Link to mockups if available
- Relevant existing components to reuse

### 7. Technical Considerations (Optional)
- Known constraints or dependencies
- Integration points with existing systems
- Performance requirements

### 8. Success Metrics
How will success be measured?
- "Reduce time to complete X by 50%"
- "Increase conversion rate by 10%"

### 9. Open Questions
Remaining questions or areas needing clarification.

---

## Writing for Junior Developers

The PRD reader may be a junior developer or AI agent. Therefore:

- Be explicit and unambiguous
- Avoid jargon or explain it
- Provide enough detail to understand purpose and core logic
- Number requirements for easy reference
- Use concrete examples where helpful

---

## Output

- **Format:** Markdown (`.md`)
- **Location:** `specs/prds/`
- **Filename:** `prd-[feature-name].md` (kebab-case)

---

## Example PRD

```markdown
# PRD: Task Priority System

## Introduction

Add priority levels to tasks so users can focus on what matters most. Tasks can be marked as high, medium, or low priority, with visual indicators and filtering to help users manage their workload effectively.

## Goals

- Allow assigning priority (high/medium/low) to any task
- Provide clear visual differentiation between priority levels
- Enable filtering and sorting by priority
- Default new tasks to medium priority

## User Stories

### US-001: Add priority field to database
**Description:** As a developer, I need to store task priority so it persists across sessions.

**Acceptance Criteria:**
- [ ] Add priority column to tasks table: 'high' | 'medium' | 'low' (default 'medium')
- [ ] Generate and run migration successfully
- [ ] Typecheck passes

### US-002: Display priority indicator on task cards
**Description:** As a user, I want to see task priority at a glance so I know what needs attention first.

**Acceptance Criteria:**
- [ ] Each task card shows colored priority badge (red=high, yellow=medium, gray=low)
- [ ] Priority visible without hovering or clicking
- [ ] Typecheck passes
- [ ] Verify in browser

### US-003: Add priority selector to task edit
**Description:** As a user, I want to change a task's priority when editing it.

**Acceptance Criteria:**
- [ ] Priority dropdown in task edit modal
- [ ] Shows current priority as selected
- [ ] Saves immediately on selection change
- [ ] Typecheck passes
- [ ] Verify in browser

### US-004: Filter tasks by priority
**Description:** As a user, I want to filter the task list to see only high-priority items when I'm focused.

**Acceptance Criteria:**
- [ ] Filter dropdown with options: All | High | Medium | Low
- [ ] Filter persists in URL params
- [ ] Empty state message when no tasks match filter
- [ ] Typecheck passes
- [ ] Verify in browser

## Functional Requirements

- FR-1: Add `priority` field to tasks table ('high' | 'medium' | 'low', default 'medium')
- FR-2: Display colored priority badge on each task card
- FR-3: Include priority selector in task edit modal
- FR-4: Add priority filter dropdown to task list header
- FR-5: Sort by priority within each status column (high to medium to low)

## Non-Goals

- No priority-based notifications or reminders
- No automatic priority assignment based on due date
- No priority inheritance for subtasks

## Technical Considerations

- Reuse existing badge component with color variants
- Filter state managed via URL search params
- Priority stored in database, not computed

## Success Metrics

- Users can change priority in under 2 clicks
- High-priority tasks immediately visible at top of lists
- No regression in task list performance

## Open Questions

- Should priority affect task ordering within a column?
- Should we add keyboard shortcuts for priority changes?
```

---

## Checklist

Before saving the PRD:

### Standard Checks
- [ ] Asked clarifying questions with lettered options
- [ ] Incorporated user's answers
- [ ] User stories are small and specific
- [ ] Functional requirements are numbered and unambiguous
- [ ] Non-goals section defines clear boundaries
- [ ] Saved to `specs/prds/prd-[feature-name].md`

### DataWarehouse-Specific Checks (MANDATORY)
- [ ] **API Validation:** For new entities, has schema been validated against live endpoint?
- [ ] **Outcome-Based Criteria:** Acceptance criteria describe outcomes, not implementation steps
- [ ] **DDL = Deploy + Verify:** Every DDL story includes deployment AND INFORMATION_SCHEMA verification
- [ ] **Downstream Impact:** For schema changes, all downstream consumers listed
- [ ] **One Entity, One Sprint:** If touching Bronze, Silver and Gold fixes included in SAME PRD
- [ ] **Batch Similar Fixes:** If 3+ entities have same issue, ONE story to fix all (not N stories)
- [ ] **No Investigation-Only Stories:** Investigation stories must include the fix, not just findings
- [ ] **Final Story = Documentation Sync:** Last user story reviews all sprint changes and updates specs (source-to-target-mappings.md, transformation-rules.md, 3e-api-field-mappings.md, CLAUDE.md, dataWarehouseGuidelines.md) if any data movement or transformation logic changed

### Anti-Pattern Review (Check NONE apply)
- [ ] No stories that just "update a file" without verifying the change works
- [ ] No stories that change Bronze without addressing Silver impact
- [ ] No stories that write DDL without deploying it
- [ ] No stories with vague criteria like "works correctly" or "handles edge cases"
- [ ] No duplicate stories (same fix applied to multiple entities separately when batchable)

---

## Next Step

Once the PRD is complete, run `/groom-user-stories` to convert it to `offices/pm/prd.json` (this also records the PM initial sign-off). The PRD then goes through 3 more sign-offs in sequence before Ralph can execute:

1. **DW Architect Review** (Kunai) -- Drop the PRD in the architect's inbox for technical review and annotations
2. **QA Review** (Tester) -- Drop the PRD in the tester's inbox for testability review
3. **PM Final Sizing** (`/resize-sprint`) -- Sizing validation, then move to `offices/ralph/sprint.json`
