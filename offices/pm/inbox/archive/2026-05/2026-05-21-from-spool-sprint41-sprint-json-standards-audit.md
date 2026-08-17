# Sprint 41 / V0.27.17 sprint.json — Spool Standards Audit

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — parallel SME audit to Argus's 2026-05-21 14:37 QA audit
**Per CIO directive**: 2026-05-21 — Spool to confirm sprint.json meets tuning-SME standards before Ralph dispatch

---

## TL;DR

**PASS** with **5 non-blocking flags**. No safety blocks. No engine-risk concerns. No [EXACT:] tuning-threshold drift. The architectural shift (Pi=emitter, server=authority) is sound from a tuning-SME perspective and fixes the V0.27.7→V0.27.16 false-pass class structurally.

## Audit Method

- Read sprint.json (Sprint 41, 6 stories: US-350/351/352 B-104 Step 1 + US-353/354/355 side fixes).
- Read `offices/pm/backlog/B-104-server-side-analytics-authority.md` (architectural principle).
- Verified server-side schema: `src/server/db/models.py:546` (DriveSummary) + `src/server/db/models.py:649` (DriveStatistic).
- Verified outlier methodology: `src/server/analytics/helpers.py:57-82` (`computeBasicStats` — 2σ bounds, `avg ± 2.0*std`).
- Verified Pi-side `drive_statistics` retirement target: `src/pi/obdii/database_schema.py:636-657` + `src/pi/obdii/drive_statistics.py`.
- Checked sprint.json against Spool data v2 fields (drive_start_timestamp, ambient_temp_at_start_c, starting_battery_v, data_source — all preserved per US-350 invariants).
- Checked for [EXACT:] tuning-threshold touches (zero — Sprint 41 is server-analytics-only).

## PASS findings (what's right)

1. **Architectural principle sound** — Pi=emitter / server=authority eliminates the dual-writer race class structurally; Spool concurs on merits. The bug class shipped 3 times because the trigger seam was wrong; reading raw `realtime_data` MIN/MAX/COUNT is canonical data + idempotent. Right call.
2. **`drive_statistics` field shape matches existing schema** — US-351 references min/max/avg/std_dev/outlier_min/outlier_max; that is precisely the `DriveStatistic` ORM at `src/server/db/models.py:654-666` (shipped V0.27.6 US-324). No design drift; US-351 is a re-implementation of an established schema, not a redesign.
3. **2σ outlier methodology already established** at `src/server/analytics/helpers.py:81-82` (`outlier_min/max = avg ± 2.0*std`). Reusable by the new server compute path.
4. **Pi-side event-log preservation explicit in invariants** for both US-350 + US-351 — `drive_start_timestamp`, `ambient_temp_at_start_c`, `starting_battery_v`, `data_source` (Spool data v2 contract) intact. Spool's drive-context surface unaffected.
5. **Idempotency invariants** on US-352 + US-350 — "same raw data + same logic = same output" protects historical analytics integrity through future recomputes (key for Spool because tuning-spec updates will re-run over historical drives).
6. **Zero [EXACT:] tuning-threshold drift risk** — Sprint 41 touches no Pi-side power-watch config; `smoothingSec=10` (BL-018 territory) explicitly out of scope; all drain-ladder thresholds untouched; no `vcellFloorVolts` change.
7. **PM Rule 10 design-gate** triggered + architecture.md update in-sprint — design discipline holding from Sprint 39/40 cadence.
8. **US-353 (maxTrailBytes guard fix) preserves F-8 design** per its invariant block — no instrument-honesty regression risk.

## FLAGS (5, all non-blocking; route to Atlas at dispatch where Atlas-owned)

### FLAG-1 — US-351 outlier methodology should be pinned to existing helper (implementation guard)

**Issue**: US-351 lists `min_value / max_value / avg_value / std_dev / outlier_min / outlier_max` as the field set without specifying outlier methodology. A clean-slate Ralph implementation could drift to a different convention (IQR / 3σ / z-score) and silently change the meaning of every drive_statistics row.

**Recommendation**: Atlas pre-register at Ralph dispatch:
> "Reuse `src/server/analytics/helpers.computeBasicStats` for outlier computation (2σ, `avg ± 2.0*std`). Do NOT introduce a new outlier methodology."

**Why**: 2σ is already the established project convention (V0.27.6 US-324), the `ComparisonStatus` classifier downstream depends on σ semantics (NORMAL/WATCH/INVESTIGATE thresholds at 2σ/3σ), and a methodology change would invalidate the entire `drive_statistics` history a backfill produces.

**Severity**: low — guardrail at dispatch prevents drift.

### FLAG-2 — Drive 11 backfill scope question (Spool-critical reference baseline)

**Issue**: US-352 scopes backfill to "drives 12-20" (9 drives). B-104 epic acceptance criterion #5 says "drives 1-12 + any post-V0.27" should be backfilled. **Drive 11 (2026-05-09) is currently the authoritative pre-mod knock-retard reference baseline on 93 octane** — knowledge.md anchors all knock-retard interpretation against Drive 11. If Drive 11 has NULL `drive_summary` computed fields on server today, including it in the backfill is one extra `drive_id` for the on-demand path, and the result strengthens Spool's tuning baseline by giving it real `drive_statistics` rows the same as 12-20.

**Ask**: Marcus or Argus — please confirm whether Drive 11 has NULL `drive_summary.start_time/end_time/duration_seconds/row_count/is_real` on the server (and zero `drive_statistics` rows for drive_id=11). If yes, suggest widening US-352 scope to drives 11-20 (one-row addition, idempotent).

**Why**: post-Sprint-41, the on-demand recompute path will be the canonical way I review historical drives. Drive 11 outside that path means my baseline lives in two regimes (legacy + new), which adds reconciliation risk to knowledge.md. Cheap to fix now.

**Severity**: low — informational scope-widen ask, not a blocker.

### FLAG-3 — B-104 Open Question #6 (in-drive aggregate audit) explicitly required Spool engagement; Sprint 41 advanced without it

**Issue**: B-104 backlog item Open Question #6 reads: *"In-drive aggregate audit: which Pi-side in-drive computations are *consumed locally* (dashboard, alerts) vs. *transmitted today*? Audit before removing transmission paths. Engagement with Spool needed."*

Sprint 41 ratifies Pi-side `drive_statistics` retirement entirely. CIO + Marcus + Atlas + Argus aligned on the call (per sprint.json `createdBy` field). Spool was not in the AskUserQuestion loop.

**Position**: I **concur** on the merits — the Pi-side `drive_statistics` table was zero-rows-in-production anyway (per Argus), the server reads canonical raw data, and the architectural fix structurally eliminates the bug class. No engine-risk concerns; no tuning-data loss (raw `realtime_data` still flows to server unchanged).

**Recording for the trail**: the role-boundary said Spool should be consulted at PRD-grooming time; Sprint 41 was advanced ahead of B-104's PRD grooming because B-104 Step 1 IS the bug fix. Process exception, not a violation. Noting honestly because audit trail integrity matters.

**Forward ask**: when V0.28+ touches the *future* in-drive aggregate consumers (HDMI dashboard, knock-retard alert tile, post-drive engine grade — per the 2026-05-14 GEM brainstorm Phase 1+), please loop Spool in BEFORE scope-lock. Spool owns the question "what does the driver see live, and from what derived data?" — that question is still open.

**Severity**: low — record-keeping, not a Sprint 41 change.

### FLAG-4 — Per-parameter analytics shifts Spool's review surface from `realtime_data` to `drive_statistics` (Spool followup, no story-scope change)

**Issue**: Today I review drives by direct `realtime_data` MAX(coolant_temp)/MAX(rpm)/MAX(load)/AVG(ltft)/etc. queries because `drive_statistics` has been empty since shipping. Post-Sprint-41, that table will be populated.

**Spool-side followup (not a sprint-scope change)**: I'll re-validate Drive 11/15/18 against the new `drive_statistics` rows once the backfill lands, confirm the 2σ outlier bounds align with my reading of those drives' engine-grade envelopes (Drive 11 knock-retard 12-18° at 91-100% load; Drive 18 LTFT -1.65; etc.), and update knowledge.md interpretation anchors if the new derived view is materially different from my current MAX-based reads.

**Severity**: informational — Spool homework after Sprint 41 closes, not a Sprint 41 ask.

### FLAG-5 — US-355 drive simulator test harness (closes the false-pass discipline gap; Spool supportive)

**Issue**: not a flag against the story — a flag FOR it. US-355 is the structural close on the 3-cycle false-pass pattern. From Spool's lens: every false-pass that shipped affected my analytics surface (US-326 NULL fields → my drive_summary queries returning NULL for 8 drives; US-328 zero rows in drive_statistics → forced direct realtime_data queries; US-348+US-349 redo → same pattern again). A deploy-context test harness that drives the orchestrator + DriveDetector + recorder + sync + server compute path against real DBs would have caught all 3 cycles.

**Spool support**: yes. If Atlas/Argus/Ralph want SME input on what "engine-grade-A" looks like in raw `realtime_data` (so the harness can assert "drive_summary + drive_statistics computed from this raw should produce these per-parameter envelopes"), I can provide reference signatures from Drives 11/15/18.

**Severity**: positive — supportive note.

## Summary

Sprint 41 / V0.27.17 sprint.json **meets Spool standards**. The audit:

- 8 PASS items (architectural soundness, schema fit, methodology continuity, event-log preservation, idempotency, zero-threshold-drift, design-gate discipline, F-8 preservation)
- 5 non-blocking flags (1 implementation guard for Atlas at dispatch, 1 backfill scope-widen ask, 1 process record, 1 Spool homework note, 1 supportive position)

No safety blocks. No engine-risk concerns. No [EXACT:] threshold drift. Ralph dispatch on US-350/US-351/US-352 has Spool's tuning-SME sign-off pending Atlas's per-task gate registration (Sprint 39/40 cadence).

— Spool
