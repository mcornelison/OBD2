from=Rex(Dev); to=Marcus(PM); date=2026-06-29; topic=Sprint 47/V0.29.1 -- 3 remaining stories all externally gated (SPRINT_BLOCKED); audience=agent; urgency=medium; refs=US-388,US-390,US-367,US-387

# BL-sprint47-remaining-gated -- all Ralph-pickable work in Sprint 47 is done; the 3 open stories are gated on Atlas + Spool

## State
Sprint 47 / V0.29.1 is **6 of 9 passes:true**: US-386, US-387, US-389, US-391, US-392, US-379 (just shipped).
The 3 remaining stories are **all blocked on external sign-offs / sequencing** -- no story Ralph can pick up without violating a story's own `conditionalOutcome`. Emitting `SPRINT_BLOCKED` so `ralph.sh` stops cleanly rather than spinning empty iterations.

## The 3 gated stories

### US-388 -- FIX DriveDetector close-signal (Root 2) -- BUILD-BLOCKED on Atlas
- `conditionalOutcome`: *"BUILD BLOCKED until US-387 RCA accepted by Atlas -- do not code before the root cause is rendered."*
- The US-387 RCA shipped (`docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md`) and was routed to Atlas: `offices/architect/inbox/2026-06-28-from-rex-us387-rca-ready-for-review.md`.
- **No Atlas acceptance reply has landed in `offices/ralph/inbox/`.** Until that acceptance arrives, US-388 cannot be coded. If the RCA reveals the fix is architectural (it identifies a tick-driven-close structural root), it routes back to Atlas for a design ruling before coding.
- **PM action:** chase Atlas's review of the US-387 RCA; relay the acceptance (or change-request) into Ralph's inbox.

### US-390 -- regression lock -- sequenced AFTER US-388
- Dispatch build-order #4: *"US-390 -- regression lock (after US-388)."* The story locks the US-386 reproducer into the permanent regression manifest -- but that reproducer is currently RED-as-xfail; the "lock" presumes US-388's fix has flipped it GREEN (US-388 removes the xfail markers). Locking a still-failing reproducer into the fast suite/manifest now would bake in a known-red xfail. Respecting the dispatch sequencing -> blocked behind US-388.
- **PM action:** unblocks automatically once US-388 lands.

### US-367 -- ECU lineage backfill (2-row) -- BLOCKED on Spool
- `conditionalOutcome`: *"if Spool has not signed off on signature naming convention OR has not derived the swap instant, BLOCK the backfill + route an A2AL note to Spool."*
- No Spool sign-off note (naming convention) or swap-instant derivation is present in `offices/ralph/inbox/` or visible to Ralph. The story also requires live `obd2db` access for the backfill + join verification.
- **PM action:** route an A2AL request to Spool for (1) the ECU signature/cal naming-convention sign-off and (2) the precise swap-instant (~2026-05-22, last old-ECU drive-end / first new-ECU drive-start), dated BEFORE the backfill commit. The backfill swap instant must be passed as a script PARAM, not hardcoded.

## What just shipped (US-379)
Test-only fixture fix: `test_harnessTooling_canCatchSchemaVsOrmDivergence_synthetic`'s historical `drive_statistics` CREATE TABLE block carried the pre-US-371 `drive_id` column, so the Phase-1 ORM INSERT failed on `summary_id`-missing (a rename artifact) instead of the intended `data_quality`-missing I-041 symptom. Renamed to `summary_id` (column/PK/FK). Target test passes for the right reason; `tests/integration -m "not slow"` 18 passed; ruff clean. Committed `7193b0b`.

## Unblock summary (PM)
1. Get Atlas to accept (or change-request) the US-387 RCA -> relay to `offices/ralph/inbox/` -> unblocks US-388 -> then US-390.
2. Get Spool's signature-naming sign-off + swap-instant -> relay to `offices/ralph/inbox/` -> unblocks US-367 (still needs live obd2db at run time).

-- Rex
