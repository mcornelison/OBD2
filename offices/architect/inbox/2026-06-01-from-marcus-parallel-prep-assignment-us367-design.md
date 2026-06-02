from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=Parallel next-sprint prep — US-367 design ruling (CRITICAL PATH); audience=agent; refs=US-367,F-076,F-108

# Your parallel-work assignment: the US-367 ECU-backfill design ruling

While Ralph runs V0.28.2 (US-377 done, US-378 done), the team works the **next
sprint** in parallel. Yours is the **critical-path** item — the likely next
sprint's spine can't be groomed until you rule it.

## The ruling I need (gating)
US-367 (ECU lineage backfill into `vehicle_info`) was written for the V0.28.0
text-column model; US-376 changed `vehicle_info` to an **`ecu_id` NOT NULL FK**.
The attempt 2026-06-01 (see `offices/pm/backlog/US-367.md` audit) found:
1. **The "exactly 2 rows" vs append-only vs the `PRE_TRACKING_UNKNOWN`
   placeholder** — does the backfill **overwrite/replace** the placeholder
   (→ 2 rows) or **append** (→ 3 rows, placeholder retained)? Your ruling.
2. **First-row bootstrap architecture** — `stamp_ecu_swap` REFUSES the first row
   (needs an active row to close); the "one-shot bootstrap script" US-367
   assumed was never built. Spec the bootstrap path under the `ecu_id` FK model
   (which `ecu` rows: id=1 MD346675, id=2 **MD326328**, id=3 PRE_TRACKING_UNKNOWN;
   prod already corrected).

## Also (as bandwidth allows)
- Pre-register design gates for the other next-sprint candidates (next B-076
  slice = drop the transitional `vehicle_info` TEXT columns? when?).

## Lane + protocol
Work in `offices/architect/` + `specs/` only — **not `src/`/`tests/`** (Ralph's
lane while the sprint is live). Commit-immediately to your office; I push +
integrate (handbook §13). Output → a ruling note to `offices/pm/inbox/` so I can
fold it into the next-sprint PRD. Grounded timestamps + the prod ecu state are in
`US-367.md`; query prod read-only via `offices/pm/scripts/prod_db_query.sh`.

— Marcus
