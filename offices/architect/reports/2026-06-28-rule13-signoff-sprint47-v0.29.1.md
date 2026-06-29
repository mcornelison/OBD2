# Atlas Rule-13 Sign-off — Sprint 47 / V0.29.1 (data-integrity hardening)

**By:** Atlas (Architect) · **Date:** 2026-06-28 · **Tasked by:** CIO (Ralph blocked on dispatch gate)
**Verdict: PASS — freeze intact, aggregation exact, lint clean, my rulings faithfully baked in. Cleared for dispatch.**
**Frozen contract:** `offices/ralph/sprint.json` · `bigDoDHash 687eb90b75187048abe82eb09f259dba1edb2c17241cab094964220b25f9e86d` · frozenAt `2026-06-28T22:55:49Z` · 9 stories · 32 bigDoD clauses.

## Freeze-hash audit (per `specs/rule-13-audit-discipline.md`)

Read `sprint.json` with **explicit UTF-8** (my own prior lesson: a bare Windows `open()` mangled the `→` U+2192 and nearly produced a false BLOCK). Used the real `_freeze.canonicalizeBigDoD` recipe (strip → sort → join `\n` → sha256/utf-8) to avoid call-site divergence.

| Check | Result |
|---|---|
| Recomputed hash == stored | ✅ `687eb90b…` == `687eb90b…` |
| bigDoD clause count | ✅ 32 (== Marcus's stated 32) |
| bigDoD == exact per-story validationCriteria sum (multiset) | ✅ identical; 0 missing, 0 extra |
| Fresh rebuild-from-stories reproduces the frozen hash | ✅ proves no orphan/injected clause |
| `sprint_lint --path` | ✅ **0 errors**, 21 warnings |

Per-story VC counts: US-386:2, US-387:2, US-388:2, US-389:4, US-390:2, US-367:10, US-391:4, US-392:3, US-379:3 → 32.

The 21 warnings are all cosmetic (title >70 chars; acceptance count > size cap; "first acceptance not pre-flight audit") — validation-criteria-upfront thoroughness, NOT scope bloat. Warnings don't enter the freeze hash and don't gate Rule-13. Sizing/split is the CIO's call (he directed one full sprint, no 47a/47b).

## Architectural fidelity — my rulings are present in the frozen contract

- **US-367 → 2 rows (option a):** acceptance[0] = "exactly 2 real ECU-era rows … a 3rd row would overlap the MD346675 window at the resolver's >1-window raise, sync.py:605"; FK=`ecu_id` via `resolveOrCreateEcu` + DERIVED TEXT snapshots → `findEcuCoherenceViolations()` empty; gapless single-active partition (MD346675 install=start-of-tracking, removal=swap; MD326328 install=swap, removal=NULL); swap instant = script PARAM (Spool-derived, not hardcoded); placeholder provenance → log/commit not a live row; one-shot bootstrap blessed as the sole `stamp_ecu_swap` exception. VC: COUNT=2, sentinel=0, ecu_id-NULL=0, removal-NULL=1, coherence empty, join 1-24/25+, resolver no-overlap. ✅
- **C-3 (Root-1 spawn source):** US-389 acceptance + a dedicated validationCriteria row name the 06-06 02:25 two-PID spawn trigger (systemd `Restart=` race / watchdog / manual+service overlap), with a conditionalOutcome for the journal aging out. ✅
- **US-391 four invariants:** stop-after-N / preserve-raw / surface-once / re-drainable, explicitly tagged "Atlas invariant 1-4"; route-back conditionalOutcome tightened to "new cross-tier table (A-4-family)". ✅
- **US-367 ↔ US-391 cross-story:** `validationMethod` carries "re-drain quarantine after US-367" alongside `dtc_freeze_frame COUNT>0`. ✅
- **US-388 shape-pending:** title "(SHAPE PENDING RCA US-387)"; conditionalOutcomes "BUILD BLOCKED until US-387 RCA accepted by Atlas" + architectural-route-back. ✅ (A-11 discipline honored.)
- **IRL re-gate (§3.4 of my RCA ruling):** short/back-to-back + key-on-after-missed-close + deploy-double-start; "a single clean drive is explicitly insufficient." ✅
- **Design-gate DoD (C-4):** US-388 (DriveDetector section) + US-389 (boot-path section) update `specs/architecture.md` in-sprint. ✅

## Disposition
- **Rule-13 PASS.** Marcus may fork `sprint/sprint47-V0.29.1` from `dev` and dispatch. This clears gate #1 of `BL-sprint47-not-dispatched` (Ralph's refuse-first was correct).
- **US-388 stays build-blocked** until I accept the US-387 RCA (its `validationCriteria` "Atlas review of the RCA" is the gate). I owe that review when Ralph files the RCA.
- The A-9 IRL re-gate + US-367 self-heal verification remain **deploy-time** validations (needs the car), not part of merge — fold the pending Sprint 46 `pi.bus.enabled` flag-flip into the same Pi window.

— Atlas
