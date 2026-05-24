# Post-Drive Anomaly Engine — Design Spec Ready for V0.29+ Grooming Queue

**Date**: 2026-05-21
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Routine — backlog grooming intake; not Sprint 41 candidate
**Status**: No action required until V0.29+ grooming opens

---

## TL;DR

CIO + Spool ran a brainstorm session 2026-05-21 (continuation of the 2026-05-14 GEM brainstorm). One sub-thread (post-drive analytics) ran end-to-end through the `superpowers:brainstorming` skill. Output: a complete design spec committed to `docs/superpowers/specs/2026-05-21-post-drive-anomaly-engine-design.md`. CIO direction explicit at session close: **this is backlog grooming, not sprint preparation**. Skipping `writing-plans` handoff per lane discipline — Marcus owns sprint planning at sprint-spin time.

## Spec summary

**Scope**: V1.0 MVP = 3 detectors fully wired end-to-end (knock_retard, coolant_temp, ltft_drift) → V1.0 Full = expand to 9 → V2+ = trend/predictive/Ollama-narrative layers.

**Key design choices** (all spec'd in detail):
- Hybrid detection (fixed Spool safety thresholds + 2σ statistical drift + Spool-rule overrides)
- Hybrid baseline (Drive 11 anchor + rolling-5-prior-drives + 3σ anchor-only escape)
- Hybrid severity (4-tier safety / 3-tier drift; honors CIO A6 2026-05-14)
- Weighted-by-signal engine grade (knock 3.0×, coolant 2.5×, LTFT 1.0×; STOP-DRIVING override → D)
- Spool-rule YAML registry — Spool publishes domain rules without Ralph code dispatch
- Server-side authority per B-104; Pi-local mirror tables read-only
- Rides Sprint 41 US-350/US-352 paths + US-355 deploy-context simulator as integration gate

**Validation against existing drives**: math reproduces my PM-note grading judgment for Drives 11/14/15/17/18 (Drive 11=A, Drive 14=A-, Drive 15=A via Spool-rule downgrade, Drives 17/18=A). Locked as regression fixtures.

**Counts**: 14 acceptance criteria, 5 open questions, 8 related backlog items, 9 sections totaling ~700 lines.

## Cross-link suggestions for the backlog

This spec IS the implementation design for several existing GEMs. At grooming time, recommend cross-linking:

| Existing item | Relationship |
|---|---|
| **B-089** GEM-4 Spool engine grade per drive | This spec IS the implementation design for it. Letter grade A/A-/B+/B/B-/C/D + grade_reason live in `drive_summary` per the design. |
| **B-093** GEM-8 baseline-relative anomaly detection | This spec implements the per-drive form (Drive 11 anchor + rolling-5). Cross-drive trend form belongs to sub-thread C (predictive) — not yet brainstormed. |
| **B-094** GEM-9 MrSpool RAG digital twin | V3.0 narrative layer consumes the `--json` output from `show_drive_anomalies` CLI. Schema-compatible for future. |
| **B-086** GEM-1 warnings-first quiet UI | This spec's parked-mode anomaly tile lives INSIDE the B-086 carousel. Single-cell ownership — open question #5 in the spec. |
| **B-088** GEM-3 knock-retard real-time alert | Sibling surface (real-time vs post-drive). Threshold/severity definitions are shared (4-tier safety from CIO A6). Don't duplicate work. |

PM lean (your call): you might want a single umbrella **B-###** with the design spec as the primary doc + the existing GEMs as sub-items. Or leave them as cross-linked siblings. Either works; I have no preference.

## Open questions captured in the spec (PRD-grooming time)

1. B-074 MAP PID dependency — V1 uses ENGINE_LOAD; MAP would enrich load-band; not a blocker
2. `data_source` filter for grade computation — recommend NO for production, YES for unit tests
3. Re-baseline Drive 11 procedure (post-ECMLink V3 install someday)
4. Drives 6/7/8 pre-mod-shelf backfill scope — depends on Sprint 41 US-352 widening decision (Spool already flagged in 2026-05-21 14:37 audit)
5. Carousel cell ownership overlap with B-086 — coordinate at PRD time

## Other sub-threads still open (CIO didn't brainstorm them yet)

The 2026-05-21 brainstorm only covered sub-thread **A** (post-drive analytics). Three more sub-threads remain queued at CIO's discretion:

- **B**: Maintenance tracking (oil changes, brake fluid, plugs) — NEW domain, zero backlog coverage
- **C**: AI-driven predictive analytics ("your car best performs when...") — pattern-mining over historical drives; distinct from B-087/B-094
- **D**: UI carousel refinement (95% full-screen + alert auto-snap; specs/samples/*.png mockups) — extends B-086

CIO will direct timing on those. No PM action needed.

## Lane discipline notes

- Spec lives in `docs/superpowers/specs/` (committed `fd344bf`); standard project location for design docs.
- I did NOT cross-link the spec into B-089/B-093/B-094 myself — that's PM lane (you maintain the backlog files).
- I did NOT invoke `writing-plans` — that's sprint-prep work, not grooming. Atlas pre-registers per-task gates at Ralph dispatch time per Sprint 39/40 cadence.
- PM Rule 10 design-gate territory will trigger when this enters a sprint (B-104 architecture is load-bearing); Atlas separately notified.

## What I need from you (eventually, not now)

- At V0.29+ grooming opens: review the spec + decide cross-link strategy (umbrella B-### vs. cross-linked siblings)
- Loop me in for `/review-stories-tuner` before Ralph dispatch (Sprint 39/40 cadence — I review the stories you draft from this spec for tuning-threshold drift)
- No urgency. Sprint 41 + V0.27 chain merge come first.

— Spool
