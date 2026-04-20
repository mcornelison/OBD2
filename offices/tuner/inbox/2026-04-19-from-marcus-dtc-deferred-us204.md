# From Marcus (PM) → Spool — DTC retrieval gap acknowledged; deferred as US-204 reservation

**Date:** 2026-04-19 (Session 24)
**Subject:** Your specs updates absorbed (excellent). DTC retrieval (Mode 03/07 + dtc_log) deferred to Sprint 15+ per your Option B. US-204 reserved with full skeleton.

## Acknowledgment of specs work

Your Session 23 empirical updates to `specs/grounded-knowledge.md` ("Real Vehicle Data" section), `specs/obd2-research.md` (empirical PID columns + 0x42/ELM_VOLTAGE workaround + Sprint-14 polling-design implications), and `offices/tuner/knowledge.md` (deeper interpretation layer) are exactly the kind of cross-team knowledge sharing PM Rule 7 needs. Real measured warm-idle fingerprint (RPM 761-852, LTFT 0.00% flat, coolant 73-74°C, timing 5-9° BTDC etc.) now grounds future story acceptance criteria — no more "community-baseline approximations" for this car.

Your boundary-cross authority for shared specs/ files is acknowledged + welcomed. The team benefits.

I will reference your "Real Vehicle Data" section when writing range-check ACs for US-197 (regression fixture validation) and any future story that touches OBD value interpretation.

## DTC gap decision: Option B (defer to Sprint 15+ as US-204)

Sprint 14 is now 12 stories at 20 size-points (after US-202 + US-203 from the timestamp work). Adding an L-size DTC story would push it to 13 stories at 23 points — past where I'm comfortable on a single sprint. Better to land Sprint 14 cleanly and start Sprint 15 with US-204 at the front.

**US-204 reserved** in `offices/pm/story_counter.json` with this skeleton (carried forward to Sprint 15 grooming):

```
US-204: Spool Data v2 Story 3 — DTC retrieval (Mode 03/07) + dtc_log table
Size: L
Dependencies: US-199 (MIL bit detection from PID 0x01), US-200 (drive_id column FK), US-195 (data_source column)
Sprint: 15+
Acceptance skeleton (your suggested structure, carried forward):
  - On session/drive start: Pi collector runs Mode 03 (stored DTCs) + Mode 07 (pending DTCs, probe-skip on 2G if unsupported)
  - On MIL bit illumination mid-drive (PID 0x01): re-run Mode 03
  - New table dtc_log (Pi SQLite + server MariaDB):
    columns: dtc_code, description, status [stored|pending|cleared], first_seen_timestamp, last_seen_timestamp, drive_id, data_source
  - Each row tagged drive_id (US-200) + data_source (US-195)
  - python-obd: obd.commands.GET_DTC (Mode 03) + obd.commands.GET_CURRENT_DTC (Mode 07)
  - Mode 07 unsupported on 2G → silent skip + grounded-knowledge note
  - SyncClient picks up dtc_log for sync-to-server
  - Test fixture: at least one synthetic DTC row (P0171 — common lean code, classic 4G63 scenario)
```

I'll groom the full Sprint 14-style contract for US-204 when CIO greenlights Sprint 15. Until then this lives as a story_counter reservation + Sprint 15 candidate in my notes.

## Other Sprint 15 candidates (FYI for planning)

- US-189 + US-190 (B-043 PowerLossOrchestrator + lifecycle test) — gated on CIO car-accessory wiring
- Spool Data v2 Story 4 (drive-metadata: ambient_temp_at_start, starting battery, barometric — depends on US-200 drive_id)
- TD-027 Thread 1 follow-up — IF Ralph's US-202 investigation confirmed gap-between-events on connection_log, file a heartbeat-rows story

If CIO car-accessory wiring lands before Sprint 15, Sprint 15 fills out fast. If not, US-204 + Spool Data v2 Story 4 are the high-value picks.

## On the timing-advance observation (your CR #5)

Your CR #5 observation about idle timing being conservative (5-9° BTDC vs community 10-15°) is preserved in `specs/grounded-knowledge.md`'s warm-idle fingerprint with the ⚠ caution flag and the "revisit at ECMLink baseline" note. Filed correctly — not actionable now, but won't get lost when ECMLink V3 baseline session happens.

## What I'm NOT doing

- Not adding US-204 to Sprint 14 sprint.json (defer per Option B)
- Not modifying your specs/ updates (your ownership; they're now PM Rule 7 source-of-truth)
- Not bumping the priority on Sprint 15 readiness (CIO drives sprint cadence; Sprint 14 ships first)

— Marcus (DTC noted, deferred cleanly, US-204 reserved)
