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
- **Shell-script grep counter over JSON**: `grep -c '"field": true' file.json 2>/dev/null || echo 0` silently returns 0 on a field-name drift. Typo `passes` vs `passed` in `ralph.sh` made the sprint-progress display stuck at `0` for an unknown number of sessions. If a counter reads a schema, it needs an assertion path or a `python -c 'import json'` lookup — not a `|| echo 0` fallback that hides broken matches.

## Development Patterns
- **Mechanical batch subagent**: for high-volume refactors, dispatch ONE well-scoped subagent with the full file list, not one per file.
- **Scope escape hatch**: when a numeric exit criterion exceeds scope, split the biggest offenders + exempt the rest in a README block.
- **Parallel session branch gotcha**: if PM does `git checkout main` while Ralph is on a sprint branch, Ralph's worktree flips. Recovery: stash/checkout/pop.
- **Spool values are sacred**: file every SME value as explicit validated config. Never reinterpret, round, or hide as magic numbers. Use `[EXACT: value — DO NOT CHANGE]` markers.

## Infrastructure
- **SSH**: `ssh chi-srv-01` and `ssh chi-eclipse-01` both work passwordless. Use hostnames, not IPs. BatchMode=yes works on both.
- **Chi-Srv-01 real IP**: `10.27.27.10`, NOT `.120` as in architecture.md. CIO aware, network admin task.
- **Pi legacy code**: `/home/mcornelison/Projects/EclipseTuner` at `a28fa1e` (Jan 31). Pre-reorg, ~60 commits behind. Safe `git pull`.
- **CRLF**: `.gitattributes` with `eol=lf` + `core.autocrlf=input`. Never use `autocrlf=true` — it adds CRLF on checkout.
- **Server isolation**: rsync deploy boundary (`/mnt/projects/` → `/opt/obd2-server/`). Never run production from NAS mount. Spec at `docs/superpowers/specs/2026-04-15-server-isolation-pattern.md`.
- **Windows is primary dev**: Linux boxes are deployment targets. All code must work on Windows for dev/test.
- **Z: (Windows) === `/mnt/projects/O/OBD2v2` on chi-srv-01** — same NAS share. Edits from Windows land on chi-srv-01 immediately; no scp needed for `.env`, `deploy/*.sh`, etc. Caveat: plaintext secrets in `.env` are visible to anyone with NAS read access.
- **MariaDB datadir on chi-srv-01** lives on root LVM (`/dev/mapper/chi--srv--01--vg-root`), NOT on RAID. RAID failures do NOT affect the project DB. Verify before emergency response with `SELECT @@datadir;` + `df /var/lib/mysql`.
- **Interactive sudo does NOT work through Claude Code's `!` prefix** — hangs on password prompt with no input path. Route sudo work via (a) user's terminal with paste-back, or (b) `NOPASSWD` in `/etc/sudoers.d/` for specific binaries.
- **.env legacy-stub trap**: `DB_SERVER`, `DB_DRIVER`, `API_CLIENT_ID`, `API_CLIENT_SECRET`, `API_TOKEN_URL` are treated as "critical vars" by `validate_config.py:74` and `tests/conftest.py:169`. Cannot remove them from `.env` without updating validator + tests in lockstep.
- **Unix_socket MariaDB admin pattern**: on a box where the OS user is the intended DB admin, use `CREATE USER 'u'@'localhost' IDENTIFIED VIA unix_socket; GRANT ALL ON *.* WITH GRANT OPTION;` — passwordless from the CLI when logged in as that OS user, full admin rights.

## Design
- **Supersede, don't patch**: when a new design approach makes old PRDs obsolete, create a clean new spec absorbing old stories. Don't edit scattered old docs.
- **Validation-first for mature codebases**: Pi has 164 files — crawl phase proves what works, not writes new code.

## Testing
- Test baseline post-reorg: 1488 collected (1469 passed, 19 deselected fast; 1487+1 skipped full)
- Test baseline post-Sprint 7: 1720 passed (+251 from server-crawl stories), 3 pre-existing failures
- `stories.json` → renamed to `sprint.json` 2026-04-15; uses `passes` field (not `passed`)
- ralph_agents.json has `type`, `lastCheck`, `note` fields — richer than DW template
- agent.md must be lowercase for Pi (Linux case-sensitive FS)
