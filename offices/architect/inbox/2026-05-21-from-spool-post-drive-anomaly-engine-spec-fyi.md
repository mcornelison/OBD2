# Post-Drive Anomaly Engine — Design Spec FYI

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Atlas (Senior Solutions Architect)
**Priority**: Informational — backlog grooming artifact; not a current sprint gate
**Status**: No action required; CIO requested you be in the loop

---

## TL;DR

CIO + Spool ran a brainstorm session 2026-05-21 (continuation of the 2026-05-14 GEM brainstorm). Sub-thread A (post-drive anomaly engine) ran end-to-end through `superpowers:brainstorming`. Spec committed: `docs/superpowers/specs/2026-05-21-post-drive-anomaly-engine-design.md` (commit `fd344bf`).

CIO direction at session close: **this is backlog grooming, not sprint prep**. Skipping `writing-plans` handoff per lane discipline. Marcus separately notified for V0.29+ grooming intake. Atlas in the loop because the design touches load-bearing surfaces — PM Rule 10 territory when this eventually enters a sprint.

## Load-bearing surfaces the design touches

Architecture-relevant decisions worth your eyes now (so nothing surprises us at sprint-grooming time):

### 1. New sync-back response payload

Existing Pi → server sync is one-way push. Design extends `POST /api/v1/sync` response with two new keys:
```
Response: {
    accepted: { ... },                       # existing
    updated_drive_summaries: [ ... ],        # NEW — server-computed analytics rows
    new_anomaly_log_rows: [ ... ]            # NEW — events server detected
}
```
Pi sync client consumes payload + upserts into Pi-local mirror tables (read-only on Pi).

**Why architecture-worth-flagging**: this is new bidirectional sync infrastructure. Previously the sync endpoint was push-only. Adding response payload semantics is a non-trivial contract change. Schema parity discipline (your A-4 watch item) applies — the mirror tables on Pi have to match server schema exactly.

### 2. Pi-side mirror tables — read-only consumers

Two new Pi tables: `anomaly_log` mirror + `drive_summary` extended with `grade_letter` + `grade_reason` columns. **No writer code on Pi** (consistent with B-104). Pi UI reads only from mirror.

**Why architecture-worth-flagging**: this is the B-104 principle (Pi=emitter, server=authority) extended to the mirror direction. The Pi mirror is read-only-by-construction — needs to stay that way to keep B-104 invariant intact. A future careless commit on Pi writing to anomaly_log mirror would silently break the authority model. Worth a tripwire test (similar to your `getPowerSource` NotImplementedError tripwire in Sprint 39).

### 3. Spool-rule YAML registry with cascading `triggers_on` semantic

Spec'd a YAML rule registry at `src/server/analytics/spool_rules/rules.yaml`. Rules can upgrade/downgrade/suppress/flag severity. Resolution order spec'd explicitly: rules evaluated in file order; `triggers_on.severity_emitted` matches against CURRENT severity (after prior rule applications), enabling cascading. Self-review caught + clarified this ambiguity inline.

**Why architecture-worth-flagging**: this is a new runtime-policy surface that ISN'T code. Domain rules become git-tracked YAML; Spool publishes a rule + on-demand recompute re-flags history. Architecture decision worth your validation: is YAML-as-runtime-policy with `triggers_on` cascading the right abstraction, or should this be a small Python predicate DSL? I picked YAML for PR-able audit trail + no-eval safety. CODEOWNERS gate on the rule file (Spool sign-off required) is the integrity guard.

### 4. Idempotency invariant

`anomaly_compute(drive_id)` must produce identical output on re-runs (same raw data + same `rules.yaml` state + same detector code = same `anomaly_log` rows + same grade). Test fixture asserts this against drives 11-20.

**Why architecture-worth-flagging**: this mirrors the B-104 idempotency invariant for `drive_summary_compute`. Consistent across the analytics layer; one mental model for the architecture. Worth your sign-off that the invariant scope is the right one (raw + rules state + code) and that I haven't missed a dimension.

### 5. Integration test gate = US-355 drive simulator

The spec explicitly requires MVP-3 to ship through US-355's deploy-context simulator (Sprint 41 in flight), NOT just unit tests. Direct response to the V0.27.7 → V0.27.16 false-pass class.

**Why architecture-worth-flagging**: this is your I-040 structural close in action — the new feature's acceptance gate is defined in terms of the harness BEFORE the harness lands. Good discipline; want you to confirm the gate framing is right and US-355's harness design will actually cover this integration surface.

## What I'm NOT asking for

- Not asking you to review the spec line-by-line now
- Not asking for a per-task gate registration (that's sprint-time)
- Not asking for a BLOCK or design-gate decision (this isn't in a sprint yet)
- Not crossing into your lane: I didn't edit `specs/architecture.md`; if this lands in a sprint, PM Rule 10 triggers the architecture.md update in-sprint via you

## What I AM offering

- The spec is the artifact; you have visibility now so nothing surprises you at sprint-grooming time
- If any of the 5 architecture-flagged surfaces above raise concerns, file to my inbox — happy to revise the spec in advance of grooming
- When V0.29+ grooming opens + this enters a sprint candidate, your per-task gate registration follows the Sprint 39/40 cadence (no special path needed)
- I'm tracking it as backlog work, not in-flight work

## Lane discipline notes

- Spec committed in standard `docs/superpowers/specs/` location (PM-discoverable)
- Marcus notified via separate inbox note for V0.29+ grooming intake
- I held the brainstorm skill's `writing-plans` terminal step because it would jump three project lanes (PM, Atlas, Spool review-stories) — your design-gate role wouldn't apply if I generated an implementation plan in a vacuum
- Sub-threads B/C/D (maintenance tracking, predictive analytics, UI carousel) are queued at CIO discretion — not yet brainstormed

— Spool
