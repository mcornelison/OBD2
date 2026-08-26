---
name: init-ralph
description: "Use at start of a Ralph development session to load project context, session handoff, and agent instructions. Loads minimum context first, then on-demand."
---

# Ralph Session Startup

Mirrors `/closeout-ralph`. Loads what the last session saved so Ralph starts cold with full context and minimum token cost.

---

## The Job

Load context in priority order. Stop after Step 3 and report status — everything else loads on-demand when the CIO gives direction.

---

## Step 1: Read Project Context

Read `$FLEET_SHARE/ralph/claude.md` for architecture awareness (3 tiers, developer rules, knowledge index, where-things-live table).

Then read the root `CLAUDE.md` for project-wide context (commands, testing, coding standards, specs system, project management structure).

The richest session-handoff signal lives in `$FLEET_SHARE/ralph/ralph_agents.json` — each agent's `note` field carries the last-session close summary.

---

## Step 2: Read Headless Contract

Read `$FLEET_SHARE/ralph/prompt.md` — the per-iteration headless contract. Covers:
- Story selection + agent coordination
- 5 refusal rules
- TDD workflow + Definition of Done
- Quality / safety constants
- `<promise>` tag stop conditions (authoritative)
- PM communication protocol
- Load-on-demand knowledge index

---

## Step 3: Check Inbox and Sprint State

**Inbox** — scan `$FLEET_SHARE/ralph/inbox/` for any unread notes from teammates (Spool, Marcus, Tester). Read any that exist. These may contain pre-sprint context, review feedback, or architectural guidance.

**Sprint state** — read the active sprint file:
- `$FLEET_SHARE/ralph/sprint.json` (new contract format), OR
- `$FLEET_SHARE/ralph/stories.json` (legacy format)

Whichever exists. Report: how many stories total, how many passed, how many pending, how many blocked.

**Agent state** — read `$FLEET_SHARE/ralph/ralph_agents.json`. Report which agents are assigned/unassigned.

---

## Step 4: Report Status to CIO

Print a concise status:
- Sprint: N stories (N passed / N pending / N blocked)
- Inbox: N notes (list senders + topics)
- Agents: assignment status; surface the most recent agent `note` field as the session handoff
- Test baseline (run tests if uncertain)
- Top 3 next actions inferred from sprint.json + ralph_agents.json + inbox (or "awaiting direction")

Then wait for direction. Do NOT start working on stories until the CIO says go.

---

## On-Demand Loading (after CIO gives direction)

Once the CIO tells Ralph what to work on, load ONLY what's needed:

- **Sprint work**: read the specific story from sprint.json, then read ONLY the files listed in `scope.filesToRead` for that story. Do NOT explore beyond the manifest.
- **Code knowledge**: read `$FLEET_SHARE/ralph/knowledge/codebase-architecture.md` for tier layout, config patterns, orchestrator structure.
- **Sprint contract rules**: read `$FLEET_SHARE/ralph/knowledge/sprint-contract.md` for the 5 rules, sizing caps, reviewer discipline.
- **Session learnings**: read `$FLEET_SHARE/ralph/knowledge/session-learnings.md` for accumulated gotchas and CIO feedback.
- **Sweep history**: read `$FLEET_SHARE/ralph/knowledge/sweep-history.md` ONLY when referencing prior reorg work.
- **Specific file work**: read the file(s) the CIO points you at.
- **Review work**: read the artifact to review.
- **Design/brainstorming**: load relevant specs or PRDs as the CIO directs.

**The One Source of Truth rule**: during story execution, Ralph reads ONLY `scope.filesToRead`. Do not speculatively read `specs/`, `progress.txt`, memory files, or other stories. The sprint contract IS the context.

**Knowledge is local**: Ralph's detailed knowledge lives in `$FLEET_SHARE/ralph/knowledge/`, NOT in shared auto-memory. Shared memory (`$FLEET_SHARE/knowledge/memory/`) is cross-agent only, and Ralph does
NOT load it at init -- the scope.filesToRead rule above governs.

---

## What NOT to Do

- Do NOT read every file in the repo to "get up to speed" — load minimum, expand on demand
- Do NOT start executing stories without CIO direction
- Do NOT push to origin without CIO permission
- Do NOT modify `ralph_agents.json` notes at startup (that's closeout's job)

$ARGUMENTS
