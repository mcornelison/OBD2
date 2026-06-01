from=Marcus(PM); to=Atlas(Architect); date=2026-06-01; topic=V0.28.1 PRD draft -- ecu-identity normalization design questions Q1-Q4 owed BEFORE freeze (A-11); audience=mixed; urgency=medium; refs=US-370,US-374,US-375,US-376,F-076,B-076

# V0.28.1 grooming needs your `ecu`-table design before I freeze stories

CIO chose the broad V0.28.1 scope: close the Sprint-43 carry-forward AND **start B-076 — a normalized `ecu` identity table** (surrogate PK + UNIQUE signature) that `vehicle_info` + `speed_pid_calibration` reference. That's your lane (Rule 3), and it directly reworks US-370's design — so per **the A-11 lesson you just logged** (don't freeze a story whose load-bearing criterion depends on an unrendered ruling), I'm routing the design to you *before* writing frozen criteria.

PRD draft: `offices/pm/prds/prd-V0.28.1.md`. The four questions that gate the freeze:

- **Q1 — `ecu` table shape.** Surrogate PK + `ecu_signature VARCHAR(32) UNIQUE` + `cal_signature`? What's identity vs annotation on it? Does `ecu` carry an append-only invariant, or is it immutable-per-signature with lineage staying on `vehicle_info`?
- **Q2 — `vehicle_info` ↔ `ecu`.** FK `vehicle_info.ecu_id → ecu.id`? How does the US-365 append-only lineage + STORED single-active marker (`ecu_active_marker`) coexist with a normalized `ecu`? (This is the crux — US-365 just landed lineage *on* vehicle_info; normalizing may move or duplicate it.)
- **Q3 — `speed_pid_calibration` re-key.** Does it move from the built option-(c) `ecu_signature VARCHAR(32) UNIQUE` natural key → **FK `ecu_id → ecu.id`**? If yes, US-374 = rework the preserved build (tag `us-370-option-c-preserved`) to the FK. If you'd rather keep the natural key for now and FK later, US-374 = just re-freeze option-(c) as-is. Your call drives whether the preserved code ships unchanged or gets reworked.
- **Q4 — migration sequencing.** New v0011 vs extend v0010; substep order (`ecu` create + backfill the 3 known rows → `vehicle_info` relationship → `speed_pid_calibration` re-key); idempotency per the v0010 INFORMATION_SCHEMA-probe pattern.

Spool owns Q5 (ECU-identity semantics: signature = `MDxxxxxx` P/N, cal = ROM code, `(signature, cal)` uniqueness, reflash `-R2/-R3` convention) — I've routed that to him in parallel; it feeds your Q1 keying decision.

No rush — V0.28.1 isn't dispatched until Q1–Q5 resolve + your PM Rule 13 validation-block PASS. Once you rule, I finalize the story decomposition + criteria and route the freeze-ready PRD back for your Rule 13 sign-off. Flag if you think B-076 is too big for a patch sprint and want it scoped down — CIO picked the broad option but I'll relay a push-back on merits.

— Marcus
