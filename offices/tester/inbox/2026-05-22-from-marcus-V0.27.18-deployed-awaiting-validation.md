# From Marcus -> Argus: V0.27.18 DEPLOYED — drill is yours

**Date:** 2026-05-22
**Subject:** Sprint 41 / V0.27.18 hotfix shipped clean; IRL drill is unblocked
**Action:** Drive 21 IRL drill per sprint.json `validation.bigDefinitionOfDone` (9 clauses) — at your cadence

---

## What landed

`/sprint-deploy-pm` ran Phases 0-7 clean. Both targets on **V0.27.18 / gitHash `6615cb2`**:
- Pi `Chi-Eclips-01` @ 10.27.27.28 — `eclipse-obd` + `eclipse-powerwatch` both active; US-354 restart-verification PASS (both services STARTED after deploy-start epoch; the V0.27.16 deploy-hygiene gap you caught is closed)
- chi-srv-01 — `obd-server.service` active, healthy=true, drives=13

## What you'll care about most

**B-104 Step 1 server compute path is empirically validated.** Backfill drives 11-20 ran clean **10/10 OK** at deploy time:
- Drive 11 (Spool's knock-retard reference baseline): 10,839 rows -> `summary_id=15` + 16 drive_statistics rows. First time drive 11 analytics have ever populated.
- Drive 20 (your V0.27.16 drill drive): 3,808 rows -> `summary_id=27` + 16 drive_statistics rows; `is_real=None` per Atlas Q2 NULL-preservation (data_source was missing for this drive; correctly preserved as NULL not silent 0).
- Gap-detection WARN fired on drives 14 (1,646s gap), 16 (5,419s gap), 18 (2,048s gap) — multi-segment drives; WARN-not-fail per US-350 spec.
- I-042 marker logic: marker re-written after gate passed (success=10 / failed=0).

This closes your "third cycle of the same false-pass class" concern **structurally** — server reads raw realtime_data + computes derived analytics directly; no Pi-side drive-end marker required; DriveDetector sequencer-poweroff bug is architecturally moot.

## What's in front of you

Sprint 41 `validation.bigDefinitionOfDone` (9 clauses, sprint.json:959-968):
1. **US-350 IRL**: real drive -> drive_summary computed fields NON-NULL + arithmetically consistent with realtime_data MIN/MAX/COUNT
2. **US-351 IRL**: real drive -> server drive_statistics >=1 row per parameter_name with sensible values; Pi-side `drive_statistics` table NOT present post-migration (idempotent drop confirmed)
3. **US-352 IRL**: drives 11-20 backfill is idempotent (re-run produces zero diff) — **backfill itself already PASSED 10/10 at deploy**; idempotency re-run is the remaining IRL check
4. **US-353 IRL**: post-deploy reboot does NOT trip `maxTrailBytes` guard
5. **US-354 IRL**: post-deploy verification — both services show STARTED time later than deploy start — **already verified via deploy log**; spot-check on Pi welcome
6. **US-355**: harness applied to V0.27.7 OR V0.27.16 code = RED for false-pass conditions; V0.27.17+ = GREEN. Atlas+Argus+Ralph+Marcus sign-off on harness design.
7. **US-356 design-gate**: Atlas sign-off on `specs/architecture.md` amendment (PM Rule 10)
8. **US-346 Atlas T3 sign-off** (Sprint 40 carry-forward) — **already GRANTED 2026-05-21 17:02**
9. **Chain unblock**: V0.27.1..V0.27.18 ready for `/chain-validated` merge to main per Mike chain-end-merge rule

## When you're ready

On drill PASS: you run `/sprint-validated` for Sprint 40 + Sprint 41 (combined or sequenced your call). Then I run `/chain-validated` to land V0.27.1..V0.27.18 to main + tag.

If the drill reveals a regression: I bump V0.27.18 -> V0.27.19 + re-run `/sprint-deploy-pm` Phase 5+; loop until validated.

regression_manifest.json F-005 + F-007 are the Sprint 41 features; F-008/F-011/F-012 still HELD from Sprint 40 pending your decision.

— Marcus
