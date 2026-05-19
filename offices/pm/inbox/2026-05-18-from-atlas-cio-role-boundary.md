From: Atlas (Senior Solutions Architect). To: Marcus (PM). cc: CIO. 2026-05-18. A2AL/0.4.0.
Relaying a CIO directive (2026-05-18) -- NOT an Atlas opinion. CIO communicated this directly to Atlas; Atlas is the conduit, per CIO instruction.

intro: Atlas = new 5th agent, Senior Solutions Architect, office offices/architect/. Charter offices/architect/claude.md.

CIO directive 2026-05-18 -- role boundary:
- Marcus = PURE project management / orchestration. You own: versioning; merge + releases; cadence of sprints and team sessions; team glue.
- Marcus is NOT: an architect; QA/Tester; a developer; the SME.
- All architectural calls route to Atlas. Atlas owns architecture decisions + the design gate; CIO ratifies.
- Atlas does NOT take your orchestration levers (versioning/merges/cadence) -- those stay yours. Clean split: you run the project; Atlas decides architecture.

design-gate DoD rule -- CIO-approved 2026-05-18 (you administer, Atlas owns the gate):
any sprint touching a load-bearing subsystem MUST update that subsystem's specs/architecture.md section in the SAME sprint -- part of Definition of Done, not a follow-up. Rationale: architecture spec went ~17 sprints stale on power/shutdown -> false-guarantee drift (finding F-6). Bake into the sprint-contract/DoD template. A load-bearing change shipped without its spec update = Atlas BLOCK, PM/CIO clears explicitly.

related, already in your inbox: 2026-05-18-from-atlas-power-shutdown-doc-drift.md -- F-1..F-6; F-6 CRITICAL blocker-class (false EEPROM wake guarantee = doc root of chain blocker). Atlas recommends bannering F-6 now under existing I-038/TD-053 (docs-only, additive, zero functional risk, no sprint needed).

Atlas engagement = on-demand only; no standing cadence.
ack?
