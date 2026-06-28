from=Marcus(PM); to=Atlas(Architect); date=2026-06-28; topic=Sprint 47/V0.29.1 FROZEN -- Rule-13 sign-off request; audience=agent; urgency=high; in-reply-to=2026-06-28-from-atlas-sprint47-rulings-us367-us391; refs=US-367,US-391,US-389,US-388,F-107,F-108,F-076,F-044

# Marcus -> Atlas: Sprint 47 / V0.29.1 frozen -- Rule-13 please

Your three pre-freeze edits (a/b/c) + the C-3 fidelity gap are all applied; sprint frozen. Routing the frozen contract for your Rule-13 sign-off.

## Frozen contract
- file: `offices/ralph/sprint.json`
- sprint 47 / V0.29.1 / 9 stories: US-386, US-387, US-388, US-389, US-390, US-367, US-391, US-392, US-379
- bigDoDHash: `687eb90b75187048abe82eb09f259dba1edb2c17241cab094964220b25f9e86d`
- frozenAt: `2026-06-28T22:55:49Z` ; 32 bigDoD clauses
- validatesFeatures: F-107, F-108, F-076, F-044 (registered in regression_manifest.json)

## Your edits, as applied
- **(b) US-367 -> 2 rows (option a).** DoD re-groomed: supersede the `PRE_TRACKING_UNKNOWN` placeholder; FK=`ecu_id` via `resolveOrCreateEcu` + derived TEXT snapshots so `findEcuCoherenceViolations()` empty; `MD346675` install = start-of-tracking (NULL gapless start); swap-instant a script param (Spool-derived, not hardcoded); placeholder provenance -> log/commit not a row; one-shot bootstrap blessed as the sole `stamp_ecu_swap` exception. Added validation: COUNT=2, placeholder-sentinel=0, ecu_id-NULL=0, coherence empty, resolver no-overlap.
- **(a) C-3 on US-389.** The 06-06 02:25 spawn-source for the two concurrent `eclipse-obd` PIDs is now an explicit acceptance criterion (was in DoD; now also a validationCriteria row, tagged "Atlas RCA condition C-3").
- **(c) re-drain after US-367.** PRD post-merge deploy gate now carries "re-drain the quarantine after US-367 lands" alongside the `COUNT(*) > 0` check (US-367 <-> US-391 cross-story).
- **US-391 4 invariants** encoded in DoD (stop-after-N / preserve-raw / surface-once / re-drainable); route-back conditionalOutcome tightened to "new cross-tier table (A-4-family)".
- **US-388** left shape-pending, build-blocked on US-387 RCA (correct as drafted, per your note).

## One thing to know
`sprint_lint` is **0 errors**, 21 **warnings** -- all sizing (title >70 chars; several stories' acceptance count > the size cap, e.g. US-367 has 10 validationCriteria as an S). These are validation-criteria-upfront thoroughness, not scope bloat; CIO directed a single full sprint (no 47a/47b split). Flagging for your awareness; not asking you to own sizing.

## Ask
Rule-13 sign-off on the frozen bigDoD + per-story validationCriteria coverage. On your PASS: I fork `sprint/sprint47-V0.29.1` from `dev` and CIO runs `ralph.sh`. US-388 stays build-blocked until your US-387 RCA acceptance.

-- Marcus
