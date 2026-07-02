# Issue: 4 historical orphaned `production` drain_event rows in the live Pi DB

**Filed by:** Rex (Dev), 2026-07-02, during US-434 (Sprint 53 / V0.29.7).
**Severity:** Low (historical residue; no active-code defect; benign to analytics baselines that filter on `end_timestamp`).
**Scope:** Data-hygiene decision on the live Pi DB (+ already-synced server rows) — a **PM/Atlas ruling**, not a code change. Filed per US-434 AC2 ("flag PM/Atlas first, do NOT build unflagged") and Refusal Rule 1.

## Summary

US-434 (F-062) is a **verify-first** story: confirm drain_event rows close cleanly on
poweroff, else flag. Verification result is a THIRD case the story's two AC branches
did not fully anticipate:

- **Forward-looking = MOOT (no code warranted).** There are **0 production callers** of
  `BatteryHealthRecorder.startDrainEvent` / `endDrainEvent` in `src/` (grep for
  `.startDrainEvent(` / `.endDrainEvent(` → no matches; the last dead store was removed
  in TD-058 / US-427, `hardware_manager.py:73`). Nothing opens a drain during operation,
  so **a poweroff can never orphan one going forward.** A targeted close in
  ShutdownSequencer (US-434 AC2) would be dead code and could not fix the historical rows.
  The only live writer is the bench CLI `scripts/record_drain_test.py`, which opens **and
  immediately closes** a drain in one operator-driven run (docstring lines 5-6, 445 — "the
  row lands as a single unit"), and since US-224 it defaults to `load_class='test'`.

- **Residue = 4 historical orphaned rows.** The live Pi DB
  (`/home/mcornelison/Projects/Eclipse-01/data/obd.db`, `battery_health_log`) has **4 rows
  with `end_timestamp IS NULL`**, all `load_class='production'`:

  | drain_event_id | start_timestamp      | end_timestamp | runtime_seconds |
  |----------------|----------------------|---------------|-----------------|
  | 1              | 2026-05-04T13:21:08Z | NULL          | NULL            |
  | 9              | 2026-05-09T01:47:10Z | NULL          | NULL            |
  | 18             | 2026-05-12T01:37:29Z | NULL          | NULL            |
  | 21             | 2026-05-13T19:29:08Z | NULL          | NULL            |

  (28 rows total; newest of any row = 2026-05-16T01:54:27Z — nothing new since.)

## Root cause of the residue (now-removed path)

These are **not** current-code defects. `load_class='production'` was written by the
**US-216 auto-write path** (`battery_health.py:40` "current production callers",
`:155-159` "library-level `LOAD_CLASS_DEFAULT` stays 'production' — that feeds US-216's
auto-write path"). That auto-open path existed in early May, opened `production` drains,
and on those 4 occasions the shutdown did not close them — i.e. **F-062 was a real bug
while that path was live.** The path has since been retired (culminating in the
TD-058 / US-427 dead-store removal), so no new orphans can form. The 4 rows are frozen
residue from that era; the bench CLI's `test` default (US-224) means bench runs since
late April are not implicated.

## Why no code was written for US-434

1. No **current** open-path exists (0 callers) → nothing to close on poweroff → the F-062
   mechanism is moot forward-looking.
2. A ShutdownSequencer close cannot retroactively close rows opened weeks ago by a
   deleted path.
3. Closing/backfilling the 4 rows is a **data-repair on the live Pi DB** that would also
   need to reconcile the **already-synced server copies** (`battery_health_log` →
   server, `drain_event_id` is the sync PK). That is a runtime data-migration decision,
   not a `src/` change, and it touches BL-015 semantics (a real drain vs. a ~10s
   shutdown) — squarely a PM/Atlas call.

## Recommended options (for PM / Atlas)

- **(A) Leave as historical residue.** Analytics runtime-trend baselines already require a
  non-NULL `runtime_seconds` (and thus a closed row), so these 4 open rows are excluded
  from trends today. Lowest risk; the DB simply carries 4 known-benign artifacts.
- **(B) Backfill a synthetic close.** Set `end_timestamp` (e.g. to the next boot's first
  timestamp, or the known poweroff time) + compute `runtime_seconds`, on **both** the Pi
  and the server, as a one-shot data-repair (its own tiny story) with `notes` marking it
  a reconstructed close. Cleaner DB; requires a careful both-tier migration.
- **(C) Tombstone.** Add a `notes='orphaned-US216-autowrite-residue'` tag without inventing
  an end time, so the rows are self-documenting.

No option changes `src/` behavior going forward — this is purely disposition of 4 legacy rows.

## Evidence commands (read-only, reproducible)

```bash
# 0 production callers:
rg '\.startDrainEvent\(|\.endDrainEvent\(' src/    # -> no matches

# Live-Pi orphan query (read-only):
ssh mcornelison@10.27.27.28 "sqlite3 -readonly \
  /home/mcornelison/Projects/Eclipse-01/data/obd.db \
  \"SELECT drain_event_id, start_timestamp, load_class \
    FROM battery_health_log WHERE end_timestamp IS NULL ORDER BY drain_event_id;\""
```
