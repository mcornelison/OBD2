---
id: F-068
parent: E-002
status: pending
renamedFrom: B-068
createdAt: 2026-05-27
updatedAt: 2026-05-27
---

# B-068: Sustained WOT capture drive plan (operator drill, not code)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Medium                 |
| Status       | Pending (Sprint 30+ candidate; gated on B-063 + Drive 11+) |
| Category     | tuning / drive-plan    |
| Size         | S (operator-only; no code) |
| Related PRD  | None                   |
| Dependencies | B-063 fuse-box wiring complete; first clean Drive 11+ baseline produced |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10: Drive 7 hit 100% engine load momentarily but **N=1 for under-load data + WOT was incidental**. Sustained WOT (5-10+ sec at full boost) is the single most valuable missing tuning data point.

## What sustained WOT data tells us that incidental WOT doesn't

- Thermal margin under sustained load (coolant + IAT trend over 10+ sec at full WOT)
- MAF saturation behavior (does MAF flatten / clip near 158 g/s peak?)
- Timing-pull behavior (does ECU pull timing under sustained load even without knock-pull DTCs?)
- Stock fuel system delivery limits (LTFT/STFT trends at 100% load show injector duty saturation)
- Closed-loop O2 behavior post-WOT-enrichment (B1S1 return-to-switching latency)

## Drive plan (post-B-063, future Drive 11/12/13)

1. Empty stretch of road, 3rd or 4th gear pull
2. Accelerator floored, hold for **5-10 sec at full WOT**
3. Repeat 2-3 times with 30-sec cooldown between
4. Tag drive intent as `datalog_pull` (per `drive_annotations` schema spec)
5. Pre-drive checklist: tank >= 3/4, ambient temp logged, weather noted, no anomalies

## Acceptance Criteria

- [ ] CIO approval on the drive plan (safety + legal context)
- [ ] At least one Drive captures 5-10 sec sustained WOT segment
- [ ] Realtime_data row count for the WOT segment >= expected rate (engine load >= 95% sustained)
- [ ] Spool produces grading + tuning notes from the captured data

## Notes

**No code in this backlog item** -- it's a drive-plan / operator drill. Filed for backlog visibility so it doesn't get forgotten when Drive 11+ unblocks.

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-new-tuning-research-and-feature-candidates.md` Item A
