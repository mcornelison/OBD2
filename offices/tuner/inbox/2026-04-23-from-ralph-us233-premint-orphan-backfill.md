# US-233 closed: pre-mint orphan-row backfill (Drive 3, 225 rows)

**Date:** 2026-04-23
**From:** Rex (Ralph agent, Session 103)
**To:** Spool (Tuning SME) + Marcus (PM)
**Story:** US-233 (Sprint 18 P2 — Spool Sprint17 consolidated Section 9)

## Summary

Shipped `scripts/backfill_premint_orphans.py` to associate the 225
NULL-drive_id rows captured during Drive 3's 39-second
BT-connect-to-cranking window with `drive_id = 3`. Policy decision:
**option (a) — post-hoc backfill script** (rejected (b) live state
machine change and (c) document NULL as authoritative).

## Pre-flight audit (AC #1)

`ssh chi-eclipse-01 sqlite3 ~/Projects/Eclipse-01/data/obd.db "..."`
returned:

| Date | NULL-drive_id real-tagged rows |
|------|--------------------------------|
| 2026-04-21 | 188 |
| 2026-04-23 | 225 |
| **Total** | **413** |

Of the 225 rows on 2026-04-23: 221 fall in the 39-sec window
`16:36:10–49Z` (Drive 3 starts at `16:36:50Z`); the other 4 are at
the very edges. Spool's "225 in BT-connect window" is the correct
characterization.

The 188 rows on 2026-04-21 are a separate concern — pre-US-212
pollution era, no subsequent drive within any reasonable cap.
US-227's truncate (filter `drive_id=1 AND data_source='real'`) will
NOT catch them because they are NULL drive_id, not 1. Out of US-233
scope; flagged here for post-US-227 follow-up.

| drive_id | data_source='real' rows |
|----------|------------------------|
| 1 (US-227 target) | 2,939,090 |
| 3 (legitimate) | 6,089 |

## Policy decision (AC #2)

Picked **(a) backfill via script after-the-fact** for these reasons:

1. **Lowest risk.** No changes to the US-200 `EngineStateMachine` or
   the live drive-id minting flow; can't break US-219 review ritual,
   US-214 dual-writer reconciliation, or US-228 cold-start backfill
   timing.
2. **Reuses Sprint 15 patterns.** Same dry-run sentinel + backup-first
   + idempotent-UPDATE shape as `scripts/truncate_session23.py`.
3. **Concrete value for Spool.** Re-tags the 225 rows so the BT-connect
   window becomes part of Drive 3's per-drive analytics — Spool's
   warm-engine fingerprint can include the pre-cranking battery V,
   coolant snapshot, baseline timing.
4. **Honors invariants.** Pre-US-200 rows + the 188 pollution rows
   stay NULL because no drive started within the cap; option (a) doesn't
   conflate them with anything.

Rejected (b) because the stopConditions explicitly warn that changes
to US-200 transitions or interactions with US-219 / US-214 are a
bail-out signal. Rejected (c) because it leaves Spool unable to
include the pre-cranking 39 seconds in his per-drive analysis.

## What ships (per filesToTouch)

| File | Action | Notes |
|------|--------|-------|
| `scripts/backfill_premint_orphans.py` | NEW | 380 LOC; `--db PATH`, `--dry-run` / `--execute` mutex, `--window-seconds N` (default 60), `--max-orphans-per-drive N` (default 1000); idempotent transactional UPDATE; sentinel-gated execute; backup-before-mutation. |
| `tests/pi/obdii/test_premint_orphan_backfill.py` | NEW | 30 tests across 6 classes — scanOrphans (4), scanDriveStarts (3), findOrphanBackfillMatches (10 incl. real Drive 3 + 188 pollution scenarios), applyBackfill (6), safety cap (1), CLI (6). All pass; in-memory SQLite synthesis, no SSH. |
| `specs/architecture.md` Section 5 | MOD | New "Pre-mint orphan policy (US-233)" subsection between drive-end detection (US-229) and Migration. Documents option (a) decision, why not (b)/(c), 6 backfill invariants. |
| `docs/testing.md` | MOD | New "Backfilling pre-mint orphan rows (CIO-facing, US-233)" section: when to run, 6-step CIO procedure, safety gates summary, off-Pi test coverage pointer, "what the script does NOT do" scope-limit list. |
| `src/pi/obdii/engine_state.py` | NOT TOUCHED | Listed in `filesToTouch` but only relevant for option (b). Skipping per scope-fence (parenthetical guidance in story scope). |

## Algorithm (for review)

For each NULL-drive_id real row, find the *nearest subsequent* real
`drive_id` whose `MIN(timestamp)` falls within `--window-seconds` of
the orphan. UPDATE attaches the orphan to that drive. Orphans with
no subsequent drive within the cap stay NULL.

Tested against the actual 225-row scenario (synthesized at the
correct cadence: 39s span / 225 rows → ~5.77 rows/sec). All 225
match drive_id=3 with `--window-seconds 60`.

## Verification

| Step | Result |
|------|--------|
| `pytest tests/pi/obdii/test_premint_orphan_backfill.py -v` | **30 passed in 13.86s** |
| `ruff check scripts/backfill_premint_orphans.py tests/pi/obdii/test_premint_orphan_backfill.py` | All checks passed |
| `python offices/pm/scripts/sprint_lint.py` | 0 errors, 25 warnings (all pre-existing sizing informationals) |
| Fast suite `pytest tests/ -m "not slow" -q` | running at writeup; will be reported in completionNotes |
| Live `--execute` against the Pi | NOT RUN from this session — deferred to CIO discretion. The script is hardened (dry-run sentinel, backup-first, transaction wrapper, per-drive cap) and operator-facing per `docs/testing.md`. |

## Scope-fence honorarium (per refusal rule #3)

`src/pi/obdii/engine_state.py` listed in `scope.filesToTouch` was
NOT modified. The parenthetical guidance in the story scope clarifies
this file is only touched for option (b); option (a) requires no
state-machine change.

## Out-of-scope follow-ups (filed to inbox, not implemented)

1. **188 NULL-drive_id rows on 2026-04-21.** Pre-US-212 pollution era,
   no subsequent drive within any reasonable cap. US-227's truncate
   filter (`drive_id=1`) won't catch them because they are NULL. Worth
   a one-line `DELETE FROM realtime_data WHERE drive_id IS NULL AND
   data_source='real'` AFTER US-227 ships, OR roll into US-227 by
   widening the filter. PM/Spool call.

2. **Server-side propagation of re-tagged drive_id values.** The
   cursor-based sync uses `synced_at`; once a row is synced, an UPDATE
   to its `drive_id` does not re-sync. The 225 orphans on chi-srv-01
   will stay NULL after Pi-side backfill runs. Either: (a) extend the
   sync to detect drive_id changes and re-push, (b) run an equivalent
   server-side SQL update keyed on `(source_device, source_id)` after
   Pi backfill, OR (c) accept divergence (Pi is canonical for
   per-drive queries; server is for cross-drive analytics where the
   pre-mint window is a rounding error). My recommendation: (b) once
   US-226's sync proves stable in production. Filed as a candidate
   Sprint 19 story.

3. **Recurrence prevention.** Future drives with the same
   BT-connect-before-cranking pattern will continue to produce
   orphans. The script is post-hoc cleanup, not a runtime fix. If the
   pattern is sufficiently noisy in steady-state, consider revisiting
   option (b) in a future sprint with explicit US-200 / US-214 /
   US-219 compatibility analysis.

## Post-flight: don't run on the regression fixture

`data/regression/pi-inputs/eclipse_idle.db` is a separate file from
the live Pi DB. The script operates on the path passed via `--db`. As
long as the operator points at `data/obd.db` (or equivalent on the Pi),
the fixture is untouched. No script-side path-or-hash guard added —
keeping the operator runbook the source of truth on what to point at.

— Rex
