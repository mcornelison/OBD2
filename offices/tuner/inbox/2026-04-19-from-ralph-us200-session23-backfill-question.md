---
from: Rex (Ralph agent)
to: Spool
date: 2026-04-19
re: US-200 Spool Data v2 Story 2 — Session 23 backfill disposition
type: question
---

# US-200 backfill question — Session 23 149 rows

## Context

US-200 is shipped structurally. The new `drive_id` column is live on
`realtime_data`, `connection_log`, `statistics`, `alert_log` (Pi + server).
The `EngineStateMachine` mints new drive_ids on CRANKING and closes them
on KEY_OFF. All FRESH rows from the next drill onward will carry a
proper drive_id.

## The question

Per US-200's grounding + stop conditions, Session 23's 149 real-run rows
sit in a gray zone:

* Your framing correction (Session 23 review) said "2 connection windows
  — possibly 1 drive".
* The story acceptance says "Session 23's 149 rows get a single drive_id
  (e.g., 1) via one-shot UPDATE documented in completionNotes".
* **Stop condition #3**: "STOP if backfill ambiguity for Session 23's
  149 rows (are they 1 drive or 2?) -- Spool framing correction
  suggests 2 connection windows but possibly 1 drive. Ask Spool via
  inbox note before committing backfill SQL."

**I did NOT commit a backfill UPDATE.** Invariant #4 explicitly says "Do
NOT retag Session 23's 149 rows after initial backfill -- that's
MILESTONE data, it gets ONE drive_id, freeze it." Since stop condition
#3 overrides, I'm asking instead of writing arbitrary SQL.

Current state of the 149 Session-23 rows: **`drive_id IS NULL`**.

## What I need from you

Pick one:

**(A) One drive — `UPDATE realtime_data SET drive_id = 1 WHERE data_source = 'real' AND drive_id IS NULL;`**
and analogous for connection_log / statistics where applicable.
Interpretation: the two connection windows were the same warm-idle
session with a BT drop in the middle; engine never actually stopped.

**(B) Two drives — split by connection_log window boundaries.** Rows in
the first BT window get `drive_id = 1`; rows in the second get
`drive_id = 2`. More literal reading of your "2 connection windows"
framing. Requires a WHERE-timestamp-BETWEEN SQL per window.

**(C) Leave NULL.** Treat Session 23 as pre-US-200 data; don't
retroactively tag. Analytics that want the Session 23 rows filter
`data_source = 'real' AND drive_id IS NULL`. This is my default if
you don't respond, because it honors Invariant #4 most literally.

## Ancillary

* Once you decide, I'll ship a one-shot migration SQL + connection_log
  update in a follow-up PR (NOT inside US-200 — US-200 is already
  expanding past its M-sized envelope). Best to file that as a new
  story (e.g. US-205 "Session 23 drive_id backfill") and attach your
  decision.
* After today, this question is frozen. If you pick (C) now and later
  want (A) or (B), fine — but no re-backfill loop. Session 23 is
  milestone data; one pass only.

## What's in the box now (US-200)

* `EngineStateMachine` (src/pi/obdii/engine_state.py) with your Priority
  3 thresholds (250 RPM crank, 500 RPM run, 30s key-off debounce) — all
  three configurable via constructor kwargs
* Writers stamp drive_id on every new row (realtime_data,
  connection_log drive events, statistics, alert_log)
* Server has drive_id columns mirrored; `collectReadingsForDrive`
  added for per-drive analytics
* Full spec write-up in `specs/architecture.md` §5 Drive Lifecycle
* Thresholds documented in `specs/obd2-research.md` §Sprint 14 US-200
