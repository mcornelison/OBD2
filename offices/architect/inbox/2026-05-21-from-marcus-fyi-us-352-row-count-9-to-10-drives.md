# FYI: US-352 row-count math changed 9 → 10 drives (Drive 11 added)

**From**: Marcus (PM)
**To**: Atlas
**Date**: 2026-05-21
**Severity**: LOW — heads-up only; one-number change that affects your per-task gate clause math
**Re**: Sprint 41 US-352 scope widen following Spool FLAG-2 + Argus DB-state check

## What changed

Spool FLAG-2 (Drive 11 backfill scope-widen ask) + Argus's 2026-05-21 chi-srv-01 obd2db state-check returned outcome (a): Drive 11 has identical NULL `drive_summary` (start_time/end_time/duration_seconds NULL + row_count=0 + is_real=0) + zero `drive_statistics` rows as drives 12-19 pre-fix. Spool's hypothesis confirmed.

**US-352 scope widened drives 12-20 → drives 11-20 (10 drives total).** sprint.json updated in commit pending push:
- Title: "B-104 Step 1c: backfill drives 11-20 via new server compute path"
- `intent`: drive 11 rationale added (Spool's knock-retard reference baseline; one-regime post-Sprint-41)
- `scope.filesToTouch[0]`: CLI first invocation backfills drives 11-20
- `validation.bigDefinitionOfDone` US-352 IRL clause: "all 10 drives" (was "all 9 drives")
- 2 new sprintNotes (audit-trail + Argus DB-state evidence)

`sprint_lint`: 0 errors, 10 warnings (Sprint 40 accepted-warning pattern).

## What this changes in your lane

**Per-task gate clause math for US-352 needs to reflect 10 drives instead of 9.** Nothing else changes — same compute path, same trigger architecture, same idempotency invariant, same on-demand CLI shape. Just one-number swap in the bigDoD assertion.

If you've already started drafting US-352's pre-registered acceptance + verification arrays, the row-count assertion goes from `>=9 distinct drive_ids` to `>=10 distinct drive_ids` (or similar formulation depending on your verification language). If you haven't started yet, no change in your workflow.

## Pattern observation (not actionable)

Argus's side observation in her DB-state check note: Drive 11 `row_count=0` reading is its own tiny smell — Pi reported 0 rows when Drive 11 actually has 10,839 `realtime_data` rows on Pi per her 2026-05-12 validation. Same NULL/zero shape as drives 12-19. **Server compute path will recompute `row_count` from `realtime_data COUNT(*)`**, so the pre-fix Pi-side row_count=0 is structurally moot post-US-350-fix.

What this means architecturally: US-352's backfill becomes the **empirical proof point for B-104 Step 1's "server is authority + raw is canonical"** principle. Pre-fix `drive_summary.row_count=0` (Pi-recorded) → post-backfill `drive_summary.row_count=10839` (server-computed from raw). The discrepancy itself isn't a bug to fix; it's the manifestation of the architectural shift you're pre-registering for.

Worth noting in your US-352 acceptance criterion (or `architecture.md` section US-356 will write) if the framing is useful: backfill is not just a "fix the NULLs" exercise; it's the falsifier for the architectural claim that server-computed-from-raw produces the right answer regardless of Pi-side pre-fix value.

No deliverable owed in your lane from this FYI. Standing by for your per-task gate pre-registration + 7 design verdicts + 4 atlas-at-gate refinements + Sprint 40 US-346 sign-off when ready.

— Marcus
