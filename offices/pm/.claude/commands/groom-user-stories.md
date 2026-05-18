---
name: groom-user-stories
description: "Convert PRDs to prd.json format for the Ralph autonomous agent system. Use when you have an existing PRD and need to convert it to Ralph's JSON format. Triggers on: convert this prd, turn this into ralph format, create prd.json from this, ralph json."
---

> **Workflow:** `/groom-product-requirements` (create PRD) → `/groom-user-stories` (convert to JSON in `offices/pm/prd.json`, PM initial sign-off) → DW Architect reviews → Tester (QA) reviews → `/resize-sprint` (PM final sizing, moves to `offices/ralph/sprint.json`) → `ralph.sh` (execute autonomously) → `/ralph-status` (check progress)

# Ralph PRD Converter

Converts existing PRDs to the prd.json format that Ralph uses for autonomous execution.

---

## Prerequisite

You need a PRD before using this skill. If you don't have one yet, run `/groom-product-requirements` first to create it.

---

## The Job

Take a PRD (markdown file or text) and convert it to `offices/pm/prd.json` in the PM workspace. This keeps the PRD separate from Ralph's active sprint until all sign-offs are complete.

**Important:** The file is written to `offices/pm/prd.json`, NOT `offices/ralph/sprint.json`. The `/resize-sprint` command handles the handoff to Ralph after all 4 sign-offs are recorded (PM initial, DW Architect, QA, PM final sizing).

---

## Output Format

```json
{
  "project": "[Project Name]",
  "branchName": "ralph/[feature-name-kebab-case]",
  "description": "[Feature description from PRD title/intro]",
  "signOffs": {
    "pmInitialReview": {
      "reviewer": "Mike (PM)",
      "reviewDate": "YYYY-MM-DD",
      "status": "APPROVED",
      "notes": "[Summary of PM prep work, pre-flight checks completed, scope decisions]"
    },
    "architectReview": {
      "reviewer": "Kunai (DW Architect)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    },
    "qaReview": {
      "reviewer": "Tester (QA)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    },
    "pmFinalSizing": {
      "reviewer": "Mike (PM)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    }
  },
  "userStories": [
    {
      "id": "US-001",
      "title": "[Story title]",
      "description": "As a [user], I want [feature] so that [benefit]",
      "acceptanceCriteria": [
        "Criterion 1",
        "Criterion 2",
        "Typecheck passes"
      ],
      "priority": "[high/medium/low]",
      "passes": false,
      "notes": "",
      "dependencies": []
    }
  ]
}
```

**Field notes:**
- `signOffs`: Tracks the 4 sequential review gates. PM populates `pmInitialReview` at creation time. The other 3 start as `PENDING` and are filled in by each reviewer in sequence: DW Architect → QA (Tester) → PM Final Sizing.
- `signOffs.*.status`: `"APPROVED"`, `"APPROVED with annotations"`, `"APPROVED with findings"`, or `"REJECTED"`. A REJECTED status blocks the workflow.
- `dependencies`: Array of story IDs this story depends on (empty `[]` if none)
- `passes`: Always `false` initially; Ralph updates this when story completes
- `notes`: Always empty `""` initially; Ralph logs issues here

---

## Story Size: The Number One Rule

**Each story must be completable in ONE Ralph iteration (one context window).**

Ralph spawns a fresh Claude instance per iteration with no memory of previous work. If a story is too big, the LLM runs out of context before finishing and produces broken code.

### How to Judge Story Size

Think about what fills the context window:
- **Codebase context**: Files Ralph needs to read to understand the task (~20-40K tokens for typical stories)
- **Story instructions**: The PRD, acceptance criteria, and conversation (~5K tokens)
- **Code to write**: New/modified code Ralph generates (~10-30K tokens)
- **Iteration buffer**: Back-and-forth for fixes, tests, verification (~20K tokens)

**Target:** Keep total under 100K tokens to leave headroom. In practice, this means:
- Touch 1-3 files max
- Add/modify under 500 lines of code
- Have 3-5 acceptance criteria

### Right-sized stories:
- Add a database column and migration
- Add a UI component to an existing page
- Update a server action with new logic
- Add a filter dropdown to a list

### Too big (split these):
- "Build the entire dashboard" - Split into: schema, queries, UI components, filters
- "Add authentication" - Split into: schema, middleware, login UI, session handling
- "Refactor the API" - Split into one story per endpoint or pattern

**Rule of thumb:** If you cannot describe the change in 2-3 sentences, it is too big.

---

## Story Ordering: Dependencies First

Stories execute in priority order. Earlier stories must not depend on later ones.

**Correct order:**
1. Schema/database changes (migrations)
2. Server actions / backend logic
3. UI components that use the backend
4. Dashboard/summary views that aggregate data

**Wrong order:**
1. UI component (depends on schema that does not exist yet)
2. Schema change

---

## Acceptance Criteria: Must Be Verifiable

Each criterion must be something Ralph can CHECK, not something vague.

### Good criteria (verifiable):
- "Add `status` column to tasks table with default 'pending'"
- "Filter dropdown has options: All, Active, Completed"
- "Clicking delete shows confirmation dialog"
- "Typecheck passes"
- "Tests pass"

### Bad criteria (vague):
- "Works correctly"
- "User can do X easily"
- "Good UX"
- "Handles edge cases"

### Always include as final criterion:
```
"Typecheck passes"
```

For stories with testable logic, also include:
```
"Tests pass"
```

### For stories that change UI, also include:
```
"Verify in browser"
```

Frontend stories are NOT complete until visually verified. Ralph will use browser automation to navigate to the page, interact with the UI, and confirm changes work.

---

## Conversion Rules

1. **Each user story becomes one JSON entry**
2. **IDs**: Sequential (US-001, US-002, etc.)
3. **Priority**: Based on dependency order, then document order
4. **All stories**: `passes: false` and empty `notes`
5. **branchName**: Derive from feature name, kebab-case, prefixed with `offices/ralph/`
6. **Always add**: "Typecheck passes" to every story's acceptance criteria

---

## Splitting Large PRDs

If a PRD has big features, split them:

**Original:**
> "Add user notification system"

**Split into:**
1. US-001: Add notifications table to database
2. US-002: Create notification service for sending notifications
3. US-003: Add notification bell icon to header
4. US-004: Create notification dropdown panel
5. US-005: Add mark-as-read functionality
6. US-006: Add notification preferences page

Each is one focused change that can be completed and verified independently.

---

## Example

**Input PRD:**
```markdown
# Task Status Feature

Add ability to mark tasks with different statuses.

## Requirements
- Toggle between pending/in-progress/done on task list
- Filter list by status
- Show status badge on each task
- Persist status in database
```

**Output prd.json:**
```json
{
  "project": "TaskApp",
  "branchName": "ralph/task-status",
  "description": "Task Status Feature - Track task progress with status indicators",
  "signOffs": {
    "pmInitialReview": {
      "reviewer": "Mike (PM)",
      "reviewDate": "2026-02-13",
      "status": "APPROVED",
      "notes": "4 stories, dependency-ordered. Pre-flight: no API changes, no DDL deployment needed."
    },
    "architectReview": {
      "reviewer": "Kunai (DW Architect)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    },
    "qaReview": {
      "reviewer": "Tester (QA)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    },
    "pmFinalSizing": {
      "reviewer": "Mike (PM)",
      "reviewDate": null,
      "status": "PENDING",
      "notes": ""
    }
  },
  "userStories": [
    {
      "id": "US-001",
      "title": "Add status field to tasks table",
      "description": "As a developer, I need to store task status in the database.",
      "acceptanceCriteria": [
        "Add status column: 'pending' | 'in_progress' | 'done' (default 'pending')",
        "Generate and run migration successfully",
        "Typecheck passes"
      ],
      "priority": "high",
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-002",
      "title": "Display status badge on task cards",
      "description": "As a user, I want to see task status at a glance.",
      "acceptanceCriteria": [
        "Each task card shows colored status badge",
        "Badge colors: gray=pending, blue=in_progress, green=done",
        "Typecheck passes",
        "Verify in browser"
      ],
      "priority": "medium",
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-003",
      "title": "Add status toggle to task list rows",
      "description": "As a user, I want to change task status directly from the list.",
      "acceptanceCriteria": [
        "Each row has status dropdown or toggle",
        "Changing status saves immediately",
        "UI updates without page refresh",
        "Typecheck passes",
        "Verify in browser"
      ],
      "priority": "low",
      "passes": false,
      "notes": ""
    },
    {
      "id": "US-004",
      "title": "Filter tasks by status",
      "description": "As a user, I want to filter the list to see only certain statuses.",
      "acceptanceCriteria": [
        "Filter dropdown: All | Pending | In Progress | Done",
        "Filter persists in URL params",
        "Typecheck passes",
        "Verify in browser"
      ],
      "priority": "medium",
      "passes": false,
      "notes": ""
    }
  ]
}
```

---

## Archiving Previous Runs

**Before writing a new offices/pm/prd.json, check if there is an existing one from a different feature:**

1. Read the current `offices/pm/prd.json` if it exists
2. Check if `branchName` differs from the new feature's branch name
3. If different and has content, confirm with the user before overwriting

**Note:** `offices/pm/prd.json` is the PM's grooming workspace. The active sprint lives in `offices/ralph/sprint.json` and is managed separately via `/sprint-turnover`.

---

## Checklist Before Saving

Before writing `offices/pm/prd.json`, verify:

- [ ] **Previous PRD checked** (if offices/pm/prd.json exists with different branchName, confirm overwrite)
- [ ] **signOffs section included** with `pmInitialReview` set to APPROVED and today's date; other 3 set to PENDING
- [ ] Each story is completable in one iteration (small enough)
- [ ] Stories are ordered by dependency (schema to backend to UI)
- [ ] Every story has "Typecheck passes" as criterion
- [ ] UI stories have "Verify in browser" as criterion
- [ ] Acceptance criteria are verifiable (not vague)
- [ ] No story depends on a later story
