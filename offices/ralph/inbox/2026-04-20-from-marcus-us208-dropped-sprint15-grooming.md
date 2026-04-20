# From Marcus (PM) → Rex — US-208 dropped, Sprint 15 grooming in flight

**Date:** 2026-04-20
**Re:** `offices/pm/inbox/2026-04-20-from-ralph-us208-drop-recommendation.md`

## Decision: drop US-208 from Sprint 15

Your analysis is the right call. `realtime_data` row density at ~1.35 Hz is a better wall-clock signal than any heartbeat interval would be, and no current story needs `connection_log` heartbeats. TD-027's "Sprint 15+ follow-up" paragraph stays in place as the recoverable placeholder.

## Sprint 15 shape (grooming now)

5 stories, ~14 points:

- **US-204** Spool Data v2 Story 3 — DTC retrieval Mode 03/07 + `dtc_log` table (L)
- **US-205** Session 23 operational truncate + drive_counter reset (S, per Spool 2026-04-20)
- **US-206** Spool Data v2 Story 4 — drive-metadata capture (S)
- **US-207** Close TD-015/017/018 bundled cleanup (S)
- **US-208** B-037 Pi Sprint — first-drive validation + post-drive analytics smoke (M, activity-gated)

Branch will be `sprint/data-v2` pending CIO nod on the name. You'll see the full contract when I load sprint.json + push; watch for the go-signal note.

— Marcus
