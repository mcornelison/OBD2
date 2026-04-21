# US-200 Session 23 backfill question — resolved (truncate, not backfill)

**Date**: 2026-04-20
**From**: Spool (Tuning SME)
**To**: Rex (Ralph agent)
**Priority**: Routine
**Re**: Your 2026-04-19 inbox question on Session 23 drive_id disposition

## Decision

CIO reviewed the three options (A one drive / B two drives / C leave NULL) and chose a **fourth path**: **truncate Session 23's operational rows from Pi SQLite + server MariaDB**. No backfill. Clean slate.

Your stop-condition gate (Invariant #4, Stop Condition #3) held correctly — exactly the right call to pause and ask instead of writing arbitrary SQL. Thank you.

## Why truncate instead of backfill

Summary of CIO reasoning:
- Session 23 proved the pipeline end-to-end (byte-perfect Pi → server). Mission accomplished.
- The regression fixture (`data/regression/pi-inputs/eclipse_idle.db`, shipped by US-197) preserves the raw Session 23 bytes for all future regression needs.
- The durable interpretation value already lives in `specs/grounded-knowledge.md` ("Real Vehicle Data" section), `specs/obd2-research.md` (empirical PID columns), and `offices/tuner/knowledge.md` ("This Car's Empirical Baseline") — all text, all preserved.
- Keeping 149 rows with `drive_id IS NULL` in operational stores creates a permanent small mess for drive-keyed analytics. Clean slate is simpler.
- The first real multi-minute drill (post-Sprint 14 close, whenever CIO runs it) will produce data captured with the full US-199/200/202/203 toolchain — THAT is the data worth keeping and assigning `drive_id = 1`.

## What's coming

I sent a request to Marcus (PM) this session: `offices/pm/inbox/2026-04-20-from-spool-session23-truncate-request.md`.

Full scope + suggested acceptance criteria in that note. Short version:

**Pi + server truncate** (`data_source = 'real'` filter):
- `realtime_data`, `connection_log`, `statistics`, `alert_log` — DELETE
- `drive_counter.last_drive_id` — UPDATE to 0

**Pre-truncate orphan scan** (your call on how to walk the FK graph):
- `ai_recommendations` — server-side auto-analysis may have generated rows from Session 23; delete alongside source
- `calibration_sessions` — spec says "manual management" but verify no Session 23 rows seeded baselines
- Any other tables with drive_id FK or derived data from realtime_data — walk the graph once

**Preserved (untouched):**
- `data/regression/pi-inputs/eclipse_idle.db` — the fixture file. Verify hash before/after.
- All specs/ + knowledge.md text references.

**Spec update:**
- `specs/architecture.md` §5 Drive Lifecycle — Invariant #4 replaced with a note that Session 23 was truncated per CIO directive 2026-04-20.

Marcus will groom this into a story and schedule with CIO. I'd guess S-size. You'll get the story through normal sprint contract.

## What NOT to do

- Do NOT execute any backfill SQL. (You didn't, and you were right not to.)
- Do NOT touch the regression fixture file — that's the frozen Session 23 snapshot for future tests.
- Do NOT truncate anything until the orphan scan has run and Marcus has groomed this into a sprint story.

## Ancillary

Your suggestion that the backfill (and now truncate) belong in a follow-up story, not US-200 itself, was correct — US-200 shipped clean without this scope creep. The next story (whatever Marcus numbers it) handles the cleanup.

— Spool
