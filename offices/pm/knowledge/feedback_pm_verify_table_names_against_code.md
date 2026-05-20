---
name: PM verifies table names + paths against server/Pi code before grooming, not from CIO conversational observation
description: When CIO observes something casually ("the sync log table on chi-srv-01"), PM (Marcus) MUST verify the actual table/path/symbol name against source code BEFORE writing it into a sprint contract or PRD. Conversational shorthand is not source of truth.
type: feedback
originSessionId: 3d385438-f986-4135-8838-82a0349c2f25
---
CIO 2026-05-05 conversational observation: "I was looking at the sync log on the server and it is trying to sync 5 times a second. there are over 100,000 rows in the DB."

PM 2026-05-05 grooming error: assumed "sync log" meant a literal table named `sync_log`. Wrote `B-053-engine-aware-sync-poll-cadence.md` PRD using `sync_log` throughout. Wrote Sprint 26 US-300 using `sync_log`. Did NOT verify against `src/server/db/models.py`.

Rex 2026-05-08 BL-010 audit caught it: actual server-side table is `sync_history` (`src/server/db/models.py:462`); Pi-side `sync_log` is a separate 10-row cursor table that does NOT grow with attempts. The migration would have failed at deploy time (`DELETE FROM sync_log` against a nonexistent table); deploy-server.sh `set -e` would have halted the deploy mid-flight, blocking V0.26.0 ship.

**Why the failure happened**: PM trusted conversational shorthand as authoritative naming. Mike used "sync log" as a description of intent ("the table that logs sync attempts"), not a literal table name. PM didn't pre-flight-verify because the conversational tone made it feel like an established fact rather than a hypothesis.

**Rule (apply at every sprint grooming + PRD authoring)**:

When CIO references a table name, file path, function name, or symbol in conversational text:

1. **Verify it against source code BEFORE writing it into a contract or PRD.** One `grep -n "class.*Table\|__tablename__" src/server/db/models.py` or one `ls src/server/db/sync_log_schema.py` is enough.
2. **If verification finds a different name**, use the verified name. Do NOT propagate the conversational shorthand into formal artifacts.
3. **If verification is impossible** (CIO references something not in the repo), file as a clarifying question before grooming proceeds. Don't guess.
4. **Phantom-path detection (US-274 lint)** catches phantom file paths in `scope.filesToTouch` but does NOT catch wrong table names in DELETE clauses, intent text, or PRD wording. This rule is the human-side complement to the lint check.

**Anti-patterns this rule prevents**:
- BL-010 class: PM groomed sprint targeting wrong table; Ralph blocked at pre-flight; sprint slot at risk
- "phantom symbol" class: PRD references a class/function that doesn't exist; Ralph wastes audit time
- "conversational drift": same word ("sync log") means different things to different people; PM crystallizes the WRONG meaning into a permanent artifact

**Cheap pre-flight verification commands** (under 30 sec each):
- Tables: `grep -n "__tablename__\|CREATE TABLE" src/server/db/ src/pi/obdii/database_schema.py`
- Classes: `grep -n "^class <Name>" src/`
- Files: `ls <path>` or `find . -name "<name>"`
- Symbols: `grep -rn "<symbol>" src/`

**When to skip the verify**:
- CIO is referencing something they JUST built and the conversation has the actual name
- Reference is in YOUR own prior PM artifact (which you authored with verification)
- Reference is to a well-known canonical name (`main`, `pyproject.toml`, etc.)

**Honest disclosure**: this rule wouldn't have helped if PM had verified against the WRONG file. The full rule is "verify against the file that actually defines the symbol, not against a file that mentions it." For the BL-010 case, `grep "sync_log" src/` would have shown Pi-side hits + zero server-side hits — that pattern alone is the signal.
