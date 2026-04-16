---
name: closeout-ralph
description: "Use at end of a Ralph development session, or when the CIO says to save progress and prepare for next sprint."
---

# Ralph Session Closeout

End-of-session ritual for Ralph (autonomous dev agent). Saves all session knowledge so the next Ralph instance starts cold with full context.

---

## The Job

Perform these steps in order. Commit at the end.

---

## Step 1: Gather Session Facts

Before writing anything, collect:
- What was worked on this session (stories, sprints, design work, reviews)
- What was completed (stories passed, files committed, decisions made)
- What's blocked or unfinished
- Key learnings that would help the next Ralph instance
- Current test baseline (`pytest tests/ --collect-only | tail -1` for fast suite count)
- Current sprint state (read `offices/ralph/sprint.json` or `offices/ralph/stories.json`)
- Agent assignment state (read `offices/ralph/ralph_agents.json`)

---

## Step 2: Write Session Handoff (`offices/ralph/session-handoff.md`)

**Rewrite this file completely each closeout** (not append — always fresh). This is the #1 thing the next Ralph reads to get up to speed.

### Format

```markdown
# Ralph Session Handoff

**Last updated:** YYYY-MM-DD, Session N
**Branch:** <current branch>
**Last commit:** <hash> <message>

## Quick Context

### What's Done
- [Completed work: stories, features, design docs, inbox notes]
- [Include commit hashes for key commits]

### What's In Progress
- [Active stories, pending reviews, open questions]

### What's Blocked
- [BL- files filed, stories blocked on dependencies, CIO actions needed]

### Test Baseline
- Fast suite: NNNN passed, N skipped, N deselected
- Full suite: NNNN passed, N skipped

### Sprint State
- Sprint ID: [sprint ID from sprint.json]
- Stories: N passed / N pending / N blocked

### Agent State
- [Agent name]: [status] — [note]

## What's Next (priority order)
1. [Immediate next action]
2. [Second priority]
3. [Third priority]

## Key Learnings from This Session
- [Things the next Ralph needs to know that aren't in auto-memory or agent.md]
- [Gotchas, surprises, changed assumptions]
```

---

## Step 3: Update Progress Log (`offices/ralph/progress.txt`)

Append a session summary block:

```
## YYYY-MM-DD — Session N
Task: [Brief description of session work]

### What was accomplished:
- [Bullet points]

### Files committed:
- [List of files with commit hashes]

### Learnings for future iterations:
- [Transferable insights]
---
```

---

## Step 4: Update Knowledge

### Local knowledge (`offices/ralph/knowledge/`)

This is Ralph's primary knowledge store. Update these files:

- **`session-learnings.md`** — append any new gotchas, CIO feedback, or code patterns learned this session
- **`sprint-contract.md`** — update if any contract rules changed
- **`codebase-architecture.md`** — update if code structure changed (new packages, renamed modules)
- **`README.md`** — update the index if new knowledge files were created

Create new knowledge files if a topic is substantial enough to warrant its own file. Index them in the README.

### Shared auto-memory (`C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`)

Update ONLY the cross-agent facts that all agents need:
- **Current State** — session number, test baseline, sprint state, commits ahead of origin
- **Shared Memory Index** — only if a new SHARED memory file was created

**Do NOT put Ralph-specific detail in shared memory.** Other agents (Marcus, Spool, Tester) load MEMORY.md too. Keep it under 60 lines.

---

## Step 5: Update Agent State (`offices/ralph/ralph_agents.json`)

Update the agent entry that ran this session:
- Set `lastCheck` to today's date
- Update `note` with a one-line summary of what was done
- Set `status` to `unassigned` (session is over)

---

## Step 6: Commit

1. `git status` to see all modified files
2. Stage only the closeout files:
   - `offices/ralph/session-handoff.md`
   - `offices/ralph/progress.txt`
   - `offices/ralph/ralph_agents.json`
   - Any auto-memory files modified
   - Any inbox notes written during this session (if not already committed)
3. Commit with message:
   ```
   docs: Ralph session N closeout — [2-3 word summary]
   ```
4. Do NOT push to origin (CIO decides when to push)

---

## Step 7: Report to CIO

Print:
- Session number and 2-3 bullet accomplishments
- Commits made this session (hashes + one-liners)
- Commits ahead of origin
- Top 3 next actions for the next session
- Any unresolved blockers or questions

---

## What NOT to Do

- Do NOT push to origin (CIO decides when to push)
- Do NOT modify code files during closeout
- Do NOT delete or archive sprint.json / stories.json (Marcus decides lifecycle)
- Do NOT update specs/ files (that's a separate knowledge-update task)
- Do NOT make up accomplishments — only record what actually happened
- Do NOT create new backlog items (send a note to PM inbox instead)

$ARGUMENTS
