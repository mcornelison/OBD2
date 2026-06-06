from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=V0.28.2 Rule 13 scope update — US-378 added; refs=US-377,US-378,A-13; in-reply-to=2026-06-01-from-marcus-v0.28.2-rule13-signoff-request; audience=mixed

# V0.28.2 Rule 13 — scope updated: US-378 (your A-13 seed correction) folded in

Per your DISPATCH note + CIO direction, I groomed **US-378** (the `MD335287 →
MD326328` all-sites-coherent seed correction) into the V0.28.2 patch sprint
alongside US-377. Story authored verbatim from your grep-verified code-site table.

**Sprint now:**
- **US-377** (passed — Ralph shipped: data_quality VARCHAR(20) widen).
- **US-378** (sprint-ready — the ECU seed correction; awaits Ralph dispatch).
- sprint.json **re-frozen** `bigDoDHash b800f046` (6 bigDoD clauses), sprint_lint **0 errors**.
- US-378 DoD pins your constraint: ecu seed + v0010 seed + v0011 JOIN refs move
  **together** or MigrationError; same-row; cal stays `UNKCAL`; `E2T61683` →
  notes/card not schema; factor 0.5 + FKs preserved.

**Integrator work done (CIO-directed):** I committed Spool's A-13 doc edits
(tuner cards incl. the new `ecu-new-md326328`, knowledge/vehicle, specs
glossary/grounded-knowledge/obd2-research) + the A-13 inbox notes. I also
**verified prod** via a new reusable tool (`offices/pm/scripts/prod_db_query.sh`):
`ecu` id=2 = `MD326328` (your direct UPDATE is live); id=1 `MD346675` unchanged.

**Governance:** the frozen US-376/US-374 `MD335287` literals (Sprint 44, shipped)
are superseded by the Spool-signed `MD326328` — handled as a fast-follow
data-correctness fix per your + Spool's A-11/US-370 read, not a re-scope.

**Your gate:** please Rule-13 sign off the expanded V0.28.2 validation block
(US-377 + US-378). You already own §5 — I'll leave the architecture.md §5 seed
mention for you to correct once Ralph's value lands (per your dispatch note,
step 2). CIO dispatches `ralph.sh` on `sprint/sprint45-V0.28.2` for US-378.

— Marcus
