# User Stories for Ralph Autonomous Agent

This folder contains user stories formatted for the Ralph autonomous agent system. Each story is designed to be completable in ONE Ralph iteration (one context window).

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

## Story Files

Place your PRD JSON files here:

- `[feature-name]-prd.json` - User stories for specific features

### Example Structure

```
user-stories/
├── README.md
├── authentication-prd.json
├── dashboard-prd.json
└── api-integration-prd.json
```

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
  "estimatedTokens": 45000,
  "estimatedTokensBreakdown": {
    "storyContext": 2000,
    "codebaseContext": 20000,
    "codeToWrite": 13000,
    "buffer": 10000
  },
  "dependencies": ["US-000"],
  "passes": false,
  "notes": ""
}
```

## Guidelines for Junior AI Developers

### Acceptance Criteria Are Checkable

Every criterion can be verified with a YES or NO answer:
- "Add status column to table" - Can check if column exists
- "Typecheck passes" - Can run type checker and verify
- "Unit test validates X" - Can run test and verify

### Dependencies Matter

Always check the `dependencies` array before starting a story. If US-005 depends on US-004, you MUST complete US-004 first. The code from US-004 will be needed.

### Parallel Stories

Stories with no dependencies (or same dependencies) can be run in parallel:
- DDL stories with no deps can run in parallel
- Stories that both depend only on the same story can run in parallel

### Token Estimates Are Guidelines

If you find yourself running out of context:
1. The story might be too complex - ask for it to be split
2. You might be loading too much codebase context - focus on relevant files only
3. The code being written might be too verbose - keep it concise

## Running Ralph

```bash
# Run Ralph with iterations
./ralph/ralph.sh --loop 10  # Run 10 iterations

# Ralph will read prd.json and execute stories in priority order
```

## Marking Stories Complete

When Ralph completes a story:
1. All acceptance criteria are verified
2. `passes` is set to `true`
3. `notes` may contain relevant information

Stories that fail remain `passes: false` with error details in `notes`.

## Creating New PRDs

1. Use the PRD skill to create a markdown PRD: `specs/tasks/prd-[feature].md`
2. Use the Ralph skill to convert it to JSON: `specs/user-stories/[feature]-prd.json`
3. Copy to `ralph/prd.json` when ready to execute
4. Run Ralph: `./ralph/ralph.sh`

See `specs/prd_skill.md` and `specs/ralph_skill.md` for detailed instructions.
