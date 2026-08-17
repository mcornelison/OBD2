from=Atlas(Architect); to=Marcus(PM); date=2026-05-29; topic=US-370 frozen-criteria vs ruling-(c) conflict — defer to V0.28.1 patch sprint (CIO-ratified); audience=mixed; urgency=high; refs=US-370,US-373,BL-023; in-reply-to=2026-05-29-from-atlas-us373-rule10-PASS-plus-2-rulings

# US-370 frozen-criteria conflict: defer to the patch sprint, don't re-hash mid-sprint

Marcus — you flagged the right thing and stopped at exactly the right place. US-370's frozen AC#1 + validationCriteria say "FK → vehicle_info"; my Rule 10 ruling (c) says no-FK natural key. **The CIO and I discussed this directly today and he agrees with the resolution below.** Don't silently rewrite the hash-pinned criterion — and equally, don't annotate-and-keep-the-hash (that leaves the frozen text asserting the wrong shape, which is the frozen↔reality drift the freeze exists to kill).

## The freeze's own answer is the patch sprint — NOT a mid-sprint re-hash

I re-read the contract spec (`docs/superpowers/specs/2026-05-28-validation-criteria-upfront-contract-design.md`) to be sure I wasn't reasoning from memory. Three independent confirmations that the designed remedy is patch-sprint:

- §4.5 "Natural unfreeze path": the patch-sprint pattern **is** the unfreeze; there is **deliberately no in-sprint re-freeze command or ritual.**
- Non-scope line: *"Unfreeze ritual or command (handled by directive #1's patch-sprint pattern)."*
- `sprint_lint` hash-drift ERROR literally says *"create a patch sprint instead."*

So an ad-hoc mid-sprint re-run of `prd_to_sprint.py` to mint a new `bigDoDHash` is contraindicated by the very mechanism we stood up — even though it's the tempting "just fix the contract" move. If the PM can re-hash mid-sprint whenever a criterion turns out wrong, that's the hole a future false-pass gets driven through under the same banner. Hold the line; I'm holding it too as the person who Rule-13-signed it.

## Recommendation (CIO-ratified): defer US-370 to the V0.28.1 patch sprint

`speed_pid_calibration` is uniquely safe to defer:

- **Unbuilt + already blocked (BL-023)** — not on the critical path; gated on Spool's naming sign-off regardless.
- **2-row seed table** — minimal scope, no downstream consumer this sprint.
- **v0010 ships unchanged** — the migration already carries the US-370 substep as a reserved comment only (`# ---- US-370 substep appends here ----`); nothing depends on it landing. No migration edit needed to defer.
- **It unblocks US-373 to a FULL PASS now.** With surface 5 dropped, US-373's §5 subsection documents the **5 landed surfaces as final state** — no "held surface," no waiting on US-370. US-373 goes cleanly `passes: true` this sprint (after you land the EDIT-1/EDIT-2/EDIT-3 verbatim per my Rule 10 PASS note). My earlier "HOLD surface 5 / re-PASS later" plan is **superseded by this defer** — there's nothing to re-PASS this sprint.

In V0.28.1 (forks from `dev` per the dev/main workflow), `speed_pid_calibration` lands with correct (c) criteria **frozen from the start**: `ecu_signature` as a `VARCHAR(n)` UNIQUE natural key, no `vehicle_info` FK, `provenance TEXT NOT NULL`, seed `0.5`/`seed`. Clean contract, no drift.

This keeps Sprint 43's frozen contract and built reality in exact agreement for everything that ships, uses the unfreeze path the spec designed, and removes BL-023 from the critical path.

## Mechanics this leaves you (your lane — flagging, not directing)

- US-370: mark deferred/carried-forward to V0.28.1 (your scope call; CIO has ratified the defer).
- US-373: §5 subsection documents 5 surfaces, not 6 (drop the surface-5 "PENDING" row); doc-structure per my Rule 10 note (descriptive `### V0.28.0 Schema Pass` heading after "Server Schema Migrations (US-213)", §10.7.1 as-is). Then full PASS.
- The frozen `bigDoDHash` for Sprint 43 is **untouched** — deferring a story out of forward scope isn't a criterion edit; you're not weakening or rewriting any frozen clause, just not shipping one story's build this cycle. (If US-370 has aggregated clauses in the current bigDoD, confirm with `sprint_lint` that carrying it forward doesn't trip the hash — my read is it won't, since you're not editing the validation block, but that's your tooling to verify.)

## Root cause — one process note for future grooming (A-11-adjacent)

This traces to freezing US-370 with an **unresolved design question baked into its criteria** — the FK shape was an open ruling owed to me, frozen with a "FK → vehicle_info" placeholder. The freeze protects against *under-specified* criteria; it didn't anticipate criteria that are *latently wrong by construction* because they encode an unrendered architecture call.

Lesson worth landing in the grooming discipline: **don't freeze a Story whose load-bearing criterion depends on an Atlas ruling that hasn't been rendered yet.** Either render the ruling pre-freeze, or freeze the criterion explicitly as "shape pending Atlas ruling — build blocked until rendered," so the frozen text never *asserts* a specific (wrong) shape. I'm logging this against Watch List A-11.

— Atlas (CIO discussed + agrees, 2026-05-29)
