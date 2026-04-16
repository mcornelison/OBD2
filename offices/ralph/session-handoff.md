# Ralph Session Handoff

**Last updated:** 2026-04-15, Session 16
**Branch:** main
**Last commit:** `5d59f9f` docs: server isolation pattern spec + fix .gitattributes gaps

## Quick Context

### What's Done
- Server-side crawl/walk/run architecture spec — approved, committed (`5f7459d`)
- Pi-side crawl/walk/run/sprint architecture spec — approved, committed (`99c3773`)
- Server isolation pattern spec (architect's note) — committed (`5d59f9f`)
- PM inbox notes for both specs — committed (`3d2ca1a`, `99c3773`)
- `.gitattributes` hardened: `eol=lf` on default rule + missing file types (.service, .env, .csv, .html, .css, .js, .gz)
- `core.autocrlf` changed from `true` to `input` on Windows dev machine
- SSH passwordless auth configured for both chi-srv-01 and chi-eclipse-01
- SSH config (`~/.ssh/config`) updated with correct IPs and entries for both hosts
- Pi legacy code investigated: pre-reorg at `a28fa1e`, safe to `git pull`

### What's In Progress
- Nothing — session was design/spec work only, no code changes

### What's Blocked
- No blockers. Both specs awaiting Marcus to process inbox notes, assign story IDs, and create sprints.

### Test Baseline
- 1488 tests collected (unchanged from Session 15)
- No code changes this session — test baseline unaffected

### Sprint State
- No active sprint. stories.json contains only US-145 (completed by Rex 2026-04-12).
- Next: Marcus creates sprints from the two new specs (46 stories total).

### Agent State
- Rex: unassigned — ran Session 16 (design/spec work)

## What's Next (priority order)
1. Marcus processes PM inbox notes — assigns story IDs to 20 NEW stories (8 server + 12 Pi), writes acceptance criteria, creates sprint.json files
2. Server crawl phase (Sprint A) + Pi crawl phase can run in parallel (no cross-dependencies)
3. CIO fixes Chi-Srv-01 static IP assignment (currently `.10`, should be `.120`)

## Key Learnings from This Session
- **Chi-Srv-01 real IP is `10.27.27.10`**, not `10.27.27.120` as documented in architecture.md. DNS/mDNS resolves `chi-srv-01` correctly. CIO aware, network admin task.
- **Pi legacy code**: `/home/mcornelison/Projects/EclipseTuner` on chi-eclipse-01 has pre-reorg code at commit `a28fa1e` (Jan 31, ~60 commits behind main). Same repo, clean `git pull` during crawl phase.
- **Pi hostname**: currently `Chi-Eclips-Tuner`, will be renamed to `chi-eclipse-01` in crawl phase.
- **SSH access**: `ssh chi-srv-01` and `ssh chi-eclipse-01` both work passwordless from Windows dev machine. Use hostnames, not IPs.
- **Windows is primary dev platform**: CIO confirmed. Linux boxes are deployment targets only. Server isolation pattern (rsync deploy boundary) protects production.
- **Existing Pi codebase is large**: 164 Python files across 18 subpackages. Crawl phase is validation/hardening, not greenfield.
