# Correction — Drive 8 was NOT car-coupled (portable inverter, not stereo USB-C)
**Date**: 2026-05-10
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — fact correction on prior note

## What I got wrong

In yesterday's note `2026-05-10-from-spool-three-drives-tonight-power-blocker-drive-counter-clarification.md` I described Drive 8 as "the first drive under car-coupled Pi power (key-switched USB-C from new stereo)." **That's wrong.** Per CIO clarification just now:

- **Drive 8** was on **a portable camping-battery + AC inverter setup** with the Pi using its stock 5A power supply. CIO had the portable battery in the car for the drive. Pi was on stable wall-equivalent AC throughout. This is the **same power model as Drives 6 + 7.**
- **Drive 9 was the FIRST drive on the car-coupled stereo USB-C path** — and it immediately demonstrated the undersizing problem (capture rate degraded 12×, dashboard flickering, drains opening).
- **Drive 10 was the SECOND attempt** — same outcome (drain id=12 opened 8 sec into drive).

## Updated framing for Sprint 28 planning

The car-coupled stereo USB-C path has a **0/2 success rate** (drives 9 + 10 both failed validation). It's not "loose connector during drive 9" — it's "the path is fundamentally undersized for Pi 5." The first actual successful car-coupled-power baseline drive will be **drive_id=11+** post-fuse-box-wiring, not Drive 8.

## What this changes (and what it doesn't)

**Doesn't change**:
- DriveDetector warm-restart-cranking gap is still a real bug (P1 candidate).
- battery_health_log close-event-on-poweroff race priority bump P3→P2 still applies.
- Hardware blocker (USB-C undersized → fuse-box wiring required) is still the gate on further IRL drives.
- PID 0x2F probe story is still on the P3 list.
- drive_counter sync gap is still a P3 cleanup.

**Does change**:
- Whatever team narrative captures "first car-coupled drive milestone" should reference **Drive 9** (failed), not Drive 8 (succeeded).
- Drive 8 stays on the pre-mod baseline shelf; its rationale shifts from "first car-coupled" to "first cold-start city/highway baseline." Same shelf membership, different framing.

`knowledge.md` + `drive-annotations.md` + `obd2db.drive_annotations` all corrected.

— Spool
