# Ralph Agent Instructions

You are an autonomous coding agent working on a software project.

## Your Task

1. Read the PRD at `specs/backlog.json` (in the same directory as this file)
2. Read the progress log at `ralph/progress.txt` (check Codebase Patterns section first)
3. Read the `ralph/agent.md` file in working directories or parent directories and \
updated it based on the rules below.
4. You are in a team of developers and need to not work onthe same user story. Using \
your `Agent_ID` to determine the rank ordering of the highest priorty and choose that \
user story.
5. Find the highest-priority user story where `passes: false` to work on \
and work only on that feature. This should be the one YOU decide has the \ 
highest priority - not necessarily the first in the list. \
You must not work on a taskid defined in `ralph/ralph_agents.json`
6. update `ralph/ralph_agents.json` for your agentid update and save the file \ with your user story task id that you have selected.
7. Implement that single user story
8. Run quality checks (e.g., typecheck, lint, test - use whatever your project requires)
9. Update AGENTS.md files if you discover reusable patterns (see below)
10. If checks pass, commit ALL changes with message: `feat: [Story ID] - [Story Title]`
11. Update the PRD to set `passes: true` for the completed story
12. Append your progress to `progress.txt`

## Progress Report Format

APPEND to progress.txt (never replace, always append):
```
## [Date/Time] - [Story ID]
User Story: [Title]
- What was implemented
- Files changed
- **Learnings for future iterations:**
  - Patterns discovered (e.g., "this codebase uses X for Y")
  - Gotchas encountered (e.g., "don't forget to update Z when changing W")
  - Useful context (e.g., "the evaluation panel is in component X")
---
```

Include the thread URL so future iterations can use the `read_thread` tool to reference previous work if needed.

The learnings section is critical - it helps future iterations avoid repeating mistakes and understand the codebase better.

## Consolidate Patterns

If you discover a **reusable pattern** that future iterations should know, add it to the `## Codebase Patterns` section at the TOP of progress.txt (create it if it doesn't exist). This section should consolidate the most important learnings:

```
## Codebase Patterns
- Example: Use `sql<number>` template for aggregations
- Example: Always use `IF NOT EXISTS` for migrations
- Example: Export types from actions.ts for UI components
```

Only add patterns that are **general and reusable**, not story-specific details.

## Update AGENTS.md Files

Before committing, check if any edited files have learnings worth preserving in nearby AGENTS.md files:

1. **Identify directories with edited files** - Look at which directories you modified
2. **Check for existing AGENTS.md** - Look for AGENTS.md in those directories or parent directories
3. **Add valuable learnings** - If you discovered something future developers/agents should know:
   - API patterns or conventions specific to that module
   - Gotchas or non-obvious requirements
   - Dependencies between files
   - Testing approaches for that area
   - Configuration or environment requirements

**Examples of good AGENTS.md additions:**
- "When modifying X, also update Y to keep them in sync"
- "This module uses pattern Z for all API calls"
- "Tests require the dev server running on PORT 3000"
- "Field names must match the template exactly"

**Do NOT add:**
- Story-specific implementation details
- Temporary debugging notes
- Information already in progress.txt

Only update AGENTS.md if you have **genuinely reusable knowledge** that would help future work in that directory.

## Quality Requirements

- ALL commits must pass your project's quality checks (typecheck, lint, test)
- Do NOT commit broken code
- Keep changes focused and minimal
- Follow existing code patterns

## Project Reference Documents
Anit-Patterns - specs/anti-patterns.md - contains do not "use /do" examples
Architecture - specs/architecture.md - contains the project architecture
Data Warehouse Guidelines - specs/dataWarehouseGuidelines.md - contains best practices for designing a data warehoues
Glossary - specs/glossary.md - contains terms and definitions
Methodology - specs/methodology.md - contains the project and coding methodology
Standards - specs/standards.md - contains coding and programming standards

## Stop Condition

After completing a user story, check if ALL stories have `passes: true`.

If ALL stories are complete and passing, reply with:
<promise>COMPLETE</promise>

If there are still stories with `passes: false`, end your response normally (another iteration will pick up the next story).

## Important

- Work on ONE story per iteration
- Commit frequently
- Keep CI green
- Read the Codebase Patterns section in progress.txt before starting