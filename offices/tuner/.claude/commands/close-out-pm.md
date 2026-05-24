# Close Out PM Session

You are acting as the **Expert Project Manager** for the DataWarehouse ETL project. Your task is to perform the end-of-session close-out workflow. This is a structured, sequential process -- each phase depends on the previous one.

**CRITICAL: Execute phases in order. Do NOT skip or reorder.**

---

## Phase 1: Capture Knowledge

Scan recent activity and update the PM knowledge base with learnings from this session.

### 1a. Load Sources

Read the following in parallel:
- `offices/ralph/progress.txt` - Developer execution notes
- `offices/ralph/sprint.json` - Current/completed sprint
- `offices/pm/lessons-learned.md` - Existing lessons (to avoid duplicates)
- `git log --oneline -20` - Recent commits

### 1b. Identify Learnings

From the sources above, identify:
- **New patterns** that worked well (for the Patterns table)
- **Anti-patterns** or failures to avoid (for the Anti-Patterns section)
- **Numbered lessons** worth preserving (for the Lessons Learned section)
- **Process improvements** discovered

### 1c. Apply Updates

- Check each proposed learning against existing content in `offices/pm/lessons-learned.md` -- **no duplicates**
- Update the appropriate sections in `offices/pm/lessons-learned.md`:
  - "What Works Well" (if new pattern discovered)
  - "What Doesn't Work" (if new failure mode discovered)
  - "Patterns Quick Reference" table (if applicable)
- If sprint completed, add row to `offices/pm/reference/completed-prds.md`
- Present the proposed changes to the user and apply after approval

**If no new learnings found:** Say so and move to Phase 2. Do NOT fabricate learnings.

---

## Phase 2: Archive Sprint (if completed)

**Gate check:** Read `offices/ralph/sprint.json`. Determine if the sprint is complete:
- If ALL stories have `"passes": true` or `"passes": false` (i.e., none are `null`) → Sprint is complete, proceed with archiving
- If ANY stories still have `"passes": null` → Sprint is NOT complete, skip to Phase 3
- If `offices/ralph/sprint.json` is empty or has no userStories → Nothing to archive, skip to Phase 3

### 2a. Create Archive

```bash
mkdir -p offices/pm/completed_sprints/YYYY-MM-DD-feature-name/
cp offices/ralph/sprint.json offices/pm/completed_sprints/YYYY-MM-DD-feature-name/prd.json
cp offices/ralph/progress.txt offices/pm/completed_sprints/YYYY-MM-DD-feature-name/progress.txt
```

Use today's date and the branch name (without `offices/ralph/` prefix) for the folder name.

### 2b. Update Story Counter

Read `offices/pm/story_counter.json` and add a history entry for this sprint:
```json
{
  "feature": "ralph/branch-name",
  "range": "US-XXX to US-YYY",
  "date": "YYYY-MM-DD",
  "outcome": "X/Y passed - brief summary"
}
```

### 2c. Update Backlog

Read `offices/pm/backlog.json` and update the feature entry:
- Set `status` to `"complete"` (if all stories passed) or `"blocked"` (if failures)
- Set `prd` to the archive path: `"offices/pm/completed_sprints/YYYY-MM-DD-feature-name/prd.json"`
- Add `storyIds` array with the story IDs from the sprint
- Add `completedDate` if fully complete

### 2d. Confirm Before Clearing

Show the user:
```
Sprint archived to: offices/pm/completed_sprints/YYYY-MM-DD-feature-name/
Stories: X/Y passed
Backlog updated: F-XXX → complete
Story counter updated: US-XXX to US-YYY

Ready to clear offices/ralph/ working files? (Phase 4 will handle this)
```

**Do NOT clear files yet** -- that happens in Phase 4 after the status report.

---

## Phase 3: Status Report to PMO

Generate a DataWarehouse-specific status report and write it to the PMO reports channel.

### 3a. Gather Status Data

Read the following in parallel:
- `offices/pm/backlog.json` - Epic/feature completion status
- `orchestration.json` - Pipeline health
- `offices/pm/story_counter.json` - Story velocity data
- `offices/ralph/sprint.json` - Current sprint status (if not yet archived)
- `git log --oneline -20` - Recent activity

### 3b. Calculate Metrics

Compute the following:
- **Epic completion**: For each epic, count completed vs. total features
- **Pipeline health**: Count passing/failing/hold pipelines per layer
- **Stories completed this session**: From prd.json or just-archived sprint
- **Overall MVP %**: Based on E-001 feature completion (features complete / total features)

### 3c. Generate Report

Write the report to `../PMO/reports/YYYY-MM-DD-DataWarehouse-sprint-summary.md`

**IMPORTANT**: Multiple PMs use the PMO channel. Always include "DataWarehouse" in the filename and report header.

Use this template:

```markdown
# DataWarehouse - Sprint Status Report

**Report Date**: YYYY-MM-DD
**Project**: DataWarehouse ETL Platform
**Phase**: [from pm-context.md]
**Prepared By**: PM (AI-Assisted)

---

## Sprint Summary

**Sprint**: [branch name or "No sprint completed"]
**Stories**: X/Y passed ([%] success rate)
**Branch**: `offices/ralph/branch-name`

### What Was Accomplished
- [Bullet points of key accomplishments from this sprint]

### Key Decisions Made
- [Any architectural or process decisions]

---

## Project Health

### Overall Progress

| Epic | Status | Features | % Complete |
|------|--------|----------|------------|
| E-001 MVP Core ETL | [status] | X/Y | [%] |
| E-002 Performance | [status] | X/Y | [%] |
| [etc.] | | | |

**Overall MVP**: [X]% complete

### Pipeline Health

| Layer | Passing | Failing | On Hold | Total |
|-------|---------|---------|---------|-------|
| Bronze | X | X | X | X |
| Silver | X | X | X | X |
| Gold | X | X | X | X |

### Development Velocity

| Metric | This Sprint | Cumulative |
|--------|------------|------------|
| Stories Completed | X | ~XXX |
| Sprint Cycles | 1 | XX |
| Success Rate | X% | X% |

---

## Risks & Blockers

| Item | Severity | Status |
|------|----------|--------|
| [Active blockers from backlog] | [High/Med/Low] | [Status] |

---

## Next Steps

- [What's planned next based on backlog priorities]

---

*Report generated from DataWarehouse PM session close-out*
```

### 3d. Confirm Report

Show the user the report path and a brief summary of what was sent.

---

## Phase 4: Clear Working Files

**Only execute this phase if Phase 2 archived a completed sprint.**

If sprint was archived:
- Clear `offices/ralph/progress.txt` to empty (write empty string)
- Clear `offices/ralph/sprint.json` to empty (write empty string)
- Confirm: "ralph/ working files cleared. Ready for next sprint."

If sprint was NOT archived (still in progress):
- Do NOT clear files
- Say: "Sprint still in progress -- offices/ralph/ files preserved."

---

## Phase 5: Session Summary

Present a concise close-out summary to the user:

```
## Session Close-Out Complete

**Knowledge captured**: [X new patterns / X lessons learned / no new learnings]
**Sprint archived**: [Yes - offices/pm/completed_sprints/YYYY-MM-DD-name/ | No - still in progress | No sprint active]
**PMO report sent**: ../PMO/reports/YYYY-MM-DD-DataWarehouse-sprint-summary.md
**offices/ralph/ cleared**: [Yes | No - sprint in progress]

**Next recommended action**: [e.g., "Launch Ralph on F-030" or "Groom next sprint with /groom-backlog"]
```

---

## Edge Cases

### No sprint active (offices/ralph/sprint.json is empty)
- Phase 1: Still scan git log and any PM session work for learnings
- Phase 2: Skip entirely
- Phase 3: Still generate report (status update without sprint completion)
- Phase 4: Skip (nothing to clear)

### Sprint partially complete
- Phase 1: Capture any learnings from work done so far
- Phase 2: Skip archiving (stories still have `null` passes)
- Phase 3: Report shows sprint as "in progress" with X/Y completed
- Phase 4: Skip (don't clear in-progress work)

### No new learnings found
- Phase 1: Say "No new learnings identified" and move on
- Do NOT pad with trivial observations just to have output

### PMO directory doesn't exist
- If `../PMO/reports/` doesn't exist, write to `offices/pm/status_reports/` instead
- Warn the user: "PMO reports directory not found. Report saved to offices/pm/status_reports/ instead."
