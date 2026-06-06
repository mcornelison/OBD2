# Atlas → Marcus — Drive-27 single-attribution IRL gate: **PASS** (A-9 closed)

**From:** Atlas (Architect) · **To:** Marcus (PM) · **Date:** 2026-06-05
**Re:** the drive-27 single-attribution IRL drill — the drive-side gate for the V0.28 chain (Sprints 43/44/45)

## Verdict: PASS

The drive-27 IRL drill is green. First attempt today scrubbed (dongle unplugged, zero OBD
capture — documented, system stayed honest). The **re-drive (dongle seated) captured and synced
cleanly as server `drive_id=27`**, and the authoritative recompute confirms single-attribution.

## Evidence (chi-srv-01 prod, verified directly)
- `drive_summary` 27 after `recompute_drive_analytics --drive-id 27`:
  `start 2026-06-06 01:09:59 · end 01:22:36 · duration 757s · row_count 4771 · is_real=1 · data_quality=full`
- `drive_statistics`: 16 params / 4771 samples computed.
- Recompute result: `success=1 failed=0 attribution_anomalies=0`.
- **Single** `drive_id` (no phantom drive 28).
- Direct A-9 parallel-stream check: **0** timestamps with divergent RPM values (the exact
  drives-23/24 dual-emission signature — absent).

**Conclusion:** the V0.28.0 F-107 DriveDetector fix (US-359..364) holds IRL. The dual-attribution
defect (A-9) does not reproduce on a real drive. **A-9 is CLOSED on my Watch List.**

## What this unblocks (your lane)
This satisfies the drive-side requirement for the accumulated **43/44/45** chain. You can proceed:
**`/sprint-validated` (43/44/45) → `/chain-validated`** to land V0.28 to main, per the standing plan.
(F-005/F-007 HOLD release rides this, as previously noted.)

## Note
I ran `recompute_drive_analytics --drive-id 27` on prod to populate the summary + produce the
verdict — idempotent, the same step run for drives 23/24/25 under US-364. Nothing else changed on prod.

— Atlas
