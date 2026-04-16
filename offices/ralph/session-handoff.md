# Ralph Session Handoff

**Last updated:** 2026-04-16, Session 18
**Branch:** sprint/server-crawl
**Last commit:** `30af4f0` docs: Session 17 closeout — Sprint 7 complete + deployment tested

## Quick Context

### What's Done
- Session 18 was an infrastructure/DB setup session with the CIO — no code changes
- Confirmed chi-srv-01 MariaDB 11.8.6 running cleanly; RAID failure did NOT affect DB (data is on root LVM)
- Created `obd2db` and `obd2db_test` via `deploy/setup-mariadb.sh` with a generated 24-char password
- Created MariaDB users `obd2@localhost` and `obd2@10.27.27.%` with ALL PRIVILEGES on both DBs
- Updated project `.env` with full server config block (DATABASE_URL, PORT, OLLAMA_*, BACKUP_*, analytics thresholds) — legacy SQL Server / OAuth2 stubs preserved (validate_config.py still references them)
- End-to-end login verified from chi-srv-01 as `obd2@localhost` — both DBs visible
- Inbox note sent to Marcus: `offices/pm/inbox/2026-04-16-from-ralph-chi-srv-01-mariadb-setup-complete.md`
- CIO to run command for `mcornelison@localhost` unix_socket admin user on chi-srv-01 (provided in chat, not yet executed)

### What's In Progress
- Nothing active. Sprint 7 is 9/9 complete per sprint.json, deployment tested (Session 17 closeout commit).

### What's Blocked
- No blockers.

### Test Baseline
- 1720 passed (+251 from Sprint 7 per MEMORY.md), 3 pre-existing failures
- Did not re-run tests this session (no code changes)

### Sprint State
- Sprint 7 (Server Crawl, B-036): 9/9 stories `passes: true` in `offices/ralph/sprint.json`
- Sprint branch `sprint/server-crawl` has 12 commits ahead of `main`, ready to merge

### Agent State
- Rex: unassigned — ran Session 18 (MariaDB/env setup with CIO)
- Agent2: unassigned — last ran Session 26 (US-160 CLI reports)
- Agent3: unassigned (stale Jan 2026)
- Torque (Pi): unassigned (stale Jan 2026)

## What's Next (priority order)
1. **CIO runs mcornelison admin-grant command** (one-liner with unix_socket plugin, provided in Session 18 chat)
2. **Merge `sprint/server-crawl` → `main`** (12 commits, Sprint 7 clean)
3. **Marcus creates Pi Crawl sprint** from the Pi-side crawl/walk/run spec (still outstanding per Session 17 handoff)
4. **Materialize MariaDB tables** — run SQLAlchemy `Base.metadata.create_all()` against live `obd2db` (or Alembic if we want migrations from day one) — may become a dedicated story US-CMP-003b
5. **Address I-011 (sync/async driver) and I-012 (env var naming)** flagged in MEMORY.md

## Key Learnings from This Session
- **MariaDB data dir was NEVER on RAID** — lives on `/dev/mapper/chi--srv--01--vg-root` (LVM on root disk). CIO's concern about RAID loss affecting the DB was unfounded. Worth remembering if RAID issues recur — no emergency recovery needed for MariaDB.
- **Interactive sudo does NOT work through Claude Code's `!` prefix** — password prompt hangs silently. For sudo work over SSH, either (a) ask CIO to run the command in their own terminal and paste output, or (b) set up `NOPASSWD` in `/etc/sudoers.d/` for specific binaries.
- **Z: (Windows) = `/mnt/projects/O/OBD2v2` (chi-srv-01)** — same NAS share. `.env` edits from Windows land immediately on chi-srv-01. Good for config sync; be aware of visibility (NAS readable by anyone with access).
- **`.env` has legacy stubs that can't just be wiped** — `DB_SERVER`, `DB_DRIVER`, `API_CLIENT_ID`, `API_CLIENT_SECRET`, `API_TOKEN_URL` are treated as "critical vars" by `validate_config.py` and `tests/conftest.py`. Any `.env` refactor has to update those files in lockstep. Candidate for future tech-debt cleanup.
- **Chi-Srv-01 real IP is `10.27.27.10`**, NOT `.120` as `specs/architecture.md` still claims. `~/.ssh/config` uses the correct IP. MEMORY.md was updated mid-session but still shows .120 — next knowledge-update pass should sync both.
