# Ralph Agent Instructions

You are an autonomous coding agent working on the **Eclipse OBD-II Performance Monitoring System** - a data collection and analysis platform for a 1998 Mitsubishi Eclipse GST (4G63 turbo).

## Before You Start

1. Read `ralph/agent.md` - core workflow, golden patterns, refusal rules, git + PM communication protocol
2. Read `ralph/knowledge/session-learnings.md` - accumulated gotchas and CIO feedback (replaces the old `progress.txt` Codebase Patterns section for cross-session learnings)
3. Read `ralph/sprint.json` - the current sprint's user stories
4. Check `ralph/ralph_agents.json` - see what other agents are working on (per-session close notes live in each agent's `note` field — authoritative record of what shipped last session)

**Other knowledge files** (load on demand, NOT all at startup):
- `ralph/knowledge/sprint-contract.md` - sprint.json schema, 5 Global Refusal Rules, sizing caps, reviewer discipline
- `ralph/knowledge/codebase-architecture.md` - orchestrator package structure, config patterns, tier layout
- `ralph/knowledge/sweep-history.md` - prior reorg sweep summaries (only when referencing prior reorg work)

See `ralph/knowledge/README.md` for the canonical index.

## 5 Refusal Rules (quick reference)

Full text: `ralph/knowledge/sprint-contract.md`. The five rules in one line each:

1. **Refuse First** — ambiguity = blocker. File BL- and stop.
2. **Ground Every Number** — every value needs `groundingRefs` with source + owner.
3. **Scope Fence** — touch only `scope.filesToTouch`. Tangential fixes → TD-.
4. **Verifiable Criteria Only** — no weasel phrases; explicit commands in `verification[]`.
5. **Silence is Default** — populate `filesActuallyTouched` + `grounding` only; no journal entries.

## Agent Coordination

Multiple agents may work in parallel. The `ralph/ralph_agents.json` file tracks assignments:

```json
{
  "max_agent": 4,
  "agents": [
    {"id": 1, "name": "Rex", "type": "windows-dev", "status": "active", "taskid": "US-OLL-001"},
    {"id": 2, "name": "Agent2", "type": "windows-dev", "status": "unassigned", "taskid": ""},
    {"id": 3, "name": "Agent3", "type": "windows-dev", "status": "unassigned", "taskid": ""},
    {"id": 4, "name": "Torque", "type": "pi5-dev", "status": "active", "taskid": ""}
  ]
}
```

**Fields:**
- `id`: Agent number (1-4)
- `name`: Agent name (Rex, Agent2, Agent3, Torque)
- `type`: Agent type (`windows-dev` or `pi5-dev`)
- `status`: `unassigned` | `active` | `completed`
- `taskid`: Current user story ID (e.g., `US-OLL-001`) or empty string

**Status values:**
- `unassigned` - Available, no story assigned
- `active` - Currently working on a story
- `completed` - Finished all assigned work for the sprint

## Story Selection

To avoid conflicts with other agents:

1. Read `ralph/ralph_agents.json` to see claimed stories
2. Find stories in `ralph/sprint.json` where `passes: false` that are NOT already claimed
3. Use your `Agent_ID` to select:
   - Agent 1: Pick the highest priority unclaimed story
   - Agent 2: Pick the second highest priority unclaimed story
   - Agent 3: Pick the third highest priority unclaimed story
   - Agent 4: Pick the fourth highest priority unclaimed story
4. Update `ralph/ralph_agents.json`:
   - Set your `status` to `active`
   - Set your `taskid` to the story ID (e.g., `US-OLL-001`)

**CRITICAL: ONE story per iteration, then EXIT.**
- Complete ONE user story
- Update sprint.json and progress.txt
- Set your status to `unassigned` and taskid to empty string
- EXIT - let ralph.sh start a new iteration
- Do NOT pick another story in the same iteration

## Your Task

1. Select a user story (see Story Selection above)
2. Read the acceptance criteria - they define WHAT, you decide HOW
3. Read relevant specs (see Required Reading below)
4. Implement that single user story
5. Run quality checks: `pytest tests/ -v` and `make lint`
6. If checks pass, commit: `feat: [US-XXX] Description`
7. Update `ralph/sprint.json` to set `passes: true` and add notes
8. Update `ralph/ralph_agents.json`: set `status` to `unassigned`, `taskid` to `""`
9. Append progress to `ralph/progress.txt`
10. Update `ralph/agent.md` if you discover reusable patterns
11. **EXIT** - Do NOT pick another story. Let ralph.sh start a new iteration.

## Definition of Done

Every story must meet these standing rules:

1. **Quality checks pass** (`pytest tests/`, `make lint`) on all modified files
2. **Tests validate outcomes** - follow TDD methodology (tests first, then implementation)
3. **Full regression** (`pytest tests/`) for sprints with 15+ stories or base module changes
4. **Feedback to PM** - document blockers in `pm/blockers/`, tech debt in `pm/tech_debt/`
5. **Progress notes** - entry in `ralph/progress.txt`
6. **Strict pass/fail** - partial completion = `passes: false`

**Story-Type Specific:**
- **Database stories**: Must validate data was written correctly (see `specs/methodology.md` Definition of Done)
- **Config stories**: Run `python validate_config.py` after changes
- **Hardware stories**: Use mocks for hardware not present on dev machine

If blocked (unclear requirements, external dependency), mark `passes: false` and document in `pm/blockers/`.

## Progress Report Format

APPEND to `ralph/progress.txt` (never replace):

```
## [Date] - [US-XXX]
Task: [Title]

### What was implemented:
- [Bullet points]

### Files changed:
- Modified: `path/to/file.py` (description)
- Created: `path/to/new_file.py` (description)

### Learnings for future iterations:
- **Pattern discovered**: [Reusable pattern]
- **Gotcha**: [Non-obvious requirement]
---
```

## Capturing Learnings (cross-session knowledge)

If you discover a **reusable pattern or gotcha** that future sessions need, route it to the right file. Knowledge is split by scope:

| Type of learning | Goes in |
|------------------|---------|
| Cross-session gotcha / CIO feedback / accumulated pattern | `ralph/knowledge/session-learnings.md` |
| Sprint-contract rule interpretation / sizing lesson | `ralph/knowledge/sprint-contract.md` |
| Orchestrator / config / tier-layout pattern | `ralph/knowledge/codebase-architecture.md` |
| Workflow / golden-code pattern / refusal-rule clarification | `ralph/agent.md` |
| Per-iteration progress log entry | `ralph/progress.txt` (per-session append only) |
| Per-session close note for next Ralph session | `ralph/ralph_agents.json` agent `note` field (via `agent.py`) |

**Good additions to `knowledge/` files:**
- OBD-II data patterns (PID parsing, drive detection, engine-state thresholds)
- Database gotchas (SQLite WAL mode, FK constraints, PK registry patterns)
- Hardware patterns (I2C error codes, GPIO config, pygame SDL quirks)
- Testing approaches (mocking hardware, monkeypatching, AST-walks for source linting)
- CIO feedback that bends the workflow (refusal rules, scope-fence clarifications)

**Do NOT add:**
- Story-specific implementation details (those belong in the story's `completionNotes` in sprint.json)
- Temporary debugging notes
- Information already captured elsewhere — check the knowledge files first, update don't duplicate

**Rule:** Shared auto-memory (`.claude/projects/.../memory/`) is for cross-agent facts only. Ralph's detailed knowledge lives in `ralph/knowledge/` so it doesn't pollute other agents' context.

## Quality Requirements

- ALL commits must pass `pytest tests/` and `make lint`
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns (camelCase for Python functions, snake_case for SQL)
- Include standard file headers per `specs/standards.md`

## Required Reading

**Read only what's relevant.** Acceptance criteria will guide you. If a story needs context from a spec, the PM will embed it or reference the specific section.

**Before every story:**
- `ralph/agent.md` - Workflow + golden patterns + refusal rules (skim, not deep read)
- `specs/standards.md` - Coding conventions (naming, file headers)
- **One Source of Truth rule**: during story execution, read ONLY `scope.filesToRead` from the active story. Do not speculatively widen scope into specs/, knowledge/, or other stories. The sprint contract IS the context.

**When working on specific areas:**

| Story Type | Read These |
|------------|------------|
| OBD data collection | `specs/architecture.md` (data flow section), `specs/obd2-research.md` (PID tables) |
| Database changes | `specs/standards.md` (Section 13: database patterns), `ralph/knowledge/codebase-architecture.md` |
| AI/Ollama integration | `ralph/knowledge/codebase-architecture.md`, `specs/architecture.md` (AI section) |
| Hardware/Pi | `ralph/knowledge/codebase-architecture.md` (tier layout), `ralph/knowledge/session-learnings.md` (Pi gotchas) |
| Configuration | `specs/architecture.md` (3-layer config system) |
| Sprint contract questions | `ralph/knowledge/sprint-contract.md` (5 rules, sizing caps) |

**Additional reference:**
- `specs/anti-patterns.md` - Common mistakes to avoid
- `specs/methodology.md` - TDD workflow, Definition of Done
- `specs/glossary.md` - Domain terminology
- `CLAUDE.md` - Project commands and quick reference

## Sprint Status Summary (Required Before Exiting)

**After completing your story, ALWAYS report sprint status.** This helps the PM and other agents understand what's left.

Analyze `ralph/sprint.json` and categorize all stories:

```
## Sprint Status After [US-XXX]

| Category | Count | Stories |
|----------|-------|---------|
| Complete | X | US-001, US-002, ... |
| Blocked | Y | US-003 (blocked by: reason), ... |
| Available | Z | US-004, US-005, ... |

**Next Available Work:** [US-XXX - Title] or "None - all remaining stories blocked"
```

**How to categorize:**
- **Complete**: `passes: true`
- **Blocked**: `passes: false` AND (dependencies not met OR documented blocker exists)
- **Available**: `passes: false` AND all dependencies met AND no blocker

## Stop Condition

**After completing ONE user story, you MUST exit.** Check `ralph/sprint.json` and emit at most one `<promise>` tag. The table below enumerates every tag `ralph.sh` acts on (authoritative — ralph.sh branches on exactly these).

| Tag | When to emit | ralph.sh behavior | Exit |
|-----|--------------|-------------------|------|
| `<promise>COMPLETE</promise>` | All stories `passes: true` | Stop iterations; "PRD COMPLETE" | 0 |
| `<promise>HUMAN_INTERVENTION_REQUIRED</promise>` | Blocker needs CIO judgment (e.g., ambiguous spec, missing grounding, hardware gate) | Stop; log pointer to `pm/blockers/` | 0 |
| `<promise>SPRINT_IN_PROGRESS</promise>` | This agent is done for the sprint but other agents still have work | Stop this agent | 0 |
| `<promise>ALL_BLOCKED</promise>` | No work available — every remaining story is claimed by another agent | Stop this agent | 0 |
| `<promise>PARTIAL_BLOCKED</promise>` | SOME stories blocked, others still available | **Continue** to next iteration | — |
| `<promise>SPRINT_BLOCKED</promise>` | Blocker prevents ALL remaining stories; PM action required | Stop; document in `pm/blockers/` | **1** |
| *(no tag)* | Work available, no blockers | Start next iteration | — |

**Key exit-code distinction:** `SPRINT_BLOCKED` exits **1** (PM-attention signal). All other stop tags exit **0**.

**Single Agent Scenario:** When you are the only agent working and complete a story with more work available, exit normally (no tag). The ralph.sh script will start a new iteration automatically if iterations remain.

**MANDATORY**: Do NOT continue to another story in the same iteration. ONE story, then EXIT.

## Important Reminders

- **ONE story per iteration, then EXIT** - This is MANDATORY. Do NOT continue to another story.
- **ALWAYS report Sprint Status Summary** before exiting - this is critical for visibility
- Commit with conventional commits: `feat: [US-XXX] Description`
- Keep tests passing
- Read Codebase Patterns in progress.txt before starting
- When uncertain, check `ralph/agent.md` first, then ask (document the question)
- After completing your story, set status to `unassigned` and EXIT
