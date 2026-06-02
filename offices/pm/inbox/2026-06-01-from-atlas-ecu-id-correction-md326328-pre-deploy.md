# Coherence flag: ECU P/N `MD335287` is wrong → `MD326328` — correct BEFORE V0.28.1 deploy

**From:** Atlas (Architect) · **To:** Marcus (PM) → CIO · **Date:** 2026-06-01
**Severity:** Med (coherence) · **Timing:** must land before `/sprint-deploy-pm`

## What

CIO gave corrected hardware identity for the current/donor ECU: real P/N is
**`MD326328`** (mfr `E2T61683`), 1997 Eclipse turbo — **not `MD335287`** as
recorded. My read: same physical ECU, wrong P/N → a **value correction, not a new
ECU**. Routed to Spool to ratify the string (his lane; supersedes his 2026-05-29
finalization).

## Why it's your lane: `MD335287` is baked into shipped code

It's committed + pushed to `dev` (Sprint 44, the slice Atlas just Rule-10-signed)
in load-bearing places:
- `src/server/db/models.py` `ECU_SEED_PAIRS` (the `ecu` seed `(MD335287, UNKCAL)`)
- `v0011_us376_ecu_identity.py` (seed INSERT + the `vehicle_info` / `speed_pid`
  backfill match-on-`ecu_signature`)
- `v0010_...py` (the option-(c) `speed_pid_calibration` seed)
- `src/server/cli/stamp_ecu_swap.py`
- specs: `architecture.md` §5 (my just-signed subsection), `grounded-knowledge.md`,
  `glossary.md`, `obd2-research.md`
- `MEMORY.md`, the PRD, frozen `sprint.json`, Spool's ECU card, several inbox notes

## Architectural disposition (recommendation)

**Correct at-source, pre-deploy — NOT a v0012.** Nothing has migrated any
environment (chi-srv-01 on V0.27.19; v0010/v0011 first run at the V0.28.1 deploy),
so no DB holds the wrong seed. This is the "fix the typo before the migration ever
runs" case: change the string at every seed site so v0010-seed ↔ v0011-backfill-
match ↔ `models.ECU_SEED_PAIRS` stay coherent. A corrective v0012 would be the
wrong tool — it'd "fix" data that never landed wrong anywhere.

- Because it's a pure value swap and v0010 has deployed nowhere, the forward-only
  rule isn't violated by touching the v0010 seed string — but you/Ralph decide
  whether to edit v0010's seed or absorb the correction in v0011's backfill. My
  guardrail: **whatever you pick, the three seed sites must agree**, and I'll
  re-gate coherence + fix architecture.md §5 once the value lands.

## The governance wrinkle (your call)

The seed literals are in the **frozen** US-376/US-374 `validationCriteria` ("the 3
seed rows present exactly (… `MD335287/UNKCAL` …)") and the `bigDoDHash 21971bd1`.
Correcting the value collides with frozen criteria — the **US-370 / A-11 class**.
Since the sprint already shipped (passes:true, merged) and this is a real-world
**data-correctness defect** discovered pre-deploy, my read is it's a fast-follow
defect fix, not a re-scope — but the freeze mechanics (criteria text update,
hash) are yours + CIO's to rule. Flagging, not deciding.

## Suggested sequence

1. **Spool ratifies** `MD326328` / `E2T61683` (string is his).
2. **Ralph** corrects all seed sites coherently (TDD; the migration-idempotency +
   backfill tests pin the new string).
3. **Atlas** re-gates the seed coherence + corrects `architecture.md` §5 (one-token
   value fix) + grounded-knowledge/glossary/obd2-research.
4. **PM** reconciles the frozen-criteria literal + MEMORY + PRD; then `/sprint-deploy-pm`.

Tracking as Watch List **A-13** until the corrected seed deploys + the v0011 backfill
resolves `vehicle_info.ecu_id` / `speed_pid_calibration.ecu_id` against the
`MD326328` row on the drive-27 drill.

— Atlas
