# Ralph Agent Instructions

You are an autonomous coding agent working on the **Eclipse OBD-II Performance Monitoring System** - a data collection and analysis platform for a 1998 Mitsubishi Eclipse GST (4G63 turbo).

## Before You Start

1. Read `ralph/agent.md` - your project knowledge base (patterns, gotchas, conventions)
2. Read `ralph/progress.txt` - check the **Codebase Patterns** section first
3. Read `ralph/stories.json` - the current sprint's user stories
4. Check `ralph/ralph_agents.json` - see what other agents are working on

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
2. Find stories in `ralph/stories.json` where `passes: false` that are NOT already claimed
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
- Update stories.json and progress.txt
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
7. Update `ralph/stories.json` to set `passes: true` and add notes
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

## Codebase Patterns Section

If you discover a **reusable pattern**, add it to `## Codebase Patterns` at the TOP of `progress.txt`:

```
## Codebase Patterns
- Pattern: Use `newline=''` when opening CSV files on Windows
- Gotcha: Config paths must resolve relative to script location, not CWD
```

Only add **general and reusable** patterns, not story-specific details.

## Update agent.md

Before committing, check if learnings should be added to `ralph/agent.md`:

**Good additions:**
- OBD-II data patterns (e.g., PID parsing, drive detection states)
- Database gotchas (e.g., SQLite WAL mode, FK constraints)
- Hardware patterns (e.g., I2C error codes, GPIO config)
- Testing approaches (e.g., mocking hardware, monkeypatching)

**Do NOT add:**
- Story-specific implementation details
- Temporary debugging notes
- Information already in progress.txt

## Quality Requirements

- ALL commits must pass `pytest tests/` and `make lint`
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns (camelCase for Python functions, snake_case for SQL)
- Include standard file headers per `specs/standards.md`

## Required Reading

**Read only what's relevant.** Acceptance criteria will guide you. If a story needs context from a spec, the PM will embed it or reference the specific section.

**Before every story:**
- `ralph/agent.md` - Project patterns and critical gotchas (skim, not deep read)
- `specs/standards.md` - Coding conventions (naming, file headers)

**When working on specific areas:**

| Story Type | Read These |
|------------|------------|
| OBD data collection | `specs/architecture.md` (data flow section) |
| Database changes | `specs/standards.md` (Section 13: database patterns) |
| AI/Ollama integration | `ralph/agent.md` (Ollama section) |
| Hardware/Pi | `ralph/agent.md` (Pi 5 Deployment Context, I2C, GPIO sections) |
| Configuration | `specs/architecture.md` (3-layer config system) |

**Additional reference:**
- `specs/anti-patterns.md` - Common mistakes to avoid
- `specs/methodology.md` - TDD workflow, Definition of Done
- `specs/glossary.md` - Domain terminology
- `CLAUDE.md` - Project commands and quick reference

## Sprint Status Summary (Required Before Exiting)

**After completing your story, ALWAYS report sprint status.** This helps the PM and other agents understand what's left.

Analyze `ralph/stories.json` and categorize all stories:

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

**After completing ONE user story, you MUST exit.** Check `ralph/stories.json`:

- If ALL stories have `passes: true`: Reply with `<promise>COMPLETE</promise>`
- If a blocker prevents ALL remaining stories: Reply with `<promise>SPRINT_BLOCKED</promise>` and document in `pm/blockers/`
- If SOME stories are blocked but others are available: Reply with `<promise>PARTIAL_BLOCKED</promise>` (alerts PM to blockers while allowing work to continue)
- If work is available and no blockers: Exit normally (no promise tag) - ralph.sh will start a new iteration

**Single Agent Scenario:** When you are the only agent working and complete a story with more work available, exit normally. The ralph.sh script will start a new iteration automatically if iterations remain.

**MANDATORY**: Do NOT continue to another story in the same iteration. ONE story, then EXIT.

## Important Reminders

- **ONE story per iteration, then EXIT** - This is MANDATORY. Do NOT continue to another story.
- **ALWAYS report Sprint Status Summary** before exiting - this is critical for visibility
- Commit with conventional commits: `feat: [US-XXX] Description`
- Keep tests passing
- Read Codebase Patterns in progress.txt before starting
- When uncertain, check `ralph/agent.md` first, then ask (document the question)
- After completing your story, set status to `unassigned` and EXIT
