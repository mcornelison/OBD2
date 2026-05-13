# B-079: sync_history.started_at and completed_at written in different timezones (5h CDT/UTC offset) in the same row

| Field | Value |
|---|---|
| Priority | Low (P3) |
| Status | Pending (XS -- fold into B-076 epic OR a V0.27.8 mini-sprint; CIO decides) |
| Category | sync / timestamps / TD-027-class |
| Size | XS |
| Related | TD-027 (naive-timestamp sweep, Sprint 14 US-202/US-203 -- this is a missed writer in that class); B-076 (sync_history is renamed/restructured in that epic anyway) |
| Created | 2026-05-12 |

## Description

Tester 2026-05-12 live obd2db query: every recent `sync_history` row has `started_at` and `completed_at` differing by EXACTLY 5h00m00s -- a CDT-vs-UTC mismatch *within the same row*. One column is written with a local-time clock, the other with UTC. (5h = America/Chicago CDT offset.)

This is a TD-027-class bug: a naive-timestamp writer that escaped the Sprint 14 sweep. The `sync_history` writer (server-side or Pi-side, whichever populates these two columns) uses inconsistent clocks for the two fields.

## Fix

`rg started_at|completed_at src/` to find the `sync_history` writer; make both columns use the same clock -- UTC, per the TD-027 / `specs/standards.md` convention (canonical ISO-8601 UTC, `strftime('%Y-%m-%dT%H:%M:%SZ', 'now')` on the SQLite side / `datetime.now(timezone.utc)` on the Python side). One of the two is already correct; flip the other to match.

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: locate the `sync_history` writer; identify which of `started_at`/`completed_at` uses the wrong clock
- [ ] Both columns written in UTC; `completed_at - started_at` reflects actual sync duration (seconds, not ~5h)
- [ ] Regression test: a synthetic sync writes both columns; assert they're within seconds of each other (not ~18000s apart)
- [ ] (Optional) one-time fixup of historical rows -- low value; the B-076 prune likely truncates most of them anyway

## Source

- Tester 2026-05-12 db-review note (B-NEW-3)
