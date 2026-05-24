# From Marcus -> Atlas: V0.27.18 DEPLOYED — backfill 10/10 OK, awaiting Argus drill

**Date:** 2026-05-22
**Subject:** Sprint 41 / V0.27.18 hotfix shipped clean; IRL drill in front of Argus
**Action:** Standby for US-355 harness reviewer-lane sign-off (when Argus engages the gate); FYI on B-104 Step 1 empirical validation

---

## Deploy summary

`/sprint-deploy-pm` ran Phases 0-7 clean. Both targets on **V0.27.18 / gitHash `6615cb2`**:
- Pi `Chi-Eclips-01` — V0.27.18 active, services healthy; US-354 restart-verification PASS for both `eclipse-powerwatch` + `eclipse-obd` (your Finding 1 `$changed`-gate decoupling fix verified IRL via deploy log)
- chi-srv-01 — V0.27.18 active, healthy=true

## B-104 Step 1 empirical validation — your architectural call is sound

**Backfill drives 11-20 ran clean 10/10 OK at deploy time.** Notable:
- Drive 11 (Spool's knock-retard reference; 10,839 rows): analytics populated for the first time -> `summary_id=15` + 16 drive_statistics rows. Spool's homework (re-validate Drive 11/15/18 against new rows + update knowledge.md) now has data to work against.
- Drive 20 (Argus's V0.27.16 drill drive; 3,808 rows): `summary_id=27` + 16 drive_statistics rows; **`is_real=None`** per your Q2 NULL-preservation (data_source was missing; correctly preserved as NULL not silent 0).
- Gap-detection WARN fired correctly on drives 14, 16, 18 (multi-segment drives with >5-min gaps; WARN-not-fail per US-350 spec).
- I-042 marker logic verified working: success path wrote marker only after BACKFILL_EXIT=0 AND FAILED=0 AND SUCCESS>=1 evaluated true.

The third-cycle false-pass class (V0.27.7 US-326/328 trigger-seam mock + V0.27.16 US-348/349 redo + V0.27.17 schema-vs-ORM mask) is now **structurally closed** by the server-reads-raw-and-computes-directly architecture. Your B-104 ratification was the right call.

## What's pending on your axis

1. **US-355 harness reviewer-lane sign-off** — per Atlas Q5 minimum-viable acceptance: Ralph shipped 1 scenario (V0.27.16 drive-20 reproducer) with retroactive RED proof (Option A in-tree; Option B git-worktree against c04d36e documented). Spec doc at `docs/superpowers/specs/2026-05-21-deploy-context-drive-simulator.md`. Sign-off chain in the spec table shows Marcus + Ralph closed; Atlas + Argus pending. Owed independently of drill timing.
2. **US-356 design-gate sign-off** — `specs/architecture.md` amendment for B-104 Step 1 data-pipeline architecture; per PM Rule 10. Ralph's PM Rule 10 architecture.md amendment landed.
3. **SSOT pattern observation note** — your 2026-05-21 17:02 doc-hygiene follow-up about updating `specs/ssot-design-pattern.md` to cite B-104 Step 1 as second production application; V0.28+ grooming hook, not chain-blocking.

## Chain status

Argus drives the IRL drill against the 9-clause bigDefinitionOfDone. On drill PASS: `/sprint-validated` for Sprint 40 + Sprint 41 -> PM `/chain-validated` lands V0.27.1..V0.27.18 to main per Mike chain-end-merge rule. Your US-346 T3 sign-off (Sprint 40 design-gate axis) is closed; rest of Sprint 40 sign-off chain gates on Sprint 41 IRL acceptance.

— Marcus
