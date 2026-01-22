---
name: ralph-status
description: "Check the progress of a Ralph autonomous agent run. Use when you want to see which user stories have passed, failed, or are pending. Triggers on: ralph status, check ralph progress, how is ralph doing, ralph report."
---

> **Workflow:** `/prd` (create PRD) → `/ralph` (convert to JSON) → `ralph.sh` (execute autonomously) → `/ralph-status` (check progress)

# Ralph Status Checker

Shows the current progress of a Ralph autonomous execution run.

---

## The Job

1. Read `ralph/prd.json` to get the user stories
2. Read `ralph/progress.txt` for execution logs
3. Generate a summary report

---

## Output Format

Generate a status report like this:

```
## Ralph Progress Report

**Project:** [project name]
**Branch:** [branchName]
**Description:** [description]

### Story Status

| ID | Title | Status | Notes |
|----|-------|--------|-------|
| US-001 | [title] | ✅ Passed | |
| US-002 | [title] | ❌ Failed | [notes from prd.json] |
| US-003 | [title] | ⏳ Pending | |

### Summary

- **Passed:** X of Y stories
- **Failed:** X stories
- **Pending:** X stories

### Recent Activity

[Last 10-20 lines from progress.txt, if available]
```

---

## Status Icons

- ✅ **Passed**: Story completed successfully (`passes: true`)
- ❌ **Failed**: Story attempted but failed (`passes: false` with notes)
- ⏳ **Pending**: Story not yet attempted (`passes: false`, no notes)

---

## What to Check

1. **ralph/prd.json** - Contains:
   - `project`, `branchName`, `description`
   - `userStories[]` with `id`, `title`, `passes`, `notes`

2. **ralph/progress.txt** - Contains:
   - Timestamped execution logs
   - Which stories were attempted
   - Error messages and outcomes

---

## If Files Don't Exist

- **No prd.json**: Report "No Ralph run configured. Run `/ralph` to set up a PRD first."
- **No progress.txt**: Report "Ralph has not started yet. Run `ralph.sh` to begin execution."

---

## Example Report

```
## Ralph Progress Report

**Project:** TaskApp
**Branch:** ralph/task-status
**Description:** Task Status Feature - Track task progress with status indicators

### Story Status

| ID | Title | Status | Notes |
|----|-------|--------|-------|
| US-001 | Add status field to tasks table | ✅ Passed | |
| US-002 | Display status badge on task cards | ✅ Passed | |
| US-003 | Add status toggle to task list rows | ❌ Failed | Typecheck failed: missing import |
| US-004 | Filter tasks by status | ⏳ Pending | |

### Summary

- **Passed:** 2 of 4 stories
- **Failed:** 1 story
- **Pending:** 1 story

### Recent Activity

[2024-01-15 14:32] Starting US-003: Add status toggle to task list rows
[2024-01-15 14:35] Running typecheck...
[2024-01-15 14:35] ERROR: src/components/TaskRow.tsx - Cannot find module './StatusToggle'
[2024-01-15 14:36] US-003 failed: Typecheck failed
```

---

## Checklist

- [ ] Read `ralph/prd.json` for story definitions
- [ ] Read `ralph/progress.txt` for execution logs
- [ ] Calculate pass/fail/pending counts
- [ ] Show clear status table with icons
- [ ] Include recent activity from logs
- [ ] Handle missing files gracefully
