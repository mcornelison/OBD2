---
name: init-ralph
description: "Use at start of a Ralph development session to load project context, session handoff, and agent instructions. Loads minimum context first, then on-demand."
---

# Ralph Session Startup

Mirrors `/closeout-ralph`. Loads what the last session saved so Ralph starts cold with full context and minimum token cost.

---

## The Job

Load context in priority order. Stop after Step 4 and report status — everything else loads on-demand when the CIO gives direction.

---

## Step 1: Read Project Context

Read `offices/ralph/CLAUDE.md` for architecture awareness (3 tiers, developer rules, deployment context).

Then read the root `CLAUDE.md` for project-wide context (commands, testing, coding standards, specs system, project management structure).

---

## Step 2: Read Session Handoff

Read `offices/ralph/session-handoff.md` (if it exists). This is the quick-context snapshot from the last `/closeout-ralph` — it tells you where things stand: what's done, what's next, test baseline, sprint state, blockers.

If the file does not exist, this is a first session or the file was never created. Note this and continue.

---

## Step 3: Read Agent Instructions

Read `offices/ralph/agent.md` for:
- Core workflow (task selection → execution → completion)
- Coding standards and golden code patterns
- The 5 Global Refusal Rules (if present — added by sprint contract)
- Operational tips and tricks
- Git branching strategy
- PM communication protocol

---

## Step 4: Check Inbox and Sprint State

**Inbox** — scan `offices/ralph/inbox/` for any unread notes from teammates (Spool, Marcus, Tester). Read any that exist. These may contain pre-sprint context, review feedback, or architectural guidance.

**Sprint state** — read the active sprint file:
- `offices/ralph/sprint.json` (new contract format), OR
- `offices/ralph/stories.json` (legacy format)

Whichever exists. Report: how many stories total, how many passed, how many pending, how many blocked.

**Agent state** — read `offices/ralph/ralph_agents.json`. Report which agents are assigned/unassigned.

---

## Step 5: Report Status to CIO

Print a concise status:
- Session handoff loaded (yes/no, and the quick-context summary if yes)
- Sprint: N stories (N passed / N pending / N blocked)
- Inbox: N notes (list senders + topics)
- Agents: assignment status
- Test baseline from handoff (or "unknown — run tests to establish")
- Top 3 next actions from handoff (or "no handoff — awaiting direction")

Then wait for direction. Do NOT start working on stories until the CIO says go.

---

## On-Demand Loading (after CIO gives direction)

Once the CIO tells Ralph what to work on, load ONLY what's needed:

- **Sprint work**: read the specific story from sprint.json, then read ONLY the files listed in `scope.filesToRead` for that story. Do NOT explore beyond the manifest.
- **Specific file work**: read the file(s) the CIO points you at.
- **Review work**: read the artifact to review.
- **Design/brainstorming**: load relevant specs or PRDs as the CIO directs.

**The One Source of Truth rule**: during story execution, Ralph reads ONLY `scope.filesToRead`. Do not speculatively read `specs/`, `progress.txt`, memory files, or other stories. The sprint contract IS the context.

---

## What NOT to Do

- Do NOT read every file in the repo to "get up to speed" — load minimum, expand on demand
- Do NOT start executing stories without CIO direction
- Do NOT push to origin without CIO permission
- Do NOT modify the session-handoff.md at startup (that's closeout's job)

$ARGUMENTS
