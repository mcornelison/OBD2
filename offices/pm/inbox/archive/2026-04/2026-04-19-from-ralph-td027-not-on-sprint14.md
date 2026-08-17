# From Ralph → Marcus (PM) — TD-027 filed but missing from Sprint 14

**Date:** 2026-04-19 (Session 24)
**Subject:** TD-027 (timestamp accuracy + format consistency) — filed at CIO direction, not present on Sprint 14 contract. Two stories on Sprint 14 assume trustworthy timestamps. Flagging so you can decide: fold in, explicitly defer, or waive.

## What I filed

`offices/pm/tech_debt/TD-027-timestamp-accuracy-and-format-consistency.md`

Filed at CIO direction following Spool's "~23 second data window" review, which CIO disputes — actual drill was several minutes. Two threads in one TD:

1. **Thread 1 — computed elapsed time is wrong.** Most likely cause: `connection_log` only writes on OPEN/CLOSE transitions, so `MAX-MIN` per session captures event-to-event gap, not true wall-clock span. Recommended fix: heartbeat rows or `session_duration_seconds` field on close.

2. **Thread 2 — format / tz inconsistency across write paths.** Three coexisting timestamp patterns in the Pi tree for `connection_log` (and likely others):
   - SQLite `DEFAULT CURRENT_TIMESTAMP` → `YYYY-MM-DD HH:MM:SS` (space separator, no Z)
   - Explicit Python INSERT via `switcher.py`, `data_retention.py`, `drive/detector.py` — tz semantics vary; some may be naive local (WRONG on Pi in America/Chicago)
   - `sync_log.py:136` ISO-8601 with `T` + trailing `Z` (correct, UTC-aware)

   Result: a single `connection_log` table can hold rows in two different string formats, depending on which code path wrote the row. `sync_log.py`'s own docstring (lines 132-134) claims its format matches `connection_log` — but the `DEFAULT CURRENT_TIMESTAMP` path does NOT produce `T` or `Z`, so the docstring is wrong or the two coexist. Any `ORDER BY timestamp` or `BETWEEN` query gives mixed semantics.

## Proposed technical solution (full detail in TD body)

1. **Schema-level unification**: replace `DEFAULT CURRENT_TIMESTAMP` with `DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))` in `database_schema.py`.
2. **Single helper**: extract `sync_log.py:136` pattern into `src/common/time/` as `utcIsoNow()`. All Python-side timestamp writes route through it.
3. **Audit pass**: grep every `INSERT INTO .*log` and `INSERT INTO realtime_data`, document write-path in an inline comment or short audit table, confirm UTC + canonical format everywhere.
4. **Tests**: `tests/pi/data/test_timestamp_format.py` asserts: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` regex match on stored rows; naive `datetime.now()` is guarded; DEFAULT and explicit paths produce the same string shape for a fixed moment.
5. **Spec**: document the canonical format in `specs/standards.md` so future code reviews catch drift.
6. **Investigation sub-task** for Thread 1: run `SELECT event_type, timestamp FROM connection_log ORDER BY timestamp` on the Session 23 `obd.db` (before fixture export overwrites it) and decide whether the 23s discrepancy is (a) gap-between-events, (b) format-mix-corrupts-delta, or (c) something else. The answer determines whether Thread 1 needs its own follow-up story.

Sizing feel: **S or low-M**. ~4-5 files: `database_schema.py`, new `src/common/time/helper.py`, three call-site cleanups, one test file. ~200-300 lines diff. No migration of existing data rows required for the fix itself, though the regression fixture export (US-197 AC) should happen BEFORE the DEFAULT change lands so the Session 23 snapshot preserves original strings.

## Why it bears on Sprint 14 directly

TD-027 is NOT cosmetic — two current Sprint 14 stories depend on timestamp trustworthiness:

- **US-195** (`data_source` column, CR #4) — the whole point is to filter analytics + AI inputs on `data_source = 'real'` + a time window. If the time-window filter is broken by format mix, the filter gate is leaky from day one.

- **US-197** (US-168 carryforward, regression fixture export) — the AC explicitly uses `WHERE data_source='real' AND timestamp BETWEEN Session-23-window` (line 549). `BETWEEN` on strings is lexicographic. If some rows are `'2026-04-19 07:15:00'` (space) and others are `'2026-04-19T07:15:00Z'` (T+Z), the BETWEEN returns wrong rows — and we ship a polluted fixture as the canonical cold-start capture.

## Options for you (pick one)

- **(a) Fold into Sprint 14** as a new story (US-202?) — at the front of the sprint so US-195 and US-197 land on top of a clean timestamp foundation. Sizing S-M.
- **(b) Fold into Sprint 14 as US-197's scope creep** — add a Step 0 to US-197 that does the unification before the fixture export. Risks bloating the story past size cap; probably cleanest as a separate story.
- **(c) Defer to Sprint 15+**, add explicit stop-condition to US-197 that says "if timestamp strings in Session 23 obd.db are NOT all uniform ISO-8601Z, stop and surface to PM before exporting the fixture" — preserves the fixture integrity even if the root cause lives another sprint.
- **(d) Waive if you believe the risk is overstated** — e.g., if you know every production write path already goes through the ISO-8601Z helper (and the DEFAULT CURRENT_TIMESTAMP rows are only in cold-init tables that never grow) then the concern may be theoretical. I can re-check if you want me to. But the mixed-format evidence in `connection_log` is visible right now in `/pi/obdii/obd_connection.py:445` (no timestamp column → uses DEFAULT) vs `/pi/profile/switcher.py:607` (explicit column → depends on caller).

Recommendation: **(a)** — small story, clean semantics, unblocks US-195/197 correctness. Sprint 14 is already 11 stories so a 12th S-story is within workflow norms.

## What I'm NOT doing

- NOT touching code. TD filed at CIO direction; technical solution drafted in the TD body + here; waiting on PM decision and sprint assignment per Scope Fence rule.
- NOT re-reading Sprint 14 contract further — my `/init-ralph` caught an earlier version; this note is based on a targeted grep for TD references + the timestamp-related story text. If Sprint 14 has evolved again since this grep, trust your version of truth.

— Ralph (Rex, Agent 1)
