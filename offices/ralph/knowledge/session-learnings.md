# Ralph Session Learnings

Accumulated gotchas, patterns, and CIO feedback. Load on-demand when working, not at startup.

## CIO Feedback (behavioral)
- **Keep deliverables tight** — CIO corrected 900→240 line design. Deliver what was asked; route extras as PM inbox notes. Don't design the surrounding system.
- **Reviewers stay in lane** — no second-guessing other experts' decisions. Value-add edits or silence.
- **No compound bash** — single commands only; chains trigger per-chunk prompts. Use `git -C`, absolute paths, parallel Bash calls.
- **Save knowledge locally** — Ralph-specific knowledge goes in `offices/ralph/knowledge/`, NOT shared auto-memory. Other agents shouldn't load Ralph's context.

## Code Patterns (gotchas)
- **Path convention**: bare imports (`from display import ...`), NOT `src.` prefix. src/ is on sys.path via conftest.
- **Lazy import patch rewiring**: when rewriting an in-function import, every `@patch('old.X')` in tests must also move. Always grep tests.
- **Mass config grep**: grep ALL `config.get(...)` patterns, not just canonical section names. Sweep 4 missed `shutdown`/`monitoring` reads.
- **Ruff scope discipline**: `ruff check --fix` auto-fixes untouched files. Only keep fixes in swept files.
- **Subagent died**: check `git log --oneline` BEFORE `git status`/`git diff`. Commits may be intact while worktree is stale.

## Development Patterns
- **Mechanical batch subagent**: for high-volume refactors, dispatch ONE well-scoped subagent with the full file list, not one per file.
- **Scope escape hatch**: when a numeric exit criterion exceeds scope, split the biggest offenders + exempt the rest in a README block.
- **Parallel session branch gotcha**: if PM does `git checkout main` while Ralph is on a sprint branch, Ralph's worktree flips. Recovery: stash/checkout/pop.
- **Spool values are sacred**: file every SME value as explicit validated config. Never reinterpret, round, or hide as magic numbers. Use `[EXACT: value — DO NOT CHANGE]` markers.

## Testing
- Test baseline post-reorg: 1488 collected (1469 passed, 19 deselected fast; 1487+1 skipped full)
- `stories.json` uses `passes` field (not `passed`)
- ralph_agents.json has `type`, `lastCheck`, `note` fields — richer than DW template
- agent.md must be lowercase for Pi (Linux case-sensitive FS)
