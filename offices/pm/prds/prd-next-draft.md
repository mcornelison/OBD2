---
sprint: TBD
version: V0.28.3 (candidate)
status: prep
createdAt: 2026-06-01
createdBy: Marcus (PM)
selectedStories: []
forksFrom: dev (after V0.28.2 deploys + validates)
---

# Next-sprint prep tracker (groomed in parallel while Ralph runs V0.28.2)

**Purpose:** aggregate the team's parallel non-coding prep (research, design
rulings, runsheets, specs) into a groom-ready PRD. Pipeline parallelism — Ralph
builds V0.28.2; the rest of the team preps the next sprint. Converts to a real
sprint PRD once the groom-ready gate (below) is green and V0.28.2 has
deployed + validated.

**Lane rule while a sprint is live:** prep work touches `offices/<role>/` +
`specs/` ONLY — never `src/`/`tests/` (Ralph's lane). §13 shared-checkout
discipline governs; PM pushes + integrates.

## Candidate scope (V0.28.3 / post-chain)
| Candidate | Source | Notes |
|---|---|---|
| **US-367** ECU lineage backfill (re-groomed for `ecu_id` FK model) | F-108, deferred 2026-06-01 | **Likely spine.** Blocked on Atlas design ruling (below). Spool-signed `MD326328`; prod ecu already correct. |
| Next **B-076** slice — drop transitional `vehicle_info` TEXT columns | F-076 | Atlas to scope timing (after coherence proven). |
| **GPS speed-calibration** enablement | Spool spec + Atlas GPS procedure | Future / post-drive-27; data-sourcing in flight. |
| **F-103** Pi splash (boot + shutdown) | Iris v1.1 spec, gated | Groom-ready prep assigned to Iris. |
| (backlog) F-074 MAP PID, F-078 sync chatter, F-082 tester data-profile, F-083 Mahalanobis | V0.28+ backlog | Pull as scope allows. |

## Prep deliverables tracker
| Agent | Deliverable | Status | Landing |
|---|---|---|---|
| **Atlas** | US-367 design ruling (2-vs-3 rows / overwrite placeholder) + first-row bootstrap architecture under `ecu_id` FK | ⏳ assigned | → `offices/pm/inbox/` |
| **Spool** | GPS-cal grounded data (gear/final-drive ratios + wheel circ) + drive-27 protocol + US-367 prior-ECU install timestamp signed | ⏳ assigned | → `specs/grounded-knowledge.md` + inbox |
| **Argus** | V0.28.2 deploy-drill runsheet + whole-chain `/sprint-validated`+`/chain-validated` evidence checklist + US-367/378 criteria review | ⏳ assigned | → `offices/tester/` + inbox |
| **Iris** | F-103 splash spec → groom-ready + F-092/F-097 UI specs | ⏳ assigned | → `offices/uidevloper/` + inbox |

## Open design questions (must be ruled before groom)
1. **US-367 rows:** overwrite the `PRE_TRACKING_UNKNOWN` placeholder (→ 2 rows) or append (→ 3 rows)? — Atlas.
2. **US-367 bootstrap:** how to seed the first `vehicle_info` row under the NOT-NULL `ecu_id` FK (stamp_ecu_swap refuses the first row) — Atlas.
3. **Next B-076 slice timing:** when to drop the transitional TEXT columns — Atlas.

## Groom-ready gate (convert to PRD when ALL true)
- [ ] Atlas: US-367 design questions 1–2 ruled.
- [ ] Spool: US-367 prior-ECU window + swap instant signed; GPS-cal data pinned.
- [ ] Argus: V0.28.2 + chain runsheets drafted; next-sprint validationCriteria reviewed.
- [ ] Iris: F-103 spec groom-ready (if F-103 is in scope).
- [ ] V0.28.2 deployed + recompute green + F-005/F-007 HOLD released.
- [ ] V0.28 chain `/chain-validated` to main (or decision to stack another patch).

→ Then: PM writes the real PRD, `prd_to_sprint` → freeze → Atlas Rule 13 → CIO dispatches Ralph.

## Audit
- 2026-06-01 created (PM) — operationalizes the parallel-prep plan (CIO-directed). Assignment notes routed to all four non-coding agents.
