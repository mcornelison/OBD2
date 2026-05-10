# B-069: Cross-drive comparison tool (Spool ergonomics)

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low                    |
| Status       | Pending (V0.28+ feature sprint candidate) |
| Category     | tuner / analytics      |
| Size         | M (~100 LOC + SQL views OR a Python script) |
| Related PRD  | None                   |
| Dependencies | drive_annotations table (B-057) for filter columns like mod_state / cold_start / engine_load |
| Created      | 2026-05-10             |

## Description

Spool 2026-05-10: with drives 3-8 on the pre-mod baseline shelf, querying "show me LTFT trend across all healthy idle drives" or "show me coolant warm-up curves across cold-start drives" is currently a **manual SQL exercise**. Spool ends up writing one-off queries.

## Proposed feature

Small CLI / skill that takes a parameter name + filter predicate and produces aggregated comparison across drives matching the filter.

Examples:
- `/spool-compare LTFT_1 mod_state=premod is_actual_drive=true` -- LTFT trend across drives 6-8
- `/spool-compare COOLANT_TEMP cold_start=true` -- warm-up curves across drives 3, 4, 5, 6, 8
- `/spool-compare TIMING_ADVANCE engine_load=>80` -- timing under load across drives with peak engine_load > 80%

## Implementation approach

Probably a Python script in `offices/tuner/` reading `obd2db` directly. ~100 LOC. Alternative: SQL view templates Spool can copy-paste.

## Acceptance Criteria

- [ ] CLI tool accepts parameter name + filter dict
- [ ] Returns aggregated comparison across matching drives (mean / min / max / N=count + per-drive breakdown)
- [ ] Filter dict supports: mod_state, drive_id range, is_actual_drive, engine_load threshold, cold_start flag
- [ ] Spool can run from chi-srv-01 OR locally; clean error if needed columns don't exist (pre-B-057)

## Notes

**Filed for V0.28+ feature sprint** -- not bug-fix work. Pairs with B-057 drive_annotations table (provides the filter columns); could ship same sprint.

**Source**: `offices/pm/inbox/archive/2026-05/2026-05-10-from-spool-new-tuning-research-and-feature-candidates.md` Item B
