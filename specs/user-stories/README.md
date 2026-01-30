# User Stories for Ralph Autonomous Agent

This folder contains documentation about the user story format that Ralph uses for autonomous execution. The actual stories live in `ralph/stories.json`.

## Token Budget

- **Context Window Size**: 200,000 tokens
- **Max per Story**: 150,000 tokens (75% of context)
- **Typical Story**: 40,000 - 75,000 tokens

### Token Breakdown Per Story

| Component | Tokens | Description |
|-----------|--------|-------------|
| Story Context | 2,000-3,000 | The user story description and acceptance criteria |
| Codebase Context | 18,000-30,000 | Relevant files Ralph needs to read to understand the task |
| Code to Write | 10,000-24,000 | The actual code Ralph will generate |
| Buffer | 10,000-13,000 | Conversation overhead and safety margin |

## Story Structure

Each story follows this JSON structure:

```json
{
  "id": "US-001",
  "title": "Short descriptive title",
  "description": "As a [user], I want [feature] so that [benefit]",
  "acceptanceCriteria": [
    "Specific verifiable criterion 1",
    "Specific verifiable criterion 2",
    "Typecheck passes"
  ],
  "priority": "high",
  "dependencies": ["US-000"],
  "passes": false,
  "notes": ""
}
```

## Guidelines for Developers

### Acceptance Criteria Are Checkable

Every criterion can be verified with a YES or NO answer:
- "Add status column to table" - Can check if column exists
- "Typecheck passes" - Can run type checker and verify
- "Unit test validates X" - Can run test and verify

### Dependencies Matter

Always check the `dependencies` array before starting a story. If US-005 depends on US-004, you MUST complete US-004 first.

### Story Size Rule

Each story must be completable in ONE Ralph iteration (one context window). If it touches more than 3 files or 500 lines, it's too big -- split it.

## Workflow

```
PM creates PRD (pm/prds/prd-*.md)
       |
       v
/ralph converts PRD to stories.json (ralph/stories.json)
       |
       v
ralph.sh executes stories autonomously
       |
       v
/ralph-status checks progress
```

## Running Ralph

```bash
./ralph/ralph.sh 10  # Run 10 iterations
# Ralph reads ralph/stories.json and executes stories in priority order
```

## Marking Stories Complete

When Ralph completes a story:
1. All acceptance criteria are verified
2. `passes` is set to `true`
3. `notes` may contain relevant information

Stories that fail remain `passes: false` with error details in `notes`.
