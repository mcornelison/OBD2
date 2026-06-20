# TD-039: US-213 server schema migration gate retroactively no-op for drive_summary

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Low                       |
| Status       | **Resolved 2026-04-30 (US-249)** |
| Category     | architecture / process / docs |
| Affected     | `src/server/migrations/`, Sprint 16 retrospective record |
| Introduced   | Sprint 16 US-213 (gate built without authoring the v0004 migration that the gate would have caught was missing) |
| Created      | 2026-04-29                |
| Resolved     | 2026-04-30                |

## Resolution (US-249, Sprint 20)

Closed via two-layer remediation per remediation plan options (b) + (c):

**(b) PRD-template addition** — `offices/pm/prds/_template.md` created. New PRDs lead with a "Schema Impact" gate (one of three checkboxes: server migration required: yes / no / N/A) so the question is forced at grooming time instead of being missed in execution.

**(c) CI schema-diff check** — `scripts/schema_diff.py` implemented. Loads the Pi SQLite schema by executing the canonical CREATE TABLE constants in an in-memory sqlite3 connection (column extraction delegated to PRAGMA table_info, no fragile regex), loads the server schema from `src.server.db.models.Base.metadata.tables`, emits a deterministic JSON diff. Gate trips (exit 1) ONLY when the TD-039 silent-data-loss direction is present: Pi has columns the server lacks (excluding the four documented mirror columns `source_id`/`source_device`/`synced_at`/`sync_batch_id` and the two documented PK rename pairs `battery_health_log.drain_event_id` and `calibration_sessions.session_id`). Server-side extras (analytics columns, PK strategy differences) are reported in the diff for visibility but do not fail the gate -- they don't risk data loss.

Smoke run on current schemas (2026-04-30): 17 Pi tables, 19 server tables, 11 shared, 3 reporting drift (drive_summary / profiles / vehicle_info, all server-side-only by-design extras), 0 gate failures, exit 0.

CI hookup deferred to a future story per US-249 stopCondition #2 (avoid GitHub Actions changes outside the project's existing workflow). Manual usage: `python scripts/schema_diff.py --verbose` from the project root before any deploy that touches a shared capture table; non-zero exit = drift to fix before shipping.

Tests: 23/23 pass in `tests/scripts/test_schema_diff.py` (15 pure-function tests for `computeDiff`, 4 loader smoke tests, 4 CLI exit-code tests).

## Description

Sprint 16 US-213 shipped the "server schema migration gate" — a deploy-time check that runs server migrations and fails the deploy if they don't apply cleanly. Validated as working when it shipped (migrations v0001/v0002/v0003 applied cleanly; gate enforced).

But: the gate is only as effective as the migration list. **No v0004 migration was ever authored for `drive_summary`**, even though Sprint 15 US-206 (cold-start metadata columns) and Sprint 16 US-214 (drive_summary reconciliation) modified the Pi schema and the server-side code that consumes it. As a result, the gate has been a **silent no-op** for `drive_summary`: it ran every deploy, found nothing to do, passed, and the schema drift persisted.

This is a **process gap**, not a code defect. The gate works as designed; what was missing was a discipline of "every Pi-schema-change PR must include the corresponding server migration".

## Why It Was Accepted

It wasn't deliberately accepted — it was overlooked. Sprint 15's US-206 description focused on Pi-side columns; the server-side ripple wasn't called out in acceptance criteria. Sprint 16's US-214 (drive_summary reconciliation) was Pi-internal logic; it didn't touch the server table either.

## Risk If Not Addressed

**As a code-debt item, low risk** — TD-038 fixes the immediate symptom (the missing v0004 migration). If TD-038 ships, the actively-failing sync stops failing.

**As a process-debt item**, the risk is recurrence. Without an explicit rule or check, the next time someone adds a Pi-schema column they may again forget the server-side migration. TD-039 captures the retro lesson so future sprints can:

1. Add a story-template field "server migration required: yes/no/N/A" to PRD grooming
2. Add a CI check that compares Pi schema (sqlite) vs server schema (mariadb) for tables that exist on both — any unaligned column flagged
3. Or just rely on alert-load: if sync starts failing, log + alert quickly so it doesn't go undetected for weeks

**Likelihood: medium (will recur unless process changes). Impact: low (each instance is fixable with one migration once detected). Compound risk: low + medium = low overall.**

## Remediation Plan

**Not blocking; capture and defer.** Three possible remediations, ranked by cost:

**(a) Doc-only**: add a one-liner to `specs/standards.md` under "schema changes" — every Pi-schema PR includes a server-migration partner PR. Free; relies on memory.

**(b) PRD-template addition**: add a "Server migration required?" checkbox to `offices/pm/prds/_template.md` and any new PRD that touches Pi schema. Cheap; catches at grooming time.

**(c) CI schema-diff check**: a script in `scripts/` that diffs Pi sqlite schema vs server mariadb schema for the tables that exist on both, flags unaligned columns. Most expensive; most reliable.

PM lean: **(b)** for now; revisit (c) if TD-038-style drift recurs.

## Related

- **TD-038** (drive_summary schema drift, immediate symptom) — fixes the bug; TD-039 captures the meta-lesson
- **Sprint 16 US-213** (server schema migration gate) — works as designed; content was incomplete
- **Sprint 15 US-206** (cold-start metadata) — Pi-schema change without server-migration partner
- **Source note**: `offices/pm/inbox/2026-04-29-from-spool-chi-srv-01-power-cycle-and-drive-summary-schema-drift.md` Section 2

## Notes

- Optional: this TD can be closed-without-fix if the team decides the discipline is implicit and doesn't need a process change. PM judgment.
