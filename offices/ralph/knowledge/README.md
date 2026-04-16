# Ralph Knowledge Base

Ralph-specific knowledge files. Loaded on-demand by `/init-ralph`, NOT all at startup.

**Rule:** Shared auto-memory (`.claude/projects/.../memory/`) is for cross-agent facts only. Ralph's detailed knowledge lives HERE so it doesn't pollute other agents' context.

## Index
- `sprint-contract.md` — sprint.json schema, 5 rules, sizing, reviewer discipline
- `session-learnings.md` — accumulated learnings across sessions (gotchas, patterns, feedback)
- `codebase-architecture.md` — orchestrator package structure, config patterns, tier layout
- `sweep-history.md` — reorg sweep summaries (load only when referencing prior reorg work)
