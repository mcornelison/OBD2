---
name: closeout-pm
description: "End-of-session ritual for Marcus (PM). Triages inbox, audits sprint contract, updates shared knowledge (MEMORY.md + projectManager.md), commits PM-side changes, pushes to sprint branch (NEVER merges mid-sprint while Ralph is working). Run at end of every PM session."
---

# PM Session Closeout

End-of-session ritual for Marcus (PM). Captures the workflow refined Session 24 (2026-04-19) when CIO directed building reusable PM tooling. Replaces the older `closeout-session-pm.md` workflow.

---

## Prerequisites

Run these PM tools (built Sessions 23-24, lives in `offices/pm/scripts/`) at session boundaries:
- `python offices/pm/scripts/pm_status.py` — sprint + backlog + counter snapshot
- `python offices/pm/scripts/backlog_set.py` — backlog mutation CLI
- `python offices/pm/scripts/sprint_lint.py` — Sprint Contract v1.0 audit

If any are missing, build them per `offices/pm/scripts/README.md`.

---

## Phase 1 — Inbox triage

PM owns decisions; closeout makes sure no decisions are floating.

1. List inbox by recency:
   ```bash
   ls -lt offices/pm/inbox/ | head -10
   ```
2. Identify any unread / unanswered notes (no corresponding response in `offices/<recipient>/inbox/`).
3. For each, decide + reply via inbox note `offices/<recipient>/inbox/<date>-from-marcus-<topic>.md`.
4. Decisions can include: fold a TD into the current sprint as a new story, defer to Sprint N+1 with a story_counter reservation, or waive with explicit rationale.
5. If a decision adds/changes a sprint story, follow Phase 3 (sprint hygiene) before commit.

---

## Phase 2 — Specs + working tree check

Spool may have updated `specs/grounded-knowledge.md` or `specs/obd2-research.md` (CIO-authorized boundary cross). PM Rule 7 source-of-truth changes there.

1. `git status --short` — anything in `specs/` modified?
2. If yes, read the new sections so future story acceptance criteria use the updated grounded values.
3. Note in MEMORY.md update (Phase 4) so other PM sessions know.
4. Check working tree for in-flight Ralph code (`src/`, `tests/`) — these stay uncommitted per Rule 8 (sprint-close commits them).

---

## Phase 3 — Sprint state hygiene

Make sure the sprint contract is clean before committing.

1. `python offices/pm/scripts/pm_status.py --sprint` — confirm story states.
2. `python offices/pm/scripts/sprint_lint.py` — catch schema violations:
   - Missing `feedback: {filesActuallyTouched: null, grounding: null}` scaffold
   - `passes: null` instead of `passes: false`
   - Banned phrases (`etc.`, `handle edge cases`, `tests pass` without command)
   - Titles > 70 chars
   - L stories missing `pmSignOff`
3. Apply safe mechanical fixes (don't change Ralph's discipline mid-sprint — sizing-cap warnings are informational per `feedback_pm_sprint_contract_calibration.md`).
4. Re-run sprint_lint until 0 errors. Warnings reviewed but acceptable.

---

## Phase 4 — Update shared knowledge

### MEMORY.md (`C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`)

Auto-loaded into every future session. **Cap: 200 lines** (truncated beyond).

Update these sections:
- **Current State** header date + session number
- **Branch + commits** — current sprint branch, latest commit hash, count of stories complete vs pending
- **Mid-sprint adds** — any new stories filed this session
- **Spool spec updates** — if any
- **Sprint execution order** — refresh if changed
- **CIO directives this session** — any new rules
- **Sprint 15+ candidates** — keep forward-looking section current

If new feedback memory was created this session, add a one-line entry to the "Shared Memory Index" section.

If MEMORY.md grows past ~150 lines, condense closed-history sections (Sprint X details collapse to one line referencing `projectManager.md`).

### projectManager.md (`offices/pm/projectManager.md`)

This is the PM-only deep-history file (1500+ lines is fine).

1. Bump header `**Last Updated**:` to today + session number.
2. Update `**Current Phase**:` if changed.
3. **Rename existing "Last Session Summary" → "Previous Session Summary"** then write a new "Last Session Summary" with format:
   ```
   ### Last Session Summary (YYYY-MM-DD, Session N — Short Title)

   **What was accomplished:**
   - Bullet points; include commit hashes + file counts where meaningful

   **Key decisions:**
   - With rationale if non-obvious

   **Key artifacts produced:**
   - File paths

   **What's next:**
   1. Numbered priority list

   **Unfinished work:**
   - In-progress items + blockers + unpushed commits
   ```
4. Update `### Current State (...)` block in "Quick Context for New Sessions".
5. Update `### Immediate Next Actions (Session N+1 pickup)` — strikethrough completed items with DONE marker, add new items.

### story_counter.json + backlog.json

If Phase 1 added stories or reservations:
- `story_counter.json` — bump nextId, add reservation lines.
- `backlog.json` — use `python offices/pm/scripts/backlog_set.py --feature B-XXX --add-phase ... --updated-by "Marcus (PM, Session N — short)"` to update phase records + lastUpdated atomically.

---

## Phase 5 — Commit + push (PM-side ONLY)

**Critical Rule 8:** PM commits only PM-domain files mid-sprint. Sprint-close commits everything else.

### Stage these (PM-domain):
- `offices/ralph/sprint.json` — sprint contract changes I made
- `offices/pm/story_counter.json`
- `offices/pm/backlog.json`
- `offices/pm/projectManager.md`
- `offices/pm/scripts/*.py` + `README.md` — new tools / updates
- `offices/pm/inbox/<date>-from-*-*.md` — inbox notes received this session
- `offices/<recipient>/inbox/<date>-from-marcus-*.md` — inbox notes I sent
- `offices/pm/tech_debt/TD-*.md` — only if PM filed (not Ralph-filed annotated)
- `offices/pm/blockers/BL-*.md` — only if PM filed
- `offices/pm/prds/prd-*.md` — only if PM filed

### DO NOT stage:
- `src/**` — Ralph's domain (sprint-close)
- `tests/**` — Ralph's domain (sprint-close)
- `specs/**` — Spool's domain (Spool commits separately)
- `offices/ralph/{progress.txt,session-handoff.md,ralph_agents.json}` — Ralph's session tracking (sprint-close)
- `offices/ralph/knowledge/*` — Ralph's domain
- `offices/tuner/**` (except inbox notes I sent) — Spool's domain
- `.claude/commands/*` — only if I explicitly created/modified a slash command (verify intentional)
- `.claude/settings.local.json` — persistent local drift, NEVER commit
- `data/*.db-shm`, `data/*.db-wal` — SQLite ephemera
- `**/scheduled_tasks.lock` — runtime locks

### Commit message format
```
chore(pm): Session N closeout — <2-4 word summary>

<2-4 sentence narrative of what changed and why>

Files:
  <bullet list of staged files with one-line purpose each>

NOT committed (per Rule 8, sprint-close commits these):
  <bullet list of major in-flight files left unstaged>
```

### Push
```bash
git -C /z/o/OBD2v2 push origin sprint/<current-sprint-branch>
```

### **NEVER MERGE TO MAIN MID-SPRINT**
Ralph is working on the sprint branch. Merging to main would break his working tree. Sprint-close (separate ritual) is when merge happens.

### If any local-noise files were touched (e.g., `.claude/settings.local.json` got new auto-allows during the session)
Leave them in working tree as-is. They've been "modified" in working tree for many sessions; they don't need to be reset.

---

## Phase 6 — Summary to CIO

Print a brief closeout summary:

```
**Session N closeout complete.** Branch `sprint/<name>` at `<short-hash>`, pushed (NOT merged).

**Key actions:**
- <bullet>
- <bullet>

**Sprint progress:** X / Y stories complete.

**Next session pickup:**
- <next action>
- <next action>

**Open items for CIO awareness (if any):**
- <decisions awaiting CIO direction>
- <hardware tasks gating Sprint N+1>
```

Keep it tight — CIO can read MEMORY.md / projectManager.md for detail.

---

## What NOT to do

- Do NOT push to `main`. Sprint branch only.
- Do NOT merge to `main` mid-sprint while Ralph is working.
- Do NOT modify code files (`src/`, `tests/`) — Marcus never writes code.
- Do NOT update `specs/` files — Spool's domain.
- Do NOT commit Ralph's session-tracking files mid-sprint.
- Do NOT make up session accomplishments — only record what actually happened.
- Do NOT skip running `sprint_lint.py` — catches mistakes that compound across sessions.
- Do NOT delete the existing `closeout-session-pm.md` without CIO approval (it's a deprecation candidate but until CIO says so, leave it).

$ARGUMENTS
