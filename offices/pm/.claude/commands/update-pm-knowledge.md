# Update PM Knowledge Base

You are acting as an expert Project Manager for the DataWarehouse ETL project. Your task is to update the PM knowledge base with critical learnings. The primary target file is `offices/pm/lessons-learned.md`.

## Mode Selection

First, ask the user which mode they prefer:
1. **Auto-scan mode** - Scan recent activity and suggest learnings
2. **Interview mode** - Ask questions about what was learned

## Auto-Scan Mode

If auto-scan mode is selected:

1. Read the following sources for recent activity:
   - `offices/ralph/progress.txt` - Recent Ralph execution notes
   - `git log --oneline -20` - Recent commits
   - `offices/pm/completed_sprints/` - Recently completed sprints
   - `orchestration.json` - Current pipeline status

2. Identify potential learnings such as:
   - Patterns that worked well or failed
   - Performance insights
   - Technical decisions made
   - Blockers encountered and how they were resolved
   - New risks discovered

3. Present findings to the user and ask which should be captured.

## Interview Mode

If interview mode is selected, ask the user:
1. What did you work on recently?
2. What worked well? What patterns should we remember?
3. What didn't work? What should we avoid?
4. Any new risks or blockers discovered?
5. Any decisions made that should be documented?

## Knowledge Update Rules

**CRITICAL RULES - You MUST follow these:**

1. **No duplication** - Before adding anything, check if it already exists in:
   - `offices/pm/lessons-learned.md` (existing patterns and lessons)
   - `offices/pm/reference/decision-log.md` (architecture decisions)
   - `offices/pm/backlog.json` (tracked as features/items)
   - Do NOT add if already captured elsewhere

2. **No specs/ content** - The following belongs in `specs/`, NOT in PM knowledge:
   - Technical specifications
   - API documentation
   - Schema definitions
   - Coding standards
   - Architecture decisions (use `specs/architecture.md`)

3. **No ralph/ content** - The following belongs in `offices/ralph/`, NOT in PM knowledge:
   - Current sprint details (that's `offices/ralph/sprint.json`)
   - Execution logs (that's `offices/ralph/progress.txt`)
   - Agent instructions (that's `offices/ralph/AGENT.md`)

4. **Only critical information** - Ask yourself: "Will this help the PM or AI agents make better decisions in the future?" If no, don't add it.

## What DOES Belong in PM Knowledge

- Sprint cadence and capacity learnings
- Story sizing guidelines (what works, what doesn't)
- Performance benchmarks and targets
- Risk patterns and mitigations
- Stakeholder communication insights
- Decision rationale (why, not what)
- Patterns that succeeded or failed repeatedly
- Process improvements

## Update Process

1. Read current `offices/pm/lessons-learned.md`
2. Identify the appropriate section for the new learning:
   - "What Works Well" → new patterns that succeeded
   - "What Doesn't Work" → new anti-patterns or failures
   - "Patterns Quick Reference" → reusable pattern entries
   - If it's an architecture **decision**, add to `offices/pm/reference/decision-log.md` instead
   - If it's a new **risk**, add to `offices/pm/reference/risk-register.md` instead
3. Draft the update (keep it concise - 1-3 sentences per item)
4. Show the user the proposed changes
5. Apply only after user approval

## Output Format

When proposing updates, format as:

```
## Proposed Updates to PM Knowledge Base

### Section: [Section Name]
**Add:**
- [New learning to add]

### Section: [Section Name]
**Update:**
- [Existing item] -> [Updated version]

---
Approve these changes? (yes/no/edit)
```
