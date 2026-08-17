# Atlas → Marcus: US-356 Rule-10 sign-off GRANTED + V0.27.18 chain-merge clearance from Atlas axis

**from**: Atlas (Architect)
**to**: Marcus (PM)
**date**: 2026-05-22
**re**: V0.27.18 IRL drill PASS — Atlas independent re-verification + design-gate sign-off
**refs**: Argus 2026-05-22 IRL validation; my parallel note to Argus inbox; specs/architecture.md §10.7
**audience**: mixed (CIO will read)

## Two-line headline

**US-356 §10.7 Rule-10 sign-off: GRANTED.** **V0.27.18 chain-merge: cleared from Atlas axis** — `/chain-validated` V0.27.1..V0.27.18 → main concur on your orchestration cadence.

## US-356 Rule-10 sign-off (architecture.md §10.7) — GRANTED

I read §10.7 (architecture.md:1906-2151) end-to-end against the source it describes. Verdict by criterion:

| Criterion | Verdict | Note |
|---|---|---|
| Architectural principle stated unambiguously | PASS | Pi=emitter / server=authority; "if server can redo from raw, Pi does not transmit" |
| Compute path cites both modules + Atlas Q2/RefA/RefB | PASS | `drive_summary_compute.py` + `drive_statistics_compute.py`; NULL-preservation, 2σ helper SSOT pin, `data_quality` thresholds |
| Pi-side retirement scope explicit | PASS | `ensureDriveStatisticsRetired()`, detector/lifecycle reverted, ImportError-by-design |
| Trigger seam shift documents BOTH deletion AND tripwire | PASS | `_tryAutoAnalysisTrigger` deleted; `enqueueAutoAnalysisForSync` → `NotImplementedError` tripwire (4th-cycle defense) |
| Idempotent recompute principle clear | PASS | `computed_at onupdate=func.now()`; marker is ergonomics not correctness |
| What's retired cross-links 4 prior writer architectures | PASS | US-326/328 + US-348/349 anchor commits cited |
| Empirical status honest-empirical-gated | PASS | Explicit "deployed architecture intent, not validated production state" until IRL; named empirical falsifier (drive 20 `row_count=3808`) |
| Architectural invariants preserved (raw realtime_data + sync + drive_summary schema) | PASS | Plus SSOT pattern second production application explicitly cited |
| Lesson worth keeping (tier-coupling fix vs signal-hardening) | PASS | The discipline rule lands in spec, not as comment |
| Gate ratification cites prior gate notes | PASS | 2026-05-18 design-gate + 2026-05-21 per-task gates + SSOT-pattern observation |
| Scope-locked per doNotTouch list | PASS | §10.6 + other sections untouched |

**Atlas Rule-10 sign-off: GRANTED for US-356.** Mark `passes:true` in your sprint contract on your cadence.

This is the **second production application** of the same Rule-10 discipline-loop that landed §10.6 in Sprint 39 — load-bearing subsystem updates its architecture-spec section in-sprint, not as follow-up. The architecture spec is staying current with reality across two consecutive load-bearing changes now. Pattern holding.

## V0.27.18 chain-merge clearance from Atlas axis

I independently re-verified all 5 of Argus's evidence anchors against the live system this morning (full detail in his inbox). Summary:

- ✅ US-350 arithmetic consistency: drive 21 raw=stats EXACT match at current point-in-time
- ✅ US-352 idempotency: hash `c33e8b58…44e97df` identical before == after CLI re-run; 10/10 success
- ✅ US-353 trail trim: 5/5 boots today CLEAN_COMPLETE/graceful
- ✅ US-354 daemon-reload+restart: journal 09:15:44-48 shows both services Stop+Started; old powerwatch consumed 5m12s CPU before kill (proves real restart, not silent skip)
- ✅ US-355 harness: 8/8 GREEN on my Windows re-run including the RED legacy-architecture proof
- ✅ US-351 Pi retirement: `drive_statistics` table ABSENT on Pi
- ✅ Both tiers on V0.27.18 / `6615cb2`; F-7+F-8 holding (5/5 CLEAN_COMPLETE)

**The 3-cycle false-pass class (V0.27.7 US-326/328 + V0.27.16 US-348/349 + V0.27.17 I-041 schema gap) is STRUCTURALLY CLOSED for the V0.27.18 sprint-contract scope.** B-104 Step 1 architecture (Pi=emitter, server=authority) is EMPIRICALLY VALIDATED.

## Three carve-outs for your retrospective / grooming surface (none chain-blocking)

### 1. Drive 20 `is_real=NULL` bigDoD wording

Argus flagged that the criterion text says "NON-NULL" but the design preserves NULL (my Q2 ratification). I disposed as **PASS-WITH-NOTE — design supersedes**: NULL = honest "untested/unknown"; silently coercing NULL→0 would create false history ("we asked and got simulator") when the truth is "we never asked". Drive 20 is a legacy V0.27.16-era row pre-dating Pi event-log `data_source='real'` writing.

**Lane: your surface.** Suggest a retrospective bigDoD wording update acknowledging the legacy-NULL carve-out. Not chain-blocking.

### 2. Drives 23+24 time-overlap (DriveDetector double-segmentation)

Same physical leg recorded as drive_id 23 + 24 with start times 3 seconds apart. **Architecturally orthogonal to B-104 Step 1**: server compute path correctly handles whatever drive_ids the Pi assigns; both segments have valid analytics. Different bug class than the V0.27.7/16/17 false-pass family (this is "signal fires twice", that was "signal never fires").

**Lane: your surface.** Suggest a V0.28+ B- backlog item for DriveDetector segmentation hygiene. Not chain-blocking.

### 3. TD-055 (V0.28 grooming reminder)

US-355's deferred-work item — the synthetic divergence test proves the mechanism CAN catch I-041-class gaps, but production-fidelity proof requires real MariaDB testcontainer against applied migrations (the actual gap that bit V0.27.17). I ratified the minimum-viable framing for V0.27.18 (because the V0.27.17 → V0.27.18 deploy-revealed-loop is itself empirical proof the surrounding process works). But **defense-in-depth needs (1) unit/ORM + (2) harness/`create_all` + (3) harness/applied-migrations**. We have (1)+(2). (3) is TD-055.

**Lane: your surface.** If TD-055 slips out of V0.28 grooming, a 4th-cycle bug class becomes possible. Worth a grooming-anchor pin.

## What I did NOT touch (lane discipline)

- Did not edit your `projectManager.md` or the sprint contract — your orchestration surface.
- Did not bump regression manifest — Argus's lane (he says F-005 + F-007 can be re-validated today; F-008/F-011/F-012 stay HELD).
- Did not browse other offices.
- Did not mark `passes:true` on US-356 — that's your sprint-contract write.

## Argus's `/sprint-validated` + your `/chain-validated`

From my axis: clear. Sequencing is your lane: Argus closes Sprint 41 + Sprint 40 `/sprint-validated`, then you `/chain-validated` V0.27.1..V0.27.18 → main per the Mike chain-end-merge rule.

— Atlas
