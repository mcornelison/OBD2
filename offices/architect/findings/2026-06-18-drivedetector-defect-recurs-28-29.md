# Finding — DriveDetector defect RECURS on drives 28/29 (A-9 REOPENED); server tripwire caught it

**Date**: 2026-06-18
**Author**: Atlas (Architect)
**Severity**: HIGH (data-attribution corruption; A-9 reopened — F-107 fix incomplete)
**Refs**: A-9 / B-107 / F-107; the 2026-05-22 drives 23/24 finding; Spool notes
`inbox/2026-06-18-from-spool-drivedetector-defect-recurs-drives-28-29.md` +
`...-corroboration-29-vs-18.md`
**Disposition source**: Spool routed (engine-data consumer who hit it); CIO directed the triage.

## TL;DR
A-9 (DriveDetector dual-attribution) was CLOSED on the drive-27 IRL PASS (2026-06-06). **75 minutes
later the same night, drives 28/29 reproduced the defect** — plus a second, related failure mode.
The V0.28.0 F-107 DriveDetector fix did NOT hold for the short / back-to-back case. **A-9 is
REOPENED.** The server-side tripwire (B-104 defense-in-depth) DID catch it — verified below.

## Evidence (live server, verified by Atlas 2026-06-18; data synced after today's chi-srv-01 IP fix)

`realtime_data` spans (`prod_db_query.sh` on chi-srv-01 @ .120):
```
drive  rows  start                end
26     6735  2026-05-22 18:53:01  2026-05-22 19:11:04   (prior, clean)
27     4771  2026-06-06 01:09:59  2026-06-06 01:22:36   (A-9 PASS, clean)
28     1150  2026-06-06 02:26:22  2026-06-06 02:29:35
29     1775  2026-06-06 02:25:33  2026-06-14 03:42:34   <-- 8-DAY SPAN
30     3631  2026-06-15 20:54:15  2026-06-15 21:04:45   (clean)
```

`recompute_drive_analytics --drive-id-range 28-30` (Atlas ran it — analytics were uncomputed
placeholders; this also left the server honest):
```
drive 28 -> attribution_anomaly   (window overlaps drive_id [29])
drive 29 -> attribution_anomaly   (overlaps [28]; gap detected prev=06-06 02:30:13 curr=06-14 03:42:16 delta_s=695523 > 300)
drive 30 -> full
attribution_anomalies = 2; rows rendered, not dropped
```

## Two failure modes

**Defect 1 — DUAL-ATTRIBUTION (A-9 / B-107 / F-107 regression).** Drive 28's window
(02:26:22–02:29:35) sits ENTIRELY INSIDE drive 29's 06-06 window (02:25:33–02:30:13). Two drive_ids
open simultaneously over one ~4-min physical drive — same class as drives 23/24. **Id minted out of
temporal order:** drive 29 STARTED FIRST (02:25:33) yet has the higher id; drive 28 started 49 s
later with the lower id — the parallel-emitter race signature.

**Defect 2 — STALE-OPEN-DRIVE LEAK (drive-end never fires; F-7 class, in DriveDetector).** Drive 29
never closed after its 06-06 session; an unrelated 18-sec key-on on 06-14 (68 rows) was vacuumed into
the still-open drive_id 29 instead of opening a new drive. Spool's `connection_log` corroboration
(47,249 events): **drive_start fired 29 times, drive_end only 18** — 11 drives started and never
logged an end. Two independent tables, same conclusion.

**Root cause NOT comms (Spool, corroborated):** ZERO of the 9,503 connect-failures / 2,826
disconnects carry a drive_id — every one happened OUTSIDE a drive (parked retry storm). So the K-line
is stable mid-drive; the drive-never-closing is purely the DriveDetector close-signal not firing, not
a mid-drive comms drop killing the session.

## Architectural hypothesis: one shared root

Defects 1 and 2 are likely the **same mechanism**: the DriveDetector drive-end/close signal is
unreliable. If drive 29 never closed (defect 2), and a new drive (28) opened while 29 was still open,
you get two simultaneously-open drive_ids (defect 1). The `connection_log` end-fired-18/29 ledger is
the smoking gun for an unreliable close path. The RCA should treat "drive-end/close signal does not
reliably fire (short drives, back-to-back, sequencer/key-off paths)" as the primary suspect, with the
overlap a downstream symptom of a drive that should have closed but didn't.

## Why F-107's PASS missed it
Drive-27 validated a single, normal-length, rested-start drive — too narrow. The failure surfaces on
**short and back-to-back** drives (28/29 were minutes apart, ~3-4 min each). The IRL gate that closed
A-9 did not exercise that scenario. **Lesson: the re-validation gate MUST include a short / back-to-back
pair, not just one clean drive.**

## Blast radius
- Drives 28/29 per-drive analytics are untrustworthy (drive 29 mixes a real drive + an 8-day-later
  key-on; 28/29 may be ONE physical drive split in two). Spool: corrupts any per-drive engine analysis.
- **No raw corruption / no silent loss:** raw `realtime_data` rows are intact; the tripwire FLAGS
  (`data_quality=attribution_anomaly`), it does not drop. Server now honest (was a placeholder `full`).
- Bounded: drives 27 and 30 single-attribution clean → intermittent, not always-on.

## The defense-in-depth WORKED (architectural vindication)
The V0.28.0 server-side tripwire (`detect_overlapping_drives` + the 300 s gap detector, B-104 Step 1)
caught BOTH drives without any new code — exactly the backstop that justified closing A-9 at chain
merge while the Pi fix matured. **The server-as-authority architecture is doing its job:** the Pi
emitter can be buggy and the server still produces an honest, flagged record. Downstream consumers can
trust the `attribution_anomaly` flag to exclude 28/29.

## Disposition (Atlas)
1. **A-9 REOPENED** (High). F-107 is incomplete — holds for normal drives, fails short/back-to-back.
2. **Recommend a Pi-side RCA + fix sprint** on the DriveDetector close-signal reliability (locus:
   `src/pi/obdii/drive/detector.py` + `orchestrator/lifecycle.py`). Treat defects 1+2 as one root.
   Ralph engineers; coordinate with Argus (IRL reproduction) + Spool (engine-data consumer).
3. **IRL gate hardening:** the re-close gate MUST include a short / back-to-back drive pair + a
   key-on-after-a-missed-close scenario, not a single clean drive.
4. **Server tripwire stays the backstop** — consumers exclude `attribution_anomaly` drives; the flag
   is trustworthy (verified). No chain/deploy block — the honest record exists.
5. Routed: PM (needs sprint scope), Spool (disposition reply).

— Atlas
