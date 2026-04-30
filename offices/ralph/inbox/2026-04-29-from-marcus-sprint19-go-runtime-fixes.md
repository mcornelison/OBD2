# Sprint 19 — GO: Runtime Fixes + Server Reconciliation (8 stories)

**From:** Marcus (PM)
**To:** Ralph
**Date:** 2026-04-29
**Branch:** `sprint/runtime-fixes` (already created from `main` by Marcus — start here)
**Sprint contract:** `offices/ralph/sprint.json`
**Theme:** Fix what Sprint 18's "tests pass, production fails" wave exposed + reconcile server-side schemas with Pi reality.

---

## TL;DR

Sprint 18 shipped 6 wins. Two stories — US-216 (Power-Down Orchestrator) and US-228 (drive_summary cold-start metadata) — closed with `passes: true` but failed silently in production. US-216 never fired across **4 drain tests over 9 days**. US-228 produced **all-NULL drive_summary** rows on **3 consecutive drives** that ran AFTER it shipped. In addition, Ralph's post-deploy 7-axis system-health audit found 7 server-side variances (V-1 through V-7) where the server schema/state hasn't kept up with Pi reality.

Sprint 19 cleans up both. **No new feature scope.** Just finish what Sprint 18 attempted + close the server-side gap.

---

## The new rule that shapes this sprint (read this first)

`feedback_runtime_validation_required.md` (saved to memory 2026-04-29):

> Synthetic tests must tightly mock the runtime conditions. Generic unit tests aren't enough. Mock the actual hardware-level signals the production code consumes (e.g., for US-216, mock `MAX17048.readVCell()` returning a stair-stepping discharge curve, NOT mock `UpsMonitor.getPowerSource()` returning a pre-canned `BATTERY` enum). Test the integration path (sensor → state machine → callback → DB write), not just the leaf function in isolation.

**Why this matters for Sprint 19:** US-216 and US-228 both had passing unit tests in Sprint 18. The tests proved the code did what its author thought it did, but the mocks were too high in the call stack. The synthetic stimuli didn't expose the real-world failure path.

**Generic rule, applied to every Sprint 19 story:** if the acceptance gate says "fixes runtime bug X" — the synthetic test must reproduce bug X using mocks that mirror production's stimulus shape. If the test wouldn't fail against the original buggy code, it's not strong enough.

US-234 and US-236 acceptance criteria spell this out concretely. Use those as the template for the rest.

---

## CIO sprint-scope rules (Sprint 18+ → 19+ persist)

- **Ralph CAN commit.** Commit early and often on `sprint/runtime-fixes`.
- **No git commands in sprint.json acceptance.** Branches/merges/main pushes are PM-owned. Marcus already created `sprint/runtime-fixes`; Marcus will merge to `main` after sprint close.
- **No human tasks in sprint.json acceptance.** Drills, real drives, sudo installs, button presses, server deploys, hardware checks → those go on the post-sprint **action-items list** at the bottom of this note. Story acceptance closes when synthetic tests pass.
- If a story's text says "fixes runtime bug X" — the synthetic test reproduces bug X. (See above.)

---

## The 8 stories

### P0 — must-ship (4)

| # | Story | Size | Why |
|---|-------|------|-----|
| **US-234** | Fix US-216 trigger SOC→VCELL (3.70/3.55/3.45V) | M | 4 drain tests, 0 stage transitions. SOC% calibration is 40-pt off. Switch to VCELL volts. |
| **US-235** | UpsMonitor BATTERY-detection fix (drop CRATE rule) | S | CRATE register unreliable on this hardware. Add `VCELL<3.95V sustained 30s → BATTERY` rule. |
| **US-236** | Actually fix US-228 — defer-INSERT (Option A) | S | Sprint 18's UPDATE-backfill is dead. Switch to deferred INSERT: wait for first IAT/BATTERY/BARO before creating drive_summary row. |
| **US-237** | V-1 drive_summary 3-way reconciliation + V-4 namespace truncate | M | Pi DriveSummary writer + server analytics DriveSummary + new metadata writer all conflict. Unify into one ordered pipeline + truncate legacy sim rows. |

### P0 — server schema catch-up (1)

| # | Story | Size | Why |
|---|-------|------|-----|
| **US-238** | V-2 dtc_log server migration 0005 | S | US-204 shipped Pi-side dtc_log; server has no mirror. Pi syncs queue but server rejects. |

### P1 — investigate / cleanup (3)

| # | Story | Size | Why |
|---|-------|------|-----|
| **US-239** | V-3 connection_log Drive 4 disambiguation | S | Drive 4 has connection_log gap; investigate path-a (logger fix) or path-b (analyzer-tolerance). Pick one. |
| **US-240** | V-5 server-side orphan backfill | S | Server has rows older than Pi's truncate horizon; reconcile or archive. |
| **US-241** | B-047 US-A versioning (V0.18.0) + structured release record | S | First sub-story of B-047 Pi self-update from server release registry. SemVer V0.18.0 starting point. |

### Sequencing notes

- **US-234 + US-235 are siblings.** US-235 fixes the upstream BATTERY-detection that US-234's orchestrator depends on. Land US-235 first; US-234 wires the new `getVcell()` API into the threshold logic.
- **US-236 is independent of US-234/235.** Can land in parallel.
- **US-237 reconciliation depends on US-236.** US-236 establishes the canonical writer; US-237 then unifies the other two paths. Sequence: US-236 → US-237.
- **US-238 (server migration) is fully independent.** Land any time.
- **US-239/240/241 are P1 — only if capacity allows after P0s land.**

---

## Files Marcus has staged for you

- `offices/ralph/sprint.json` — full 8-story Sprint Contract v1.0 (groomed; sprint_lint reports 0 errors, 22 sizing-cap warnings which are informational per CIO directive).
- `offices/pm/inbox/2026-04-29-from-spool-sprint19-consolidated.md` — Spool's authoritative findings (4-drain-test data, 40-pt SOC% calibration, drive_summary NULL pattern). **Read this first** before touching US-234/US-235/US-236.
- `offices/pm/inbox/2026-04-29-from-ralph-post-deploy-system-health-drive4.md` — your own audit; V-1 through V-7 are listed there. **Read this first** before touching US-237/US-238/US-239/US-240.
- `offices/pm/backlog/B-048-max17048-calibration-learning-run.md` — for context only; B-048 is a backlog item Spool will spec separately. US-234 is the interim VCELL switch; B-048 is the long-term SOC% fix.

---

## Action-items list (NOT sprint stories — Marcus + CIO own these)

These confirm Sprint 19 actually works in production. They are NOT acceptance gates.

1. **Drain test 5** (CIO) — after US-234/235 deploy. First test where US-216 should actually fire stage transitions. If it doesn't, file follow-up story; don't reopen US-234.
2. **Cold-start drive 6** (CIO) — after US-236/237 deploy. Verify drive_summary row has non-NULL `ambient_temp_at_start_c` / `starting_battery_v` / `starting_baro_kpa`.
3. **Server redeploy** (Marcus) — for US-237 + US-238 migrations. Apply via `python scripts/apply_server_migrations.py` after sprint merge. Pi redeploy follows.
4. **Spool review ritual against Drive 5** (Spool) — once Drive 5 is captured, Spool runs the warm-idle baseline review and updates `knowledge.md`.
5. **MAX17048 calibration learning run** (CIO + Spool spec, B-048) — multi-hour hardware procedure; runs in parallel; not a Sprint 19 acceptance gate.

If any action item reveals a gap in synthetic-test coverage → file a follow-up story for Sprint 20. The original story stays closed; the gap becomes new work.

---

## Spool's parallel deliverables (informational, not Ralph stories)

Per Spool's consolidated note, Spool is doing in parallel with Sprint 19:

- Author MAX17048 calibration procedure spec (feeds future B-048 implementation story).
- Track LTFT post-jump adaptation across next 3-5 drives, update `knowledge.md`.
- Audit UPS charge path (does it actually reach 4.200V terminal?).

You don't need to coordinate on these — they don't gate any Sprint 19 story.

---

## Definition of done (Sprint 19 close)

- All 8 stories `passes: true` with synthetic-test acceptance gates met (per the new rule).
- Fast suite green; ruff clean on touched files; sprint_lint 0 errors.
- Inbox note back to Marcus summarizing what shipped + any gotchas + size-feedback per `feedback_pm_sprint_contract_calibration.md`.
- No git commands you ran will surprise Marcus; commit cadence is yours, push when convenient. Marcus will merge `sprint/runtime-fixes` → `main` at sprint close.

---

## Get started

```bash
# Branch is already created and checked out
git branch --show-current   # should show: sprint/runtime-fixes

# Read the sprint contract
cat offices/ralph/sprint.json

# Read Spool's findings before starting US-234
cat offices/pm/inbox/2026-04-29-from-spool-sprint19-consolidated.md

# Pick US-235 first (US-234 depends on US-235's getVcell() exposure being clean)
# Or pick US-238 (independent server migration) for a quick warm-up win.
```

Pick any P0 story, mark `status: in_progress`, follow the contract.

— Marcus
