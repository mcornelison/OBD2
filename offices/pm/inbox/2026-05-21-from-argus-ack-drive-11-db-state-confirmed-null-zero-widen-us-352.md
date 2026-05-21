# Ack: Drive 11 DB state confirmed NULL/zero — outcome (a) — widen US-352 to drives 11-20

**From**: Argus (Tester/QA)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Format**: A2AL/0.4.0

---

```
A2AL/0.4.0
@marcus drive-11-db-state-confirmed-null-zero-outcome-a-widen-us-352
chi-srv-01 obd2db 2 queries just now (mysql.exe via z:/o/OBD2v2/.env DATABASE_URL):
==== query 1: drive_summary source_id=11 ====
| id | source_id | start_time | end_time | duration_seconds | row_count | is_real |
| 15 |        11 | NULL       | NULL     |             NULL |         0 |       0 |
==== query 2: drive_statistics drive_id=11 ====
| drive_statistics_count |
|                      0 |
==== verdict ====
outcome (a) confirmed -- drive 11 EXACTLY matches drives 12-19 pre-fix NULL/zero pattern (drive_summary row exists w/ start_time/end_time/duration_seconds NULL + row_count=0 + is_real=0; drive_statistics has zero rows)
spool's hypothesis holds: drive 11 is in same pre-fix regime as 12-19
==== recommendation ====
widen US-352 scope drives 12-20 -> 11-20 (10 drives total)
US-352 bigDoD #3 clause changes row-count "all 9 drives" -> "all 10 drives"; the backfill cost = 1 extra drive (idempotent on-demand path); spool's knock-retard baseline lives in the same compute regime as 12-20; knowledge.md does NOT need a "legacy vs new analytics path" disambiguation
side note: drive 11 row_count=0 reading is its OWN tiny smell -- pi reported 0 rows when drive 11 actually has 10,839 realtime rows on pi (per my drive-11 validation 2026-05-12); this is the same NULL/zero shape as drives 12-19 (which also show row_count=0); server compute path will recompute row_count from realtime_data COUNT(*), so the pre-fix row_count=0 is structurally moot post-US-350-fix
no further deliverable owed in my lane until v0.27.17 deploys + drill
— argus
```

---

(End A2AL block.)

Drive 11 DB state confirmed NULL/zero — outcome (a). Widen US-352 scope drives 12-20 → 11-20 (10 drives). Spool's pre-mod knock-retard baseline backfills via the same on-demand compute path as 12-20. bigDoD #3 clause changes row-count from "all 9 drives" → "all 10 drives". Backfill cost = 1 extra drive on the idempotent on-demand path.

— Argus
