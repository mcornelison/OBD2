---
name: closeout-session-pm
description: "Close out a PM session. Updates projectManager.md (session handoff, Quick Context, next actions), auto memory, and commits. Run at end of every PM session."
---

# PM Session Closeout

End-of-session ritual for Marcus (PM). Updates all persistent knowledge so the next session starts clean.

---

## The Job

Perform these steps in order. Each step updates a specific file. Commit at the end.

---

## Step 1: Determine Session Number and Date

- Read current `pm/projectManager.md` header to find the last session number
- Increment by 1 for this session
- Use today's date

---

## Step 2: Update Quick Context (`pm/projectManager.md`)

Read the "Quick Context for New Sessions" section and update:

### Current State
- **What's Done**: Summarize completed work (modules, tests passing, completed B-items, infrastructure changes)
- **What's In Progress**: Active sprint stories, pending CIO actions
- **Active Sprint PRDs**: List PRDs in current sprint with story counts
- **Other Active PRDs**: List remaining active PRDs
- **Git**: Branch, commits ahead of origin
- **Agents**: Current assignment status
- **Story Counter**: Current nextId from `pm/story_counter.json`

### Immediate Next Actions
- Move completed items to ~~strikethrough~~ with DONE and session number
- Add new next actions discovered this session
- Keep the list prioritized (most urgent first)
- CIO hardware/physical actions should note any timeline context

---

## Step 3: Update Session Handoff (`pm/projectManager.md`)

Rename the existing "Last Session Summary" to "Previous Session Summary" and create a new "Last Session Summary" with:

### Format
```
### Last Session Summary (YYYY-MM-DD, Session N - Short Title)

**What was accomplished:**
- Bullet points of every significant action taken this session
- Include commit hashes for key commits
- Include file counts/stats where meaningful

**Key decisions:**
- Any decisions made, with rationale if non-obvious

**What's next:**
1. Numbered priority list of immediate next actions
2. Include both PM actions and CIO actions

**Unfinished work:**
- Items started but not completed
- Items that are blocked and why
- Commits not pushed to origin
```

---

## Step 4: Update `pm/projectManager.md` Header

- Update `**Last Updated**:` line with today's date and session number
- Update `**Current Phase**:` if the phase description has changed

---

## Step 5: Update Auto Memory (`MEMORY.md`)

Read `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` and update:

- **Current State** section: session number, date, key facts about where the project stands
- **Key Infrastructure** section: only if hardware changed (new GPU, new server, etc.)
- **Memory Index** section: add pointers to any new memory files created this session

If a new memory file was created this session, verify it's indexed in MEMORY.md.

---

## Step 6: Verify and Commit

1. Run `git status` to see all modified files
2. Run `git diff --stat` to confirm the changes look right
3. Stage only the PM/memory files modified in this closeout:
   - `pm/projectManager.md`
   - `pm/backlog.json` (if modified)
   - `pm/story_counter.json` (if modified)
   - Any new PRDs or backlog items created
   - Memory files (if modified outside the commit cycle)
4. Commit with message format:
   ```
   docs: Session N closeout — [2-3 word summary]
   ```
5. Report final git status (commits ahead of origin)

---

## Step 7: Summary to CIO

Print a brief closeout summary:
- Session number and what was accomplished (2-3 bullets)
- Commits made this session (hashes + one-liners)
- Commits ahead of origin (remind if push needed)
- Top 3 next actions for the next session

---

## What NOT to Do

- Do NOT push to origin (CIO decides when to push)
- Do NOT modify code files (Marcus never writes code)
- Do NOT update specs/ files (that's a separate knowledge-update task)
- Do NOT create new backlog items without CIO direction
- Do NOT make up session accomplishments — only record what actually happened

$ARGUMENTS
