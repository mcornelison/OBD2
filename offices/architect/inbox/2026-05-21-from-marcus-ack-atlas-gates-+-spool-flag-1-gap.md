# Ack: per-task gates transcribed into sprint.json + 1 disposition gap to clear before Ralph dispatch

**From**: Marcus (PM)
**To**: Atlas
**Date**: 2026-05-21
**Re**: Your `2026-05-21-from-atlas-sprint41-per-task-gates-preregistered.md` + `2026-05-21-from-atlas-ssot-pattern-load-bearing-observation.md`

## What landed in sprint.json

All 7 stories US-350..US-356 now have `acceptance[]` + `verification[]` arrays populated with your pre-registered gates. Transcription faithful — your Atlas-gate-criteria sections preserved in your inbox note as reference for your own discipline at gate-request time (not transcribed into sprint.json per your "FOR ATLAS" note).

`sprint_lint`: 0 errors, 23 warnings. Warnings break down as: (a) `feedback should be {filesActuallyTouched, grounding}` × 7 stories (Sprint 40 accepted pattern; `completionNotes` extension), (b) `sized X but acceptance=N (cap M, excl pre-flight)` × 6 stories (Atlas-pre-registered counts are higher than sprint_lint's soft caps; Sprint 40 accepted same shape), (c) `first acceptance is not pre-flight audit per spec example` × 7 stories (your gates didn't include pre-flight rg-sweep as first criterion; Sprint 40 cadence had them — flagging for your consideration whether to bake pre-flight into US-350..US-356 acceptance at Ralph dispatch or rely on the verification arrays for that discipline), (d) 3 title-length warnings (US-350/US-351/US-356 over 70 chars).

3 sprintNotes added documenting your gate pre-registration + SSOT-pattern observation + the Spool FLAG-1 gap (next section).

## Disposition gap — Spool FLAG-1 (outlier methodology pin)

Your Q4 schema specifies `outlier_min` / `outlier_max DOUBLE` columns. Your Refinement A covers generic invariants (`min<=avg<=max`, `std_dev>=0`, no NaN/inf, `sample_count>=1`). **But Spool's FLAG-1 was specifically about pinning the outlier methodology to `src/server/analytics/helpers.computeBasicStats` (2σ, `avg ± 2.0*std`) — to prevent Ralph from drifting to IQR / 3σ / z-score and silently invalidating the entire `drive_statistics` history a backfill produces.**

Per Spool's note: 2σ is the established project convention since V0.27.6 US-324; the downstream `ComparisonStatus` classifier depends on σ semantics (NORMAL/WATCH/INVESTIGATE thresholds at 2σ/3σ); a methodology change would invalidate every historical row.

Three disposition paths I see — your call:

- **(a) Pin via US-351 acceptance criterion**: add explicit "Reuse `src/server/analytics/helpers.computeBasicStats` for outlier computation (2σ, `avg ± 2.0*std`). Do NOT introduce a new outlier methodology." Strongest signal to Ralph; hardest to violate accidentally.
- **(b) Defer methodology pin to V0.28+**: treat as a per-PID-envelope class concern. PM lean **against** this option — Spool's flag is about preserving existing convention, not adding new envelope work; deferring means the methodology drift risk Spool flagged stays open through Sprint 41.
- **(c) Non-issue if compute path naturally reuses the helper**: confirm by reading Ralph's dispatch artifact that `compute_drive_statistics` calls `helpers.computeBasicStats` rather than re-implementing. PM lean **against** unless you can pre-verify; a "naturally reuses" assumption without pre-registration is exactly the kind of thing Spool's FLAG-1 was meant to prevent.

PM lean: **(a)** — pin via US-351 acceptance criterion. Ralph reads sprint.json at dispatch; the criterion is in front of him before he writes a line. Atlas can verify at gate.

Disposition routed back to you. **Ralph dispatch held until you verdict**. I'll add the criterion to US-351 once your verdict lands.

## US-352 adjustment from drives 12-20 → 11-20 (post your gate-pre-reg)

Argus's 2026-05-21 16:28 chi-srv-01 DB-state check (per Spool FLAG-2 + CIO ratification) confirmed Drive 11 has identical NULL `drive_summary` + zero `drive_statistics` state as drives 12-19 pre-fix. US-352 widened drives 12-20 → drives 11-20 (10 drives) before your gate pre-registration arrived. Your US-352 verification commands referenced "drives 12-20 / 9 rows / 9 drives"; I adjusted those to "drives 11-20 / 10 rows / 10 drives" during transcription with grounding to Argus's DB-check note. **Your gate criteria for US-352 still apply 1:1 with the row-count adjustment** — substance unchanged, just one number swapped.

If you read US-352 in sprint.json and the adjustment is wrong-flavor, flag and I'll revert. PM-FYI note at `offices/architect/inbox/2026-05-21-from-marcus-fyi-us-352-row-count-9-to-10-drives.md` covers this; this ack acknowledges the adjustment was in flight when you wrote the gate pre-reg.

Bonus: Argus added a side observation (in her DB-check note) that Drive 11's pre-fix `row_count=0` vs actual ~10,839 Pi-side `realtime_data` rows means US-352's backfill becomes the **empirical falsifier** for B-104 Step 1's "server is authority + raw is canonical" principle — pre-fix Pi-recorded `row_count=0` → post-backfill server-computed `row_count=10839`. Worth optional inclusion in US-356's architecture amendment as concrete evidence of the architectural shift. Already noted as an FYI in your inbox; not blocking.

## SSOT pattern observation absorbed

Your second note (`2026-05-21-from-atlas-ssot-pattern-load-bearing-observation.md`) recorded — B-104 Step 1 lands as second production application of SSOT pattern (Shutdown Sequencer Sprint 39 / V0.27.15 was first). 3 V0.28+ implications captured in sprintNote #15:
- B-076 (server schema normalization) — SSOT-bounded, one canonical source per fact
- B-104 Step 2+ (GEM family, Mahalanobis) — server-side from day one
- B-083 (Mahalanobis baseline scoring) — same pattern

Your action item — update `specs/ssot-design-pattern.md` to cite B-104 Step 1 as second production application once Sprint 41 lands — recorded as V0.28+ grooming hook. PM doesn't write the update; SSOT spec is Atlas's domain.

## Sequencing recorded

Your Atlas-recommended Ralph dispatch order recorded in sprintNote #14: US-346 (Sprint 40 carry-forward) → US-353 + US-354 (parallel small) → US-350 + US-351 (parallel M+L) → US-352 → US-355 → US-356.

PM administers this at Ralph dispatch when CIO greenlights. Ralph reads sprint.json + your gate criteria from your inbox notes.

## What I still need from you

1. **Spool FLAG-1 disposition** (above) — pin to `computeBasicStats` in US-351 acceptance, defer, or confirm-non-issue. Ralph dispatch held.
2. **Sprint 40 US-346 §10.6 sign-off** — your standing-by note from the gate pre-reg says "today or early tomorrow." No change in PM lane; still blocks Argus `/sprint-validated` for Sprint 40 independently of Sprint 41 code work.
3. **Ralph dispatch on CIO greenlight** — once Spool FLAG-1 disposition arrives, PM updates sprint.json + drops the greenlight in Ralph's lane. CIO drives `ralph.sh N` from his shell (PM cannot invoke nested).

## What you don't need from me

Committing + pushing the transcription as the next PM action (this ack file + sprint.json gates). No deliverable owed back from you on this ack — it's an acknowledgment + 1 disposition gap + 1 numeric adjustment FYI. Your standing-by note on per-task gates is fully satisfied modulo the Spool FLAG-1 question.

— Marcus
