---
name: closeout-session-tuner
description: "Close out a Spool (Tuner SME) session. Updates sessions.md, knowledge.md if needed, auto memory, and commits. Run at end of every tuner session."
---

# Tuner Session Closeout

End-of-session ritual for Spool (Tuning SME). Updates all persistent knowledge so the next session starts clean.

---

## The Job

Perform these steps in order. Each step updates a specific file. Commit at the end.

---

## Step 1: Determine Session Number and Date

- Read `offices/tuner/sessions.md` to find the last session number
- Increment by 1 for this session
- Use today's date

---

## Step 2: Update Session Log (`offices/tuner/sessions.md`)

Add a new session entry with:

### Format
```
## Session N — YYYY-MM-DD

**Context**: [Brief context for what this session was about]

### What Happened
- Bullet points of significant actions, advice given, knowledge gained
- Note any inbox messages received and responses sent
- Note any safety advisories issued

### Key Decisions
- Tuning decisions made, thresholds set, modification recommendations given
- Include rationale for non-obvious decisions

### Current Vehicle State
- Any changes to the vehicle's modification level or status
- Current monitoring capability

### Open Items
- Unanswered questions from team
- Knowledge gaps identified
- Pending research
```

---

## Step 3: Update Knowledge Base (`offices/tuner/knowledge.md`) — If Needed

Only update if new tuning knowledge was learned this session:
- New safe operating ranges discovered or refined
- Vehicle modifications changed
- New DSMTuners or community data incorporated
- ECMLink parameters learned
- PID behavior validated against real vehicle data
- Correction to previously recorded data

**Do NOT update knowledge.md just to update it.** Only when there's genuinely new or corrected information.

If updated, also update the "Last major update" date at the top of knowledge.md.

---

## Step 4: Update Auto Memory (`MEMORY.md`)

Read `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` and update:

- **Current State** section: session number, key facts about vehicle/tuning status
- Only update if something meaningful changed (new mod installed, ECMLink status, vehicle state)

Keep it minimal. Auto memory is for cross-conversation context, not session details.

---

## Step 5: Summary to CIO

Print a brief closeout summary:
- Session number and what was accomplished (2-3 bullets)
- Any safety advisories issued this session
- Knowledge base updates (if any)
- Open items or questions for CIO

---

## What NOT to Do

- Do NOT run git commands (commits, staging, pushing — that's PM's job)
- Do NOT modify code files (Spool never writes code)
- Do NOT create backlog items or user stories (that's Marcus's job — send him a note instead)
- Do NOT modify specs/ files directly (send a note to the appropriate agent)
- Do NOT make up session accomplishments — only record what actually happened
- Do NOT update knowledge.md if nothing new was learned

$ARGUMENTS