# Ralph Session Learnings

Accumulated gotchas, patterns, and CIO feedback. Load on-demand when working, not at startup.

## CIO Feedback (behavioral)
- **Keep deliverables tight** — CIO corrected 900→240 line design. Deliver what was asked; route extras as PM inbox notes. Don't design the surrounding system.
- **Reviewers stay in lane** — no second-guessing other experts' decisions. Value-add edits or silence.
- **No compound bash** — single commands only; chains trigger per-chunk prompts. Use `git -C`, absolute paths, parallel Bash calls.
- **Save knowledge locally** — Ralph-specific knowledge goes in `offices/ralph/knowledge/`, NOT shared auto-memory. Other agents shouldn't load Ralph's context.
- **TDs go into sprints, not worked independently** — Session 59 CIO Q&A: Scope Fence rule (#3) applies both ways. Ralph doesn't touch code outside a story's `scope.filesToTouch`, and a TD outside a sprint has no scope. Path: Ralph files TD → Marcus writes user story from TD → story lands in sprint → Ralph works story. Pattern confirmed in Sprint 14: TD-023 → US-193, TD-024 → US-198, TD-025+TD-026 → US-194 (siblings combined). Do NOT try to "just fix a TD" between sprints.
- **ralph.sh is not self-callable from inside a Ralph session** — Session 59 CIO Q&A: `ralph.sh N` spawns nested `claude -p` CLI instances via `--permission-mode acceptEdits`. Running it from inside an active session clones yourself and has both fighting over the same branch + files. CIO drives ralph.sh from his own shell. If CIO asks yes/no — answer NO, briefly explain the nesting problem.
- **Grep-sample sprint contracts for targeted questions, don't read the whole file** — Session 59 pattern: when CIO asked "is TD-027 on Sprint 14", targeted grep `"id":|"title":|timestamp|TD-\d+` on sprint.json answered in one tool call without polluting execution context with stories I'm not working. Reading the full 812-line sprint.json would have violated the One Source of Truth spirit. Meta-questions about sprint coverage ≠ story execution.

## PM-Artifact Work vs Story Execution
- **PM-artifact work ≠ story execution.** Filing a TD, writing an inbox note, checking coverage — these are "meta" tasks at CIO direction. Scope Fence applies to CODE during STORY EXECUTION. CIO can direct Ralph to do PM-artifact filing any time — the rule is about guarding against speculative code drift, not against all activity outside a story.
- **TD body structure that Marcus likes** (observed from TD-023/024/025/026, applied in TD-027): Table header with Severity/Status/Filed By/Surfaced In/Blocking → "Problem" section (numbered thread enumeration if multiple) → "Expected behavior" or "Proper fix" section with concrete step list → "Acceptance for fix" with testable assertions → "Related" section linking to sibling TDs, blockers, inbox notes. Filed-By line includes session number + date for traceability.
- **PM inbox note structure that Marcus responds to** (observed from Marcus's own notes, applied in the TD-027-not-on-sprint14 note): TL;DR at top with 2-3 sentence summary → "What I filed" with file path → "Proposed technical solution" condensed from the TD → "Why it bears on Sprint N directly" with specific story IDs it affects → "Options for you" enumerated (a)/(b)/(c)/(d) with recommendation explicitly called out → "What I'm NOT doing" paragraph declaring the boundary. Signature with agent name + role tag.

## Timestamp Gotcha (Pi tree — Session 59 finding)
- **`sync_log.py:132-134` docstring is wrong.** It claims the helper's ISO-8601 `T...Z` format "matches the timestamp format used elsewhere in Pi logs (e.g. connection_log)". But `connection_log.timestamp` is `DEFAULT CURRENT_TIMESTAMP` which produces `YYYY-MM-DD HH:MM:SS` (space separator, no `T`, no `Z`). Two coexisting formats in the same table depending on which writer ran. Any `ORDER BY timestamp` / `BETWEEN` / string-comparison query gives inconsistent answers. TD-027 (Session 59) documents. Fix path: unify via SQLite `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))` + a single `utcIsoNow()` helper lifted to `src/common/time/` that every Python-side explicit INSERT routes through. Tests assert regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` on stored rows.
- **Reproducing the inconsistency**: `INSERT INTO connection_log (event_type, mac_address, success, error_message, retry_count) VALUES (...)` (no timestamp column → DEFAULT fires, produces space-format) + `INSERT INTO connection_log (timestamp, event_type, mac_address, success, error_message) VALUES (?, ?, ...)` (explicit column → caller's format wins). Both live paths exist in the tree right now: `obd_connection.py:445` uses pattern A, `switcher.py:607`, `data_retention.py:457`, `detector.py:616` all use pattern B.

## Session-Handoff Rot
- **Session-handoff.md can silently drift multiple sessions out of date.** At Session 59 /init-ralph, handoff showed Session 29 (2026-04-17, branch `main`) while ralph_agents.json showed Rex at Session 58 and git was on `sprint/pi-run`. Handoff hadn't been rewritten across sessions 30-58. When handoff + agent-state disagree, **trust the per-agent state** — it's written on every session close. The handoff is the last person to update that specific file, which may be nobody. If you inherit a stale handoff, don't panic — cross-check agent-state + git log + recent inbox notes, then write a fresh handoff at closeout.

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
