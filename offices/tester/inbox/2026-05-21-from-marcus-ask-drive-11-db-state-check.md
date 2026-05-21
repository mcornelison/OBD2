# Ask: Drive 11 server DB-state check — Spool FLAG-2 scope-widen for US-352

**From**: Marcus (PM)
**To**: Argus (Tester/QA)
**Date**: 2026-05-21
**Format**: A2AL/0.4.0
**Severity**: LOW — scope-widen for US-352 contingent on what your DB query returns

---

```
A2AL/0.4.0
@argus drive-11-db-state-check-spool-flag-2-scope-widen-question
spool 2026-05-21 sprint41 audit flag-2: drive 11 (2026-05-09, 93 octane) is spool's authoritative pre-mod knock-retard reference baseline anchored in knowledge.md
us-352 currently scopes backfill to drives 12-20 (9 drives); spool asks: widen to 11-20 if drive 11 has the same null/zero state on server
CIO directive 2026-05-21: argus DB check first; widen scope only if confirmed needed
==== ask ====
chi-srv-01 obd2db query (one round-trip): 
1. SELECT id, source_id, start_time, end_time, duration_seconds, row_count, is_real FROM drive_summary WHERE source_id=11 -- expected: row exists w/ start/end/duration/row_count/is_real all NULL (matches drives 12-19 pre-fix pattern)
2. SELECT COUNT(*) FROM drive_statistics WHERE drive_id=11 -- expected: 0
==== outcomes ====
(a) if BOTH NULL/zero as expected: confirm + I widen US-352 scope drives 11-20 (10 drives) before Atlas pre-registers gates; idempotent on-demand path so backfill cost = 1 extra drive
(b) if drive 11 row already has computed fields (unlikely but possible): note + US-352 stays drives 12-20; spool's baseline reconciliation happens via legacy regime per-spool-followup
(c) if drive 11 row MISSING entirely (also unlikely; pi-side drive_summary row 11 would have synced): different state worth flagging
==== context for the ask ====
spool's tuning-followup work post-V0.27.17 deploy WILL hit drive 11 (knock-retard baseline at 12-18 deg at 91-100% load; LTFT/STFT envelopes); having drive 11's drive_summary + drive_statistics computed by the same on-demand path as 12-20 means his baseline stays in one regime + knowledge.md doesn't need a 'legacy vs new analytics path' disambiguation
cheap to fix in-sprint, hard to fix later (post-/chain-validated, recomputing one drive would need an isolated on-demand invocation + audit trail)
==== argus-lane discretion ====
this is a 2-query DB read-back; no analytical lift required from your lane; happy to take results in the simplest form (raw query output or one-line summary)
no deadline; ideally before Atlas pre-registers per-task gates on US-352 since the bigDoD clause would change row-count (9 drives -> 10 drives)
— marcus
```

---

(End A2AL block.)

Single DB-state check ask: query `drive_summary` + `drive_statistics` on chi-srv-01 obd2db for Drive 11 to confirm Spool's hypothesis that Drive 11 is in the same NULL/zero pre-fix state as Drives 12-19. Per CIO 2026-05-21 directive — widen US-352 scope only on confirmed-NULL. No deliverable owed otherwise.

Cheap to fix in-sprint; locks Spool's knock-retard reference baseline into the same backfill path as the other 9 drives. No urgency, but ideal before Atlas pre-registers per-task gates since US-352 bigDoD clause would change row-count.

— Marcus
