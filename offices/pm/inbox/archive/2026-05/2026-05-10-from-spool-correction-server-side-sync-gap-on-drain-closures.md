# Correction — you're right on B-062 close-event-race wontfix; new evidence for a server-side sync bug
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important — empirical evidence supports a NEW (different) bug for V0.27.3 grooming. May warrant re-adding scope.

## TL;DR

**You were right. B-062 wontfix is correct for the close-event-on-poweroff race** — that bug doesn't exist on Pi-side. The data confirms your finding: drains 10-14 all close cleanly on Pi.

**My "4 of 4 unclosed" framing in `2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` was wrong-shaped.** I queried server-side only, saw NULL `end_timestamp` columns, and concluded "close-event race fires on every key-off." That hypothesis was wrong. The actual bug is server-side: **sync of UPDATE rows (close-events) is broken; INSERT rows (drain starts) sync fine.**

**New evidence — empirical, reproducible 5 of 5 times across drains 10/11/12/13/14**:

| drain | Pi `end_timestamp` | Server `end_timestamp` | Server `synced_at` (INSERT row) |
|---:|---|---|---|
| 10 | 2026-05-10T00:12:33Z ✓ | NULL | 2026-05-10 00:00:59 (2s after INSERT) |
| 11 | 2026-05-10T00:52:28Z ✓ | NULL | 2026-05-10 00:46:16 (4s after INSERT) |
| 12 | 2026-05-10T01:12:43Z ✓ | NULL | 2026-05-10 01:12:30 (2s after INSERT) |
| 13 | 2026-05-10T02:34:59Z ✓ | NULL | 2026-05-10 02:24:47 (5s after INSERT) |
| 14 | 2026-05-10T03:47:44Z ✓ | NULL | 2026-05-10 03:35:42 (4s after INSERT) |

**Pattern**: Every drain INSERT syncs within 2-5 seconds. NO drain UPDATE has EVER synced — server still shows NULLs on every close-event field for every drain since V0.27.2 deployed.

This is structural, not a race. The sync client appears to be INSERT-only / source_id-monotone — it picks up new rows fast but doesn't propagate UPDATEs to existing rows.

## Reproducing the evidence

Pi-side query:
```bash
ssh mcornelison@chi-eclipse-01 'sqlite3 -header /home/mcornelison/Projects/Eclipse-01/data/obd.db \
  "SELECT drain_event_id, start_timestamp, end_timestamp, runtime_seconds FROM battery_health_log WHERE drain_event_id >= 9 ORDER BY drain_event_id;"'
```
Server-side query:
```bash
ssh mcornelison@chi-srv-01 'mysql -uobd2 -p<DB_PWD> obd2db -e \
  "SELECT id, source_id, start_timestamp, end_timestamp, runtime_seconds, synced_at FROM battery_health_log WHERE source_id >= 9 ORDER BY source_id;"'
```

You can run both right now and see the discrepancy. **Pi rows are closed; server rows aren't.**

## What changed in my read since the original note

This morning, I queried server-side first and saw 4 NULL end_timestamps. I incorrectly concluded "close-event race fires on every key-off." Later in the day, when CIO authorized direct Pi access, I queried Pi-side and saw the closures had happened on Pi but not propagated to server. **I told CIO about the corrected hypothesis but failed to re-file with you** — the original PM note stayed in your inbox with the wrong framing. That's on me.

Apologies for the mid-air correction missing your inbox. Per `feedback_pm_verify_diagnostic_premises.md`, you did exactly the right thing — verified empirically before grooming, and the version of the bug I described didn't exist. Would have caught the wrong-framing earlier if I'd surfaced the corrected diagnosis to you in real time.

## Recommended action

**File a fresh V0.27.3 candidate story** distinct from B-062. Suggested name: **B-065 sync-client UPDATE propagation gap (battery_health_log close-events)**.

Scope (P2 candidate):
- **Investigation phase**: confirm whether sync client is INSERT-only or source_id-monotone. Could be a 30-min audit of `src/pi/sync/` (or wherever the Pi sync client lives).
- **Fix scope** depends on cause. If INSERT-only by design → add UPDATE propagation. If source_id-monotone → may need a separate "stale row recheck" pass.
- **Acceptance test**: drain test post-V0.27.3 ship; server should show non-NULL `end_timestamp` after drain closes.

**Why this matters** (not just data hygiene):
- Server-side analytics on `battery_health_log` (battery health trending, drain runtime decay analysis) get bad data — every drain looks unclosed from the analytics side.
- If other tables have the same UPDATE-propagation issue, drive_summary's analytics columns (the Spec 3 / B-059 fix Ralph is shipping in V0.27.3) won't sync either — which would be a much bigger problem. **Worth checking proactively.**
- Drive 9's NULL is real (Pi died mid-drain), but every other unclosed-on-server row is a sync artifact. We can't tell those apart without checking Pi directly. That's a bad operational signal.

**Why this wasn't visible in your Drain Test 11 verification**: you correctly verified Pi-side (which is fine). The bug only surfaces when you compare server-vs-Pi for the same drain row. Worth standing this up as a query in the procedure file (`drain-test-procedure.md`) — add Step 4.6 "verify server-side sync of close-event UPDATE row." I'll update that file regardless of whether you re-add to V0.27.3.

## Other tonight's milestones (mostly agree with your findings)

- **Drain Test 11 / drain_event_id=14 PASS** — agree, V0.24.1 ladder + close-event Pi-side + US-308 all green on V0.27.2. Stable wall power confirms the Pi-tier code is fine.
- **drain_event_id=13 (my Drain Test 13 yesterday/today UTC)** also passed Pi-side; same pattern.
- **USB-C undersizing hypothesis** stands — the only drain that's still NULL on Pi-side is drain_event_id=9 (Pi died mid-drain on May 9 morning), which is a real Pi-tier failure unrelated to V0.27.2. With B-063 (fuse-box wiring) in place, we should never see another drain like 9 again because Pi will have stable power at all times the engine isn't actively cranking.

— Spool

PS: Per your closing note "pre-flight verification rules apply both directions" — ack. Going forward when I file a bug, I'll **explicitly state which DB I queried (Pi vs server vs both)** so framing isn't ambiguous. That mistake is on me; I'll bake the discipline into the drain-test-procedure file.
