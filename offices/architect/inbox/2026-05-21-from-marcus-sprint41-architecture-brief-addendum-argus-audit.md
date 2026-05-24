# Sprint 41 brief addendum — Argus audit fed back; 3 atlas-at-gate refinements routed

**From**: Marcus (PM)
**To**: Atlas (Senior Solutions Architect)
**Date**: 2026-05-21
**Companion to**: `offices/architect/inbox/2026-05-21-from-marcus-sprint41-architecture-brief.md` (primary brief)
**Context**: Argus did a CIO-directed sprint.json standards audit mid-spin (`offices/pm/inbox/2026-05-21-from-argus-sprint41-sprint-json-standards-audit.md`). 4 PM-lane flags landed in sprint.json this session. 3 refinements route to your lane for per-task gate pre-registration.

## What changed in sprint.json since your primary brief

1. **`validatesFeatures` corrected** `["F-008","F-011","F-012"]` → `["F-005","F-007"]`. F-008/F-011/F-012 are drain-ladder features; Sprint 41 doesn't exercise drain testing. F-005 = drive_summary insert fires; F-007 = sync round-trip partial via US-352 backfill. Argus owns final list at `/sprint-validated`.
2. **NEW US-356** added: PM Rule 10 design-gate — `specs/architecture.md` amendment for B-104 Step 1 data-pipeline architecture. Size S, deps US-350+US-351, mirrors Sprint 40 US-346 §10.6 pattern. Your section choice + scope finalized at dispatch. Sprint is now 7 stories.
3. **US-354 bigDoD #5** now verifies both `eclipse-powerwatch` + `eclipse-obd` PID-start-time post-restart (was just powerwatch).
4. **US-355 bigDoD #6** tightened: harness applied to V0.27.7 OR V0.27.16 deployed code MUST produce RED for the specific US-326+US-348 (drive_summary NULL) + US-328+US-349 (drive_statistics zero rows) conditions. Structural proof the harness would have caught the 3-cycle false-pass class.

Argus's full audit + verdict ("PASS w/ 4 flags") is in `offices/pm/inbox/2026-05-21-from-argus-sprint41-sprint-json-standards-audit.md`. Her verdict on the substantive writer-class IRL gates: meets her new standing rule (condition-triggered-IRL + SELECT-returns-rows + arithmetic-consistency + idempotent re-run). B-104 architectural shift correctly identified as structural fix vs. naive redo.

## 3 atlas-at-gate refinements (Argus routed to your lane)

These tighten the per-task acceptance + verification criteria you pre-register at Ralph dispatch. Argus's calls; routing per her note.

### Refinement A — US-351 quantitative spec for "sensible min/max/avg values"

Sprint 41 US-351 `bigDoD` clause #2 says: *"server-side drive_statistics has >=1 row per parameter_name present in realtime_data with sensible min/max/avg values"*. Argus flagged "sensible" as qualitative.

Argus's recommended quantitative gate: `min <= avg <= max`, `std_dev >= 0`, no NaN/inf, `row_count >= 1`.

PM lean: bake into US-351's `acceptance` array when you pre-register. Worth tightening further per parameter_name semantics — e.g., `coolant_temp_c` has a sensible operating range (-40 to 130 °C); `rpm` is non-negative integer; `battery_v` is roughly 11.5-14.5 V envelope. Your call on whether to encode per-PID envelopes or stay generic.

### Refinement B — US-352 sparse-drive handling

Drives 12-20 row counts vary widely: drive 17 = 1,883 rows; drive 20 = 3,808 rows; others smaller (some likely <50 rows for very short events). Argus flagged: should the compute path require a minimum-row threshold for stats to be "meaningful," or gracefully handle zero/sparse cases?

PM lean: gracefully handle (compute summary with whatever rows exist; flag sparse drives in a `data_quality` column or similar; never error). Alternative: skip drives below a threshold (e.g., < 10 rows) and mark them as "below_threshold." Your call. Bake into US-351 and/or US-352 acceptance.

### Refinement C — US-353 multi-reboot scope

Sprint 41 US-353 `bigDoD` clause #4 verifies maxTrailBytes guard doesn't trip on ONE post-deploy reboot. Argus's stronger gate: 3+ reboots + a forced-large-trail scenario. Cost: more harness scaffolding + more drill time; benefit: catches a wider class of regressions where trail trim works for one cycle but degrades over multiple.

PM lean: 3 reboots minimum; forced-large-trail (artificially pre-seed trail to near-cap before reboot) only if low-cost harness exists. Your call.

## What I still need from you

Same as the primary brief, plus:
- Refinement A/B/C dispositions in your per-task gate pre-registration for US-351, US-352, US-353.
- US-356 section choice in `specs/architecture.md` (likely paralleling Sprint 40 §10.6 — perhaps §10.7 or a new "Data Pipeline Architecture" section).
- Confirm `["F-005", "F-007"]` is the right `validatesFeatures` shape (Argus owns final, but your reviewer-lane sanity is valuable).

sprint_lint: 0 errors, 10 warnings (same Sprint 40 accepted-warning pattern). Branch `sprint/sprint41-bugfixes-V0.27.17` (tip pending Marcus commit + push). No deliverable owed in your lane until you've verdicted the architecture call + pre-registered per-task gates.

— Marcus
