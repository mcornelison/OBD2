# A-9 REOPENED — DriveDetector defect recurs on drives 28/29 (needs an RCA+fix sprint)

**Date**: 2026-06-18
**From**: Atlas (Architect)
**To**: Marcus (PM)
**Severity**: HIGH (data-attribution corruption) — but NOT a chain/deploy block (server backstop holds).

## What
A-9 (DriveDetector dual-attribution) was CLOSED on the drive-27 PASS. It **reproduced on drives
28/29** (06-06, 75 min after drive-27, same night). Spool routed it (dual-sourced from Pi
obd.db + connection_log); I verified on the live server + recompute. Full triage:
`offices/architect/findings/2026-06-18-drivedetector-defect-recurs-28-29.md`.

## Server-confirmed verdict (data synced after today's chi-srv-01 IP fix)
`recompute_drive_analytics 28-30`: **drive 28 + 29 → `attribution_anomaly`**, **drive 30 → `full`**.
Two modes, likely one root: (1) dual-attribution (drive 28's window inside drive 29's; ids minted
out of temporal order); (2) open-drive leak (drive 29 never closed → absorbed an 8-days-later key-on;
connection_log drive_start=29 vs drive_end=18). Comms ruled out as cause.

## Two architectural takeaways
1. **The V0.28.0 server tripwire WORKS.** It flagged both drives with no new code — the defense-in-depth
   that justified closing A-9 at chain merge did its job. The honest record exists; consumers can
   trust the `attribution_anomaly` flag to exclude 28/29. **So this does not block anything.**
2. **The Pi-side F-107 fix is INCOMPLETE** — it holds for normal single drives, fails on short /
   back-to-back. Drive-27 (one clean drive) was too narrow a gate.

## What I need from you (PM scope)
- **A new RCA + fix sprint** for the Pi DriveDetector close-signal reliability (locus:
  `src/pi/obdii/drive/detector.py` + `orchestrator/lifecycle.py`). Treat defects 1+2 as one root
  ("drive-end/close signal does not reliably fire"). Ralph engineers; **Argus owns IRL reproduction**,
  Spool is the engine-data consumer to loop in.
- **Harden the IRL gate:** the re-close validation MUST include a **short / back-to-back drive pair**
  + a **key-on-after-a-missed-close** scenario — not a single clean drive. (This is the gap that let
  the drive-27 PASS miss it.)
- **Sizing/priority:** your call vs the EDR bus slice + US-367. This is HIGH (attribution corruption)
  but the server backstop means it's not a fire — schedule deliberately, with the IRL repro as the
  long pole.

## Housekeeping I already did (transparency)
- Ran `recompute_drive_analytics 28-30` on prod (idempotent, designed tool, drive-27 precedent) — this
  also corrected a misleading placeholder (28/29/30 had been left at `data_quality='full'` with
  row_count=0/NULL times); server is now honest.

— Atlas
