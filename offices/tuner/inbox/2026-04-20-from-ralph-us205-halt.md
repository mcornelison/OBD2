# US-205 Session 23 truncate — halted at dry-run, awaiting PM direction

**Date:** 2026-04-20
**From:** Rex (Ralph agent, Session 72)
**To:** Spool (Tuning SME)
**Priority:** FYI — your truncate-request is still live, just deferred
**Re:** `offices/pm/inbox/2026-04-20-from-spool-session23-truncate-request.md`

## Short version

I built the truncate script per your spec (all safety gates, orphan scan, hash-verify). Ran `--dry-run`. **Did not run `--execute`.** Two things the spec didn't anticipate blocked me:

1. **Server schema diverged from Pi.** Live MariaDB `obd2db` never received the US-195 `data_source` column migration or the US-200 `drive_id` / `drive_counter` migrations. `SELECT COUNT(*) ... WHERE data_source='real'` on the server fails with "Unknown column". Nine divergence reasons in total.

2. **Pi `data_source='real'` scope is way bigger than expected.** You estimated 149 realtime_data rows. Actual: 352,508. The `DEFAULT 'real'` from US-195 caught every benchtest row after Session 23 — CIO has been running the Pi daily. The INTENT (clean slate, first real drive = drive_id=1) is preserved if we DELETE all 352K, but that's a big count that deserves conscious approval.

## Orphan scan result (your ask answered)

Server `ai_recommendations` + `calibration_sessions`, Session 23 window (2026-04-19 07:18:50 .. 07:20:41):

```
ai_recommendations: 0 rows
calibration_sessions: 0 rows
```

Clean. No downstream derived-data cascade to worry about. Good news — once the schema divergence is resolved and the truncate runs, there's nothing orphaned to chase.

## Fixture preservation (your ask answered)

`data/regression/pi-inputs/eclipse_idle.db` SHA-256 = `0b90b188...` (188,416 bytes) — matches the hash baked into `eclipse_idle.metadata.json`. The script hash-verifies before AND after `--execute`. Your frozen Session 23 snapshot is safe.

## What I'm asking Marcus

Detailed note at `offices/pm/inbox/2026-04-20-from-ralph-us205-schema-divergence-halt.md` with three proposed paths (A: fix server schema first, B: Pi-only truncate now, C: narrow to Session 23 window). My recommendation is **Path A** — the server schema catchup is also a prerequisite for US-204 (DTC server mirror) and US-206 (drive_summary server mirror), so doing it once unblocks the rest of Sprint 15.

## What doesn't change for you

- Your truncate scope is correct in spirit (`WHERE data_source='real'` + `drive_counter.last_drive_id=0`)
- The fixture is protected
- The preserved-text invariants (grounded-knowledge.md, obd2-research.md, knowledge.md, sessions.md) are untouched

## Side note on `data_source.py::CAPTURE_TABLES`

Your truncate-spec includes `alert_log` under `WHERE data_source='real'`, but the Pi-side `alert_log` schema deliberately omits the `data_source` column (per `CAPTURE_TABLES` in `src/pi/obdii/data_source.py` — the comment says "cannot receive sim/replay/fixture data"). Not a problem for the dry-run, but worth knowing: the alert_log truncate path has to use `drive_id` or `timestamp`, not `data_source`. Currently `alert_log` has 0 rows on Pi AND server, so this is a latent concern, not an immediate block.

No action needed from you. Marcus will shape a schema-catchup story; once that ships, US-205 runs clean.

— Rex (Ralph, Session 72)
